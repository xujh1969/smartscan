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
        self._cancel_pending = False
        self._result = None
        self._error = None

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
        if self.worker is not None and self.worker.isRunning():
            return
        self.log.clear()
        self._cancel_pending = False
        self._result = self._error = None
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.worker = BatchWorker(config)
        self.worker.progressed.connect(self._on_progress)
        self.worker.finished_batch.connect(self._on_done)
        self.worker.errored.connect(self._on_error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def cancel_clicked(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._cancel_pending = True
            self.worker.request_cancel()
            self.cancel_button.setEnabled(False)
            self.stage_label.setText("正在完成当前扫描图的保存，然后安全停止…")

    def _on_progress(self, done: int, total: int, stage: str) -> None:
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(done)
        self.stage_label.setText(f"{done}/{total} · {stage}")
        self.log.appendPlainText(f"{done}/{total} · {stage}")

    def _on_done(self, result) -> None:
        self._result = result
        state = "已停止" if self._cancel_pending else "完成"
        self.log.appendPlainText(
            f"{state}：成功 {len(result.ok)} 张，失败 {len(result.failed)} 个文件，"
            f"待复核 {len(result.review)} 个文件"
        )

    def _on_error(self, message: str) -> None:
        self._error = message
        self.log.appendPlainText(f"错误：{message}")

    def _worker_finished(self):
        if self._error is not None or self._result is None:
            self.cancelled.emit()
        else:
            self.batch_finished.emit(self._result)
            if self._cancel_pending:
                self.cancelled.emit()
