import threading

from PySide6 import QtCore, QtTest, QtWidgets

from smartscan.gui.app import MainWindow
from smartscan.models import BatchConfig, BatchResult
from smartscan.review import load_review, save_review
from tests.synthetic import make_scan_file


BOX = [(30, 30), (180, 30), (180, 160), (30, 160)]


def wait_for(qapp, predicate):
    for _ in range(500):
        qapp.processEvents()
        if predicate():
            return
        QtTest.QTest.qWait(10)
    assert predicate(), "Worker did not finish safely"


def setup_window(tmp_path):
    source = make_scan_file(tmp_path / "scan.png")
    window = MainWindow()
    window.select_page.add_files([str(source)])
    window.select_page.set_output_dir(str(tmp_path / "out"))
    window.show()
    return window, source


def complete_batch(qapp, window, sources, output):
    for source in sources:
        save_review(source, [BOX])
    window._start_batch(BatchConfig(sources, output, require_review=True))
    wait_for(qapp, lambda: window.stack.currentWidget() is window.result_page
             and not window.progress_page.worker.isRunning())


def test_unfinished_exit_shows_a_prompt_and_continue_is_the_default(qapp, tmp_path, monkeypatch):
    window, source = setup_window(tmp_path)
    seen = []

    def continue_working():
        message = qapp.activeModalWidget()
        if isinstance(message, QtWidgets.QMessageBox):
            seen.append((message.windowTitle(), message.defaultButton().text()))
            message.defaultButton().click()

    QtCore.QTimer.singleShot(0, continue_working)
    window.close()
    qapp.processEvents()
    stayed_open = window.isVisible()
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: True, raising=False)
    window.close()
    assert seen and "未完成" in seen[0][0]
    assert seen[0][1] == "继续工作"
    assert stayed_open


def test_completed_batch_does_not_prompt_until_boxes_change(qapp, tmp_path, monkeypatch):
    window, source = setup_window(tmp_path)
    complete_batch(qapp, window, [source], tmp_path / "out")
    prompts = []
    monkeypatch.setattr(window, "_confirm_unfinished_exit",
                        lambda *args: prompts.append(args) or False, raising=False)
    window.close()
    assert not prompts and not window.isVisible()
    window.show()
    save_review(source, [[(40, 30), (170, 30), (170, 160), (40, 160)]])
    window.close()
    stayed_open = window.isVisible()
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: True)
    window.close()
    assert prompts and stayed_open


def test_exporting_a_subset_leaves_other_selected_scans_unfinished(qapp, tmp_path, monkeypatch):
    window, source = setup_window(tmp_path)
    other = make_scan_file(tmp_path / "other.png")
    window.select_page.add_files([str(other)])
    complete_batch(qapp, window, [source], tmp_path / "out")
    prompts = []
    monkeypatch.setattr(window, "_confirm_unfinished_exit",
                        lambda *args: prompts.append(args) or True, raising=False)
    window.close()
    assert prompts and prompts[0][0] == 1


def test_exit_during_a_batch_confirms_then_waits_for_safe_stop(qapp, tmp_path, monkeypatch):
    import smartscan.gui.pages.progress_page as module

    started, release = threading.Event(), threading.Event()

    def slow_run(config, progress, cancel):
        started.set()
        release.wait(5)
        return BatchResult()

    monkeypatch.setattr(module, "run", slow_run)
    window, source = setup_window(tmp_path)
    window._start_batch(BatchConfig([source], tmp_path / "out"))
    wait_for(qapp, started.is_set)
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: False, raising=False)
    window.close()
    declined = window.isVisible() and not window.progress_page.worker._cancel
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: True)
    window.close()
    stop_requested = window.progress_page.worker._cancel
    waiting = window.isVisible()
    release.set()
    wait_for(qapp, lambda: not window.progress_page.worker.isRunning())
    wait_for(qapp, lambda: not window.isVisible())
    assert declined and stop_requested and waiting


def test_confirmed_exit_saves_editor_changes(qapp, tmp_path, monkeypatch):
    window, source = setup_window(tmp_path)
    save_review(source, [BOX])
    window.select_page._review()
    dialog = window.select_page.last_review_dialog
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (40, 40))
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: True, raising=False)
    window.close()
    assert (40, 40) in load_review(source).points[0]
    assert not window.isVisible()


