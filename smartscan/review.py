"""Persist user-confirmed native-pixel crop boxes, keyed by source content."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .geometry import order_quad, tilt_angle
from .models import PhotoQuad


def validate_quad(points, size: tuple[int, int]) -> list[tuple[float, float]]:
    array = np.asarray(points, dtype=np.float64)
    if array.shape != (4, 2) or not np.isfinite(array).all():
        raise ValueError("裁切框需要四个有效角点")
    width, height = size
    if (np.any(array < 0) or np.any(array[:, 0] > width - 1)
            or np.any(array[:, 1] > height - 1)):
        raise ValueError("裁切框不能超出原图")
    polygon = array.astype(np.float32)
    if not cv2.isContourConvex(polygon) or cv2.contourArea(polygon) < 16:
        raise ValueError("裁切框不能交叉、折叠或过小")
    return [tuple(map(float, point)) for point in array]


def source_identity(source: Path) -> tuple[str, tuple[int, int]]:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    with Image.open(source) as image:
        if image.mode not in ("L", "RGB", "RGBA"):
            raise ValueError("仅支持 8bit/通道的灰度或 RGB 扫描件")
        size = image.size
    return digest.hexdigest(), size


def _cache_path(digest: str) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return base / "SmartScan" / "reviews" / f"{digest}.json"


def review_path(source: Path) -> Path:
    return _cache_path(source_identity(Path(source))[0])


@dataclass
class Review:
    digest: str
    size: tuple[int, int]
    points: list[list[tuple[float, float]]]
    rotations: list[int] | None = None

    def __post_init__(self):
        if self.rotations is None:
            self.rotations = [0] * len(self.points)
        if len(self.rotations) != len(self.points) or any(
                type(angle) is not int or angle not in (0, 90, 180, 270) for angle in self.rotations):
            raise ValueError("每个裁切框需要一个有效的 90° 旋转设置")
        self.rotations = list(self.rotations)

    @property
    def revision(self) -> str:
        payload = json.dumps([self.size, self.points, self.rotations], separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf8")).hexdigest()[:16]

    def quads(self) -> list[PhotoQuad]:
        return [PhotoQuad(points=points, tilt_deg=tilt_angle(points)) for points in self.points]


def save_review(source: Path, points, *, rotations=None, expected_digest: str | None = None) -> Review:
    digest, size = source_identity(Path(source))
    if expected_digest is not None and digest != expected_digest:
        raise ValueError("原图内容已变化，请关闭后重新打开此扫描件再校正")
    boxes = [order_quad(validate_quad(box, size)) for box in points]
    review = Review(digest, size, boxes, rotations)
    payload = {"version": 2, "digest": digest, "size": size, "points": boxes,
               "rotations": review.rotations}
    path = _cache_path(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf8", dir=path.parent,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return review


def load_review(source: Path) -> Review | None:
    digest, size = source_identity(Path(source))
    try:
        data = json.loads(_cache_path(digest).read_text(encoding="utf8"))
        if data["version"] not in (1, 2) or data["digest"] != digest or tuple(data["size"]) != size:
            return None
        boxes = [order_quad(validate_quad(box, size)) for box in data["points"]]
        return Review(digest, size, boxes, data["rotations"] if data["version"] == 2 else None)
    except (OSError, ValueError, KeyError, TypeError):
        return None
