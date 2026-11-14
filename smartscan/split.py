"""The only place in the program allowed to resample pixels.

A single Lanczos rotation deskews the quad. Three corner/gap strategies are
supported: background fill (default), inward inset crop, and transparent corners.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .geometry import largest_inscribed_rect, quad_bbox
from .models import PhotoQuad

Background = tuple[int, int, int]


def fill_gaps(
    image: np.ndarray, keep_mask: np.ndarray, background: Background
) -> np.ndarray:
    out = np.asarray(image).copy()
    colour = np.asarray(background[:3], dtype=out.dtype)
    out[np.asarray(keep_mask) == 0] = colour
    return out


def deskew_and_crop(
    image: np.ndarray,
    quad: PhotoQuad,
    background: Background,
    visible_mask: np.ndarray | None = None,
    fill_mode: str = "background",
) -> np.ndarray:
    arr = np.asarray(image)
    height, width = arr.shape[:2]
    points = quad.ordered()
    cx = sum(p[0] for p in points) / 4.0
    cy = sum(p[1] for p in points) / 4.0
    bg = tuple(int(v) for v in background[:3])

    matrix = cv2.getRotationMatrix2D((cx, cy), float(quad.tilt_deg), 1.0)
    rotated = cv2.warpAffine(
        arr,
        matrix,
        (width, height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=bg,
    )

    src_points = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    rotated_points = cv2.transform(src_points, matrix).reshape(-1, 2)
    polygon = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(polygon, np.round(rotated_points).astype(np.int32), 255)

    keep = polygon
    if visible_mask is not None:
        rotated_visible = cv2.warpAffine(
            np.asarray(visible_mask, dtype=np.uint8),
            matrix,
            (width, height),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        keep = cv2.bitwise_and(polygon, rotated_visible)

    if fill_mode == "alpha":
        canvas = np.dstack(
            [rotated, np.full((height, width), 255, dtype=np.uint8)]
        )
        outside = keep == 0
        canvas[outside] = [bg[0], bg[1], bg[2], 0]
    else:
        canvas = fill_gaps(rotated, keep, bg)

    x0, y0, x1, y1 = quad_bbox(rotated_points)
    left = max(0, int(math.floor(x0)))
    top = max(0, int(math.floor(y0)))
    right = min(width, int(math.ceil(x1)) + 1)
    bottom = min(height, int(math.ceil(y1)) + 1)

    if fill_mode == "inset":
        ix0, iy0, ix1, iy1 = largest_inscribed_rect(
            rotated_points, 0.0, (width, height)
        )
        margin_x = max(1, int((ix1 - ix0) * 0.02))
        margin_y = max(1, int((iy1 - iy0) * 0.02))
        left = max(left, ix0 + margin_x)
        top = max(top, iy0 + margin_y)
        right = min(right, ix1 - margin_x)
        bottom = min(bottom, iy1 - margin_y)

    return canvas[top:bottom, left:right]
