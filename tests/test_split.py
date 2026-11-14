import numpy as np
import pytest
import cv2

from smartscan.detection import detect_quads, estimate_background
from smartscan.split import deskew_and_crop, fill_gaps
from smartscan.geometry import tilt_angle
from smartscan.models import PhotoQuad
from tests.synthetic import synthetic_tilted_scan


def test_deskew_output_is_horizontal_and_corners_filled():
    img = synthetic_tilted_scan(10.0, photo_value=60, background=240)
    background = estimate_background(img)
    quad = detect_quads(img, background)[0]

    out = deskew_and_crop(img, quad, background)

    assert out.shape[0] > 0 and out.shape[1] > 0
    assert tuple(out[0, 0]) == (240, 240, 240)
    assert float(out.mean()) < 240


def test_deskew_removes_the_tilt():
    img = synthetic_tilted_scan(10.0, photo_value=60, background=240)
    background = estimate_background(img)
    quad = detect_quads(img, background)[0]

    out = deskew_and_crop(img, quad, background)
    detected = detect_quads(out, background)

    assert detected
    assert abs(detected[0].tilt_deg) < 2.0


def test_fill_gaps_paints_masked_pixels_with_background():
    img = np.full((20, 20, 3), 60, dtype=np.uint8)
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[5:15, 5:15] = 255

    out = fill_gaps(img, mask, (240, 240, 240))

    assert tuple(out[0, 0]) == (240, 240, 240)
    assert tuple(out[10, 10]) == (60, 60, 60)


@pytest.mark.parametrize("fill_mode", ["background", "alpha"])
def test_non_rectangle_automatically_uses_inset_crop(fill_mode):
    image = np.full((320, 420, 3), 240, np.uint8)
    points = [(60, 40), (350, 65), (320, 265), (90, 240)]
    cv2.fillConvexPoly(image, np.array(points, np.int32), (60, 80, 100))
    quad = PhotoQuad(points, tilt_deg=tilt_angle(points))
    expected = deskew_and_crop(image, quad, (240, 240, 240), fill_mode="inset")
    actual = deskew_and_crop(image, quad, (240, 240, 240), fill_mode=fill_mode)
    assert np.array_equal(actual, expected)
    assert actual.shape[2] == 3
    assert actual.max() < 200


def test_rotated_rectangle_keeps_requested_transparent_corners():
    image = np.full((320, 420, 3), 60, np.uint8)
    points = cv2.boxPoints(((210, 160), (260, 140), 12)).tolist()
    quad = PhotoQuad(points, tilt_deg=tilt_angle(points))
    actual = deskew_and_crop(image, quad, (240, 240, 240), fill_mode="alpha")
    inset = deskew_and_crop(image, quad, (240, 240, 240), fill_mode="inset")
    assert actual.shape[2] == 4
    assert actual.shape[0] > inset.shape[0] and actual.shape[1] > inset.shape[1]
