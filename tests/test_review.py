import json

import numpy as np
import pytest
from PIL import Image

from smartscan.metadata import read_metadata
from smartscan.models import BatchConfig
from smartscan.pipeline import run
from smartscan.review import load_review, save_review, review_path


def scan(path):
    image = np.full((240, 360, 3), 248, np.uint8)
    image[20:220, 20:340] = (100, 120, 140)
    image[120:220, 20:340] = (160, 180, 190)
    Image.fromarray(image).save(path, dpi=(600, 600))
    return path


BOX = [(20, 20), (339, 20), (339, 219), (20, 219)]


def test_review_round_trip_and_stable_revision(tmp_path):
    source = scan(tmp_path / "scan.png")
    saved = save_review(source, [BOX])
    restored = load_review(source)
    assert restored.points == saved.points
    assert restored.revision == saved.revision
    assert restored.size == (360, 240)
    assert len(restored.digest) == 64
    assert restored.quads()[0].tilt_deg == 0
    assert save_review(source, [BOX]).revision == saved.revision


def test_review_remembers_rotations_and_includes_them_in_revision(tmp_path):
    source = scan(tmp_path / "scan.png")
    original = save_review(source, [BOX])
    rotated = save_review(source, [BOX], rotations=[270])
    assert load_review(source).rotations == [270]
    assert rotated.revision != original.revision
    assert save_review(source, [BOX], rotations=[270]).revision == rotated.revision


def test_legacy_boxes_load_with_zero_rotation(tmp_path):
    source = scan(tmp_path / "scan.png")
    original = save_review(source, [BOX])
    path = review_path(source)
    payload = json.loads(path.read_text(encoding="utf8"))
    payload["version"] = 1
    payload.pop("rotations", None)
    path.write_text(json.dumps(payload), encoding="utf8")
    assert load_review(source).rotations == [0]
    assert load_review(source).points == original.points


@pytest.mark.parametrize("rotations", [[45], [], [0, 90], [float("nan")]])
def test_bad_rotations_cannot_replace_saved_review(tmp_path, rotations):
    source = scan(tmp_path / "scan.png")
    original = save_review(source, [BOX])
    with pytest.raises(ValueError):
        save_review(source, [BOX], rotations=rotations)
    assert load_review(source).revision == original.revision


def test_export_applies_saved_rotation_without_automatic_override(tmp_path, monkeypatch):
    from smartscan.pipeline import _read_source
    from smartscan.split import deskew_and_crop
    from smartscan.detection import estimate_background
    from smartscan.rotation import apply_state
    import smartscan.pipeline as pipeline

    source = scan(tmp_path / "scan.png")
    saved = save_review(source, [BOX], rotations=[90])
    def unexpected_auto(*args):
        raise AssertionError("Saved preview direction must not be changed automatically")
    monkeypatch.setattr(pipeline, "_auto_orientation", unexpected_auto)
    result = run(BatchConfig([source], tmp_path / "out", require_review=True))
    assert len(result.ok) == 1 and not result.failed
    array, _, _ = _read_source(source)
    crop = deskew_and_crop(array, saved.quads()[0], estimate_background(array))
    with Image.open(result.ok[0].path) as output:
        assert np.array_equal(np.asarray(output), apply_state(crop, 90))
    assert read_metadata(result.ok[0].path)["rotation"] == "90"
    assert result.ok[0].orientation == "manual"
    assert not run(BatchConfig([source], tmp_path / "out")).ok
    save_review(source, [BOX], rotations=[180])
    assert len(run(BatchConfig([source], tmp_path / "out")).ok) == 1


def test_changed_source_never_receives_old_boxes(tmp_path):
    source = scan(tmp_path / "scan.png")
    save_review(source, [BOX])
    Image.new("RGB", (360, 240), (10, 20, 30)).save(source)
    assert load_review(source) is None


@pytest.mark.parametrize("points", [
    [(0, 0), (360, 0), (360, 239), (0, 239)],
    [(0, 0), (200, 200), (0, 200), (200, 0)],
    [(0, 0), (100, 0), (20, 20), (0, 100)],
    [(float("nan"), 0), (100, 0), (100, 100), (0, 100)],
])
def test_invalid_review_does_not_replace_saved_geometry(tmp_path, points):
    source = scan(tmp_path / "scan.png")
    saved = save_review(source, [BOX])
    with pytest.raises(ValueError):
        save_review(source, [points])
    assert load_review(source).revision == saved.revision


def test_bad_cache_is_ignored(tmp_path):
    source = scan(tmp_path / "scan.png")
    save_review(source, [BOX])
    path = review_path(source)
    path.write_text("broken json", encoding="utf8")
    assert load_review(source) is None
    path.write_text(json.dumps({"version": 1, "size": [360, 240]}), encoding="utf8")
    assert load_review(source) is None


def test_reviewed_export_uses_native_boxes_and_reexports_only_changed_revision(tmp_path):
    source = scan(tmp_path / "scan.png")
    out = tmp_path / "out"
    saved = save_review(source, [BOX])
    first = run(BatchConfig([source], out))
    assert len(first.ok) == 1 and not first.review
    meta = read_metadata(first.ok[0].path)
    assert meta["review_revision"] == saved.revision
    assert meta["detection_method"] == "reviewed"
    with Image.open(first.ok[0].path) as image:
        assert image.width >= 319 and image.height >= 199
        assert abs(image.info["dpi"][0] - 600) < 1
    previous = first.ok[0].path.read_bytes()
    assert not run(BatchConfig([source], out)).ok
    left = [(20, 20), (175, 20), (175, 219), (20, 219)]
    right = [(185, 20), (339, 20), (339, 219), (185, 219)]
    save_review(source, [left, right])
    second = run(BatchConfig([source], out))
    assert len(second.ok) == 2
    assert first.ok[0].path.read_bytes() == previous
    assert len(list(out.glob("*.png"))) == 3


def test_confirmed_empty_scan_does_not_fall_back_to_auto_detection(tmp_path):
    source = scan(tmp_path / "scan.png")
    save_review(source, [])
    result = run(BatchConfig([source], tmp_path / "out"))
    assert not result.ok and not result.failed and not result.review


def test_partial_reviewed_export_resumes_only_missing_crops(tmp_path):
    source = scan(tmp_path / "scan.png")
    boxes = [[(20, 20), (175, 20), (175, 219), (20, 219)],
             [(185, 20), (339, 20), (339, 219), (185, 219)]]
    save_review(source, boxes)
    config = BatchConfig([source], tmp_path / "out")
    first = run(config)
    preserved = first.ok[0].path.read_bytes()
    first.ok[1].path.unlink()
    resumed = run(config)
    assert len(resumed.ok) == 1
    assert read_metadata(resumed.ok[0].path)["review_crop_index"] == "1"
    assert first.ok[0].path.read_bytes() == preserved
    assert len(list(config.output_dir.glob("*.png"))) == 2
    assert not run(config).ok


def test_review_only_batch_never_falls_back_to_auto_for_changed_sources(tmp_path):
    source = scan(tmp_path / "scan.png")
    save_review(source, [BOX])
    Image.new("RGB", (360, 240), (80, 90, 100)).save(source)
    result = run(BatchConfig([source], tmp_path / "out", require_review=True))
    assert not result.ok
    assert len(result.failed) == 1
    assert "校正" in result.failed[0][1]
