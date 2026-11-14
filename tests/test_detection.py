import numpy as np

from smartscan.detection import (
    detect_quads,
    estimate_background,
    find_photo_cluster,
    resolve_occlusion,
)
from smartscan.models import Flags
from tests.synthetic import (
    synthetic_overlap_scan,
    synthetic_scan,
    synthetic_tilted_scan,
)

RECTS = [((0, 0), (100, 80), 150), ((100, 0), (100, 80), 90)]


def test_background_estimation_reads_scan_corners():
    img = np.full((100, 120, 3), 240, dtype=np.uint8)
    assert estimate_background(img) == (240, 240, 240)


def test_foreground_cluster_excludes_background():
    img = synthetic_tilted_scan(10.0)
    mask = find_photo_cluster(img, (240, 240, 240))
    assert mask.shape[:2] == img.shape[:2]
    assert mask[0, 0] == 0


def test_two_touching_rectangles_are_detected():
    img = synthetic_scan(RECTS)
    quads = detect_quads(img, estimate_background(img))
    assert len(quads) == 2


def test_tilted_quad_angle_within_two_degrees():
    img = synthetic_tilted_scan(10.0)
    quads = detect_quads(img, estimate_background(img))
    assert len(quads) == 1
    assert abs(quads[0].tilt_deg - 10.0) < 2.0


def test_overlap_relation_is_resolved():
    img = synthetic_overlap_scan()
    quads = resolve_occlusion(detect_quads(img, estimate_background(img)))
    statuses = [q.status for q in quads]
    assert "ok" in statuses
    assert Flags.INCOMPLETE in statuses


def test_small_speck_is_ignored():
    img = synthetic_scan(RECTS)
    img[150:153, 150:153] = (30, 30, 30)
    quads = detect_quads(img, estimate_background(img))
    assert len(quads) == 2


def test_empty_scan_returns_no_quads():
    img = np.full((80, 80, 3), 240, dtype=np.uint8)
    assert detect_quads(img, (240, 240, 240)) == []
