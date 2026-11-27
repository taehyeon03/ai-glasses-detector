"""Task attribution and controlled occlusion on validation images only."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from PIL import Image
from torchvision.transforms import GaussianBlur

from pipeline.probe import transform
from pipeline.records import append_jsonl, write_json


def integrated_gradients(score, image, baseline, steps):
    gradient = torch.zeros_like(image)
    for step in range(steps + 1):
        point = (baseline + (image - baseline) * step / steps).detach().requires_grad_(True)
        derivative = torch.autograd.grad(score(point).sum(), point)[0]
        gradient += derivative * (0.5 if step in (0, steps) else 1.0)
    attribution = (image - baseline) * gradient / steps
    with torch.no_grad():
        delta = (score(image) - score(baseline)).item()
    return attribution.detach(), dict(score_delta=delta, attribution_sum=attribution.sum().item(),
        completeness_absolute_error=abs(delta - attribution.sum().item()))


def patch_map(attribution, patch=16):
    # Sum signed contributions rather than treating absolute gradients as support.
    return torch.nn.functional.avg_pool2d(attribution.sum(1, keepdim=True), patch) * patch ** 2


def mask_patches(image, baseline, indices, patch):
    result = image.clone()
    width = image.shape[-1] // patch
    for index in indices:
        y, x = divmod(int(index), width)
        result[:, :, y * patch:(y + 1) * patch, x * patch:(x + 1) * patch] = baseline[
            :, :, y * patch:(y + 1) * patch, x * patch:(x + 1) * patch]
    return result


def explain(encoder, head, rows, config, run, device):
    destination = run / "explanations-validation"
    destination.mkdir()
    prediction_rows = [json.loads(v) for v in (run / "validation-predictions.jsonl").read_text().splitlines()]
    # Predeclared sampling includes both correct and incorrect predictions for each class.
    selected, counts = [], {}
    for index, result in enumerate(prediction_rows):
        bucket = (result["truth"], result["prediction"])
        if counts.get(bucket, 0) < 2:
            selected.append(index)
            counts[bucket] = counts.get(bucket, 0) + 1
    for index in range(len(rows)):
        if len(selected) >= config["explanation_samples"]:
            break
        if index not in selected:
            selected.append(index)
    selected = selected[:config["explanation_samples"]]
    write_json(destination / "selection.json", dict(split="validation", indices=selected,
        policy="first two per truth/prediction cell; then first unselected rows", seed=config["seed"]))
    preprocess = transform(config["image_size"])
    generator = torch.Generator().manual_seed(config["seed"])
    for index in selected:
        row = rows[index]
        record = prediction_rows[index]
        target = record["prediction"]
        with Image.open(row["path"]) as original:
            image = preprocess(original.convert("RGB")).unsqueeze(0).to(device)
            display = np.asarray(original.convert("RGB").resize((config["image_size"],) * 2))
        def margin(batch):
            logits = head(encoder(batch))
            return logits[:, target] - logits[:, 1 - target]
        with torch.no_grad():
            attention = encoder.get_last_selfattention(image)[0, :, 0, 1:]
            grid = config["image_size"] // 16
            attention = attention.reshape(-1, grid, grid).cpu().numpy()
            original_margin = margin(image).item()
        fig, axes = plt.subplots(3, 3, figsize=(10, 10))
        axes.flat[0].imshow(display)
        axes.flat[0].set_title(f"truth={row['label']} prediction={target}")
        maps = {}
        for name, baseline in [("mean", torch.zeros_like(image)),
                               ("blur", GaussianBlur(31, sigma=10)(image))]:
            attribution, completeness = integrated_gradients(margin, image, baseline, config["ig_steps"])
            heat = patch_map(attribution).flatten()
            maps[name] = heat
            append_jsonl(destination / "attribution.jsonl", dict(sample_id=row["sample_id"],
                target_class=target, score="target logit minus other logit", baseline=name,
                steps=config["ig_steps"], **completeness))
            np.savez_compressed(destination / f"sample-{index}-{name}.npz",
                                signed_ig=attribution.cpu().numpy(), patch_contributions=heat.cpu().numpy())
            ax = axes.flat[1 if name == "mean" else 2]
            ax.imshow(display)
            heatmap = torch.nn.functional.interpolate(heat.reshape(1, 1, grid, grid),
                size=image.shape[-2:], mode="nearest")[0, 0].cpu().numpy()
            bound = max(float(np.abs(heatmap).max()), 1e-9)
            ax.imshow(heatmap, cmap="bwr", vmin=-bound, vmax=bound, alpha=0.55)
            ax.set_title(f"IG ({name}); red supports class {target}")
            for fraction in [0.05, 0.10, 0.20]:
                count = max(1, round(len(heat) * fraction))
                top = heat.topk(count).indices.tolist()
                with torch.no_grad():
                    masked_margin = margin(mask_patches(image, baseline, top, 16)).item()
                    random_drops = []
                    for _ in range(config["random_mask_repeats"]):
                        indices = torch.randperm(len(heat), generator=generator)[:count].tolist()
                        random_drops.append(original_margin - margin(mask_patches(image, baseline, indices, 16)).item())
                append_jsonl(destination / "occlusion.jsonl", dict(sample_id=row["sample_id"],
                    truth=row["label"], target_class=target, baseline=name,
                    masked_patches=count, total_patches=len(heat), fraction=count / len(heat),
                    original_margin=original_margin, top_margin_drop=original_margin - masked_margin,
                    random_margin_drop_mean=float(np.mean(random_drops)),
                    random_margin_drop_std=float(np.std(random_drops)), random_drops=random_drops))
        # Raw attention is intentionally separate from class-conditional attribution.
        for ax, head_map, head_index in zip(list(axes.flat)[3:], attention, range(len(attention))):
            ax.imshow(head_map, cmap="inferno")
            ax.set_title(f"DINO raw attention head {head_index}")
        for ax in axes.flat:
            ax.axis("off")
        fig.tight_layout()
        fig.savefig(destination / f"sample-{index}.png", dpi=150)
        plt.close(fig)
        np.save(destination / f"sample-{index}-attention.npy", attention)
        count = max(1, round(len(maps["mean"]) * 0.10))
        a = set(maps["mean"].topk(count).indices.tolist())
        b = set(maps["blur"].topk(count).indices.tolist())
        append_jsonl(destination / "baseline-stability.jsonl", dict(sample_id=row["sample_id"],
            top10_percent_overlap=len(a & b) / count))
        print(f"explanation validation index={index}", flush=True)
