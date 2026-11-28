"""Command-line YouTube timeline test.

python -m scripts.youtube_timeline_test --list-models
python -m scripts.youtube_timeline_test --model mobilenet-crop-s44 \
    --url https://www.youtube.com/watch?v=VIDEO --timeline "0:12-0:20=ordinary, 1:05=camera"
"""
import argparse
import json
from pathlib import Path

from pipeline.youtube_timeline import DEFAULT_MODELS, DEFAULT_ROOT, list_models, run_test


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--models-root", default=str(DEFAULT_MODELS))
    parser.add_argument("--model", help="Bundle folder name under --models-root, or a bundle path")
    parser.add_argument("--url")
    parser.add_argument("--timeline", help="e.g. '0:10-0:25=ordinary, 1:30, 2:00-2:10=camera'")
    parser.add_argument("--label", default="unknown", help="Default label: ordinary, camera, none, unknown")
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--save-frames", action="store_true", help="Save annotated JPEG frames under the private output")
    parser.add_argument("--output", default=str(DEFAULT_ROOT))
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    if args.list_models:
        print(json.dumps(list_models(args.models_root), indent=2, ensure_ascii=False))
        return
    if not (args.model and args.url and args.timeline):
        parser.error("--model, --url, --timeline are required")
    bundle = Path(args.model) if Path(args.model).is_dir() else Path(args.models_root) / args.model
    record = run_test(bundle, args.url, args.timeline, args.label, args.fps, args.save_frames,
                      args.output, note=args.note)
    print(json.dumps(dict(run_id=record["run_id"], status=record["status"], summary=record["summary"],
                          run_dir=str(Path(args.output) / record["run_id"])), indent=2, ensure_ascii=False))
    raise SystemExit(0 if record["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
