"""Near-background gutter detection for tightly tiled album pages.

These are the failure cases of the paper-ridge detector: prints almost fill
the sheet and their gutters are only a few pixels wide.
"""

from __future__ import annotations

import cv2
import numpy as np

from smartscan.detection import detect_quads
from smartscan.gutters import gutter_quads

BG = (238, 238, 238)


def _photo(width: int, height: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.integers(30, 190, size=3, dtype=np.uint8)
    noise = rng.integers(-28, 28, size=(height, width, 3), dtype=np.int16)
    return np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def _collage(gutter: int = 8) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    image = np.full((600, 900, 3), BG, np.uint8)
    step_x, step_y = 300, 300
    cell_w, cell_h = step_x - gutter, step_y - gutter
    boxes = []
    for row in range(2):
        for col in range(3):
            x0, y0 = col * step_x, row * step_y
            x1, y1 = x0 + cell_w, y0 + cell_h
            image[y0:y1, x0:x1] = _photo(cell_w, cell_h, row * 3 + col + 1)
            boxes.append((x0, y0, x1, y1))
    return image, boxes


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(1.0, area_a + area_b - inter)


def test_gutter_quads_recovers_every_print_in_a_tiled_collage():
    image, expected = _collage()
    quads = gutter_quads(image, BG)
    found = [q.bbox() for q in quads]
    assert len(found) == len(expected)
    for target in expected:
        assert max(_iou(target, box) for box in found) > 0.85


def test_gutter_quads_does_not_cut_a_single_print():
    image = np.full((600, 900, 3), BG, np.uint8)
    image[10:590, 10:890] = _photo(880, 580, 99)
    quads = gutter_quads(image, BG)
    assert len(quads) <= 1
    if quads:
        assert _iou((10, 10, 890, 590), quads[0].bbox()) > 0.85


def test_gutter_quads_discards_a_blank_sheet():
    image = np.full((600, 900, 3), BG, np.uint8)
    assert gutter_quads(image, BG) == []


def test_detect_quads_uses_gutters_when_paper_ridges_are_too_thin():
    image, expected = _collage(gutter=3)
    quads = detect_quads(image, BG)
    found = [q.bbox() for q in quads]
    assert len(found) >= 4
    assert sum(max(_iou(target, box) for box in found) > 0.8
               for target in expected) >= 4


def test_gutter_quads_ignores_a_textured_line_inside_one_print():
    """A horizon inside a photo is not a pale gutter and must not split it."""
    image = np.full((600, 900, 3), BG, np.uint8)
    block = _photo(880, 580, 7)
    block[280:300, :] = (250, 250, 250)
    image[10:590, 10:890] = block
    quads = gutter_quads(image, BG)
    assert len(quads) == 1
