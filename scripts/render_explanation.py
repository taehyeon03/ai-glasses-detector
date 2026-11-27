"""Render a compact comparison from saved arrays without another model run."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run, analysis = Path(args.run), Path(args.analysis)
    config = json.loads((run / "provenance.json").read_text())["config"]
    digest = json.loads((run / "data-audit.json").read_text())["release_checksums_sha256"]
    index = json.loads((Path(config["image_cache"]) / digest / "index.json").read_text())
    row = index["rows"]["validation"][args.index]
    predictions = [json.loads(v) for v in (run / "validation-predictions.jsonl").read_text().splitlines()]
    target = predictions[args.index]["prediction"]
    size = config["image_size"]
    with Image.open(row["path"]) as original:
        rgb = np.asarray(original.convert("RGB").resize((size, size), Image.Resampling.BILINEAR))
    folder = analysis / "explanations-validation"
    attention = np.load(folder / f"sample-{args.index}-attention.npy").mean(0)
    ig = np.load(folder / f"sample-{args.index}-blur.npz")["patch_contributions"].reshape(attention.shape)
    factor = size // attention.shape[0]
    attention = np.repeat(np.repeat(attention, factor, 0), factor, 1)
    ig = np.repeat(np.repeat(ig, factor, 0), factor, 1)
    names = ["ordinary", "camera"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4), layout="constrained")
    for ax in axes:
        ax.imshow(rgb)
        ax.axis("off")
    axes[0].set_title(f"Truth: {names[row['label']]}\nPrediction: {names[target]}")
    axes[1].imshow(attention, cmap="inferno", alpha=0.6)
    axes[1].set_title("DINO attention\nMean across all heads")
    bound = max(float(np.abs(ig).max()), 1e-9)
    axes[2].imshow(ig, cmap="bwr", vmin=-bound, vmax=bound, alpha=0.55)
    axes[2].set_title(f"IG for {names[target]}\nRed supports; blue opposes")
    fig.suptitle(f"Validation example {args.index}; research visualization")
    fig.savefig(args.output, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
