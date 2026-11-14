import numpy as np
import subprocess
import sys
import pytest
from PIL import Image
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from smartscan.gui.review_dialog import CropScene, CropView, ReviewDialog
from smartscan.gui.pages.select_page import SelectPage
from smartscan.review import load_review, save_review
from smartscan.geometry import order_quad


BOX = [(20, 20), (180, 20), (180, 180), (20, 180)]


def source_file(path):
    Image.fromarray(np.full((300, 400, 3), 140, np.uint8)).save(path)
    return path


def make_view(qapp):
    scene = CropScene()
    picture = QtGui.QImage(400, 300, QtGui.QImage.Format.Format_RGB32)
    picture.fill(QtGui.QColor("gray"))
    scene.set_image(picture)
    view = CropView(scene)
    view.resize(800, 600)
    view.show()
    qapp.processEvents()
    view.fit_image()
    return scene, view


def drag(view, start, end):
    a = view.mapFromScene(QtCore.QPointF(*start))
    b = view.mapFromScene(QtCore.QPointF(*end))
    QtTest.QTest.mousePress(view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=a)
    QtTest.QTest.mouseMove(view.viewport(), b, 40)
    QtTest.QTest.mouseRelease(view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=b)


def test_mouse_can_adjust_add_and_delete_crop_boxes(qapp):
    scene, view = make_view(qapp)
    scene.add_quad(BOX)
    scene.add_quad([(220, 20), (360, 20), (360, 180), (220, 180)])
    drag(view, (20, 20), (35, 35))
    assert np.allclose(scene.points()[0][0], (35, 35), atol=2)
    assert scene.points()[1][0] == (220, 20)
    scene.draw_mode = True
    drag(view, (30, 210), (150, 280))
    assert len(scene.points()) == 3
    scene.remove_selected()
    assert len(scene.points()) == 2
    view.close()


def test_undo_reverses_each_drag_add_and_delete_as_one_operation(qapp):
    scene, view = make_view(qapp)
    scene.set_quads([BOX])
    original = scene.points()
    drag(view, (20, 20), (45, 40))
    moved = scene.points()
    scene.set_draw_mode(True)
    drag(view, (220, 30), (350, 180))
    added = scene.points()
    scene.remove_selected()
    scene.undo()
    assert scene.points() == added
    assert scene.quad_items[-1].isSelected()
    scene.undo()
    assert scene.points() == moved
    scene.undo()
    assert scene.points() == original
    scene.undo()
    assert scene.points() == original
    view.close()


def test_ctrl_z_from_toolbar_undoes_and_saved_result_stays_undone(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    original = dialog.scene.points()
    drag(dialog.view, (20, 20), (40, 40))
    assert dialog.undo_button.isEnabled()
    dialog.save_current()
    dialog.add_button.setFocus()
    QtTest.QTest.keyClick(dialog.add_button, QtCore.Qt.Key.Key_Z, QtCore.Qt.KeyboardModifier.ControlModifier)
    assert dialog.scene.points() == original
    assert dialog.user_edited
    dialog.reject()
    assert load_review(source).points == original


def test_drag_undo_groups_multiple_moves_and_ignores_invalid_edits(qapp):
    scene, view = make_view(qapp)
    scene.set_quads([BOX])
    original = scene.points()
    start = view.mapFromScene(QtCore.QPointF(20, 20))
    QtTest.QTest.mousePress(view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=start)
    for point in ((30, 30), (40, 40), (50, 50)):
        QtTest.QTest.mouseMove(view.viewport(), view.mapFromScene(QtCore.QPointF(*point)), 20)
    QtTest.QTest.mouseRelease(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                             pos=view.mapFromScene(QtCore.QPointF(50, 50)))
    assert scene.points() != original
    scene.move_corner(scene.quad_items[0], 0, (250, 250))
    scene.undo()
    assert scene.points() == original
    scene.undo()
    assert scene.points() == original
    view.close()


def test_delete_during_corner_drag_preserves_undo_order(qapp):
    scene, view = make_view(qapp)
    scene.set_quads([BOX])
    original = scene.points()
    QtTest.QTest.mousePress(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           pos=view.mapFromScene(QtCore.QPointF(20, 20)))
    QtTest.QTest.mouseMove(view.viewport(), view.mapFromScene(QtCore.QPointF(40, 40)), 30)
    moved = scene.points()
    scene.remove_selected()
    QtTest.QTest.mouseRelease(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                             pos=view.mapFromScene(QtCore.QPointF(40, 40)))
    assert scene.points() == []
    scene.undo()
    assert scene.points() == moved
    scene.undo()
    assert scene.points() == original
    view.close()


def test_preview_gives_canvas_height_and_places_draw_in_top_toolbar(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.resize(1000, 700)
    dialog.show()
    qapp.processEvents()
    assert dialog.add_button.mapTo(dialog, QtCore.QPoint()).y() < dialog.view.mapTo(dialog, QtCore.QPoint()).y()
    assert dialog.view.height() > dialog.height() * 0.70
    assert not any(label.isVisible() and "按住空格" in label.text()
                   for label in dialog.findChildren(QtWidgets.QLabel))
    dialog.reject()


def test_loading_another_scan_clears_undo_history(qapp, tmp_path):
    sources = [source_file(tmp_path / name) for name in ("one.png", "two.png")]
    for source in sources:
        save_review(source, [BOX])
    dialog = ReviewDialog(sources)
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))
    dialog.next_source()
    original = dialog.scene.points()
    dialog.scene.undo()
    assert dialog.scene.points() == original
    dialog.reject()


