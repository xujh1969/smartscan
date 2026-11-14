"""Main window and application entry point."""

from __future__ import annotations

import os
import sys

from PySide6 import QtCore, QtWidgets

from .pages.progress_page import ProgressPage
from .pages.result_page import ResultPage
from .pages.select_page import SelectPage


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SmartScan — 老照片扫描件批量拆分")
        self.resize(1080, 720)

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
        self.stack.setCurrentWidget(self.progress_page)
        self.progress_page.start(config)

    def _show_results(self, result) -> None:
        self.result_page.set_results(result.ok)
        self.stack.setCurrentWidget(self.result_page)

    def _back_to_select(self) -> None:
        self.stack.setCurrentWidget(self.select_page)


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
