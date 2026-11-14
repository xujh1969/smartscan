import numpy as np
from PIL import Image

from smartscan.metadata import build_text_chunk, read_metadata, write_png
from smartscan.rotation import rotate_and_save


def _make_png(path):
    arr = np.zeros((6, 10, 3), dtype=np.uint8)
    arr[:, :4] = (120, 120, 120)
    arr[:, 4:] = (200, 200, 200)
    text = build_text_chunk(
        source="s.tif",
        digest="abcd1234",
        quad=[(0, 0), (10, 0), (10, 6), (0, 6)],
        tilt_deg=0.0,
        rotation=0,
        orientation="unknown",
        flags=["incomplete", "auto"],
        confidence=0.9,
    )
    write_png(path, Image.fromarray(arr), dpi=(600, 600), text=text)
    return arr


def test_rotate_and_save_changes_pixels_and_metadata(tmp_path):
    path = tmp_path / "001_abcd1234.png"
    base = _make_png(path)

    state = rotate_and_save(path, base, step=1, current_state=0)

    assert state == 90
    meta = read_metadata(path)
    assert meta["rotation"] == "90"
    assert meta["orientation"] == "manual"
    assert "auto" not in meta["flags"]
    assert "incomplete" in meta["flags"]
    with Image.open(path) as image:
        assert image.size == (6, 10)
        assert tuple(round(v) for v in image.info["dpi"]) == (600, 600)


def test_two_rotations_always_start_from_base(tmp_path):
    path = tmp_path / "001_abcd1234.png"
    base = _make_png(path)

    rotate_and_save(path, base, step=1, current_state=0)
    state = rotate_and_save(path, base, step=1, current_state=90)

    assert state == 180
    with Image.open(path) as image:
        written = np.asarray(image.convert("RGB"))
    assert np.array_equal(written, np.rot90(base, 2))
