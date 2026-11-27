"""Train MobileCLIP comparators and controlled part-evidence ablations."""
import argparse
import gc
import json
import random
import subprocess
import sys
import time
import traceback
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torchvision.models import MobileNet_V3_Small_Weights

from pipeline.mobile_train import norms
from pipeline.part_data import prepare_parts
from pipeline.part_model import create
from pipeline.probe import plot_confusion,plot_history
from pipeline.records import append_jsonl,metrics,provenance,sha256,write_json
from scripts.validate_run import validate


def call(network,inputs,ids,features=None):
    if features is not None:
        return network.head(features[ids])
    return network(inputs["global"][ids],inputs["parts"][ids] if "parts" in inputs else None,
        inputs["quality"][ids] if "quality" in inputs else None,
        inputs["valid"][ids] if "valid" in inputs else None)


@torch.no_grad()
def evaluate(network,inputs,labels,ids,batch_size,features=None):
    network.eval()
    logits=torch.cat([call(network,inputs,batch,features).float() for batch in ids.split(batch_size)])
    scores=logits.softmax(1)[:,1]
    predictions=(scores>=.5).long()
    return metrics(labels[ids].tolist(),predictions.tolist(),F.cross_entropy(logits,labels[ids]).item()),scores.tolist(),predictions.tolist()


@torch.no_grad()
def encode(network,images,indices,features,batch_size):
    network.eval()
    for batch in indices.split(batch_size):
        features[batch]=network.encode(images[batch])


