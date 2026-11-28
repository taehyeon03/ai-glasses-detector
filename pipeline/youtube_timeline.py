"""Score chosen time ranges of a YouTube video with a fixed model bundle.

The video is streamed through ffmpeg and is never written to disk.
Annotated frames are saved only when requested, and only under the private output root.
Results from online video are a separate domain (`youtube_video`).
They are not merged with real_worn field measurements.
"""
import json
import re
import shutil
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np

from pipeline.records import append_jsonl, write_json

DEFAULT_ROOT = Path.home() / ".local/share/ai-glasses-field-evaluation/youtube"
DEFAULT_MODELS = Path.home() / ".local/share/ai-glasses-models"
LABELS = {"ordinary": "ordinary_glasses", "ordinary_glasses": "ordinary_glasses",
          "camera": "camera_glasses", "camera_glasses": "camera_glasses",
          "none": "no_glasses", "no_glasses": "no_glasses",
          "unknown": "unknown", "": "unknown"}
POINT_WINDOW = 2.0
MIN_SCORED_FRAMES = 3
MAX_SEGMENT_SECONDS = 600


def parse_time(text):
    """Accept `75`, `1:15`, `01:01:15` or `1m15s`; return seconds."""
    text = text.strip().lower()
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", text)
    if match and any(match.groups()):
        h, m, s = match.groups()
        return int(h or 0) * 3600 + int(m or 0) * 60 + float(s or 0)
    parts = text.split(":")
    if not 1 <= len(parts) <= 3 or not all(re.fullmatch(r"\d+(?:\.\d+)?", p) for p in parts):
        raise ValueError(f"시간 형식을 읽을 수 없습니다: {text!r}")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def parse_timeline(text, default_label="unknown"):
    """Parse `0:10-0:25=ordinary, 1:30, 2:00-2:10=camera` into segments.

    A single point becomes a window of +-POINT_WINDOW seconds.
    Separators: comma, semicolon or newline.
    """
    default_label = LABELS.get(default_label.strip().lower())
    if default_label is None:
        raise ValueError("알 수 없는 기본 라벨입니다")
    segments = []
    for raw in re.split(r"[,;\n]+", text):
        item = raw.strip()
        if not item:
            continue
        label = default_label
        if "=" in item:
            item, tag = item.split("=", 1)
            label = LABELS.get(tag.strip().lower())
            if label is None:
                raise ValueError(f"알 수 없는 라벨입니다: {tag.strip()!r}")
        if "-" in item.strip().lstrip("-"):
            start_text, end_text = item.split("-", 1)
            start, end = parse_time(start_text), parse_time(end_text)
        else:
            point = parse_time(item)
            start, end = max(point - POINT_WINDOW, 0.0), point + POINT_WINDOW
        if end <= start:
            raise ValueError(f"끝 시간이 시작 시간보다 빠릅니다: {raw.strip()!r}")
        if end - start > MAX_SEGMENT_SECONDS:
            raise ValueError(f"한 구간은 {MAX_SEGMENT_SECONDS}초를 넘을 수 없습니다: {raw.strip()!r}")
        segments.append(dict(index=len(segments), start=start, end=end, label=label))
    if not segments:
        raise ValueError("타임라인이 비어 있습니다")
    return segments


def format_time(seconds):
    seconds = float(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m}:{s:04.1f}"


def summarize_segment(segment, frames, threshold):
    """Mean of scored frame scores against the fixed bundle threshold."""
    scored = [f["camera_probability"] for f in frames if f.get("camera_probability") is not None]
    reasons = {}
    for f in frames:
        reasons[f["reason"]] = reasons.get(f["reason"], 0) + 1
    mean = sum(scored) / len(scored) if scored else None
    if len(scored) < MIN_SCORED_FRAMES:
        verdict, prediction = "판정 보류", None
    elif mean >= threshold:
        verdict, prediction = "카메라 안경 의심", "camera_glasses"
    else:
        verdict, prediction = "일반 안경 쪽으로 분류", "ordinary_glasses"
    label = segment["label"]
    if prediction is None or label in ("unknown", "no_glasses"):
        correct = None
    else:
        correct = prediction == label
    return dict(segment, n_frames=len(frames), n_scored=len(scored), reasons=reasons,
                mean_score=mean, max_score=max(scored) if scored else None,
                alarm_frame_ratio=sum(s >= threshold for s in scored) / len(scored) if scored else None,
                verdict=verdict, prediction=prediction, correct=correct)


