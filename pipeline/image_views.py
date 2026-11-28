"""Image preprocessing shared by training and lightweight ONNX evaluation."""

import cv2

import json

import numpy as np

from PIL import Image

YUNET_REVISION = '48b10fa505aeb51fbd127fc60a5c660040e823b7'

YUNET_URL = 'https://media.githubusercontent.com/media/opencv/opencv_zoo/' + YUNET_REVISION + '/models/face_detection_yunet/face_detection_yunet_2023mar.onnx'

MEAN_RGB = np.array([123, 116, 104], dtype=np.uint8)

def clip_box(box, size=224):
    x0, y0, x1, y1 = box
    return [max(0, min(size - 1, int(np.floor(x0)))), max(0, min(size - 1, int(np.floor(y0)))), max(1, min(size, int(np.ceil(x1)))), max(1, min(size, int(np.ceil(y1))))]

def geometry(face, size=224):
    points = np.asarray(face[4:14]).reshape(5, 2)
    eyes = sorted(points[:2], key=lambda p: p[0])
    left, right = eyes
    distance = float(np.linalg.norm(right - left))
    if distance < 12:
        return None
    center = (left + right) / 2
    box = clip_box([center[0] - 1.12 * distance, min(left[1], right[1]) - 0.52 * distance, center[0] + 1.12 * distance, max(left[1], right[1]) + 0.55 * distance], size)

    def around(point, radius_x, radius_y):
        return clip_box([point[0] - radius_x * distance, point[1] - radius_y * distance, point[0] + radius_x * distance, point[1] + radius_y * distance], size)
    left_outer = left + np.array([-0.46 * distance, 0])
    right_outer = right + np.array([0.46 * distance, 0])
    regions = dict(glasses=box, lens_left=around(left, 0.34, 0.33), lens_right=around(right, 0.34, 0.33), outer_left=around(left_outer, 0.22, 0.28), outer_right=around(right_outer, 0.22, 0.28), lower_face=around(points[3:5].mean(0), 0.35, 0.25), forehead=around(center + np.array([0, -0.9 * distance]), 0.35, 0.25))
    side = max(8, int(0.4 * distance))
    fx, fy, fw, fh = face[:4]
    candidates = [[0, 0, side, side], [size - side, 0, size, side], [0, size - side, side, size], [size - side, size - side, size, size]]

    def overlap(b):
        return max(0, min(b[2], fx + fw) - max(b[0], fx)) * max(0, min(b[3], fy + fh) - max(b[1], fy))
    regions['background_corner'] = min(candidates, key=overlap)
    return dict(roi=box, regions=regions, landmarks=points.tolist(), face_box=[float(v) for v in face[:4]], confidence=float(face[-1]))

def matched_views(original, info, size):
    full = np.asarray(original.resize((size, size), Image.Resampling.BILINEAR)).copy()
    if info is None:
        return {name: full.copy() for name in ['full', 'roi_mask', 'roi_crop']}
    x0, y0, x1, y1 = info['roi']
    masked = np.empty_like(full)
    masked[:] = MEAN_RGB
    masked[y0:y1, x0:x1] = full[y0:y1, x0:x1]
    sx, sy = (original.width / size, original.height / size)
    crop = original.crop((x0 * sx, y0 * sy, x1 * sx, y1 * sy)).resize((size, size), Image.Resampling.BILINEAR)
    return dict(full=full, roi_mask=masked, roi_crop=np.asarray(crop))

def add_bridge_region(geometry, size=224):
    if geometry is None:
        return None
    updated = json.loads(json.dumps(geometry))
    eyes = np.asarray(geometry['landmarks'][:2])
    distance = float(np.linalg.norm(eyes[1] - eyes[0]))
    center = eyes.mean(0) + np.array([0.0, -0.18 * distance])
    updated['regions']['bridge'] = clip_box([center[0] - 0.22 * distance, center[1] - 0.28 * distance, center[0] + 0.22 * distance, center[1] + 0.28 * distance], size)
    return updated

PARTS = ['outer_left', 'bridge', 'outer_right']

def local_views(original, geometry, full_size=224, local_size=112):
    images = np.zeros((3, 3, local_size, local_size), dtype=np.uint8)
    quality = np.zeros((3, 4), dtype=np.float32)
    valid = np.zeros(3, dtype=np.float32)
    boxes = []
    if geometry is None:
        return (images, quality, valid, boxes)
    geometry = add_bridge_region(geometry, full_size)
    sx, sy = (original.width / full_size, original.height / full_size)
    for index, name in enumerate(PARTS):
        x0, y0, x1, y1 = geometry['regions'][name]
        view = np.asarray(original.crop((x0 * sx, y0 * sy, x1 * sx, y1 * sy)).resize((local_size, local_size), Image.Resampling.BILINEAR))
        gray = cv2.cvtColor(view, cv2.COLOR_RGB2GRAY)
        images[index] = view.transpose(2, 0, 1)
        quality[index] = [min(np.log1p(cv2.Laplacian(gray, cv2.CV_64F).var()) / 10, 1), gray.mean() / 255, gray.std() / 128, geometry['confidence']]
        valid[index] = 1
        boxes.append([x0, y0, x1, y1])
    return (images, quality, valid, boxes)