def train(config,run,metadata,part_meta):
    seed=config["seed"]
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark=False
    torch.backends.cudnn.allow_tf32=False
    torch.backends.cuda.matmul.allow_tf32=False
    meta=provenance(config)
    meta.update(torch=torch.__version__,cuda=torch.version.cuda,device=torch.cuda.get_device_name(),
                tf32=False,mobileclip_input="controlled 224px; official S0 default is 256px")
    write_json(run/"provenance.json",meta)
    (run/"pip-freeze.txt").write_text(subprocess.check_output([sys.executable,"-m","pip","freeze"],text=True))
    write_json(run/"data-audit.json",dict(audit=metadata["audit"],
        source_manifest_sha256=metadata["source_manifest_sha256"],part_cache=part_meta))
    inputs={"global":torch.from_numpy(np.load(Path(config["view_cache"])/"roi_crop.npy")).cuda()}
    if config["mode"].startswith("parts_"):
        for key,name in [("parts","parts.npy"),("quality","quality.npy"),("valid","valid.npy")]:
            inputs[key]=torch.from_numpy(np.load(Path(config["part_cache"])/name)).cuda()
    labels=torch.tensor([row["label"] for row in metadata["rows"]],device="cuda")
    indices={split:torch.tensor([i for i,row in enumerate(metadata["rows"]) if row["split"]==split],
                                device="cuda") for split in ["train","validation","test"]}
    network=create(config).cuda()
    write_json(run/"model.json",dict(mode=config["mode"],parameters=sum(p.numel() for p in network.parameters()),
        trainable_parameters=sum(p.numel() for p in network.parameters() if p.requires_grad),
        local_size=config["local_size"],global_size=config["image_size"],
        normalization="raw [0,1]" if config["mode"].startswith("mobileclip") else "ImageNet",
        pretrained_sha256=sha256(config["mobileclip_checkpoint"]) if config["mode"].startswith("mobileclip") else
            sha256(Path(torch.hub.get_dir())/"checkpoints"/Path(MobileNet_V3_Small_Weights.IMAGENET1K_V1.url).name)))
    features=None
    if config["mode"]=="mobileclip_linear":
        features=torch.empty((len(labels),512),device="cuda")
        encode(network,inputs["global"],torch.cat([indices["train"],indices["validation"]]),features,config["eval_batch_size"])
    lr=config["linear_lr"] if features is not None else config["lr"]
    optimizer=torch.optim.AdamW([p for p in network.parameters() if p.requires_grad],lr=lr,weight_decay=config["weight_decay"])
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=config["epochs"])
    scaler=torch.amp.GradScaler("cuda",enabled=config["amp"] and features is None)
    best_key=None; best_state=None; best_epoch=None; step=0
    norms(network,run,0)
    for epoch in range(1,config["epochs"]+1):
        started=time.time(); network.train()
        shuffled=indices["train"][torch.randperm(len(indices["train"]),device="cuda")]
        for batch in shuffled.split(config["batch_size"]):
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda",dtype=torch.float16,enabled=config["amp"] and features is None):
                loss=F.cross_entropy(call(network,inputs,batch,features),labels[batch])
            scaler.scale(loss).backward(); scaler.step(optimizer); scaler.update()
            step+=1
            append_jsonl(run/"steps.jsonl",dict(epoch=epoch,step=step,loss=loss.item(),lr=optimizer.param_groups[0]["lr"]))
        scheduler.step()
        for split in ["train","validation"]:
            result,_,_=evaluate(network,inputs,labels,indices[split],config["eval_batch_size"],features)
            append_jsonl(run/"metrics.jsonl",dict(split=split,epoch=epoch,step=step,**result))
            if split=="validation":
                key=(result["macro_f1"],-result["false_positive_rate"],-result["loss"])
                if best_key is None or key>best_key:
                    best_key=key; best_epoch=epoch
                    best_state={k:v.detach().cpu().clone() for k,v in network.state_dict().items()}
                print(f"{config['mode']} s{seed} epoch={epoch} val_f1={result['macro_f1']:.4f} "
                    f"fpr={result['false_positive_rate']:.4f} seconds={time.time()-started:.1f}",flush=True)
        norms(network,run,epoch)
    network.load_state_dict(best_state); network.eval()
    torch.save(dict(model=best_state,config=config,best_epoch=best_epoch),run/"checkpoint.pt")
    if features is not None:
        encode(network,inputs["global"],indices["test"],features,config["eval_batch_size"])
    final={}
    for split in ["train","validation","test"]:
        result,scores,predictions=evaluate(network,inputs,labels,indices[split],config["eval_batch_size"],features)
        final[split]=result
        write_json(run/f"{split}-final.json",result)
        plot_confusion(result,run/f"{split}-confusion.png")
        for row,score,prediction in zip([r for r in metadata["rows"] if r["split"]==split],scores,predictions):
            append_jsonl(run/f"{split}-predictions.jsonl",dict(sample_id=row["sample_id"],
                product_id=row["product_id"],identity_group_id=row["identity_group_id"],truth=row["label"],
                prediction=prediction,camera_probability=score,quality_flags=row["quality_flags"]))
    append_jsonl(run/"metrics.jsonl",dict(split="test",epoch=best_epoch,step=step,
        evaluation="final_selected_checkpoint",**final["test"]))
    write_json(run/"summary.json",dict(best_epoch=best_epoch,threshold=.5,selection="validation macro-F1; ties: FPR then loss",
        final=final,checkpoint_sha256=sha256(run/"checkpoint.pt"),jetson_validation="pending"))
    plot_history(run)
    del network,inputs,features,optimizer,scaler
    gc.collect(); torch.cuda.empty_cache()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",required=True)
    parser.add_argument("--runs",required=True)
    parser.add_argument("--modes",nargs="+")
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text())
    metadata=json.loads((Path(config["view_cache"])/"metadata.json").read_text())
    if metadata["source_manifest_sha256"]!=config["dataset_manifest_sha256"]:
        raise ValueError("Dataset revision mismatch")
    part_meta=prepare_parts(config)
    for mode in args.modes or config["modes"]:
        for seed in config["seeds"]:
            run=Path(args.runs)/f"{mode}-s{seed}"
            if run.exists():
                if json.loads((run/"status.json").read_text())["state"]=="completed":
                    validate(run); continue
                raise ValueError(f"Refusing to overwrite {run}")
            run.mkdir(parents=True)
            start=time.time()
            write_json(run/"status.json",dict(state="running",started_at=datetime.now(timezone.utc).isoformat()))
            try:
                train(dict(config,mode=mode,seed=seed),run,metadata,part_meta)
                write_json(run/"status.json",dict(state="completed",elapsed_seconds=time.time()-start,
                    finished_at=datetime.now(timezone.utc).isoformat(),jetson_validation="pending"))
                write_json(run/"record-validation.json",validate(run))
            except BaseException:
                write_json(run/"status.json",dict(state="failed",traceback=traceback.format_exc()))
                raise


if __name__=="__main__":
    main()
