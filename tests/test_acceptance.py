"""Acceptance-level checks for the design spec's verification checklist."""

import numpy as np
from PIL import Image

from smartscan.gui.app import MainWindow
from smartscan.gui.pages.result_page import RotationStore
from smartscan.metadata import build_text_chunk, read_metadata, write_png
from smartscan.models import BatchConfig, SplitResult
from smartscan.pipeline import run
from tests.synthetic import make_scan_file


def _text():
    return build_text_chunk(
        source="s.tif",
        digest="abcd1234",
        quad=[(0, 0), (10, 0), (10, 6), (0, 6)],
        tilt_deg=0.0,
        rotation=0,
        orientation="unknown",
        flags=[],
        confidence=0.9,
    )


def _png(tmp_path, name):
    path = tmp_path / name
    array = np.arange(180, dtype=np.uint8).reshape(6, 10, 3)
    write_png(path, Image.fromarray(array), dpi=(600, 600), text=_text())
    return SplitResult(path=path, source="s.tif", digest="abcd1234")


def test_rotation_state_can_be_restored_after_a_restart(tmp_path):
    path = tmp_path / "001_abcd1234.png"
    base = np.arange(180, dtype=np.uint8).reshape(6, 10, 3)
    text = _text()
    text["rotation"] = "90"
    text["orientation"] = "auto"
    text["flags"] = "auto"
    write_png(path, Image.fromarray(np.rot90(base, -1).copy()), dpi=(600, 600), text=text)
    result = SplitResult(
        path=path,
        source="s.tif",
        digest="abcd1234",
        rotation=90,
        orientation="auto",
        flags=["auto"],
    )

    store = RotationStore()
    store.register(result)
    state = store.rotate(result, -1)

    assert state == 0
    with Image.open(path) as image:
        assert np.array_equal(np.asarray(image.convert("RGB")), base)
    assert read_metadata(path)["rotation"] == "0"


def test_cancel_keeps_already_completed_results(tmp_path):
    first = make_scan_file(tmp_path / "a.tif")
    second = make_scan_file(tmp_path / "b.tif")
    output = tmp_path / "out"
    calls = {"count": 0}

    def cancel():
        calls["count"] += 1
        return calls["count"] > 1

    result = run(
        BatchConfig([first, second], output),
        progress=lambda *args: None,
        cancel=cancel,
    )

    assert len(result.ok) == 1
    assert len(list(output.glob("*.png"))) == 1


def test_batch_rotation_only_touches_checked_photos(qapp, tmp_path):
    one = _png(tmp_path, "001_abcd1234.png")
    two = _png(tmp_path, "002_abcd1234.png")
    window = MainWindow()
    window.result_page.set_results([one, two])

    window.result_page._cards[0].checkbox.setChecked(True)
    window.result_page.batch_cw.click()

    assert read_metadata(one.path)["rotation"] == "90"
    assert read_metadata(two.path)["rotation"] == "0"
    window.close()
