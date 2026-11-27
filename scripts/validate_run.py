"""Check that a completed run satisfies the common presentation record contract."""
import argparse
import hashlib
import json
from pathlib import Path


def validate(root):
    root = Path(root)
    status = json.loads((root / "status.json").read_text())
    if status["state"] != "completed":
        raise ValueError("Run has not completed")
    summary = json.loads((root / "summary.json").read_text())
    provenance = json.loads((root / "provenance.json").read_text())
    for key in ["git_commit", "git_dirty", "command", "config", "started_at", "python"]:
        if key not in provenance:
            raise ValueError(f"Missing provenance: {key}")
    for key in ["dataset_id", "dataset_revision", "seed"]:
        if key not in provenance["config"]:
            raise ValueError(f"Missing data/config identity: {key}")
    rows = [json.loads(v) for v in (root / "metrics.jsonl").read_text().splitlines()]
    for row in rows:
        for key in ["loss", "accuracy", "macro_f1", "confusion_matrix", "class_order",
                    "false_positive_rate", "camera_recall", "epoch", "step", "split"]:
            if key not in row:
                raise ValueError(f"Missing metric: {key}")
        cm = row["confusion_matrix"]
        if len(cm) != 2 or any(len(v) != 2 for v in cm):
            raise ValueError("Expected a 2x2 confusion matrix")
        if row["class_order"] != ["ordinary_glasses", "camera_glasses"]:
            raise ValueError("Class order changed")
        if sum(map(sum, cm)) != row["n"]:
            raise ValueError("Confusion matrix support does not match sample count")
    evaluation_only = provenance["config"].get("evaluation_only",False)
    expected = {0} if evaluation_only else set(range(1, provenance["config"]["epochs"] + 1))
    for split in ["train", "validation"]:
        items = [v for v in rows if v["split"] == split]
        if {v["epoch"] for v in items} != expected or len(items) != len(expected):
            raise ValueError(f"Missing or repeated epochs: {split}")
    tests = [v for v in rows if v["split"] == "test"]
    if len(tests) != 1 or tests[0]["epoch"] != summary["best_epoch"]:
        raise ValueError("Expected one test evaluation for selected checkpoint")
    digest = hashlib.sha256((root / "checkpoint.pt").read_bytes()).hexdigest()
    if digest != summary["checkpoint_sha256"]:
        raise ValueError("Checkpoint changed after evaluation")
    for split in ["train", "validation", "test"]:
        if not (root / f"{split}-predictions.jsonl").is_file():
            raise ValueError(f"Missing per-image predictions: {split}")
        if not (root / f"{split}-confusion.png").is_file():
            raise ValueError(f"Missing confusion figure: {split}")
    figure = "evaluation.png" if evaluation_only else "learning_curves.png"
    for file in ["pip-freeze.txt", figure, "data-audit.json"]:
        if not (root / file).is_file():
            raise ValueError(f"Missing artifact: {file}")
    return dict(valid=True, epochs=0 if evaluation_only else len(expected), test_evaluations=len(tests),
                jetson_validation=summary["jetson_validation"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    args = parser.parse_args()
    print(json.dumps(validate(args.run), indent=2))
