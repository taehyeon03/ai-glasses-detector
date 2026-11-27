"""Refine explanations without training again or consulting the test set."""
import argparse
import json
import shutil
import time
import traceback
from pathlib import Path

import torch
from torch import nn

from pipeline.data import prepare
from pipeline.explain import explain
from pipeline.probe import load_encoder
from pipeline.records import provenance, sha256, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-run", required=True)
    parser.add_argument("--analysis-dir", required=True)
    parser.add_argument("--max-steps", type=int, default=512)
    args = parser.parse_args()
    source, output = Path(args.training_run), Path(args.analysis_dir)
    output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    write_json(output / "status.json", dict(state="running", kind="checkpoint_analysis"))
    try:
        saved = torch.load(source / "checkpoint.pt", map_location="cpu", weights_only=True)
        config = dict(saved["config"], ig_steps=32, ig_max_steps=args.max_steps, ig_tolerance=0.02)
        record = provenance(config)
        record.update(kind="checkpoint_analysis", training_run=str(source),
                      checkpoint_sha256=sha256(source / "checkpoint.pt"),
                      training_metrics_reference=str(source / "summary.json"))
        write_json(output / "provenance.json", record)
        shutil.copy2(source / "validation-predictions.jsonl", output / "validation-predictions.jsonl")
        data = prepare(config["dataset_root"], config["image_cache"])
        device = torch.device(config["device"])
        encoder = load_encoder(config, device)
        head = nn.Linear(saved["input_features"], 2).to(device)
        head.load_state_dict(saved["head"])
        head.eval()
        explain(encoder, head, data["rows"]["validation"], config, output, device)
        write_json(output / "status.json", dict(state="completed", kind="checkpoint_analysis",
                                               elapsed_seconds=time.time() - started))
    except BaseException:
        write_json(output / "status.json", dict(state="failed", traceback=traceback.format_exc()))
        raise


if __name__ == "__main__":
    main()
