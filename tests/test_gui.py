import numpy as np
from PIL import Image

from smartscan.gui.app import MainWindow
from smartscan.metadata import build_text_chunk, read_metadata, write_png
from smartscan.models import SplitResult


def _result(tmp_path):
    path = tmp_path / "001_abcd1234.png"
    arr = np.arange(180, dtype=np.uint8).reshape(6, 10, 3)
    text = build_text_chunk(
        source="s.tif",
        digest="abcd1234",
        quad=[(0, 0), (10, 0), (10, 6), (0, 6)],
        tilt_deg=0.0,
        rotation=0,
        orientation="unknown",
        flags=[],
        confidence=0.9,
    )
    write_png(path, Image.fromarray(arr), dpi=(600, 600), text=text)
    return SplitResult(path=path, source="s.tif", digest="abcd1234")


def test_main_window_has_three_pages_and_start_disabled(qapp):
    window = MainWindow()
    assert window.page_count() == 3
    assert window.select_page.start_button.isEnabled() is False
    window.close()


def test_select_page_enables_start_when_files_and_output_are_set(qapp, tmp_path):
    window = MainWindow()
    source = tmp_path / "a.tif"
    source.write_bytes(b"scan")

    window.select_page.add_files([str(source)])
    window.select_page.set_output_dir(str(tmp_path))

    assert window.select_page.start_button.isEnabled() is True
    window.close()


def test_result_page_rotates_a_photo_and_updates_disk(qapp, tmp_path):
    result = _result(tmp_path)
    window = MainWindow()
    window.result_page.set_results([result])

    assert window.result_page.card_count() == 1
    window.result_page.rotate_card(0, 1)

    assert read_metadata(result.path)["rotation"] == "90"
    with Image.open(result.path) as image:
        assert image.size == (6, 10)
    window.close()


def test_result_page_can_inspect_a_photo(qapp, tmp_path):
    result = _result(tmp_path)
    window = MainWindow()
    window.result_page.set_results([result])

    window.result_page.inspect_card(0)

    assert window.result_page.last_dialog is not None
    assert "查看" in window.result_page.last_dialog.windowTitle()
    window.close()