def test_discard_exit_does_not_save_new_boxes_or_rotations(qapp, tmp_path, monkeypatch):
    window, source = setup_window(tmp_path)
    original = save_review(source, [BOX])
    window.select_page._review()
    dialog = window.select_page.last_review_dialog
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (40, 40))
    dialog.scene.rotate_quad(dialog.scene.quad_items[0], 1)
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: "discard")
    def unexpected_save():
        raise AssertionError("Do not save when discarding edits")
    monkeypatch.setattr(dialog, "save_current", unexpected_save)
    window.close()
    assert not window.isVisible() and not dialog.isVisible()
    assert load_review(source).revision == original.revision


def test_exit_prompt_offers_a_real_discard_choice(qapp, tmp_path):
    window, source = setup_window(tmp_path)
    choices = []
    def discard():
        message = qapp.activeModalWidget()
        choices.extend(button.text() for button in message.buttons())
        for button in message.buttons():
            if button.text() == "不保存并退出":
                button.click()
                break
    QtCore.QTimer.singleShot(0, discard)
    window.close()
    assert not window.isVisible()
    assert set(choices) == {"继续工作", "保存并退出", "不保存并退出"}


def test_failed_save_keeps_editor_and_program_open(qapp, tmp_path, monkeypatch):
    window, source = setup_window(tmp_path)
    save_review(source, [BOX])
    window.select_page._review()
    dialog = window.select_page.last_review_dialog
    dialog.scene.move_corner(dialog.scene.quad_items[0], 0, (40, 40))
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: True)
    monkeypatch.setattr(dialog, "save_current", lambda: False)
    window.close()
    assert window.isVisible() and dialog.isVisible() and dialog.user_edited
    monkeypatch.undo()
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: True)
    window.close()


def test_exit_waits_for_preview_detection(qapp, tmp_path, monkeypatch):
    import smartscan.gui.review_dialog as module

    started, release = threading.Event(), threading.Event()

    def slow_detect(*args):
        started.set()
        release.wait(5)
        return []

    monkeypatch.setattr(module, "detect_quads", slow_detect)
    window, source = setup_window(tmp_path)
    window.select_page._review()
    dialog = window.select_page.last_review_dialog
    wait_for(qapp, started.is_set)
    monkeypatch.setattr(window, "_confirm_unfinished_exit", lambda *args: True)
    window.close()
    waiting = window.isVisible()
    release.set()
    wait_for(qapp, lambda: not window.isVisible())
    assert waiting and not dialog.isVisible()


def test_detection_can_finish_while_exit_confirmation_is_open(qapp, tmp_path, monkeypatch):
    import smartscan.gui.review_dialog as module

    started, release = threading.Event(), threading.Event()

    def slow_detect(*args):
        started.set()
        release.wait(5)
        return []

    monkeypatch.setattr(module, "detect_quads", slow_detect)
    window, source = setup_window(tmp_path)
    window.select_page._review()
    dialog = window.select_page.last_review_dialog
    wait_for(qapp, started.is_set)

    def confirm_after_detection():
        release.set()
        wait_for(qapp, lambda: dialog.worker is None)
        message = qapp.activeModalWidget()
        for button in message.buttons():
            if message.buttonRole(button) == QtWidgets.QMessageBox.ButtonRole.AcceptRole:
                button.click()
                break

    QtCore.QTimer.singleShot(0, confirm_after_detection)
    window.close()
    assert not window.isVisible() and not dialog.isVisible()


def test_batch_cancel_returns_to_selection_after_recording_completed_work(qapp, tmp_path, monkeypatch):
    import smartscan.gui.pages.progress_page as module

    started, release = threading.Event(), threading.Event()

    def slow_run(config, progress, cancel):
        started.set()
        release.wait(5)
        return BatchResult(completed=list(config.source_files))

    monkeypatch.setattr(module, "run", slow_run)
    window, source = setup_window(tmp_path)
    window._start_batch(BatchConfig([source], tmp_path / "out"))
    wait_for(qapp, started.is_set)
    window.progress_page.cancel_clicked()
    assert window.stack.currentWidget() is window.progress_page
    release.set()
    wait_for(qapp, lambda: window.stack.currentWidget() is window.select_page)
    assert not window._unfinished_sources()
    window.close()
