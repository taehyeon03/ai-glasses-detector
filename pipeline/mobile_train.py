"""Fine-tune MobileNetV3-Small using the common experiment record schema."""
import argparse
import gc
import json
import random
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torchvision
from torch import nn
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

from pipeline.mobile_data import build
from pipeline.probe import plot_confusion, plot_history
from pipeline.records import append_jsonl, metrics, provenance, sha256, write_json


def model(pretrained=True):
    weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
    network = mobilenet_v3_small(weights=weights)
    network.classifier[-1] = nn.Linear(network.classifier[-1].in_features, 2)
    return network


def normalize(images):
    images = images.float() / 255
    mean = images.new_tensor([.485, .456, .406])[None, :, None, None]
    std = images.new_tensor([.229, .224, .225])[None, :, None, None]
    return (images - mean) / std


@torch.no_grad()
def evaluate(network, images, labels, indices, batch_size):
    network.eval()
    all_logits = []
    for ids in indices.split(batch_size):
        all_logits.append(network(normalize(images[ids])).float())
    logits = torch.cat(all_logits)
    targets = labels[indices]
    scores = logits.softmax(1)[:, 1]
    predictions = (scores >= .5).long()
    loss = nn.functional.cross_entropy(logits, targets).item()
    return metrics(targets.tolist(), predictions.tolist(), loss), scores.tolist(), predictions.tolist()


def norms(network, run, epoch):
    for name, value in network.named_parameters():
        parameter = value.detach().float()
        append_jsonl(run / "weight_norms.jsonl", dict(epoch=epoch, layer=name,
            trainable=value.requires_grad, l2=parameter.norm().item(),
            rms=parameter.square().mean().sqrt().item()))


def train(config, run, data):
    seed = config["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    device = torch.device("cuda")
    meta = provenance(config)
    meta.update(torch=torch.__version__, torchvision=torchvision.__version__, cuda=torch.version.cuda,
                device=torch.cuda.get_device_name(), amp=config["amp"])
    write_json(run / "provenance.json", meta)
    (run / "pip-freeze.txt").write_text(subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    write_json(run / "data-audit.json", {k: v for k, v in data.items() if k != "rows"})
    source = Path(config["view_cache"]) / f"{config['view']}.npy"
    print(f"loading {config['view']} cache to GPU", flush=True)
    images = torch.from_numpy(np.load(source)).to(device)
    labels = torch.tensor([v["label"] for v in data["rows"]], device=device)
    splits = {split: torch.tensor([i for i, row in enumerate(data["rows"]) if row["split"] == split],
                                 device=device) for split in ["train", "validation", "test"]}
    network = model().to(device)
    pretrained_path = Path(torch.hub.get_dir()) / "checkpoints" / Path(MobileNet_V3_Small_Weights.IMAGENET1K_V1.url).name
    write_json(run / "model.json", dict(architecture="mobilenet_v3_small", trainable="all parameters",
        parameters=sum(p.numel() for p in network.parameters()),
        pretrained_url=MobileNet_V3_Small_Weights.IMAGENET1K_V1.url,
        pretrained_sha256=sha256(pretrained_path)))
    optimizer = torch.optim.AdamW(network.parameters(), lr=config["lr"], weight_decay=config["weight_decay"])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=config["epochs"])
    scaler = torch.amp.GradScaler("cuda", enabled=config["amp"])
    best_key, best_epoch, best_state = None, None, None
    global_step = 0
    norms(network, run, 0)
    for epoch in range(1, config["epochs"] + 1):
        started = time.time()
        network.train()
        ids = splits["train"][torch.randperm(len(splits["train"]), device=device)]
        for batch in ids.split(config["batch_size"]):
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda", dtype=torch.float16, enabled=config["amp"]):
                logits = network(normalize(images[batch]))
                loss = nn.functional.cross_entropy(logits, labels[batch])
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            global_step += 1
            append_jsonl(run / "steps.jsonl", dict(epoch=epoch, step=global_step,
                loss=loss.item(), lr=optimizer.param_groups[0]["lr"]))
        scheduler.step()
        for split in ["train", "validation"]:
            result, _, _ = evaluate(network, images, labels, splits[split], config["eval_batch_size"])
            append_jsonl(run / "metrics.jsonl", dict(split=split, epoch=epoch, step=global_step, **result))
            if split == "validation":
                key = (result["macro_f1"], -result["false_positive_rate"], -result["loss"])
                if best_key is None or key > best_key:
                    best_key, best_epoch = key, epoch
                    best_state = {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}
                print(f"{config['view']} s{seed} epoch={epoch} val_f1={result['macro_f1']:.4f} "
                      f"fpr={result['false_positive_rate']:.4f} seconds={time.time()-started:.1f}", flush=True)
        norms(network, run, epoch)
    network.load_state_dict(best_state)
    network.eval()
    torch.save(dict(model=best_state, config=config, best_epoch=best_epoch), run / "checkpoint.pt")
    final = {}
    for split in ["train", "validation", "test"]:
        result, scores, predictions = evaluate(network, images, labels, splits[split], config["eval_batch_size"])
        final[split] = result
        write_json(run / f"{split}-final.json", result)
        plot_confusion(result, run / f"{split}-confusion.png")
        split_rows = [r for r in data["rows"] if r["split"] == split]
        for row, score, predicted in zip(split_rows, scores, predictions):
            append_jsonl(run / f"{split}-predictions.jsonl", dict(sample_id=row["sample_id"],
                product_id=row["product_id"], identity_group_id=row["identity_group_id"],
                truth=row["label"], prediction=predicted, camera_probability=score,
                quality_flags=row["quality_flags"]))
    append_jsonl(run / "metrics.jsonl", dict(split="test", epoch=best_epoch, step=global_step,
        evaluation="final_selected_checkpoint", **final["test"]))
    write_json(run / "summary.json", dict(best_epoch=best_epoch, threshold=.5,
        selection="validation macro-F1; ties: lower FPR, then lower loss", final=final,
        checkpoint_sha256=sha256(run / "checkpoint.pt"), jetson_validation="pending"))
    plot_history(run)
    del images, network, optimizer, scaler
    gc.collect()
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--views", nargs="+", default=["full", "roi_mask", "roi_crop"])
    args = parser.parse_args()
    base = json.loads(Path(args.config).read_text())
    data = build(base)
    from scripts.validate_run import validate
    for view in args.views:
        for seed in base["seeds"]:
            run = Path(args.runs) / f"mobilenet-{view}-s{seed}"
            if run.exists():
                if json.loads((run / "status.json").read_text())["state"] == "completed":
                    validate(run)
                    continue
                raise ValueError(f"Refusing to overwrite unfinished run: {run}")
            run.mkdir(parents=True)
            config = dict(base, seed=seed, view=view)
            started = time.time()
            write_json(run / "status.json", dict(state="running", started_at=datetime.now(timezone.utc).isoformat()))
            try:
                train(config, run, data)
                write_json(run / "status.json", dict(state="completed", elapsed_seconds=time.time()-started,
                    finished_at=datetime.now(timezone.utc).isoformat(), jetson_validation="pending"))
                write_json(run / "record-validation.json", validate(run))
            except BaseException:
                write_json(run / "status.json", dict(state="failed", traceback=traceback.format_exc()))
                raise


if __name__ == "__main__":
    main()
