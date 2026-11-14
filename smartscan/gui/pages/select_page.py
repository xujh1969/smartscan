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
        layout.addWidget(QtWidgets.QLabel("① 选择一批扫描图（可跨目录、可拖拽）"))
        layout.addLayout(file_buttons)
        layout.addWidget(self.file_list, stretch=1)
        layout.addWidget(QtWidgets.QLabel("② 指定结果目录（只输出平铺 PNG）"))
        layout.addLayout(output_row)
        layout.addLayout(settings_row)
        layout.addWidget(self.start_button)

        self.add_button.clicked.connect(self._pick_files)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_files)
        self.output_button.clicked.connect(self._pick_output)
        self.output_edit.textChanged.connect(lambda _: self._update_start())
        self.start_button.clicked.connect(self._emit_batch)

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

    def _pick_files(self) -> None:
        selected, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "选择扫描图",
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

    def _emit_batch(self) -> None:
        config = BatchConfig(
            source_files=[Path(p) for p in self.files],
            output_dir=Path(self.output_edit.text().strip()),
            max_tilt_deg=float(self.tilt_spin.value()),
            fill_mode=self.fill_combo.currentData(),
        )
        self.batch_requested.emit(config)
