from PIL import Image

from smartscan.metadata import read_metadata
from smartscan.models import BatchConfig
from smartscan.pipeline import estimate_disk_need, run
from tests.synthetic import make_scan_file


def _run(config):
    return run(config, progress=lambda *args: None, cancel=lambda: False)


def test_failure_of_one_file_does_not_stop_batch(tmp_path):
    good = make_scan_file(tmp_path / "g.tif")
    bad = tmp_path / "missing.tif"

    result = _run(BatchConfig([good, bad], tmp_path / "out"))

    assert len(result.ok) == 1
    assert len(result.failed) == 1
    assert all(p.suffix == ".png" for p in (tmp_path / "out").iterdir())


def test_output_png_keeps_dpi_and_source_metadata(tmp_path):
    source = make_scan_file(tmp_path / "g.tif")

    result = _run(BatchConfig([source], tmp_path / "out"))

    assert len(result.ok) == 1
    with Image.open(source) as source_image:
        expected_dpi = tuple(round(v) for v in source_image.info["dpi"])
    with Image.open(result.ok[0].path) as image:
        assert tuple(round(v) for v in image.info["dpi"]) == expected_dpi
    meta = read_metadata(result.ok[0].path)
    assert meta["source"] == str(source.resolve())
    assert len(meta["digest"]) == 8


def test_rerun_skips_completed_files_and_never_overwrites(tmp_path):
    source = make_scan_file(tmp_path / "g.tif")
    out = tmp_path / "out"
    first = _run(BatchConfig([source], out))
    before = {p.name: p.read_bytes() for p in out.glob("*.png")}

    second = _run(BatchConfig([source], out))
    after = {p.name: p.read_bytes() for p in out.glob("*.png")}

    assert len(first.ok) == 1
    assert len(second.ok) == 0
    assert before == after


def test_estimate_disk_need_is_positive(tmp_path):
    source = make_scan_file(tmp_path / "g.tif")
    assert estimate_disk_need(BatchConfig([source], tmp_path / "out")) > 0


def test_over_tilt_photos_are_exported_and_flagged_not_silently_dropped(tmp_path):
    source = make_scan_file(tmp_path / "g.tif", angle_deg=30.0)

    result = _run(BatchConfig([source], tmp_path / "out", max_tilt_deg=5.0))

    assert len(result.ok) == 1
    assert "low_confidence" in result.ok[0].flags
    assert result.review == [source]
