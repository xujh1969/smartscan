import cv2
import pytest

from smartscan.geometry import (
    is_rectangle,
    largest_inscribed_rect,
    order_quad,
    quad_bbox,
    rotate_points,
    tilt_angle,
)


@pytest.mark.parametrize("rect", [
    ((7000, 9000), (1000, 1500), 25.4),
    ((4000, 6000), (500, 700), 0.6),
])
def test_large_scan_rotation_roundoff_still_counts_as_rectangle(rect):
    assert is_rectangle(cv2.boxPoints(rect).tolist())


def test_tilt_angle_of_rotated_square():
    quad = [(10, 0), (20, 10), (10, 20), (0, 10)]
    assert abs(tilt_angle(quad) - 45.0) < 1e-6


def test_order_quad_starts_at_top_left():
    assert order_quad([(10, 10), (10, 0), (0, 10), (0, 0)]) == [
        (0, 0), (10, 0), (10, 10), (0, 10)
    ]


def test_largest_inscribed_rect_stays_within_shape():
    quad = [(10, 0), (20, 10), (10, 20), (0, 10)]
    x0, y0, x1, y1 = largest_inscribed_rect(quad, tilt_deg=45.0, shape=(100, 80))
    assert 0 <= x0 < x1 <= 100
    assert 0 <= y0 < y1 <= 80


def test_rotate_points_by_quarter_turn():
    out = rotate_points([(1, 0)], 90.0, (0, 0))
    assert abs(out[0][0]) < 1e-9
    assert abs(out[0][1] - 1.0) < 1e-9


def test_quad_bbox_covers_all_points():
    assert quad_bbox([(10, 0), (20, 10), (10, 20), (0, 10)]) == (0, 0, 20, 20)
