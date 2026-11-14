from smartscan.detection import detect_quads, estimate_background
from smartscan.split import deskew_and_crop
from tests.synthetic import synthetic_tilted_scan


def _setup():
    image = synthetic_tilted_scan(10.0, photo_value=60, background=240)
    background = estimate_background(image)
    quad = detect_quads(image, background)[0]
    return image, background, quad


def test_inset_mode_cuts_away_corner_triangles():
    image, background, quad = _setup()
    filled = deskew_and_crop(image, quad, background)
    inset = deskew_and_crop(image, quad, background, fill_mode="inset")

    assert inset.shape[2] == 3
    assert inset.shape[0] < filled.shape[0] or inset.shape[1] < filled.shape[1]


def test_alpha_mode_makes_corners_transparent():
    image, background, quad = _setup()

    out = deskew_and_crop(image, quad, background, fill_mode="alpha")

    assert out.shape[2] == 4
    assert out[0, 0, 3] == 0
    assert out[out.shape[0] // 2, out.shape[1] // 2, 3] == 255
