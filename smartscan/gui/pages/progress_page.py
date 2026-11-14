"""Page 2: background batch processing with progress and cancellation."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from smartscan.pipeline import run


class BatchWorker(QtCore.QThread):
    progressed = QtCore.Signal(int, int, str)
    finished_batch = QtCore.Signal(object)
    errored = QtCore.Signal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            result = run(
                self.config,
                progress=lambda *args: self.progressed.emit(*args),
                cancel=lambda: self._cancel,
            )
            self.finished_batch.emit(result)
        except Exception as exc:
            self.errored.emit(str(exc))


class ProgressPage(QtWidgets.QWidget):
    batch_finished = QtCore.Signal(object)
    cancelled = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: BatchWorker | None = None

        self.progress_bar = QtWidgets.QProgressBar()
        self.stage_label = QtWidgets.QLabel("等待开始")
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.cancel_button = QtWidgets.QPushButton("取消（保留已完成结果）")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("正在拆分…"))
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.stage_label)
        layout.addWidget(self.log, stretch=1)
        layout.addWidget(self.cancel_button)

        self.cancel_button.clicked.connect(self.cancel_clicked)

    def start(self, config) -> None:
        self.log.clear()
        self.progress_bar.setValue(0)
        self.worker = BatchWorker(config)
        self.worker.progressed.connect(self._on_progress)
        self.worker.finished_batch.connect(self._on_done)
        self.worker.errored.connect(self._on_error)
        self.worker.start()

    def cancel_clicked(self) -> None:
        if self.worker is not None:
            self.worker.request_cancel()
        self.cancelled.emit()

    def _on_progress(self, done: int, total: int, stage: str) -> None:
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(done)
        self.stage_label.setText(f"{done}/{total} · {stage}")
        self.log.appendPlainText(f"{done}/{total} · {stage}")

    def _on_done(self, result) -> None:
        self.log.appendPlainText(
            f"完成：成功 {len(result.ok)} 张，失败 {len(result.failed)} 个文件，"
            f"待复核 {len(result.review)} 个文件"
        )
        self.batch_finished.emit(result)

    def _on_error(self, message: str) -> None:
        self.log.appendPlainText(f"错误：{message}")
        self.cancelled.emit()
