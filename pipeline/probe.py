"""A reproducible frozen-encoder baseline with validation-only model selection."""
import argparse
import json
import random
import subprocess
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import transforms

from pipeline.data import Images, prepare
from pipeline.records import append_jsonl, metrics, provenance, sha256, write_json


def load_encoder(config, device):
    encoder = torch.hub.load(config["hub_repo"], config["encoder"], pretrained=True,
                             trust_repo=True, skip_validation=True)
    return encoder.eval().requires_grad_(False).to(device)


def transform(size):
    # Preserve all of the frame, including the temples. No center crop.
    return transforms.Compose([transforms.Resize((size, size)), transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])


@torch.no_grad()
def extract(encoder, rows, config, device):
    batches = DataLoader(Images(rows, transform(config["image_size"])),
                         batch_size=config["image_batch_size"], shuffle=False,
                         num_workers=config["workers"], pin_memory=device.type == "cuda")
    features, labels = [], []
    for step, (images, target) in enumerate(batches):
        features.append(encoder(images.to(device)).float().cpu())
        labels.append(target)
        if step % 25 == 0:
            print(f"feature batch {step}/{len(batches)}", flush=True)
    return torch.cat(features), torch.cat(labels)


@torch.no_grad()
def evaluate(head, features, labels, threshold=0.5):
    logits = head(features)
    loss = nn.functional.cross_entropy(logits, labels).item()
    scores = logits.softmax(1)[:, 1]
    predictions = (scores >= threshold).long()
    return metrics(labels.tolist(), predictions.tolist(), loss), scores, predictions


def plot_history(run):
    history = [json.loads(line) for line in (run / "metrics.jsonl").read_text().splitlines()]
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.5))
    for ax, metric in zip(axes, ["loss", "accuracy", "macro_f1"]):
        for split in ["train", "validation"]:
            items = [v for v in history if v["split"] == split]
            ax.plot([v["epoch"] for v in items], [v[metric] for v in items], label=split)
        ax.set(xlabel="epoch", ylabel=metric)
        ax.legend()
    fig.tight_layout()
    fig.savefig(run / "learning_curves.png", dpi=160)
    plt.close(fig)


def plot_confusion(result, path):
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.imshow(result["confusion_matrix"], cmap="Blues")
    for i, row in enumerate(result["confusion_matrix"]):
        for j, n in enumerate(row):
            ax.text(j, i, str(n), ha="center", va="center")
    ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["ordinary", "camera"],
           yticklabels=["ordinary", "camera"], xlabel="prediction", ylabel="truth")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def weight_norms(encoder, head, run, epoch):
    for prefix, model in [("encoder", encoder), ("head", head)]:
        for name, parameter in model.named_parameters():
            value = parameter.detach().float()
            append_jsonl(run / "weight_norms.jsonl", dict(epoch=epoch, layer=f"{prefix}.{name}",
                trainable=parameter.requires_grad, l2=value.norm().item(),
                rms=value.square().mean().sqrt().item()))


