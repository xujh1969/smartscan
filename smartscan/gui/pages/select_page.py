"""Page 1: choose a batch of scans (any directories) and one output folder."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from smartscan.models import BatchConfig


class DropListWidget(QtWidgets.QListWidget):
    files_dropped = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class SelectPage(QtWidgets.QWidget):
    batch_requested = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files: list[str] = []

        self.file_list = DropListWidget()
        self.file_list.files_dropped.connect(self.add_files)
        self.add_button = QtWidgets.QPushButton("添加扫描图…")
        self.remove_button = QtWidgets.QPushButton("移除选中")
        self.clear_button = QtWidgets.QPushButton("清空")
        self.output_edit = QtWidgets.QLineEdit()
        self.output_edit.setPlaceholderText("用于存放拆分结果的一个目录")
        self.output_button = QtWidgets.QPushButton("选择输出目录…")
        self.tilt_spin = QtWidgets.QSpinBox()
        self.tilt_spin.setRange(1, 45)
        self.tilt_spin.setValue(20)
        self.tilt_spin.setSuffix("°")
        self.fill_combo = QtWidgets.QComboBox()
        self.fill_combo.addItem("背景色填充四角", "background")
        self.fill_combo.addItem("内接裁切（不填充）", "inset")
        self.fill_combo.addItem("透明四角", "alpha")
        self.start_button = QtWidgets.QPushButton("开始拆分处理")
        self.start_button.setEnabled(False)
        self.review_button = QtWidgets.QPushButton("预览、校正裁切框，再批量裁切…")
        self.review_button.setEnabled(False)
        self.last_review_dialog = None

        file_buttons = QtWidgets.QHBoxLayout()
        for button in (self.add_button, self.remove_button, self.clear_button):
            file_buttons.addWidget(button)
        file_buttons.addStretch(1)

        output_row = QtWidgets.QHBoxLayout()
        output_row.addWidget(self.output_edit)
        output_row.addWidget(self.output_button)

        settings_row = QtWidgets.QHBoxLayout()
        settings_row.addWidget(QtWidgets.QLabel("自动扶正倾角上限"))
        settings_row.addWidget(self.tilt_spin)
        settings_row.addWidget(QtWidgets.QLabel("四角处理"))
        settings_row.addWidget(self.fill_combo)
        settings_row.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("① 添加扫描图（可一次多选；每张扫描图可包含多张照片）"))
        layout.addLayout(file_buttons)
        layout.addWidget(self.file_list, stretch=1)
        layout.addWidget(QtWidgets.QLabel("② 指定结果目录（只输出平铺 PNG）"))
        layout.addLayout(output_row)
        layout.addLayout(settings_row)
        layout.addWidget(self.review_button)
        layout.addWidget(QtWidgets.QLabel("已保存的裁切框会优先使用；原始扫描件保持不变。"))
        layout.addWidget(self.start_button)

        self.add_button.clicked.connect(self._pick_files)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_files)
        self.output_button.clicked.connect(self._pick_output)
        self.output_edit.textChanged.connect(lambda _: self._update_start())
        self.start_button.clicked.connect(self._emit_batch)
        self.review_button.clicked.connect(self._review)

    def add_files(self, paths: list[str]) -> None:
        for path in paths:
            if path and path not in self.files:
                self.files.append(path)
                self.file_list.addItem(path)
        self._update_start()

    def set_output_dir(self, path: str) -> None:
        self.output_edit.setText(path)

    def _update_start(self) -> None:
        self.start_button.setEnabled(
            bool(self.files and self.output_edit.text().strip())
        )
        self.review_button.setEnabled(self.start_button.isEnabled())

    def _pick_files(self) -> None:
        selected, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "选择扫描图（可按 Ctrl+A 全选或 Ctrl 多选）",
            "",
            "图像 (*.png *.jpg *.jpeg *.tif *.tiff *.bmp);;全部 (*.*)",
        )
        if selected:
            self.add_files(selected)

    def _remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            text = item.text()
            if text in self.files:
                self.files.remove(text)
            self.file_list.takeItem(self.file_list.row(item))
        self._update_start()

    def _clear_files(self) -> None:
        self.files.clear()
        self.file_list.clear()
        self._update_start()

    def _pick_output(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "选择结果目录")
        if folder:
            self.set_output_dir(folder)

    def _review(self):
        from smartscan.gui.review_dialog import ReviewDialog

        if self.last_review_dialog is not None and self.last_review_dialog.isVisible():
            self.last_review_dialog.raise_()
            return
        dialog = ReviewDialog([Path(path) for path in self.files], self,
                              fill_mode=self.fill_combo.currentData())
        dialog.export_requested.connect(self._emit_batch)
        self.last_review_dialog = dialog
        dialog.show()

    def _emit_batch(self, sources=None) -> None:
        # QPushButton.clicked supplies a bool; the review dialog supplies paths.
        files = sources if isinstance(sources, list) else [Path(p) for p in self.files]
        config = BatchConfig(
            source_files=files,
            output_dir=Path(self.output_edit.text().strip()),
            max_tilt_deg=float(self.tilt_spin.value()),
            fill_mode=self.fill_combo.currentData(),
            require_review=isinstance(sources, list),
        )
        self.batch_requested.emit(config)
