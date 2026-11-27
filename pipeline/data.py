"""Read the released Parquet files without keeping image bytes in RAM."""
import hashlib
import io
import json
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image
from torch.utils.data import Dataset

from pipeline.records import audit_splits, sha256, write_json

FIELDS = ["label", "sample_id", "product_id", "identity_group_id",
          "regeneration_family_id", "portrait_reference_sha256", "image_sha256",
          "quality_flags"]


def prepare(root, cache):
    root, cache = Path(root), Path(cache)
    fingerprint = sha256(root / "SHA256SUMS")
    index = cache / fingerprint / "index.json"
    if index.exists():
        saved = json.loads(index.read_text())
        audit_splits(saved["rows"])
        if all(Path(r["path"]).is_file() for rows in saved["rows"].values() for r in rows):
            return saved
    for line in (root / "SHA256SUMS").read_text().splitlines():
        expected, relative = line.split(maxsplit=1)
        file = (root / relative.lstrip("*")).resolve()
        if not file.is_relative_to(root.resolve()):
            raise ValueError("Checksum path escapes dataset")
        if sha256(file) != expected:
            raise ValueError(f"Release checksum mismatch: {file.name}")
    rows = {}
    for split in ["train", "validation", "test"]:
        rows[split] = []
        files = sorted((root / "data").glob(f"{split}-*.parquet"))
        if not files:
            raise ValueError(f"No data for {split}")
        destination = cache / fingerprint / split
        destination.mkdir(parents=True, exist_ok=True)
        for file in files:
            for batch in pq.ParquetFile(file).iter_batches(batch_size=16, columns=FIELDS + ["image"]):
                for row in batch.to_pylist():
                    blob = row.pop("image")["bytes"]
                    digest = hashlib.sha256(blob).hexdigest()
                    if digest != row["image_sha256"]:
                        raise ValueError("Image digest mismatch")
                    target = destination / f"{digest}.png"
                    if not target.exists():
                        Image.open(io.BytesIO(blob)).verify()
                        target.write_bytes(blob)
                    row["path"] = str(target)
                    rows[split].append(row)
    result = dict(release_checksums_sha256=fingerprint, rows=rows, audit=audit_splits(rows))
    expected_counts = {"train": [3500, 3500], "validation": [750, 750], "test": [750, 750]}
    for split, expected in expected_counts.items():
        actual = [sum(r["label"] == i for r in rows[split]) for i in range(2)]
        if actual != expected:
            raise ValueError(f"Unexpected counts for released split {split}: {actual}")
    write_json(index, result)
    return result


class Images(Dataset):
    def __init__(self, rows, transform):
        self.rows = rows
        self.transform = transform

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        with Image.open(row["path"]) as image:
            return self.transform(image.convert("RGB")), row["label"]
