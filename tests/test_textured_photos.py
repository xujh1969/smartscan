"""真实老照片内部有丰富色块；不能用颜色/亮度聚类代替几何接缝检测。"""

import cv2
import numpy as np

from smartscan.detection import detect_quads, estimate_background


def _textured_column():
    image = np.full((500, 300, 3), 248, dtype=np.uint8)
    bands = [(10, 160), (160, 310), (310, 460)]
    tones = [(95, 95, 95), (140, 140, 140), (70, 70, 70)]
    for index, ((top, bottom), tone) in enumerate(zip(bands, tones)):
        cv2.rectangle(image, (10, top), (210, bottom), tone, thickness=-1)
        shift = index * 18
        cv2.circle(
            image, (60 + shift, top + 45), 24, (40, 40, 40), thickness=-1
        )
        cv2.circle(
            image, (160 - shift, top + 105), 28, (190, 190, 190), thickness=-1
        )
        cv2.line(image, (25, top + 115), (85, top + 85), (20, 20, 20), 2)
    for seam in (160, 310):
        cv2.line(image, (10, seam), (210, seam), (25, 25, 25), 2)
    return image


def test_photos_with_internal_texture_are_not_split_into_colour_blobs():
    image = _textured_column()

    quads = detect_quads(image, estimate_background(image))

    assert len(quads) == 3
    for quad in quads:
        x0, y0, x1, y1 = quad.bbox()
        assert 135 <= (y1 - y0) <= 190
        assert 170 <= (x1 - x0) <= 230


def test_strong_seams_and_short_internal_lines_are_distinguished():
    image = _textured_column()

    quads = detect_quads(image, estimate_background(image))

    tops = sorted(quad_bbox_top(quad) for quad in quads)
    assert [round(top / 10) * 10 for top in tops] == [10, 160, 310]


def quad_bbox_top(quad):
    return quad.bbox()[1]
