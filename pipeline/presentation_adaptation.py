"""Training-free text and support-cache comparisons requested in the presentation."""
import argparse
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as F

from pipeline.probe import plot_confusion
from pipeline.records import append_jsonl,metrics,provenance,sha256,write_json
from scripts.validate_run import validate

PROMPTS=[
    ["a photo of ordinary eyeglasses", "a photo of ordinary sunglasses",
     "a close-up photo of conventional glasses", "a person wearing ordinary eyeglasses",
     "a pair of glasses without a built-in camera"],
    ["a photo of camera-equipped smart glasses", "a photo of camera-equipped sunglasses",
     "a close-up photo of glasses with a built-in camera", "a person wearing camera-equipped eyeglasses",
     "a pair of glasses with a small built-in camera"]]


@torch.no_grad()
def prepare_features(config,output):
    cache=Path(config["adaptation_feature_cache"])
    expected=sha256(config["mobileclip_checkpoint"])
    if cache.exists():
        saved=torch.load(cache,map_location="cpu",weights_only=True)
        metadata_digest=sha256(Path(config["view_cache"])/"metadata.json")
        if saved["pretrained_sha256"]!=expected or saved["prompts"]!=PROMPTS or saved["source_metadata_sha256"]!=metadata_digest:
            raise ValueError("Frozen feature cache mismatch")
        return saved
    sys.path.insert(0,config["mobileclip_source"])
    import mobileclip
    network,_,_=mobileclip.create_model_and_transforms("mobileclip_s0",
        pretrained=config["mobileclip_checkpoint"],reparameterize=True,device="cuda")
    tokenizer=mobileclip.get_tokenizer("mobileclip_s0")
    images=torch.from_numpy(np.load(Path(config["view_cache"])/"roi_crop.npy")).cuda()
    features=[]
    for begin in range(0,len(images),128):
        features.append(network.encode_image(images[begin:begin+128].float()/255,normalize=True).cpu())
    texts=[]
    for prompts in PROMPTS:
        texts.append(network.encode_text(tokenizer(prompts).cuda(),normalize=True).cpu())
    single=torch.stack([v[0] for v in texts])
    ensemble=F.normalize(torch.stack([v.mean(0) for v in texts]),dim=1)
    saved=dict(features=torch.cat(features),single=single,ensemble=ensemble,
        scale=network.logit_scale.exp().clamp(max=100).item(),prompts=PROMPTS,
        pretrained_sha256=expected,source_metadata_sha256=sha256(Path(config["view_cache"])/"metadata.json"))
    cache.parent.mkdir(parents=True,exist_ok=True);torch.save(saved,cache)
    return saved


def predict(features,text,scale,keys=None,values=None,alpha=0.,beta=1.):
    logits=scale*(features@text.T)
    if keys is not None:
        affinity=torch.exp(-beta*(1-features@keys.T))
        logits=logits+alpha*(affinity@values)
    return logits


def score(logits,labels):
    probabilities=logits.softmax(1)[:,1]
    predictions=(probabilities>=.5).long()
    return metrics(labels.tolist(),predictions.tolist(),F.cross_entropy(logits,labels).item()),probabilities,predictions