def summarize_run(segments):
    """Segment-level counts. Missing classes stay null instead of 0 or 1."""
    def rate(items, predicted):
        decided = [s for s in items if s["prediction"] is not None]
        return sum(s["prediction"] == predicted for s in decided) / len(decided) if decided else None
    ordinary = [s for s in segments if s["label"] == "ordinary_glasses"]
    camera = [s for s in segments if s["label"] == "camera_glasses"]
    return dict(domain="youtube_video", unit="segment",
                n_segments=len(segments),
                n_decided=sum(s["prediction"] is not None for s in segments),
                n_alarm=sum(s["prediction"] == "camera_glasses" for s in segments),
                n_ordinary_labeled=len(ordinary), n_camera_labeled=len(camera),
                false_positive_rate=rate(ordinary, "camera_glasses"),
                camera_recall=rate(camera, "camera_glasses"))


def list_models(root=DEFAULT_MODELS):
    models = []
    for manifest in sorted(Path(root).glob("*/manifest.json")):
        meta = json.loads(manifest.read_text())
        models.append(dict(id=manifest.parent.name, path=str(manifest.parent),
                           display_name=meta.get("display_name", meta.get("mode")),
                           threshold=meta.get("threshold"), mode=meta.get("mode")))
    return models


def git_state():
    repo = Path(__file__).resolve().parent.parent
    def git(*args):
        try:
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                           stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    status = git("status", "--porcelain")
    return dict(git_commit=git("rev-parse", "HEAD"), git_branch=git("branch", "--show-current"),
                git_dirty=bool(status) if status is not None else None)


def yt_dlp_command():
    """Prefer the yt-dlp module of this interpreter; fall back to the system binary."""
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        found = shutil.which("yt-dlp")
        if not found:
            raise RuntimeError("yt-dlp가 없습니다. `pip install yt-dlp`로 설치하세요.")
        return [found]


def resolve_video(url, max_height=720):
    """Return metadata and a direct stream URL. Nothing is downloaded."""
    fmt = f"bv*[height<={max_height}][vcodec!=none]/b[height<={max_height}]/b"
    out = subprocess.run([*yt_dlp_command(), "-J", "--no-playlist", "--no-warnings", "-f", fmt, url],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("yt-dlp 오류: " + (out.stderr.strip().splitlines() or ["unknown"])[-1])
    info = json.loads(out.stdout)
    chosen = info.get("requested_formats", [info])[0] if not info.get("url") else info
    if not chosen.get("url") or not chosen.get("width") or not chosen.get("height"):
        raise RuntimeError("영상 스트림의 주소나 해상도를 얻지 못했습니다")
    return dict(video_id=info.get("id"), title=info.get("title"), channel=info.get("channel") or info.get("uploader"),
                duration=info.get("duration"), webpage_url=info.get("webpage_url", url),
                stream_url=chosen["url"], width=int(chosen["width"]), height=int(chosen["height"]),
                format_id=chosen.get("format_id"), http_headers=chosen.get("http_headers") or {})


def stream_frames(video, start, end, fps):
    """Yield (time_seconds, rgb) pairs decoded by ffmpeg into memory."""
    width, height = video["width"], video["height"]
    headers = "".join(f"{k}: {v}\r\n" for k, v in video["http_headers"].items())
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if headers:
        command += ["-headers", headers]
    command += ["-ss", f"{start:.3f}", "-i", video["stream_url"], "-t", f"{end - start:.3f}",
                "-vf", f"fps={fps}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = width * height * 3
    index = 0
    try:
        while True:
            data = process.stdout.read(size)
            if len(data) < size:
                break
            yield start + index / fps, np.frombuffer(data, np.uint8).reshape(height, width, 3)
            index += 1
    finally:
        process.stdout.close()
        error = process.stderr.read().decode(errors="replace").strip()
        process.wait()
    if index == 0:
        raise RuntimeError("ffmpeg가 이 구간에서 프레임을 받지 못했습니다" + (f": {error.splitlines()[-1]}" if error else ""))


def save_annotated(path, rgb, prediction, threshold):
    import cv2
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    p = prediction.get("camera_probability")
    if prediction.get("estimated_glasses_box"):
        x1, y1, x2, y2 = prediction["estimated_glasses_box"]
        colour = (24, 35, 180) if p is not None and p >= threshold else (74, 160, 22)
        cv2.rectangle(bgr, (x1, y1), (x2, y2), colour, 2)
    text = f"score {p:.3f}" if p is not None else prediction["reason"]
    cv2.putText(bgr, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, .9, (0, 0, 0), 4)
    cv2.putText(bgr, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, .9, (255, 255, 255), 2)
    scale = 480 / max(bgr.shape[:2])
    if scale < 1:
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])


class RunLog:
    def __init__(self, path, echo=True):
        self.path = Path(path)
        self.echo = echo

    def __call__(self, message):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        with self.path.open("a") as stream:
            stream.write(line + "\n")
        if self.echo:
            print(line, flush=True)