def run_experiment(config, run):
    seed = config["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True)
    device = torch.device(config.get("device", "cuda"))
    meta = provenance(config)
    meta.update(torch=torch.__version__, cuda=torch.version.cuda,
                device=torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu")
    write_json(run / "provenance.json", meta)
    (run / "pip-freeze.txt").write_text(subprocess.check_output(
        [__import__("sys").executable, "-m", "pip", "freeze"], text=True))
    print("Verifying dataset and preparing disk cache", flush=True)
    data = prepare(config["dataset_root"], config["image_cache"])
    write_json(run / "data-audit.json", {k: v for k, v in data.items() if k != "rows"})
    rows = data["rows"]
    encoder = load_encoder(config, device)
    write_json(run / "encoder.json", dict(source=config["hub_repo"], name=config["encoder"],
        frozen=True, parameters=sum(p.numel() for p in encoder.parameters())))
    tensors = {}
    # Test features and scores are not inspected during model selection.
    for split in ["train", "validation"]:
        print(f"Extracting {split}", flush=True)
        x, y = extract(encoder, rows[split], config, device)
        tensors[split] = (x.to(device), y.to(device))
    head = nn.Linear(tensors["train"][0].shape[1], 2).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=config["lr"], weight_decay=config["weight_decay"])
    best_key, best_epoch, best_state = None, None, None
    global_step = 0
    weight_norms(encoder, head, run, 0)
    for epoch in range(1, config["epochs"] + 1):
        head.train()
        x, y = tensors["train"]
        order = torch.randperm(len(y), device=device)
        for ids in order.split(config["feature_batch_size"]):
            optimizer.zero_grad(set_to_none=True)
            loss = nn.functional.cross_entropy(head(x[ids]), y[ids])
            loss.backward()
            optimizer.step()
            global_step += 1
            append_jsonl(run / "steps.jsonl", dict(epoch=epoch, step=global_step, loss=loss.item()))
        head.eval()
        for split, (x, y) in tensors.items():
            result, _, _ = evaluate(head, x, y)
            append_jsonl(run / "metrics.jsonl", dict(split=split, epoch=epoch, step=global_step, **result))
            if split == "validation":
                key = (result["macro_f1"], -result["false_positive_rate"], -result["loss"])
                if best_key is None or key > best_key:
                    best_key, best_epoch = key, epoch
                    best_state = {k: v.detach().cpu().clone() for k, v in head.state_dict().items()}
                print(f"epoch={epoch} val_f1={result['macro_f1']:.4f} val_fpr={result['false_positive_rate']:.4f}", flush=True)
        weight_norms(encoder, head, run, epoch)
    head.load_state_dict(best_state)
    head.eval()
    torch.save(dict(head=best_state, config=config, best_epoch=best_epoch,
                    input_features=head.in_features), run / "checkpoint.pt")
    final = {}
    for split in ["train", "validation", "test"]:
        if split == "test":
            print("Final held-out test evaluation", flush=True)
            x, y = extract(encoder, rows[split], config, device)
            tensors[split] = (x.to(device), y.to(device))
        result, scores, predictions = evaluate(head, *tensors[split])
        final[split] = result
        write_json(run / f"{split}-final.json", result)
        plot_confusion(result, run / f"{split}-confusion.png")
        for row, score, predicted in zip(rows[split], scores.tolist(), predictions.tolist()):
            append_jsonl(run / f"{split}-predictions.jsonl", dict(sample_id=row["sample_id"],
                product_id=row["product_id"], truth=row["label"], prediction=predicted,
                camera_probability=score, quality_flags=row["quality_flags"]))
    append_jsonl(run / "metrics.jsonl", dict(split="test", epoch=best_epoch,
        step=global_step, evaluation="final_selected_checkpoint", **final["test"]))
    write_json(run / "summary.json", dict(best_epoch=best_epoch, threshold=0.5,
        selection="validation macro-F1; ties: lower FPR, then lower loss", final=final,
        checkpoint_sha256=sha256(run / "checkpoint.pt"), jetson_validation="pending"))
    plot_history(run)
    if config.get("explain"):
        from pipeline.explain import explain
        explain(encoder, head, rows["validation"], config, run, device)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    run = Path(args.run)
    run.mkdir(parents=True, exist_ok=False)
    started = time.time()
    write_json(run / "status.json", dict(state="running", started_at=datetime.now(timezone.utc).isoformat()))
    try:
        run_experiment(config, run)
    except BaseException:
        write_json(run / "status.json", dict(state="failed", elapsed_seconds=time.time() - started,
                                             traceback=traceback.format_exc()))
        raise
    write_json(run / "status.json", dict(state="completed", elapsed_seconds=time.time() - started,
        finished_at=datetime.now(timezone.utc).isoformat(), jetson_validation="pending"))


if __name__ == "__main__":
    main()
