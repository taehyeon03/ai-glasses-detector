"""Keep five temporally spaced frames as one inspection. Do not save images."""
import uuid
from datetime import datetime, timezone

from pipeline.field_metrics import aggregate
from pipeline.records import append_jsonl, write_json


class Recorder:
    def __init__(self, output, manifest):
        self.output = output
        self.manifest = manifest
        self.session = uuid.uuid4().hex[:12]
        self.records = []
        self.active = None

    def start(self, label, domain, person, now):
        if self.active is not None:
            raise ValueError("Inspection is already active")
        if label not in {"ordinary_glasses", "no_glasses", "camera_glasses"}:
            raise ValueError("Unknown label")
        if label == "camera_glasses" and domain != "screen_recapture":
            raise ValueError("Physical camera glasses have not been acquired")
        self.active = dict(inspection_id=uuid.uuid4().hex[:12], label=label, domain=domain,
                           person_group_id=person, count=0, next_time=now)

    def observe(self, prediction, now):
        if self.active is None or now < self.active["next_time"]:
            return False
        item = self.active
        self.output.mkdir(parents=True, exist_ok=True)
        row = dict(session_id=self.session, inspection_id=item["inspection_id"],
            person_group_id=item["person_group_id"], label=item["label"], domain=item["domain"],
            frame_index=item["count"], consent_confirmed=True,
            captured_at=datetime.now(timezone.utc).isoformat(), **prediction)
        append_jsonl(self.output / "frame-predictions.jsonl", row)
        self.records.append(row)
        item["count"] += 1
        item["next_time"] = now + 1
        if item["count"] == 5:
            self.active = None
            self.flush()
            return True
        return False

    def flush(self):
        self.active = None
        if not self.records:
            return {}
        result = aggregate(self.records, self.manifest["threshold"])
        write_json(self.output / "summary.json", dict(domains=result,
            model_sha256=self.manifest["model_sha256"], model=self.manifest.get("display_name", self.manifest["mode"]),
            images_saved=False, jetson_validation="pending",
            timing_scope="read call plus preprocessing/inference; excludes sensor exposure and upstream buffers"))
        return result
