"""Resolve local storage and installation paths without coupling them to the source tree."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get('TRYON_ROOT', PROJECT_ROOT / 'data')).expanduser().resolve()
YOLO_RUN_ROOT = Path(os.environ.get('TRYON_YOLO_RUN_ROOT', DATA_ROOT / 'work' / 'yolo')).expanduser().resolve()
QWEN_LOADER = Path(os.environ.get('TRYON_QWEN_LOADER', Path.home() / 'qwen_image' / 'app.py')).expanduser()
QWEN_SNAPSHOTS = Path(os.environ.get(
    'TRYON_QWEN_SNAPSHOTS',
    Path.home() / '.cache/huggingface/hub/models--Qwen--Qwen-Image-2.1/snapshots',
)).expanduser()
REVIEWERS = tuple(
    name.strip() for name in os.environ.get('TRYON_REVIEWERS', '검수자 1,검수자 2').split(',')
    if name.strip()
)
PRIORITY_REVIEWER = os.environ.get('TRYON_PRIORITY_REVIEWER', REVIEWERS[0] if REVIEWERS else '')
