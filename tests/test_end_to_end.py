import cv2
import numpy as np
from PIL import Image

from smartscan.geometry import rotate_points
from smartscan.metadata import read_metadata
from smartscan.models import BatchConfig
from smartscan.pipeline import run
from smartscan.rotation import rotate_and_save


def _composite_scan(path):
    canvas = np.full((360, 420, 3), 240, dtype=np.uint8)
    cv2.rectangle(canvas, (10, 10), (110, 90), (150, 150, 150), thickness=-1)
    cv2.rectangle(canvas, (110, 10), (210, 90), (90, 90, 90), thickness=-1)

    corners = [(240, 40), (360, 40), (360, 100), (240, 100)]
    tilted = np.round(
        np.asarray(rotate_points(corners, 10.0, (300, 70)))
    ).astype(np.int32)
    cv2.fillConvexPoly(canvas, tilted, (60, 60, 60))

    cv2.rectangle(canvas, (10, 200), (110, 280), (70, 70, 70), thickness=-1)
    cv2.rectangle(canvas, (80, 250), (180, 330), (150, 150, 150), thickness=-1)

    Image.fromarray(canvas).save(path, dpi=(600, 600))
    return path


def _run(config):
    return run(config, progress=lambda *args: None, cancel=lambda: False)


def test_composite_batch_produces_individual_pngs_with_metadata(tmp_path):
    source = _composite_scan(tmp_path / "batch.tif")
    output = tmp_path / "out"

    result = _run(BatchConfig([source], output))

    assert len(result.ok) >= 4
    assert len(result.failed) == 0
    assert all(p.suffix == ".png" for p in output.iterdir())
    for item in result.ok:
        with Image.open(item.path) as image:
            assert tuple(round(v) for v in image.info["dpi"]) == (600, 600)
        meta = read_metadata(item.path)
        assert meta["source"] == str(source.resolve())
        assert len(meta["digest"]) == 8
        assert meta["rotation"] in ("0", "90", "270")


def test_rerun_and_manual_rotation_preserve_everything(tmp_path):
    source = _composite_scan(tmp_path / "batch.tif")
    output = tmp_path / "out"
    first = _run(BatchConfig([source], output))
    before = {p.name: p.read_bytes() for p in output.glob("*.png")}

    second = _run(BatchConfig([source], output))
    assert len(second.ok) == 0
    assert before == {p.name: p.read_bytes() for p in output.glob("*.png")}

    chosen = first.ok[0]
    with Image.open(chosen.path) as image:
        base = np.asarray(image.convert("RGB")).copy()
    state = rotate_and_save(chosen.path, base, step=1, current_state=chosen.rotation)
    assert state == (chosen.rotation + 90) % 360
    assert read_metadata(chosen.path)["orientation"] == "manual"
