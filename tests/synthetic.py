"""Synthetic flatbed scans used by image tests (no real user photos needed)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from smartscan.geometry import rotate_points


def _rgb(value: int) -> tuple[int, int, int]:
    return (int(value), int(value), int(value))


def synthetic_scan(rects, size=(200, 260), background=240) -> np.ndarray:
    """Draw touching rectangles with different paper tones; no gaps, no borders."""
    height, width = size
    img = np.full((height, width, 3), background, dtype=np.uint8)
    for (x, y), (rect_w, rect_h), value in rects:
        cv2.rectangle(
            img, (x, y), (x + rect_w - 1, y + rect_h - 1), _rgb(value), thickness=-1
        )
    return img


def synthetic_tilted_scan(
    angle_deg: float,
    size=(200, 220),
    photo_value=60,
    background=240,
    photo_size=(120, 70),
) -> np.ndarray:
    height, width = size
    img = np.full((height, width, 3), background, dtype=np.uint8)
    cx, cy = width / 2.0, height / 2.0
    photo_w, photo_h = photo_size
    corners = [
        (cx - photo_w / 2, cy - photo_h / 2),
        (cx + photo_w / 2, cy - photo_h / 2),
        (cx + photo_w / 2, cy + photo_h / 2),
        (cx - photo_w / 2, cy + photo_h / 2),
    ]
    rotated = rotate_points(corners, angle_deg, (cx, cy))
    poly = np.round(np.asarray(rotated)).astype(np.int32)
    cv2.fillConvexPoly(img, poly, _rgb(photo_value))
    return img


def synthetic_overlap_scan(size=(180, 220), background=240) -> np.ndarray:
    """Lower-left photo is partly covered by a second photo on its lower-right corner."""
    height, width = size
    img = np.full((height, width, 3), background, dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (110, 90), _rgb(70), thickness=-1)
    cv2.rectangle(img, (80, 60), (180, 140), _rgb(150), thickness=-1)
    return img


def make_scan_file(path: str | Path, angle_deg: float = 8.0) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(synthetic_tilted_scan(angle_deg)).save(target, dpi=(600, 600))
    return target
