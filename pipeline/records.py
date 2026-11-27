"""Shared metric schema and durable experiment records."""
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CLASSES = ["ordinary_glasses", "camera_glasses"]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temp.replace(path)


def append_jsonl(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def metrics(labels, predictions, loss):
    cm = [[0, 0], [0, 0]]
    if len(labels) == 0 or len(labels) != len(predictions):
        raise ValueError("Expected matching non-empty labels and predictions")
    for actual, predicted in zip(labels, predictions):
        cm[int(actual)][int(predicted)] += 1
    per_class = {}
    for i, name in enumerate(CLASSES):
        tp = cm[i][i]
        precision = tp / max(sum(row[i] for row in cm), 1)
        recall = tp / max(sum(cm[i]), 1)
        per_class[name] = dict(precision=precision, recall=recall,
                               f1=2 * precision * recall / max(precision + recall, 1e-12),
                               support=sum(cm[i]))
    return dict(n=len(labels), loss=float(loss), accuracy=(cm[0][0] + cm[1][1]) / len(labels),
                macro_f1=sum(v["f1"] for v in per_class.values()) / 2,
                confusion_matrix=cm, class_order=CLASSES, per_class=per_class,
                false_positive_rate=cm[0][1] / max(sum(cm[0]), 1),
                camera_recall=per_class[CLASSES[1]]["recall"])


def audit_splits(rows):
    keys = ["sample_id", "identity_group_id", "regeneration_family_id",
            "portrait_reference_sha256", "image_sha256"]
    report = {}
    for key in keys:
        seen = {}
        for split, items in rows.items():
            for row in items:
                value = row.get(key)
                if not value:
                    raise ValueError(f"Missing {key} in {split}")
                if value in seen and seen[value] != split:
                    raise ValueError(f"Cross-split leakage: {key}")
                seen[value] = split
        report[key] = dict(cross_split_overlap=0, unique_values=len(seen))
    hashes = [r["image_sha256"] for items in rows.values() for r in items]
    if len(hashes) != len(set(hashes)):
        raise ValueError("Duplicate output images")
    return report


def provenance(config):
    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()
    return dict(schema_version=1, started_at=datetime.now(timezone.utc).isoformat(),
                config=config, command=sys.argv, git_commit=git("rev-parse", "HEAD"),
                git_branch=git("branch", "--show-current"),
                git_dirty=bool(git("status", "--porcelain")),
                python=sys.version, platform=platform.platform(),
                jetson_validation="pending")