def new_run_id():
    return datetime.now().strftime("yt-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def run_test(bundle, url, timeline, label="unknown", fps=2.0, save_frames=False,
             output_root=DEFAULT_ROOT, run_id=None, runtime=None, echo=True, note=""):
    """Run one test and keep every record, including failures. Returns run.json content."""
    output_root = Path(output_root)
    run_id = run_id or new_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    log = RunLog(run_dir / "run.log", echo)
    record = dict(schema_version=1, run_id=run_id, status="running",
                  started_at=datetime.now(timezone.utc).isoformat(), finished_at=None,
                  command=sys.argv, python=sys.version.split()[0], **git_state(),
                  domain="youtube_video", note=note,
                  input=dict(url=url, timeline=timeline, default_label=label, fps=fps,
                             save_frames=save_frames, point_window_seconds=POINT_WINDOW,
                             min_scored_frames=MIN_SCORED_FRAMES),
                  model=None, video=None, segments=[], summary=None, error=None,
                  video_saved=False, frames_saved=bool(save_frames), jetson_validation="pending")
    write_json(run_dir / "run.json", record)
    try:
        if not 0.2 <= float(fps) <= 10:
            raise ValueError("fps는 0.2~10 사이여야 합니다")
        segments = parse_timeline(timeline, label)
        if runtime is None:
            from pipeline.onnx_runtime import Runtime
            log(f"모델을 불러옵니다: {bundle}")
            runtime = Runtime(bundle)
        meta = runtime.metadata
        threshold = meta["threshold"]
        record["model"] = dict(path=str(bundle), id=Path(bundle).name,
                               display_name=meta.get("display_name", meta.get("mode")),
                               mode=meta.get("mode"), threshold=threshold,
                               model_sha256=meta.get("model_sha256"))
        log(f"모델: {record['model']['display_name']} / 임계값 {threshold}")
        log(f"영상 정보를 확인합니다: {url}")
        video = resolve_video(url)
        record["video"] = {k: v for k, v in video.items() if k not in ("stream_url", "http_headers")}
        log(f"영상: {video['title']} ({video['width']}x{video['height']}, {video.get('duration')}s)")
        write_json(run_dir / "run.json", record)
        if save_frames:
            (run_dir / "frames").mkdir(exist_ok=True)
        results = []
        for segment in segments:
            if video.get("duration") and segment["start"] >= video["duration"]:
                log(f"구간 {segment['index']}: 영상 길이를 넘습니다. 건너뜁니다.")
                results.append(summarize_segment(segment, [], threshold))
                continue
            log(f"구간 {segment['index']}: {format_time(segment['start'])} ~ {format_time(segment['end'])}"
                f" (라벨 {segment['label']})")
            frames = []
            began = perf_counter()
            for t, rgb in stream_frames(video, segment["start"], segment["end"], fps):
                prediction = runtime.predict(rgb)
                row = dict(run_id=run_id, segment_index=segment["index"], label=segment["label"],
                           t=round(t, 3), domain="youtube_video", **prediction)
                if save_frames:
                    name = f"s{segment['index']:02d}-{t:09.3f}.jpg"
                    save_annotated(run_dir / "frames" / name, rgb, prediction, threshold)
                    row["frame_file"] = name
                append_jsonl(run_dir / "frame-predictions.jsonl", row)
                frames.append(row)
            result = summarize_segment(segment, frames, threshold)
            result["wall_seconds"] = perf_counter() - began
            results.append(result)
            score = f"{result['mean_score']:.3f}" if result["mean_score"] is not None else "-"
            log(f"  -> {result['verdict']} · 평균 점수 {score} · 판정 프레임 {result['n_scored']}/{result['n_frames']}"
                f" · {result['reasons']}")
            record["segments"] = results
            write_json(run_dir / "run.json", record)
        record["summary"] = summarize_run(results)
        record["status"] = "completed"
        log(f"완료: 경보 구간 {record['summary']['n_alarm']}/{record['summary']['n_segments']}")
    except Exception as error:
        record["status"] = "failed"
        record["error"] = f"{type(error).__name__}: {error}"
        log("실패: " + record["error"])
        with (run_dir / "run.log").open("a") as stream:
            stream.write(traceback.format_exc())
    finally:
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(run_dir / "run.json", record)
        video = record.get("video") or {}
        append_jsonl(output_root / "history.jsonl", dict(
            run_id=run_id, status=record["status"], started_at=record["started_at"],
            finished_at=record["finished_at"], url=url, title=video.get("title"),
            video_id=video.get("video_id"), model=(record.get("model") or {}).get("display_name"),
            timeline=timeline, summary=record["summary"], error=record["error"], git_commit=record["git_commit"]))
    return record


def read_history(output_root=DEFAULT_ROOT):
    path = Path(output_root) / "history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
