import json
import tempfile
import unittest
from pathlib import Path

from pipeline.live_inspection import Recorder


class LiveInspectionTests(unittest.TestCase):
    def recorder(self, path):
        return Recorder(Path(path), dict(threshold=.5, model_sha256="test", mode="test"))

    def test_five_frames_count_as_one_false_positive_without_saving_images(self):
        with tempfile.TemporaryDirectory() as path:
            recorder = self.recorder(path)
            recorder.start("ordinary_glasses", "real_worn", "p1", 0)
            for now in range(5):
                recorder.observe(dict(camera_probability=.8, reason="scored"), now)
                recorder.observe(dict(camera_probability=.8, reason="scored"), now+.2)
            result = recorder.flush()["real_worn"]
            self.assertEqual(result["n_inspections"], 1)
            self.assertEqual(result["false_positive_rate"], 1)
            self.assertIsNone(result["camera_recall"])
            self.assertEqual(len(list(Path(path).glob("*.png"))), 0)
            self.assertEqual(len((Path(path)/"frame-predictions.jsonl").read_text().splitlines()), 5)

    def test_missing_geometry_requires_retry_and_interrupted_capture_is_incomplete(self):
        with tempfile.TemporaryDirectory() as path:
            recorder = self.recorder(path)
            recorder.start("ordinary_glasses", "real_worn", "p1", 0)
            for now in range(5):
                recorder.observe(dict(camera_probability=None, reason="geometry_missing"), now)
            recorder.start("ordinary_glasses", "real_worn", "p1", 10)
            recorder.observe(dict(camera_probability=.2, reason="scored"), 10)
            recorder.flush()
            result = json.loads((Path(path)/"summary.json").read_text())["domains"]["real_worn"]
            self.assertEqual(result["n_scored"], 0)
            self.assertEqual(result["incomplete_inspections"], 1)
            self.assertEqual(result["retry_rate"], .5)

    def test_no_physical_positive_is_fabricated(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(ValueError):
                self.recorder(path).start("camera_glasses", "real_worn", "p1", 0)


if __name__ == "__main__":
    unittest.main()
