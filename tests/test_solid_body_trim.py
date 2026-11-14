"""A thin connected tail must not stretch the last photo's bounding box."""

import cv2
import numpy as np

from smartscan.detection import detect_quads, estimate_background, trim_to_solid_body


def _column_with_tail():
    image = np.full((460, 240, 3), 248, dtype=np.uint8)
    bands = [(10, 160), (160, 310), (310, 410)]
    tones = [(95, 95, 95), (140, 140, 140), (70, 70, 70)]
    for (top, bottom), tone in zip(bands, tones):
        cv2.rectangle(image, (10, top), (210, bottom), tone, thickness=-1)
        cv2.circle(image, (80, (top + bottom) // 2), 20, (40, 40, 40), thickness=-1)
    for seam in (160, 310):
        cv2.line(image, (10, seam), (210, seam), (25, 25, 25), 2)
    cv2.rectangle(image, (10, 10), (18, 455), (30, 30, 30), thickness=-1)
    return image


def test_trim_removes_a_sparse_tail():
    cell = np.zeros((145, 208), dtype=np.uint8)
    cell[:100, :] = 255
    cell[100:, :8] = 255

    body, offset = trim_to_solid_body(cell)

    assert body.shape == (100, 208)
    assert offset == (0, 0)


def test_trim_keeps_a_solid_rectangle_unchanged():
    cell = np.full((150, 200), 255, dtype=np.uint8)

    body, offset = trim_to_solid_body(cell)

    assert body.shape == (150, 200)
    assert offset == (0, 0)


def test_thin_tail_does_not_break_photo_count_or_orientation():
    image = _column_with_tail()

    quads = detect_quads(image, estimate_background(image))

    assert len(quads) == 3
    for quad in quads:
        assert quad.fill_ratio >= 0.9
        assert abs(quad.tilt_deg) < 5
