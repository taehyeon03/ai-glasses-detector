"""Local web page for YouTube timeline tests. Listens on loopback only.

python -m scripts.youtube_test_server   # then open http://127.0.0.1:17890
"""
import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from pipeline.youtube_timeline import (DEFAULT_MODELS, DEFAULT_ROOT, list_models, new_run_id,
                                       parse_timeline, read_history, run_test)

PAGE = Path(__file__).with_name("youtube_viewer.html")
RUN_ID = re.compile(r"yt-\d{8}-\d{6}-[0-9a-f]{6}")
FRAME = re.compile(r"s\d{2}-\d{5}\.\d{3}\.jpg")


class State:
    def __init__(self, models_root, output_root):
        self.models_root = Path(models_root)
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.runtimes = {}
        self.lock = threading.Lock()
        self.active = None

    def runtime(self, bundle):
        from pipeline.onnx_runtime import Runtime
        key = str(bundle)
        if key not in self.runtimes:
            self.runtimes[key] = Runtime(bundle)
        return self.runtimes[key]

    def start(self, body):
        models = {m["id"]: m for m in list_models(self.models_root)}
        if body.get("model") not in models:
            raise ValueError("모델을 선택하세요")
        url = (body.get("url") or "").strip()
        if not re.match(r"https?://", url):
            raise ValueError("http(s) 영상 주소를 입력하세요")
        parse_timeline(body.get("timeline") or "", body.get("label") or "unknown")
        if not self.lock.acquire(blocking=False):
            raise ValueError("다른 테스트가 실행 중입니다. 끝난 뒤 다시 시도하세요.")
        run_id = new_run_id()
        bundle = Path(models[body["model"]]["path"])

        def work():
            try:
                run_test(bundle, url, body["timeline"], body.get("label") or "unknown",
                         float(body.get("fps") or 2), bool(body.get("save_frames")), self.output_root,
                         run_id=run_id, runtime=self.runtime(bundle), note=body.get("note") or "")
            finally:
                self.active = None
                self.lock.release()
        self.active = run_id
        threading.Thread(target=work, daemon=True).start()
        return run_id


def handler(state):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, payload, kind="application/json; charset=utf-8"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

        def do_GET(self):
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            if not parts:
                return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if parts == ["api", "models"]:
                return self.send(200, list_models(state.models_root))
            if parts == ["api", "runs"]:
                return self.send(200, dict(active=state.active, runs=read_history(state.output_root)[::-1]))
            if len(parts) >= 3 and parts[:2] == ["api", "runs"] and RUN_ID.fullmatch(parts[2]):
                run_dir = state.output_root / parts[2]
                if not (run_dir / "run.json").exists():
                    return self.send(404, dict(error="not found"))
                if parts[3:] == ["log"]:
                    log = run_dir / "run.log"
                    return self.send(200, log.read_bytes() if log.exists() else b"", "text/plain; charset=utf-8")
                if parts[3:] == []:
                    frames_path = run_dir / "frame-predictions.jsonl"
                    frames = [json.loads(l) for l in frames_path.read_text().splitlines() if l.strip()] \
                        if frames_path.exists() else []
                    return self.send(200, dict(run=json.loads((run_dir / "run.json").read_text()), frames=frames))
                if len(parts) == 5 and parts[3] == "frames" and FRAME.fullmatch(parts[4]):
                    image = run_dir / "frames" / parts[4]
                    if image.exists():
                        return self.send(200, image.read_bytes(), "image/jpeg")
            self.send(404, dict(error="not found"))

        def do_POST(self):
            if urlparse(self.path).path != "/api/runs":
                return self.send(404, dict(error="not found"))
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 100_000)
                run_id = state.start(json.loads(self.rfile.read(length) or b"{}"))
            except (ValueError, json.JSONDecodeError) as error:
                return self.send(400, dict(error=str(error)))
            self.send(200, dict(run_id=run_id))
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=17890)
    parser.add_argument("--models-root", default=str(DEFAULT_MODELS))
    parser.add_argument("--output", default=str(DEFAULT_ROOT))
    args = parser.parse_args()
    state = State(args.models_root, args.output)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(state))
    print(f"YouTube 타임라인 테스트: http://127.0.0.1:{args.port}  (기록: {state.output_root})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
