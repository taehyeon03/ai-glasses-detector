"""Prepare matched views with geometry that is independent of class labels."""
import argparse
import json
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from pipeline.data import prepare
from pipeline.records import sha256, write_json

YUNET_REVISION = "48b10fa505aeb51fbd127fc60a5c660040e823b7"
YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/" + YUNET_REVISION +
             "/models/face_detection_yunet/face_detection_yunet_2023mar.onnx")
MEAN_RGB = np.array([123, 116, 104], dtype=np.uint8)


def clip_box(box, size=224):
    x0, y0, x1, y1 = box
    return [max(0, min(size - 1, int(np.floor(x0)))),
            max(0, min(size - 1, int(np.floor(y0)))),
            max(1, min(size, int(np.ceil(x1)))),
            max(1, min(size, int(np.ceil(y1))))]


def geometry(face, size=224):
    points = np.asarray(face[4:14]).reshape(5, 2)
    eyes = sorted(points[:2], key=lambda p: p[0])
    left, right = eyes
    distance = float(np.linalg.norm(right - left))
    if distance < 12:
        return None
    center = (left + right) / 2
    # Geometry estimates broad eyewear regions. It does not locate camera lenses.
    box = clip_box([center[0] - 1.12 * distance, min(left[1], right[1]) - .52 * distance,
                    center[0] + 1.12 * distance, max(left[1], right[1]) + .55 * distance], size)
    def around(point, radius_x, radius_y):
        return clip_box([point[0] - radius_x * distance, point[1] - radius_y * distance,
                         point[0] + radius_x * distance, point[1] + radius_y * distance], size)
    left_outer = left + np.array([-.46 * distance, 0])
    right_outer = right + np.array([.46 * distance, 0])
    regions = dict(glasses=box, lens_left=around(left, .34, .33),
                   lens_right=around(right, .34, .33),
                   outer_left=around(left_outer, .22, .28),
                   outer_right=around(right_outer, .22, .28),
                   lower_face=around(points[3:5].mean(0), .35, .25),
                   forehead=around(center + np.array([0, -.90 * distance]), .35, .25))
    side = max(8, int(.4 * distance))
    # Select the corner with the least overlap with the detected face box.
    fx, fy, fw, fh = face[:4]
    candidates = [[0, 0, side, side], [size-side, 0, size, side],
                  [0, size-side, side, size], [size-side, size-side, size, size]]
    def overlap(b):
        return max(0, min(b[2], fx+fw)-max(b[0], fx)) * max(0, min(b[3], fy+fh)-max(b[1], fy))
    regions["background_corner"] = min(candidates, key=overlap)
    return dict(roi=box, regions=regions, landmarks=points.tolist(),
                face_box=[float(v) for v in face[:4]], confidence=float(face[-1]))


def matched_views(original, info, size):
    full = np.asarray(original.resize((size, size), Image.Resampling.BILINEAR)).copy()
    if info is None:
        # The same fallback in all conditions preserves the comparison's sample set.
        return {name: full.copy() for name in ["full", "roi_mask", "roi_crop"]}
    x0, y0, x1, y1 = info["roi"]
    masked = np.empty_like(full)
    masked[:] = MEAN_RGB
    masked[y0:y1, x0:x1] = full[y0:y1, x0:x1]
    sx, sy = original.width / size, original.height / size
    crop = original.crop((x0*sx, y0*sy, x1*sx, y1*sy)).resize((size, size), Image.Resampling.BILINEAR)
    return dict(full=full, roi_mask=masked, roi_crop=np.asarray(crop))


def build(config):
    destination = Path(config["view_cache"])
    destination.mkdir(parents=True, exist_ok=True)
    index_path = destination / "metadata.json"
    if index_path.exists():
        saved = json.loads(index_path.read_text())
        if saved["source_manifest_sha256"] != config["dataset_manifest_sha256"]:
            raise ValueError("View cache belongs to a different dataset")
        if saved["size"] != config["image_size"] or saved["preprocessing_version"] != 1:
            raise ValueError("View cache transform mismatch")
        for name, digest in saved["view_sha256"].items():
            if sha256(destination / f"{name}.npy") != digest:
                raise ValueError(f"View cache changed: {name}")
        return saved
    source = prepare(config["dataset_root"], config["image_cache"])
    if source["release_checksums_sha256"] != config["dataset_manifest_sha256"]:
        raise ValueError("Source release does not match pinned manifest")
    detector_path = destination / "face_detection_yunet_2023mar.onnx"
    if not detector_path.exists():
        urllib.request.urlretrieve(YUNET_URL, detector_path)
    size = config["image_size"]
    detector = cv2.FaceDetectorYN.create(str(detector_path), "", (size, size), .6, .3, 5000)
    rows = [dict(row, split=split) for split in ["train", "validation", "test"]
            for row in source["rows"][split]]
    arrays = {name: np.lib.format.open_memmap(destination / f"{name}.npy", mode="w+",
              dtype=np.uint8, shape=(len(rows), 3, size, size))
              for name in ["full", "roi_mask", "roi_crop"]}
    failed = []
    for index, row in enumerate(rows):
        with Image.open(row["path"]) as image:
            original = image.convert("RGB")
            small = np.asarray(original.resize((size, size), Image.Resampling.BILINEAR))
            detector.setScoreThreshold(.6)
            _, faces = detector.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
            low_confidence = False
            if faces is None:
                detector.setScoreThreshold(.3)
                _, faces = detector.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
                low_confidence = True
            info = None
            if faces is not None:
                face = max(faces, key=lambda v: v[2] * v[3])
                info = geometry(face, size)
            if info is None:
                failed.append(index)
            row["geometry"] = info
            row["geometry_review"] = "pending" if info is not None else "detector_failed"
            row["low_confidence_detection"] = low_confidence
            for name, view in matched_views(original, info, size).items():
                arrays[name][index] = view.transpose(2, 0, 1)
        if index % 500 == 0:
            print(f"view cache {index}/{len(rows)}; failures={len(failed)}", flush=True)
    for array in arrays.values():
        array.flush()
    record = dict(preprocessing_version=1, size=size, source_manifest_sha256=config["dataset_manifest_sha256"],
                  detector_revision=YUNET_REVISION, detector_url=YUNET_URL,
                  detector_sha256=sha256(detector_path), rows=rows,
                  detection_failures=failed, exact_camera_annotations="pending",
                  audit=source["audit"],
                  view_sha256={name: sha256(destination / f"{name}.npy") for name in arrays})
    write_json(index_path, record)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    build(json.loads(Path(args.config).read_text()))