def test_failed_scan_load_cannot_undo_previous_scan_boxes(qapp, tmp_path):
    source = source_file(tmp_path / "one.png")
    save_review(source, [BOX])
    broken = tmp_path / "broken.png"
    broken.write_text("invalid image")
    dialog = ReviewDialog([source, broken])
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))
    dialog.next_source()
    assert not dialog.current_valid
    dialog.scene.undo()
    assert dialog.scene.points() == []
    dialog.reject()


def test_corner_cannot_cross_or_leave_the_scan(qapp):
    scene, view = make_view(qapp)
    item = scene.add_quad(BOX)
    scene.move_corner(item, 0, (200, 200))
    assert scene.points()[0][0] == (20, 20)
    scene.move_corner(item, 0, (-30, -30))
    assert scene.points()[0][0] == (20, 20)
    view.close()


def test_shared_corner_edits_the_selected_crop(qapp):
    scene, view = make_view(qapp)
    first = scene.add_quad(BOX)
    second_points = [(180, 20), (340, 20), (340, 180), (180, 180)]
    scene.add_quad(second_points)
    scene.clearSelection()
    first.setSelected(True)
    drag(view, (180, 20), (170, 30))
    assert np.allclose(first.points[1], (170, 30), atol=2)
    assert scene.points()[1] == second_points
    view.close()


def test_navigation_remembers_boxes_and_batch_export_uses_saved_sources(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    two = source_file(tmp_path / "two.png")
    save_review(one, [BOX])
    save_review(two, [BOX])
    dialog = ReviewDialog([one, two])
    dialog.show()
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))
    dialog.next_source()
    assert (30, 30) in load_review(one).points[0]
    dialog.scene.add_quad([(220, 20), (360, 20), (360, 180), (220, 180)])
    captured = []
    dialog.export_requested.connect(captured.append)
    dialog.export_saved()
    assert captured == [[one, two]]
    restored = ReviewDialog([one, two])
    assert (30, 30) in restored.scene.points()[0]
    restored.next_source()
    assert len(restored.scene.points()) == 2
    restored.reject()


def test_close_remembers_actual_edits(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    save_review(one, [BOX])
    dialog = ReviewDialog([one])
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))
    dialog.reject()
    assert (30, 30) in load_review(one).points[0]


