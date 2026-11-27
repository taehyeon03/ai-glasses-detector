#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
camera_python="${EYEWEAR_CAMERA_PYTHON:-$HOME/.local/share/ai-glasses-camera-env/bin/python}"
camera_bundle="${EYEWEAR_CAMERA_BUNDLE:-$HOME/.local/share/ai-glasses-models/mobilenet-crop-s44}"
camera_output="${EYEWEAR_CAMERA_OUTPUT:-$HOME/.local/share/ai-glasses-field-evaluation}"
if [[ ! -x "$camera_python" || ! -f "$camera_bundle/manifest.json" ]]; then
  echo "카메라 실행 환경이나 모델이 없습니다. docs/camera-evaluation.md를 확인하세요."
  exit 1
fi
cd "$repo_dir"
exec "$camera_python" -m scripts.live_camera --bundle "$camera_bundle" --output "$camera_output" "$@"
