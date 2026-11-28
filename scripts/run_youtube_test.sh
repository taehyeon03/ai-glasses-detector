#!/usr/bin/env bash
# Start the local YouTube timeline test page (loopback only) and open it in a browser.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
default_python="$HOME/.local/share/ai-glasses-camera-env/bin/python"
[[ -x "$default_python" ]] || default_python="$(command -v python3)"
camera_python="${EYEWEAR_CAMERA_PYTHON:-$default_python}"
models_root="${EYEWEAR_MODELS_ROOT:-$HOME/.local/share/ai-glasses-models}"
output_root="${EYEWEAR_YOUTUBE_OUTPUT:-$HOME/.local/share/ai-glasses-field-evaluation/youtube}"
port="${EYEWEAR_YOUTUBE_PORT:-17890}"
if [[ ! -x "$camera_python" ]]; then
  echo "Python을 찾지 못했습니다. youtube_test/README.md의 설치 절차를 확인하세요."
  exit 1
fi
if ! "$camera_python" -c "import yt_dlp" 2>/dev/null; then
  echo "yt-dlp를 실행 환경에 설치합니다."
  "$camera_python" -m pip install --quiet --upgrade yt-dlp
fi
if ! ls "$models_root"/*/manifest.json >/dev/null 2>&1; then
  echo "모델 묶음이 없습니다: $models_root/<모델 이름>/manifest.json"
  echo "youtube_test/README.md의 '모델 묶음 받기'를 확인하세요."
  exit 1
fi
cd "$repo_dir"
(sleep 1.5; xdg-open "http://127.0.0.1:$port" >/dev/null 2>&1 || true) &
exec "$camera_python" -m scripts.youtube_test_server --port "$port" --models-root "$models_root" --output "$output_root" "$@"
