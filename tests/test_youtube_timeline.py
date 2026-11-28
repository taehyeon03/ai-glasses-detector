import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from pipeline import youtube_timeline as yt


class TimelineParsingTests(unittest.TestCase):
    def test_time_formats(self):
        self.assertEqual(yt.parse_time("75"), 75)
        self.assertEqual(yt.parse_time("1:15"), 75)
        self.assertEqual(yt.parse_time("1:01:15"), 3675)
        self.assertEqual(yt.parse_time("1m15s"), 75)
        self.assertEqual(yt.parse_time("2.5"), 2.5)
        with self.assertRaises(ValueError):
            yt.parse_time("a:b")

    def test_ranges_points_and_labels(self):
        segments = yt.parse_timeline("0:10-0:20=ordinary, 1:00\n2:00-2:05=camera", "unknown")
        self.assertEqual([(s["start"], s["end"], s["label"]) for s in segments],
                         [(10, 20, "ordinary_glasses"), (58, 62, "unknown"), (120, 125, "camera_glasses")])
        self.assertEqual(yt.parse_timeline("0:01")[0]["start"], 0)

    def test_invalid_timelines(self):
        for text in ["", "0:20-0:10", "0:00-20:00", "0:10=robot"]:
            with self.assertRaises(ValueError):
                yt.parse_timeline(text)


class SummaryTests(unittest.TestCase):
    def frames(self, scores):
        return [dict(camera_probability=s, reason="scored" if s is not None else "geometry_missing") for s in scores]

    def test_mean_threshold_and_hold(self):
        seg = dict(index=0, start=0, end=5, label="ordinary_glasses")
        alarm = yt.summarize_segment(seg, self.frames([.9, .7, .6]), .5)
        self.assertEqual(alarm["verdict"], "카메라 안경 의심")
        self.assertFalse(alarm["correct"])
        ok = yt.summarize_segment(seg, self.frames([.1, .2, .9]), .5)
        self.assertEqual(ok["prediction"], "ordinary_glasses")
        self.assertTrue(ok["correct"])
        hold = yt.summarize_segment(seg, self.frames([.9, None, None, None]), .5)
        self.assertEqual(hold["verdict"], "판정 보류")
        self.assertIsNone(hold["correct"])
        self.assertEqual(hold["reasons"], {"scored": 1, "geometry_missing": 3})

    def test_missing_class_stays_null(self):
        seg = dict(index=0, start=0, end=5, label="ordinary_glasses")
        summary = yt.summarize_run([yt.summarize_segment(seg, self.frames([.9, .9, .9]), .5)])
        self.assertEqual(summary["false_positive_rate"], 1)
        self.assertIsNone(summary["camera_recall"])


class FakeRuntime:
    metadata = dict(threshold=.5, display_name="fake", mode="fake", model_sha256="x")

    def predict(self, rgb):
        return dict(camera_probability=float(rgb[0, 0, 0]) / 255, reason="scored", pipeline_ms=1.0)


class RunRecordTests(unittest.TestCase):
    def test_run_writes_records_and_history_without_video(self):
        video = dict(video_id="abc", title="t", channel="c", duration=100, webpage_url="u",
                     stream_url="s", width=4, height=4, format_id="f", http_headers={})

        def frames(_video, start, end, fps):
            for i in range(int((end - start) * fps)):
                yield start + i / fps, np.full((4, 4, 3), 230, np.uint8)
        with tempfile.TemporaryDirectory() as path, \
                mock.patch.object(yt, "resolve_video", return_value=video), \
                mock.patch.object(yt, "stream_frames", side_effect=frames):
            record = yt.run_test("bundle", "https://example", "0:00-0:03=ordinary", fps=1,
                                 output_root=path, runtime=FakeRuntime(), echo=False)
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["summary"]["false_positive_rate"], 1)
            run_dir = Path(path) / record["run_id"]
            self.assertEqual(len((run_dir / "frame-predictions.jsonl").read_text().splitlines()), 3)
            self.assertNotIn("stream_url", json.loads((run_dir / "run.json").read_text())["video"])
            self.assertEqual(len(yt.read_history(path)), 1)
            self.assertFalse(list(Path(path).rglob("*.mp4")))

    def test_failure_is_kept(self):
        with tempfile.TemporaryDirectory() as path, \
                mock.patch.object(yt, "resolve_video", side_effect=RuntimeError("blocked")):
            record = yt.run_test("bundle", "https://example", "0:00-0:03", output_root=path,
                                 runtime=FakeRuntime(), echo=False)
            self.assertEqual(record["status"], "failed")
            self.assertEqual(yt.read_history(path)[0]["status"], "failed")
            self.assertIn("blocked", (Path(path) / record["run_id"] / "run.log").read_text())


