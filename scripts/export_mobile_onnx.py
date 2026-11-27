"""Export the validation-selected crop baseline for a laptop."""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from torch import nn

from pipeline.mobile_train import model, normalize
from pipeline.records import sha256, write_json
from scripts.validate_run import validate


class RawInput(nn.Module):
    def __init__(self, network):
        super().__init__()
        self.network = network

    def forward(self, global_image):
        return self.network(normalize(global_image))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--view-cache", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run, cache, output = map(Path, [args.run, args.view_cache, args.output])
    validate(run)
    saved = torch.load(run / "checkpoint.pt", map_location="cpu", weights_only=True)
    if saved["config"]["view"] != "roi_crop":
        raise ValueError("This laptop runtime requires the original-image crop baseline")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    network = model(pretrained=False)
    network.load_state_dict(saved["model"])
    network = RawInput(network).eval()
    rows = json.loads((cache / "metadata.json").read_text())["rows"]
    ids = [i for i, row in enumerate(rows) if row["split"] == "validation"][:5]
    images = np.load(cache / "roi_crop.npy", mmap_mode="r")
    sample = torch.from_numpy(np.array(images[ids[0]:ids[0]+1], copy=True))
    torch.onnx.export(network, sample, str(output / "model.onnx"),
                      input_names=["global_image"], output_names=["logits"],
                      opset_version=13, dynamo=False)
    onnx.checker.check_model(onnx.load(str(output / "model.onnx")))
    session = ort.InferenceSession(str(output / "model.onnx"), providers=["CPUExecutionProvider"])
    checks = []
    for index in ids:
        value = np.array(images[index:index+1], copy=True)
        with torch.no_grad():
            expected = network(torch.from_numpy(value)).numpy()
        actual = session.run(None, {"global_image": value})[0]
        checks.append(dict(validation_index=index, max_abs_logit_error=float(np.abs(expected-actual).max()),
                           same_decision=bool(expected.argmax() == actual.argmax())))
    passed = all(c["same_decision"] and c["max_abs_logit_error"] < .002 for c in checks)
    write_json(output / "parity.json", dict(passed=passed, cases=checks, jetson_validation="pending"))
    if not passed:
        raise ValueError("ONNX parity failed")
    detector = "face_detection_yunet_2023mar.onnx"
    shutil.copy2(cache / detector, output / detector)
    write_json(output / "manifest.json", dict(format_version=1, mode="mobilenet-roi_crop",
        display_name="MobileNetV3-Small / glasses crop / seed 44", image_size=224, local_size=112,
        threshold=.5, class_order=["ordinary_glasses", "camera_glasses"], batch_size=1, opset=13,
        source_checkpoint_sha256=sha256(run / "checkpoint.pt"), model_sha256=sha256(output / "model.onnx"),
        selection="seed 44 selected by validation F1 in the completed crop baseline study",
        input_names=["global_image"], normalization="inside ONNX graph", jetson_validation="pending"))
    print(json.dumps(dict(output=str(output), parity=checks)))


if __name__ == "__main__":
    main()
