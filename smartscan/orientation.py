"""Conservative, fully offline orientation voting.

Only traditional image features are used. Two or more agreeing signals plus a
high confidence are required before the program dares to rotate automatically;
anything else stays untouched and is marked `unknown` for human confirmation.
180-degree flips are never decided automatically.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field

import cv2
import numpy as np

AUTO_CONFIDENCE = 0.8
REQUIRED_AGREEING_SIGNALS = 2


@dataclass
class OrientationVote:
    state: str = "unknown"
    signals: dict[str, int] = field(default_factory=dict)
    confidence: float = 0.0


def _as_gray(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 3 and arr.shape[2] == 4:
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
    if arr.ndim == 3:
        return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    return arr.astype(np.uint8, copy=False)


def _line_signal(gray: np.ndarray) -> int | None:
    edges = cv2.Canny(gray, 50, 150)
    if not np.any(edges):
        return None
    height, width = gray.shape[:2]
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=20,
        minLineLength=max(8, min(height, width) // 6),
        maxLineGap=4,
    )
    if lines is None:
        return None
    horizontal = vertical = 0.0
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        dx, dy = float(x2 - x1), float(y2 - y1)
        length = np.hypot(dx, dy)
        angle = abs(np.degrees(np.arctan2(dy, dx)))
        if angle < 12 or angle > 168:
            horizontal += length
        elif 78 < angle < 102:
            vertical += length
    if vertical > 3 * horizontal and vertical > 0:
        return 90
    if horizontal > 3 * vertical and horizontal > 0:
        return 0
    return None


def _sky_ground_signal(gray: np.ndarray) -> int | None:
    height, width = gray.shape[:2]
    half_h, half_w = height // 2, width // 2
    top_bottom = abs(
        float(gray[:half_h, :].mean()) - float(gray[height - half_h :, :].mean())
    )
    left_right = abs(
        float(gray[:, :half_w].mean()) - float(gray[:, width - half_w :].mean())
    )
    if top_bottom > 18:
        return 0
    if left_right > 18 and left_right > top_bottom:
        return 90
    return None


def _face_signal(gray: np.ndarray) -> int | None:
    cascade_file = os.path.join(
        cv2.data.haarcascades, "haarcascade_frontalface_default.xml"
    )
    if not os.path.isfile(cascade_file):
        return None
    detector = cv2.CascadeClassifier(cascade_file)
    if detector.empty():
        return None
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3)
    return 0 if len(faces) > 0 else None


def vote(image: np.ndarray) -> OrientationVote:
    gray = _as_gray(image)
    signals: dict[str, int] = {}
    for name, value in (
        ("lines", _line_signal(gray)),
        ("sky_ground", _sky_ground_signal(gray)),
        ("face", _face_signal(gray)),
    ):
        if value is not None:
            signals[name] = value
    has_rotation_evidence = any(v in (90, -90, 270) for v in signals.values())
    confidence = min(1.0, 0.25 * len(signals) + (0.5 if has_rotation_evidence else 0.0))
    return OrientationVote(
        state="voted" if signals else "unknown",
        signals=signals,
        confidence=confidence,
    )


def should_auto_rotate(result: OrientationVote) -> int:
    """Return +90 / -90 clockwise-quarter-turn angle, or 0 (leave untouched)."""
    if result.confidence < AUTO_CONFIDENCE:
        return 0
    normalized = [-90 if angle == 270 else angle for angle in result.signals.values()]
    counts = Counter(angle for angle in normalized if angle in (90, -90))
    if not counts:
        return 0
    angle, agreeing = counts.most_common(1)[0]
    return angle if agreeing >= REQUIRED_AGREEING_SIGNALS else 0
