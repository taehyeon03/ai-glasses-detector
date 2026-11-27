"""Evaluate consented sessions by inspection and keep each domain separate."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from pipeline.field_metrics import aggregate
from pipeline.onnx_runtime import Runtime
from pipeline.records import append_jsonl,sha256,write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--bundle",required=True)
    parser.add_argument("--sessions",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    runtime=Runtime(args.bundle)
    records=[]
    for manifest in sorted(Path(args.sessions).glob("session-*/frames.jsonl")):
        for line in manifest.read_text().splitlines():
            row=json.loads(line)
            if not row.get("consent_confirmed"):raise ValueError("Consent flag missing")
            image_path=(manifest.parent/row["image"]).resolve()
            if not image_path.is_relative_to(manifest.parent.resolve()):raise ValueError("Invalid image path")
            image=cv2.imread(str(image_path))
            if image is None:raise ValueError(f"Cannot read {image_path.name}")
            prediction=runtime.predict(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
            record=dict(**row,**prediction)
            append_jsonl(output/"frame-predictions.jsonl",record);records.append(record)
    if not records:
        write_json(output/"status.json",dict(state="pending",reason="No consented camera inspections"))
        print("No camera inspections. Field metrics remain pending.")
        return
    domains=aggregate(records,runtime.metadata["threshold"])
    timing=[r["pipeline_ms"] for r in records]
    write_json(output/"summary.json",dict(domains=domains,model_sha256=sha256(Path(args.bundle)/"model.onnx"),
        preprocessing_plus_inference_ms=dict(p50=float(np.percentile(timing,50)),p95=float(np.percentile(timing,95))),
        camera_to_result_latency="pending: offline image evaluation excludes acquisition and sensor buffering",
        jetson_validation="pending"))
    write_json(output/"status.json",dict(state="completed",kind="field_inspection_evaluation"))


if __name__=="__main__":main()