def test_select_page_opens_review_and_dispatches_one_batch(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    page = SelectPage()
    assert not page.review_button.isEnabled()
    page.add_files([str(source)])
    page.set_output_dir(str(tmp_path / "out"))
    captured = []
    page.batch_requested.connect(captured.append)
    page.review_button.click()
    dialog = page.last_review_dialog
    assert dialog is not None
    dialog.export_saved()
    assert len(captured) == 1
    assert captured[0].source_files == [source]
    assert captured[0].require_review
    page.close()


def test_dialog_can_close_during_initial_detection(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    dialog = ReviewDialog([source])
    dialog.show()
    assert dialog.busy
    dialog.reject()
    for _ in range(500):
        qapp.processEvents()
        if not dialog.busy:
            break
        QtTest.QTest.qWait(10)
    assert not dialog.busy
    assert dialog.worker is None
    assert not dialog.isVisible()
    assert load_review(source) is None


def test_save_failure_keeps_edits_and_does_not_advance(qapp, tmp_path, monkeypatch):
    import smartscan.gui.review_dialog as module

    one = source_file(tmp_path / "one.png")
    two = source_file(tmp_path / "two.png")
    save_review(one, [BOX])
    dialog = ReviewDialog([one, two])
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))

    def denied(*args, **kwargs):
        raise OSError("disk unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(module, "save_review", denied)
        dialog.next_source()
        assert dialog.index == 0 and dialog.dirty
        assert "保存失败" in dialog.status.text()
    dialog.reject()


def test_batch_does_not_silently_confirm_unvisited_scans(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    two = tmp_path / "two.png"
    Image.new("RGB", (400, 300), (40, 50, 60)).save(two)
    save_review(one, [BOX])
    dialog = ReviewDialog([one, two])
    batches = []
    dialog.export_requested.connect(batches.append)
    dialog.export_saved()
    assert batches == [[one]]
    assert load_review(two) is None


def test_review_dialog_exits_cleanly_in_a_fresh_process(tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    result = subprocess.run([sys.executable, "-X", "faulthandler", "-m", "pytest",
                             "tests/test_review_gui.py::test_navigation_remembers_boxes_and_batch_export_uses_saved_sources",
                             "-q", "--basetemp", str(tmp_path / "child-pytest")],
                            capture_output=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_zoom_and_mouse_pan_keep_boxes_registered_to_native_pixels(qapp):
    scene, view = make_view(qapp)
    scene.add_quad(BOX)
    before = scene.points()
    view.scale(2, 2)
    qapp.processEvents()
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum() // 2)
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum() // 2)
    center = QtCore.QPoint(400, 280)
    original = view.mapFromScene(QtCore.QPointF(20, 20))
    QtTest.QTest.mousePress(view.viewport(), QtCore.Qt.MouseButton.MiddleButton, pos=center)
    QtTest.QTest.mouseMove(view.viewport(), center + QtCore.QPoint(45, 30), 40)
    QtTest.QTest.mouseRelease(view.viewport(), QtCore.Qt.MouseButton.MiddleButton,
                             pos=center + QtCore.QPoint(45, 30))
    moved = view.mapFromScene(QtCore.QPointF(20, 20))
    assert moved.x() - original.x() >= 40
    assert moved.y() - original.y() >= 25
    wheel = QtGui.QWheelEvent(QtCore.QPointF(center), QtCore.QPointF(view.mapToGlobal(center)),
                              QtCore.QPoint(), QtCore.QPoint(0, 120),
                              QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.NoModifier,
                              QtCore.Qt.ScrollPhase.NoScrollPhase, False)
    scale = view.transform().m11()
    qapp.sendEvent(view.viewport(), wheel)
    assert view.transform().m11() > scale
    assert scene.points() == before
    image = next(item for item in scene.items() if item.zValue() == -1)
    assert view.mapFromScene(image.mapToScene(QtCore.QPointF(20, 20))) == view.mapFromScene(
        scene.quad_items[0].handles[0].scenePos())
    view.close()


def test_space_drag_pans_without_editing_a_crop_corner(qapp):
    scene, view = make_view(qapp)
    scene.add_quad(BOX)
    view.scale(2, 2)
    qapp.processEvents()
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum() // 2)
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum() // 2)
    view.setFocus()
    before = scene.points()
    origin = view.mapFromScene(QtCore.QPointF(20, 20))
    QtTest.QTest.keyPress(view, QtCore.Qt.Key.Key_Space)
    drag(view, (20, 20), (30, 30))
    QtTest.QTest.keyRelease(view, QtCore.Qt.Key.Key_Space)
    assert view.mapFromScene(QtCore.QPointF(20, 20)) != origin
    assert scene.points() == before
    assert not view._space_down
    view.close()


def test_replacing_a_source_while_editing_never_saves_old_boxes_to_new_image(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    original = source.read_bytes()
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))
    Image.new("RGB", (400, 300), (50, 60, 70)).save(source)
    assert load_review(source) is None
    assert dialog.save_current() is False
    assert load_review(source) is None
    assert "变化" in dialog.status.text()
    source.write_bytes(original)
    dialog.reject()


def test_failed_auto_detection_still_allows_manual_boxes(qapp, tmp_path, monkeypatch):
    import smartscan.gui.review_dialog as module

    source = source_file(tmp_path / "scan.png")

    def failed(*args, **kwargs):
        raise RuntimeError("detector failed")

    monkeypatch.setattr(module, "detect_quads", failed)
    dialog = ReviewDialog([source])
    for _ in range(500):
        qapp.processEvents()
        if not dialog.busy:
            break
        QtTest.QTest.qWait(10)
    assert not dialog.busy
    assert dialog.current_valid and dialog.add_button.isEnabled()
    assert "手工绘制" in dialog.status.text()
    dialog.scene.add_quad(BOX)
    assert dialog.save_current()
    assert len(load_review(source).points) == 1
    dialog.reject()


def test_export_rechecks_saved_sources_that_have_not_been_reopened(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    two = tmp_path / "two.png"
    Image.new("RGB", (400, 300), (40, 50, 60)).save(two)
    save_review(one, [BOX])
    save_review(two, [BOX])
    dialog = ReviewDialog([one, two])
    Image.new("RGB", (400, 300), (70, 80, 90)).save(two)
    batches = []
    dialog.export_requested.connect(batches.append)
    dialog.export_saved()
    assert not batches
    assert two not in dialog.confirmed
    assert "变化" in dialog.status.text()
    dialog.reject()


def test_scan_navigation_overlays_preview_sides_and_distinguishes_photo_boxes(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    two = tmp_path / "two.png"
    Image.new("RGB", (400, 300), (30, 40, 50)).save(two)
    boxes = [[(10 + x, 20), (90 + x, 20), (90 + x, 180), (10 + x, 180)]
             for x in (0, 100, 200)]
    save_review(one, boxes)
    save_review(two, [BOX])
    dialog = ReviewDialog([one, two])
    dialog.show()
    qapp.processEvents()
    assert "扫描图 1 / 2" in dialog.heading.text()
    assert "3 个照片裁切框" in dialog.heading.toolTip()
    assert dialog.next_button.text() == ">"
    assert dialog.previous_button.text() == "<"
    viewport = dialog.view.viewport()
    for button in (dialog.previous_button, dialog.next_button):
        assert button.parentWidget() is dialog.view
        center = viewport.mapFromGlobal(button.mapToGlobal(button.rect().center()))
        assert abs(center.y() - viewport.rect().center().y()) <= 1
        assert button.width() == button.height()
    assert dialog.previous_button.x() < dialog.next_button.x()
    QtTest.QTest.mouseClick(dialog.next_button, QtCore.Qt.MouseButton.LeftButton)
    assert dialog.index == 1
    assert "扫描图 2 / 2" in dialog.heading.text()
    assert "最后一张扫描图" in dialog.heading.toolTip()
    assert not dialog.next_button.isEnabled()
    assert len(load_review(one).points) == 3
    dialog.reject()


def test_thumbnail_sidebar_switches_scans_and_saves_current_boxes(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    two = tmp_path / "two.png"
    Image.new("RGB", (400, 300), (40, 80, 100)).save(two)
    for source in (one, two):
        save_review(source, [BOX])
    dialog = ReviewDialog([one, two])
    dialog.show()
    qapp.processEvents()
    assert dialog.thumbnails.count() == 2
    assert dialog.thumbnails.currentRow() == 0
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))
    rect = dialog.thumbnails.visualItemRect(dialog.thumbnails.item(1))
    QtTest.QTest.mouseClick(dialog.thumbnails.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           pos=rect.center())
    assert dialog.index == 1 and dialog.thumbnails.currentRow() == 1
    assert (30, 30) in load_review(one).points[0]
    for _ in range(30):
        if all(not dialog.thumbnails.item(i).icon().isNull() for i in range(2)):
            break
        QtTest.QTest.qWait(20)
    assert all(not dialog.thumbnails.item(i).icon().isNull() for i in range(2))
    assert dialog.thumbnails.mapTo(dialog, QtCore.QPoint()).x() < dialog.view.mapTo(dialog, QtCore.QPoint()).x()
    assert dialog.thumbnails.visualItemRect(dialog.thumbnails.item(1)).top() > dialog.thumbnails.visualItemRect(dialog.thumbnails.item(0)).top()
    dialog.reject()


def test_clicking_other_thumbnail_saves_new_box_and_all_four_corner_edits(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    two = tmp_path / "two.png"
    Image.new("RGB", (400, 300), (40, 80, 100)).save(two)
    for source in (one, two):
        save_review(source, [BOX])
    dialog = ReviewDialog([one, two])
    dialog.show()
    qapp.processEvents()
    dialog.add_button.click()
    drag(dialog.view, (220, 30), (360, 220))
    for start, end in [((220, 30), (225, 40)), ((360, 30), (350, 35)),
                       ((360, 220), (355, 210)), ((220, 220), (230, 215))]:
        drag(dialog.view, start, end)
    expected = dialog.scene.points()
    assert len(expected) == 2 and dialog.user_edited
    expected = [order_quad(points) for points in expected]
    rect = dialog.thumbnails.visualItemRect(dialog.thumbnails.item(1))
    QtTest.QTest.mouseClick(dialog.thumbnails.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           pos=rect.center())
    assert dialog.index == 1
    assert load_review(one).points == expected
    rect = dialog.thumbnails.visualItemRect(dialog.thumbnails.item(0))
    QtTest.QTest.mouseClick(dialog.thumbnails.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           pos=rect.center())
    assert dialog.index == 0 and dialog.scene.points() == expected
    dialog.reject()


def test_click_on_already_selected_thumbnail_opens_it_and_saves_current_edit(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    two = tmp_path / "two.png"
    Image.new("RGB", (400, 300), (40, 80, 100)).save(two)
    for source in (one, two):
        save_review(source, [BOX])
    dialog = ReviewDialog([one, two])
    dialog.show()
    qapp.processEvents()
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))
    with QtCore.QSignalBlocker(dialog.thumbnails):
        dialog.thumbnails.setCurrentRow(1)
    rect = dialog.thumbnails.visualItemRect(dialog.thumbnails.item(1))
    QtTest.QTest.mouseClick(dialog.thumbnails.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           pos=rect.center())
    assert dialog.index == 1
    assert (30, 30) in load_review(one).points[0]
    dialog.reject()


def test_thumbnail_selection_stays_on_current_scan_when_save_fails(qapp, tmp_path, monkeypatch):
    sources = [source_file(tmp_path / name) for name in ("one.png", "two.png")]
    for source in sources:
        save_review(source, [BOX])
    dialog = ReviewDialog(sources)
    monkeypatch.setattr(dialog, "save_current", lambda: False)
    dialog.thumbnails.setCurrentRow(1)
    assert dialog.index == 0 and dialog.thumbnails.currentRow() == 0
    dialog.reject()


def test_selected_thumbnail_has_an_outline_even_without_focus(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    dialog.add_button.setFocus()
    qapp.processEvents()
    assert dialog.thumbnails.item(0).isSelected()
    rect = dialog.thumbnails.visualItemRect(dialog.thumbnails.item(0))
    image = dialog.thumbnails.viewport().grab().toImage()
    border = [image.pixelColor(x, y).name()
              for x in range(rect.left(), rect.right() + 1)
              for y in (rect.top() + 1, rect.bottom() - 1)]
    assert "#087bb5" in border
    dialog.reject()


def test_crop_previews_rotate_save_switch_and_restore(qapp, tmp_path):
    one = source_file(tmp_path / "one.png")
    two = tmp_path / "two.png"
    Image.new("RGB", (400, 300), (40, 80, 100)).save(two)
    wide = [(20, 20), (180, 20), (180, 100), (20, 100)]
    save_review(one, [wide])
    save_review(two, [BOX])
    dialog = ReviewDialog([one, two])
    dialog.show()
    qapp.processEvents()
    dialog._refresh_crop_previews()
    assert len(dialog.preview_cards) == 1
    card = dialog.preview_cards[0]
    assert card.cw_button.parentWidget() is card.image_label
    assert card.ccw_button.parentWidget() is card.image_label
    assert card.image_label.pixmap().width() > card.image_label.pixmap().height()
    card.cw_button.click()
    assert dialog.scene.rotations() == [90]
    dialog._refresh_crop_previews()
    card = dialog.preview_cards[0]
    assert card.image_label.pixmap().width() < card.image_label.pixmap().height()
    dialog.thumbnails.setCurrentRow(1)
    assert load_review(one).rotations == [90]
    dialog.thumbnails.setCurrentRow(0)
    assert dialog.scene.rotations() == [90]
    dialog._refresh_crop_previews()
    dialog.preview_cards[0].ccw_button.click()
    assert dialog.scene.rotations() == [0]
    QtTest.QTest.keyClick(dialog.view, QtCore.Qt.Key.Key_Z, QtCore.Qt.KeyboardModifier.ControlModifier)
    assert dialog.scene.rotations() == [90]
    dialog.reject()
    reopened = ReviewDialog([one])
    assert reopened.scene.rotations() == [90]
    reopened.reject()


def test_rotation_stays_with_its_box_through_corner_edits_delete_and_undo(qapp):
    scene, view = make_view(qapp)
    scene.set_quads([BOX, [(220, 20), (360, 20), (360, 180), (220, 180)]])
    box = scene.quad_items[0]
    scene.rotate_quad(box, -1)
    scene.move_corner(box, 0, (30, 30))
    assert scene.rotations() == [270, 0]
    scene.clearSelection()
    box.setSelected(True)
    scene.remove_selected()
    assert scene.rotations() == [0]
    scene.undo()
    assert scene.rotations() == [270, 0]
    scene.undo()
    assert scene.rotations() == [270, 0]
    scene.undo()
    assert scene.rotations() == [0, 0]
    view.close()


def test_sidebar_scrolls_to_all_scans_and_overlay_tracks_resize(qapp, tmp_path):
    sources = [source_file(tmp_path / f"scan-{i}.png") for i in range(18)]
    save_review(sources[0], [BOX])
    dialog = ReviewDialog(sources)
    dialog.resize(984, 620)
    dialog.show()
    qapp.processEvents()
    last = dialog.thumbnails.item(17)
    dialog.thumbnails.scrollToItem(last)
    qapp.processEvents()
    QtTest.QTest.mouseClick(dialog.thumbnails.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           pos=dialog.thumbnails.visualItemRect(last).center())
    assert dialog.index == 17 and dialog.thumbnails.currentRow() == 17
    assert not dialog.next_button.isEnabled() and dialog.previous_button.isEnabled()
    for width, height in ((1100, 760), (984, 620)):
        dialog.resize(width, height)
        qapp.processEvents()
        area = dialog.view.viewport().rect()
        for button in (dialog.previous_button, dialog.next_button):
            pos = dialog.view.viewport().mapFromGlobal(button.mapToGlobal(QtCore.QPoint()))
            assert area.contains(QtCore.QRect(pos, button.size()))
            assert abs(pos.y() + button.height() / 2 - area.height() / 2) <= 1
    QtTest.QTest.mouseClick(dialog.previous_button, QtCore.Qt.MouseButton.LeftButton)
    assert dialog.index == 16 and dialog.thumbnails.currentRow() == 16
    assert "border-color" in dialog.next_button.styleSheet()
    assert "QPushButton:hover" in dialog.next_button.styleSheet()
    dialog.reject()


def test_navigation_stays_on_viewport_midline_after_zoom_and_scroll(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source, source])
    dialog.show()
    qapp.processEvents()

    def assert_fixed():
        area = dialog.view.viewport().rect()
        for button, x in ((dialog.previous_button, 12),
                          (dialog.next_button, area.width() - 52)):
            pos = dialog.view.viewport().mapFromGlobal(button.mapToGlobal(QtCore.QPoint()))
            assert pos.x() == x
            assert abs(pos.y() + button.height() / 2 - area.height() / 2) <= 1

    assert_fixed()
    dialog.view.scale(3, 3)
    qapp.processEvents()
    dialog.view.horizontalScrollBar().setValue(dialog.view.horizontalScrollBar().value() + 65)
    dialog.view.verticalScrollBar().setValue(dialog.view.verticalScrollBar().value() + 45)
    qapp.processEvents()
    assert_fixed()
    center = dialog.view.viewport().rect().center()
    wheel = QtGui.QWheelEvent(QtCore.QPointF(center),
                              QtCore.QPointF(dialog.view.viewport().mapToGlobal(center)),
                              QtCore.QPoint(), QtCore.QPoint(0, 120),
                              QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.NoModifier,
                              QtCore.Qt.ScrollPhase.NoScrollPhase, False)
    qapp.sendEvent(dialog.view.viewport(), wheel)
    qapp.processEvents()
    assert_fixed()
    for button in (QtCore.Qt.MouseButton.MiddleButton, QtCore.Qt.MouseButton.LeftButton):
        if button == QtCore.Qt.MouseButton.LeftButton:
            QtTest.QTest.keyPress(dialog.view, QtCore.Qt.Key.Key_Space)
        QtTest.QTest.mousePress(dialog.view.viewport(), button, pos=center)
        QtTest.QTest.mouseMove(dialog.view.viewport(), center + QtCore.QPoint(35, 25), 30)
        QtTest.QTest.mouseRelease(dialog.view.viewport(), button, pos=center + QtCore.QPoint(35, 25))
        if button == QtCore.Qt.MouseButton.LeftButton:
            QtTest.QTest.keyRelease(dialog.view, QtCore.Qt.Key.Key_Space)
        qapp.processEvents()
        assert_fixed()
    dialog.view.scale(0.7, 0.7)
    qapp.processEvents()
    assert_fixed()
    dialog.view.fit_image()
    qapp.processEvents()
    assert_fixed()
    dialog.reject()


def test_loaded_thumbnail_lower_edge_is_clickable_after_crop_edit(qapp, tmp_path):
    sources = [source_file(tmp_path / f"{i}.png") for i in range(4)]
    one = sources[0]
    for source in sources:
        save_review(source, [BOX])
    dialog = ReviewDialog(sources)
    dialog.thumbnail_timer.stop()
    dialog.show()
    qapp.processEvents()
    for _ in sources:
        dialog._load_thumbnail()
    rect = dialog.thumbnails.visualItemRect(dialog.thumbnails.item(1))
    lower_edge = QtCore.QPoint(rect.center().x(), rect.bottom() - 5)
    assert dialog.thumbnails.indexAt(lower_edge).row() == 1
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (30, 30))
    QtTest.QTest.mouseClick(dialog.thumbnails.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           pos=lower_edge)
    assert dialog.index == 1
    assert (30, 30) in load_review(one).points[0]
    dialog.reject()


def test_single_scan_explains_disabled_next_and_how_to_add_more(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    assert "仅添加了 1 张扫描图" in dialog.heading.toolTip()
    assert "返回选择扫描图" in dialog.heading.toolTip()
    assert not dialog.next_button.isEnabled()
    assert "没有下一张" in dialog.next_button.toolTip()
    assert dialog.return_button.text() == "返回选择扫描图"
    dialog.reject()


@pytest.mark.parametrize("width,height", [(1024, 700), (1280, 720)])
def test_review_controls_fit_smaller_screens(qapp, tmp_path, monkeypatch, width, height):
    class Screen:
        def availableGeometry(self):
            return QtCore.QRect(0, 0, width, height)

    monkeypatch.setattr(QtGui.QGuiApplication, "primaryScreen", lambda: Screen())
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    assert dialog.width() <= width - 40
    assert dialog.height() <= height - 80
    for button in (dialog.previous_button, dialog.next_button, dialog.export_button,
                   dialog.return_button):
        assert button.mapTo(dialog, QtCore.QPoint()).y() + button.height() <= dialog.height()
    dialog.reject()


def test_space_is_temporary_pan_even_after_a_toolbar_button_has_focus(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    center_box = [(120, 80), (260, 80), (260, 220), (120, 220)]
    save_review(source, [center_box])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    dialog.view.scale(2, 2)
    dialog.view.horizontalScrollBar().setValue(dialog.view.horizontalScrollBar().maximum() // 2)
    dialog.view.verticalScrollBar().setValue(dialog.view.verticalScrollBar().maximum() // 2)
    dialog.save_button.setFocus()
    before = dialog.scene.points()
    original = dialog.view.mapFromScene(QtCore.QPointF(120, 80))
    QtTest.QTest.keyPress(dialog.save_button, QtCore.Qt.Key.Key_Space)
    assert dialog.view._space_down
    assert dialog.view.viewport().cursor().shape() == QtCore.Qt.CursorShape.OpenHandCursor
    drag(dialog.view, (120, 80), (130, 90))
    assert dialog.scene.points() == before
    assert dialog.view.mapFromScene(QtCore.QPointF(120, 80)) != original
    QtTest.QTest.keyRelease(dialog.view, QtCore.Qt.Key.Key_Space)
    assert not dialog.view._space_down
    assert dialog.view.viewport().cursor().shape() == QtCore.Qt.CursorShape.ArrowCursor
    drag(dialog.view, (120, 80), (130, 90))
    assert np.allclose(dialog.scene.points()[0][0], (130, 90), atol=2)
    dialog.reject()


def test_drawing_a_box_returns_immediately_to_corner_editing(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    QtTest.QTest.mouseClick(dialog.add_button, QtCore.Qt.MouseButton.LeftButton)
    drag(dialog.view, (220, 30), (360, 180))
    assert len(dialog.scene.points()) == 2
    assert not dialog.scene.draw_mode and not dialog.add_button.isChecked()
    assert dialog.scene.quad_items[-1].isSelected()
    drag(dialog.view, (220, 30), (230, 40))
    assert len(dialog.scene.points()) == 2
    assert np.allclose(dialog.scene.points()[-1][0], (230, 40), atol=2)
    dialog.reject()


@pytest.mark.parametrize("draft_started", [False, True])
def test_escape_cancels_new_box_without_closing_preview(qapp, tmp_path, draft_started):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    before = dialog.scene.points()
    QtTest.QTest.mouseClick(dialog.add_button, QtCore.Qt.MouseButton.LeftButton)
    if draft_started:
        start = dialog.view.mapFromScene(QtCore.QPointF(220, 30))
        end = dialog.view.mapFromScene(QtCore.QPointF(360, 180))
        QtTest.QTest.mousePress(dialog.view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=start)
        QtTest.QTest.mouseMove(dialog.view.viewport(), end, 30)
        assert dialog.scene._rubber is not None
        QtTest.QTest.keyClick(dialog.view, QtCore.Qt.Key.Key_Escape)
        QtTest.QTest.mouseRelease(dialog.view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=end)
    else:
        QtTest.QTest.keyClick(dialog.add_button, QtCore.Qt.Key.Key_Escape)
    assert dialog.isVisible()
    assert not dialog.scene.draw_mode and not dialog.add_button.isChecked()
    assert dialog.scene._rubber is None
    assert dialog.scene.points() == before
    drag(dialog.view, (20, 20), (35, 35))
    assert np.allclose(dialog.scene.points()[0][0], (35, 35), atol=2)
    dialog.reject()


def test_space_auto_repeat_does_not_release_temporary_pan(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    QtTest.QTest.keyPress(dialog.save_button, QtCore.Qt.Key.Key_Space)
    for kind in (QtCore.QEvent.Type.KeyRelease, QtCore.QEvent.Type.KeyPress):
        repeat = QtGui.QKeyEvent(kind, QtCore.Qt.Key.Key_Space,
                                 QtCore.Qt.KeyboardModifier.NoModifier, " ", True)
        qapp.sendEvent(dialog.view, repeat)
        assert dialog.view._space_down
    QtTest.QTest.keyRelease(dialog.view, QtCore.Qt.Key.Key_Space)
    assert not dialog.view._space_down
    dialog.reject()


def test_space_cancels_unfinished_drawing_and_release_restores_editing(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    before = dialog.scene.points()
    QtTest.QTest.mouseClick(dialog.add_button, QtCore.Qt.MouseButton.LeftButton)
    start = dialog.view.mapFromScene(QtCore.QPointF(220, 30))
    end = dialog.view.mapFromScene(QtCore.QPointF(360, 180))
    QtTest.QTest.mousePress(dialog.view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=start)
    QtTest.QTest.mouseMove(dialog.view.viewport(), end, 30)
    QtTest.QTest.keyPress(dialog.view, QtCore.Qt.Key.Key_Space)
    assert dialog.scene._rubber is None and not dialog.scene.draw_mode
    QtTest.QTest.mouseRelease(dialog.view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=end)
    QtTest.QTest.keyRelease(dialog.view, QtCore.Qt.Key.Key_Space)
    assert dialog.scene.points() == before
    assert not dialog.add_button.isChecked()
    drag(dialog.view, (20, 20), (35, 35))
    assert np.allclose(dialog.scene.points()[0][0], (35, 35), atol=2)
    dialog.reject()


def test_editor_escape_does_not_intercept_a_separate_warning_dialog(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    message = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Warning, "保存失败", "保留未保存的编辑？",
                                    QtWidgets.QMessageBox.StandardButton.Discard
                                    | QtWidgets.QMessageBox.StandardButton.Cancel, dialog)
    message.show()
    qapp.processEvents()
    QtTest.QTest.keyClick(message, QtCore.Qt.Key.Key_Escape)
    warning_closed = not message.isVisible()
    editor_still_open = dialog.isVisible()
    message.close()
    dialog.reject()
    assert warning_closed and editor_still_open


def test_closing_while_space_is_held_releases_temporary_pan(qapp, tmp_path):
    source = source_file(tmp_path / "scan.png")
    save_review(source, [BOX])
    dialog = ReviewDialog([source])
    dialog.show()
    qapp.processEvents()
    QtTest.QTest.keyPress(dialog.view, QtCore.Qt.Key.Key_Space)
    assert dialog.view._space_down
    dialog.reject()
    assert not dialog.view._space_down
    assert not dialog.isVisible()
