"""Wait for the current study and then run the presentation comparisons."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from pipeline.records import write_json
from scripts.validate_run import validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-unit", required=True)
    parser.add_argument("--parent-runs", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--runs", required=True)
    args = parser.parse_args()
    root = Path(args.runs)
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "queue-status.json", dict(state="waiting", parent_unit=args.parent_unit))
    try:
        while True:
            result = subprocess.run(
                ["systemctl", "--user", "show", args.parent_unit, "--property=ActiveState", "--value"],
                check=True, text=True, capture_output=True,
            )
            if result.stdout.strip() not in {"active", "activating", "deactivating", "reloading"}:
                break
            time.sleep(20)
        config = json.loads(Path(args.config).read_text())
        for mode in config["modes"]:
            for seed in config["seeds"]:
                validate(Path(args.parent_runs) / f"{mode}-s{seed}")
        write_json(root / "queue-status.json", dict(state="running", parent_records_validated=15))
        subprocess.run([
            sys.executable, "-u", "-m", "pipeline.presentation_adaptation",
            "--config", args.config, "--runs", args.runs, "--require-parent", args.parent_runs,
        ], check=True)
        write_json(root / "queue-status.json", dict(state="completed"))
    except BaseException as error:
        write_json(root / "queue-status.json", dict(state="failed", error=str(error)))
        raise


if __name__ == "__main__":
    main()
