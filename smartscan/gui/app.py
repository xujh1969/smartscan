"""Main window and application entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from smartscan.review import load_review, source_identity

from .pages.progress_page import ProgressPage
from .pages.result_page import ResultPage
from .pages.select_page import SelectPage


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SmartScan — 老照片扫描件批量拆分")
        self.resize(1080, 720)
        self._completed_work = {}
        self._batch_signatures = {}
        self._exit_confirmed = False
        self._exit_pending = False

        self.stack = QtWidgets.QStackedWidget()
        self.select_page = SelectPage()
        self.progress_page = ProgressPage()
        self.result_page = ResultPage()
        for page in (self.select_page, self.progress_page, self.result_page):
            self.stack.addWidget(page)
        self.setCentralWidget(self.stack)

        self.select_page.batch_requested.connect(self._start_batch)
        self.progress_page.batch_finished.connect(self._show_results)
        self.progress_page.cancelled.connect(self._back_to_select)

    def page_count(self) -> int:
        return self.stack.count()

    def _start_batch(self, config) -> None:
        if self.progress_page.worker is not None and self.progress_page.worker.isRunning():
            return
        self._batch_signatures = {}
        for source in config.source_files:
            key = str(source.resolve())
            self._completed_work.pop(key, None)
            try:
                self._batch_signatures[key] = self._work_signature(source, config)
            except (OSError, ValueError):
                pass
        self.stack.setCurrentWidget(self.progress_page)
        self.progress_page.start(config)

    def _show_results(self, result) -> None:
        for source in result.completed:
            key = str(source.resolve())
            if source not in result.review and key in self._batch_signatures:
                self._completed_work[key] = self._batch_signatures[key]
        if self._exit_pending:
            return
        self.result_page.set_results(result.ok)
        self.stack.setCurrentWidget(self.result_page)

    def _back_to_select(self) -> None:
        if not self._exit_pending:
            self.stack.setCurrentWidget(self.select_page)

    def _work_signature(self, source, config=None):
        digest, _ = source_identity(source)
        reviewed = load_review(source)
        output = config.output_dir if config is not None else Path(self.select_page.output_edit.text())
        fill = config.fill_mode if config is not None else self.select_page.fill_combo.currentData()
        tilt = config.max_tilt_deg if config is not None else self.select_page.tilt_spin.value()
        return (digest, reviewed.revision if reviewed is not None else "",
                str(output.resolve()), fill, float(tilt))

    def _unfinished_sources(self):
        pending = []
        for name in self.select_page.files:
            source = Path(name)
            key = str(source.resolve())
            if key in self._completed_work:
                try:
                    if self._completed_work[key] == self._work_signature(source):
                        continue
                except (OSError, ValueError):
                    pass
            pending.append(source)
        return pending

    def _running_workers(self):
        workers = []
        worker = self.progress_page.worker
        if worker is not None and worker.isRunning():
            workers.append(worker)
        review = self.select_page.last_review_dialog
        if review is not None and review.worker is not None and review.worker.isRunning():
            workers.append(review.worker)
        return workers

    def _confirm_unfinished_exit(self, pending_count, running):
        message = QtWidgets.QMessageBox(self)
        message.setWindowTitle("工作尚未完成")
        message.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message.setText("当前工作尚未完成，确定退出程序吗？")
        detail = (f"还有 {pending_count} 张扫描图尚未完成批量裁切。" if pending_count
                  else "当前还有未保存或未导出的裁切框。")
        detail += "\n可保存裁切框与旋转设置后退出，或丢弃当前未保存的编辑。已导出的照片会保留。"
        if running:
            detail += "\n后台处理会在当前扫描图保存完成后安全停止，请稍候。"
        message.setInformativeText(detail)
        stay = message.addButton("继续工作", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        leave = message.addButton("保存并退出", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        discard = message.addButton("不保存并退出", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        message.setDefaultButton(stay)
        message.setEscapeButton(stay)
        message.exec()
        if message.clickedButton() is discard:
            return "discard"
        return "save" if message.clickedButton() is leave else False

    def _finish_exit_when_idle(self):
        if self._exit_pending and not self._running_workers():
            self.close()

    def showEvent(self, event):
        if not self._exit_pending:
            self._exit_confirmed = False
        super().showEvent(event)

    def closeEvent(self, event):
        workers = self._running_workers()
        if self._exit_pending:
            if workers:
                event.ignore()
            else:
                self._exit_pending = False
                event.accept()
            return
        review = self.select_page.last_review_dialog
        review_open = review is not None and review.isVisible()
        unsaved = review_open and (review.user_edited or review.scene._rubber is not None)
        pending = self._unfinished_sources()
        decision = "save"
        if not self._exit_confirmed and (pending or workers or unsaved):
            decision = self._confirm_unfinished_exit(len(pending), bool(workers))
            if not decision:
                event.ignore()
                return
        if decision != "discard" and review_open and review.user_edited and not review.save_current():
            event.ignore()
            return
        # The confirmation runs a nested event loop; detection may have finished
        # and deleted its worker while the user was deciding.
        workers = self._running_workers()
        self._exit_confirmed = True
        self._exit_pending = True
        for worker in workers:
            worker.finished.connect(self._finish_exit_when_idle)
        if review_open:
            if decision == "discard":
                review.discard_and_close()
            else:
                review.reject()
        self.progress_page.cancel_clicked()
        if self._running_workers():
            self.statusBar().showMessage("正在保存当前扫描图并安全停止，完成后退出…")
            event.ignore()
        else:
            self._exit_pending = False
            event.accept()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    smoke = "--smoke" in args
    if smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    if smoke:
        QtCore.QTimer.singleShot(0, app.quit)
    return app.exec()
