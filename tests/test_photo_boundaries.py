"""Photo boundaries must not be confused with scene lines or pale pixels."""

import cv2
import numpy as np
import pytest
from pathlib import Path
from PIL import Image

from smartscan.detection import detect_quads, estimate_background
from smartscan.split import deskew_and_crop
from smartscan.geometry import tilt_angle
from smartscan.models import BatchConfig
from smartscan.pipeline import run


def test_horizon_inside_a_separate_photo_is_not_a_cut():
    image = np.full((500, 400, 3), 248, dtype=np.uint8)
    cv2.rectangle(image, (30, 30), (350, 430), (90, 110, 140), -1)
    cv2.rectangle(image, (30, 220), (350, 430), (140, 170, 180), -1)

    quads = detect_quads(image, estimate_background(image))

    assert len(quads) == 1
    assert quads[0].bbox()[3] - quads[0].bbox()[1] > 390


def test_building_lines_inside_a_photo_are_not_cuts():
    image = np.full((500, 400, 3), 248, dtype=np.uint8)
    cv2.rectangle(image, (30, 30), (350, 430), (130, 140, 150), -1)
    for x in (100, 210, 290):
        cv2.line(image, (x, 30), (x, 430), (30, 30, 30), 3)
    for y in (160, 310):
        cv2.line(image, (30, y), (350, y), (40, 40, 40), 3)

    assert len(detect_quads(image, estimate_background(image))) == 1


def test_detection_mask_does_not_erase_pale_photo_content():
    image = np.full((300, 360, 3), 248, dtype=np.uint8)
    cv2.rectangle(image, (30, 30), (320, 260), (90, 100, 110), -1)
    cv2.circle(image, (170, 150), 35, (244, 245, 246), -1)
    background = estimate_background(image)
    quads = detect_quads(image, background)
    assert len(quads) == 1

    crop = deskew_and_crop(image, quads[0], background, quads[0].visible_mask)

    assert np.count_nonzero(np.all(crop == (244, 245, 246), axis=2)) > 3500


def test_background_estimation_handles_photos_in_three_corners():
    image = np.full((300, 400, 3), 248, dtype=np.uint8)
    image[:150, :] = (80, 80, 80)
    image[150:, :180] = (100, 100, 100)

    assert estimate_background(image) == (248, 248, 248)


def test_upright_portrait_does_not_get_a_ninety_degree_deskew():
    assert tilt_angle([(10, 10), (110, 10), (110, 170), (10, 170)]) == 0


def test_staggered_columns_with_paper_gutters_stay_individual():
    image = np.full((600, 500, 3), 248, dtype=np.uint8)
    for top, bottom in ((20, 190), (195, 365), (370, 540)):
        cv2.rectangle(image, (20, top), (250, bottom), (95, 105, 115), -1)
    for top, bottom in ((20, 275), (280, 535)):
        cv2.rectangle(image, (255, top), (440, bottom), (110, 120, 130), -1)

    quads = detect_quads(image, estimate_background(image))

    assert len(quads) == 5
    assert all(quad.bbox()[2] - quad.bbox()[0] > 170 for quad in quads)


@pytest.mark.parametrize("number,count", [(6, 5), (39, 1), (43, 1)])
def test_local_scans_keep_photos_whole(number, count):
    path = Path(__file__).resolve().parents[1] / "扫描" / f"扫描_20261114 ({number}).png"
    if not path.exists():
        pytest.skip("Private scan fixture is not distributed with the repository")
    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"))
    quads = detect_quads(array, estimate_background(array))
    assert len(quads) == count
    assert all(min(np.linalg.norm(np.roll(q.points, -1, axis=0) - q.points, axis=1))
               > 200 for q in quads)
    if number == 6:
        # Approximate manually checked full-print bounds, not just a count:
        # a fragment with the "right" count must still fail this regression.
        expected = [(0, 0, 1500, 1000), (0, 1030, 1500, 2000),
                    (0, 2050, 1500, 3050), (1500, 0, 2550, 1500),
                    (1500, 1500, 2550, 3050)]
        for x0, y0, x1, y1 in expected:
            best = 0
            for quad in quads:
                a, b, c, d = quad.bbox()
                intersection = max(0, min(c, x1) - max(a, x0)) * max(0, min(d, y1) - max(b, y0))
                best = max(best, intersection / ((c-a)*(d-b) + (x1-x0)*(y1-y0) - intersection))
            assert best > 0.85


def test_old_detection_results_do_not_silently_skip_the_fixed_detector(tmp_path):
    from PIL import PngImagePlugin
    from smartscan.naming import content_hash

    source = tmp_path / "scan.png"
    image = np.full((300, 360, 3), 248, dtype=np.uint8)
    image[30:260, 30:320] = (90, 100, 110)
    Image.fromarray(image).save(source)
    output = tmp_path / "out"
    output.mkdir()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("source", str(source.resolve()))
    metadata.add_text("digest", content_hash(source))
    old = output / "old.png"
    Image.new("RGB", (20, 20)).save(old, pnginfo=metadata)
    original = old.read_bytes()

    result = run(BatchConfig([source], output))

    assert len(result.ok) == 1
    assert old.read_bytes() == original


def test_ambiguous_cuts_put_the_source_in_the_review_queue(tmp_path):
    from tests.synthetic import synthetic_overlap_scan

    source = tmp_path / "overlap.png"
    Image.fromarray(synthetic_overlap_scan()).save(source)
    result = run(BatchConfig([source], tmp_path / "out"))

    assert result.ok
    assert source in result.review