def run_condition(config,root,cache,metadata,method,prompt,seed=0,shots=0):
    name=f"{method}-{prompt}-k{shots}-s{seed}"
    run=root/name
    if run.exists():
        validate(run);return
    run.mkdir(parents=True)
    start=time.time()
    write_json(run/"status.json",dict(state="running",kind="training_free"))
    settings=dict(config,method=method,prompt=prompt,seed=seed,shots_per_class=shots,
                  epochs=0,evaluation_only=True)
    write_json(run/"provenance.json",provenance(settings))
    (run/"pip-freeze.txt").write_text(subprocess.check_output([sys.executable,"-m","pip","freeze"],text=True))
    write_json(run/"data-audit.json",dict(source_metadata_sha256=cache["source_metadata_sha256"],
        source_manifest_sha256=metadata["source_manifest_sha256"],pretrained_sha256=cache["pretrained_sha256"],audit=metadata["audit"]))
    features=cache["features"].cuda();text=cache[prompt].cuda()
    labels=torch.tensor([r["label"] for r in metadata["rows"]],device="cuda")
    splits={s:torch.tensor([i for i,r in enumerate(metadata["rows"]) if r["split"]==s],device="cuda")
            for s in ["train","validation","test"]}
    keys=values=None;alpha=0.;beta=1.;support=[]
    if method=="tip_adapter":
        rng=np.random.default_rng(seed)
        for label in [0,1]:
            candidates=[i for i,r in enumerate(metadata["rows"]) if r["split"]=="train" and r["label"]==label]
            ordered=rng.choice(candidates,size=64,replace=False).tolist()
            support.extend(ordered[:shots])
        keys=features[support];values=F.one_hot(labels[support],num_classes=2).float()
        best=None
        ids=splits["validation"]
        for a in [.1,.5,1.,2.,5.,10.]:
            for b in [1.,2.,5.,10.,20.]:
                result,_,_=score(predict(features[ids],text,cache["scale"],keys,values,a,b),labels[ids])
                append_jsonl(run/"validation-search.jsonl",dict(alpha=a,beta=b,**result))
                criterion=(result["macro_f1"],-result["false_positive_rate"],-result["loss"])
                if best is None or criterion>best:
                    best=criterion;alpha=a;beta=b
    write_json(run/"support.json",dict(indices=support,split="train",shots_per_class=shots,
        policy="nested subsets from a seed-specific draw of 64 per class"))
    torch.save(dict(text=text.cpu(),keys=keys.cpu() if keys is not None else None,
        values=values.cpu() if values is not None else None,alpha=alpha,beta=beta,scale=cache["scale"],
        pretrained_sha256=cache["pretrained_sha256"]),run/"checkpoint.pt")
    final={}
    for split,ids in splits.items():
        result,probabilities,predictions=score(predict(features[ids],text,cache["scale"],keys,values,alpha,beta),labels[ids])
        final[split]=result
        append_jsonl(run/"metrics.jsonl",dict(split=split,epoch=0,step=0,evaluation="no optimizer updates",**result))
        write_json(run/f"{split}-final.json",result)
        plot_confusion(result,run/f"{split}-confusion.png")
        for index,p,pred in zip(ids.tolist(),probabilities.tolist(),predictions.tolist()):
            row=metadata["rows"][index]
            append_jsonl(run/f"{split}-predictions.jsonl",dict(sample_id=row["sample_id"],truth=row["label"],
                prediction=pred,camera_probability=p,product_id=row["product_id"]))
    write_json(run/"summary.json",dict(best_epoch=0,threshold=.5,alpha=alpha,beta=beta,
        selection="validation macro-F1, then FPR/loss; no optimizer updates",final=final,
        checkpoint_sha256=sha256(run/"checkpoint.pt"),jetson_validation="pending"))
    fig,axes=plt.subplots(1,3,figsize=(11,3),layout="constrained")
    for ax,field in zip(axes,["loss","accuracy","macro_f1"]):
        ax.bar(list(final),[r[field] for r in final.values()]);ax.set_title(field)
    fig.suptitle("Training-free evaluation; no learning curve")
    fig.savefig(run/"evaluation.png",dpi=150);plt.close(fig)
    write_json(run/"status.json",dict(state="completed",kind="training_free",elapsed_seconds=time.time()-start))
    write_json(run/"record-validation.json",validate(run))
    print(f"{name}: val_f1={final['validation']['macro_f1']:.4f}",flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",required=True)
    parser.add_argument("--runs",required=True)
    parser.add_argument("--require-parent",required=True)
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text())
    for mode in config["modes"]:
        for seed in config["seeds"]:
            validate(Path(args.require_parent)/f"{mode}-s{seed}")
    config["adaptation_feature_cache"]="/mnt/data/ai-glasses-research/mobileclip-frozen-features-v1.pt"
    metadata=json.loads((Path(config["view_cache"])/"metadata.json").read_text())
    torch.backends.cudnn.allow_tf32=False;torch.backends.cuda.matmul.allow_tf32=False
    root=Path(args.runs);root.mkdir(parents=True,exist_ok=True)
    write_json(root/"phase-status.json",dict(state="running",kind="presentation_adaptation"))
    cache=prepare_features(config,root)
    def execute(method,prompt,seed=0,shots=0):
        try:
            run_condition(config,root,cache,metadata,method,prompt,seed,shots)
        except BaseException:
            failed=root/f"{method}-{prompt}-k{shots}-s{seed}"
            write_json(failed/"status.json",dict(state="failed",kind="training_free",traceback=traceback.format_exc()))
            write_json(root/"phase-status.json",dict(state="failed",kind="presentation_adaptation"))
            raise
    for prompt in ["single","ensemble"]:
        execute("zero_shot",prompt)
    for seed in config["seeds"]:
        for shots in [1,4,16,64]:
            execute("tip_adapter","ensemble",seed,shots)
    write_json(root/"phase-status.json",dict(state="completed",training_free_conditions=14))


if __name__=="__main__":main()
