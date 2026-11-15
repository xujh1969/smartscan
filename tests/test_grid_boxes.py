"""按行列等分铺框：一键生成待确认候选框，可整步撤销，不改自动检测。

真实扫描件多为每页 5~6 张照片的规整拼贴，纸边证据不足时自动检测常只给出
一个覆盖整页的框。等分网格让用户从「微调 6 个框」开始，而不是「手画 5 个框」。
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6 import QtGui

from smartscan.gui.review_dialog import CropScene, ReviewDialog
from smartscan.review import save_review

BOX = [(20, 20), (180, 20), (180, 180), (20, 180)]


def make_scene(width: int = 400, height: int = 300) -> CropScene:
    scene = CropScene()
    picture = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGB32)
    picture.fill(QtGui.QColor("gray"))
    scene.set_image(picture)
    return scene


def source_file(path):
    Image.fromarray(np.full((300, 400, 3), 140, np.uint8)).save(path)
    return path


def test_grid_boxes_cover_the_whole_scan_in_row_major_order(qapp):
    scene = make_scene()

    count = scene.set_grid(3, 2)

    assert count == 6
    boxes = scene.points()
    assert len(boxes) == 6
    assert boxes[0][0] == (0.0, 0.0)
    assert abs(boxes[0][2][0] - 199.5) < 1
    assert abs(boxes[0][2][1] - 99.67) < 1
    assert all(0 <= x <= 399 and 0 <= y <= 299 for box in boxes for x, y in box)
    assert all(item.uncertain for item in scene.quad_items)


def test_grid_boxes_can_be_undone_in_one_step(qapp):
    scene = make_scene()
    scene.set_quads([BOX])
    original = scene.points()

    scene.set_grid(2, 2)

    assert len(scene.points()) == 4
    scene.undo()
    assert scene.points() == original


def test_grid_can_be_limited_to_an_existing_area(qapp):
    scene = make_scene()
    scene.set_quads([[(100, 50), (300, 50), (300, 250), (100, 250)]])

    scene.set_grid(2, 2, area=(100, 50, 300, 250))

    boxes = scene.points()
    assert len(boxes) == 4
    assert boxes[0][0] == (100.0, 50.0)
    assert abs(boxes[0][2][0] - 200) < 1
    assert abs(boxes[0][2][1] - 150) < 1
    assert abs(boxes[-1][2][0] - 300) < 1
    assert abs(boxes[-1][2][1] - 250) < 1


def test_review_dialog_grid_starts_from_the_auto_detected_area(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [[(40, 30), (360, 30), (360, 270), (40, 270)]])
    dialog = ReviewDialog([source])

    dialog.grid_rows.setValue(2)
    dialog.grid_columns.setValue(2)
    dialog.grid_button.click()

    boxes = dialog.scene.points()
    assert len(boxes) == 4
    assert boxes[0][0] == (40.0, 30.0)
    assert abs(boxes[-1][2][0] - 360) < 1
    assert abs(boxes[-1][2][1] - 270) < 1
    dialog.reject()


def test_review_dialog_grid_button_replaces_boxes_and_marks_them_unconfirmed(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    original = dialog.scene.points()

    dialog.grid_rows.setValue(3)
    dialog.grid_columns.setValue(2)
    dialog.grid_button.click()

    assert len(dialog.scene.points()) == 6
    assert all(item.uncertain for item in dialog.scene.quad_items)
    assert "候选" in dialog.status.text()
    assert "未确认" in dialog.status.text()
    dialog.undo_button.click()
    assert dialog.scene.points() == original
    dialog.reject()


def test_saving_grid_boxes_clears_the_unconfirmed_marker(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])

    dialog.grid_button.click()

    assert all(item.uncertain for item in dialog.scene.quad_items)
    assert dialog.save_current()
    assert not any(item.uncertain for item in dialog.scene.quad_items)
    dialog.reject()


def test_grid_controls_are_disabled_when_the_scan_cannot_be_loaded(qapp, tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_text("not an image", encoding="utf8")
    dialog = ReviewDialog([broken])

    assert not dialog.grid_button.isEnabled()
    assert not dialog.grid_rows.isEnabled()
    assert not dialog.grid_columns.isEnabled()
    dialog.reject()