if __name__ == "__main__":
    unittest.main()


class TestSetTests(unittest.TestCase):
    def write(self, path, data):
        Path(path).write_text(json.dumps(data))
        return path

    def case(self, **extra):
        return dict(dict(id="a", url="https://www.youtube.com/watch?v=x", product="p", training_overlap="ood",
                         segments=[dict(start="0:10", end="0:20", label="camera_glasses", view="frontal")],
                         review=dict(status="pending_human_review")), **extra)

    def test_valid_set_and_problems(self):
        from scripts.youtube_testset import load_set, timeline
        with tempfile.TemporaryDirectory() as path:
            ok = load_set(self.write(f"{path}/ok.json", dict(name="s", cases=[self.case()])))
            self.assertEqual(timeline(ok["cases"][0]), ["0:10-0:20=camera_glasses"])
            bad = dict(name="s", cases=[self.case(), self.case(url="https://example.com",
                       review=dict(status="confirmed?"), segments=[dict(start="0:20", end="0:10", label="x")])])
            with self.assertRaises(ValueError) as error:
                load_set(self.write(f"{path}/bad.json", bad))
            message = str(error.exception)
            for word in ["중복", "YouTube", "review.status", "segments[0]"]:
                self.assertIn(word, message)


class OverlapTests(unittest.TestCase):
    def test_overlap_required_and_no_glasses_not_applicable(self):
        from scripts.youtube_testset import load_set, overlap_of, report
        case = dict(id="a", url="https://www.youtube.com/watch?v=x", product="p", training_overlap="ood",
                    training_product_ids=[],
                    segments=[dict(start="0:00", end="0:05", label="camera_glasses", view="frontal"),
                              dict(start="0:10", end="0:15", label="no_glasses", view="frontal")],
                    review=dict(status="pending_human_review"))
        with tempfile.TemporaryDirectory() as path:
            Path(f"{path}/s.json").write_text(json.dumps(dict(name="s", cases=[case])))
            load_set(f"{path}/s.json")
            Path(f"{path}/b.json").write_text(json.dumps(dict(name="s", cases=[dict(case, training_overlap="in_training")])))
            with self.assertRaises(ValueError):
                load_set(f"{path}/b.json")
        self.assertEqual(overlap_of(case, "no_glasses"), "not_applicable")
        seg = lambda label, pred: dict(label=label, verdict="v", prediction=pred, mean_score=.5, n_scored=3, n_frames=3)
        record = dict(run_id="r", status="completed",
                      segments=[seg("camera_glasses", "camera_glasses"), seg("no_glasses", "ordinary_glasses")])
        result = report(dict(name="s"), dict(display_name="m"), [(case, record)])
        self.assertEqual(result["by_training_overlap"]["ood"]["camera_recall"], 1)
        self.assertEqual(result["by_training_overlap"]["not_applicable"]["n_segments"], 1)


class PersonGroupTests(unittest.TestCase):
    def test_person_group_needs_basis(self):
        from scripts.youtube_testset import load_set
        case = dict(id="a", url="https://www.youtube.com/watch?v=x", product="p", training_overlap="ood",
                    segments=[dict(start="0:00", end="0:05", label="ordinary_glasses", view="frontal")],
                    review=dict(status="pending_human_review"), person_group="korean")
        with tempfile.TemporaryDirectory() as path:
            Path(f"{path}/s.json").write_text(json.dumps(dict(name="s", cases=[case])))
            with self.assertRaises(ValueError):
                load_set(f"{path}/s.json")
            Path(f"{path}/s.json").write_text(json.dumps(dict(name="s", cases=[dict(case, person_group_basis="Korean-language channel")])))
            load_set(f"{path}/s.json")
