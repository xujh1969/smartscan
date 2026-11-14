"""Page 3: thumbnail grid with per-photo ±90° buttons and batch rotation."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

from smartscan.gui.thumbnails import make_thumbnail
from smartscan.metadata import read_metadata
from smartscan.models import SplitResult
from smartscan.rotation import rotate_and_save

_FILTERS = [
    ("全部", "all"),
    ("待复核", "review"),
    ("不完整 / 遮挡不确定", "incomplete"),
    ("方向未定", "unknown"),
    ("自动旋转过", "auto"),
]


class PhotoCard(QtWidgets.QFrame):
    rotate_requested = QtCore.Signal(object, int)
    inspect_requested = QtCore.Signal(object)

    def __init__(self, result: SplitResult, parent=None):
        super().__init__(parent)
        self.result = result
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFixedWidth(190)

        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.setToolTip("勾选后可批量旋转")
        self.badge = QtWidgets.QLabel()
        self.image_label = QtWidgets.QLabel()
        self.image_label.setFixedSize(160, 120)
        self.image_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.cw_button = QtWidgets.QPushButton("顺 90°")
        self.ccw_button = QtWidgets.QPushButton("逆 90°")

        head = QtWidgets.QHBoxLayout()
        head.addWidget(self.checkbox)
        head.addWidget(self.badge)
        head.addStretch(1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.ccw_button)
        buttons.addWidget(self.cw_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.image_label)
        layout.addWidget(QtWidgets.QLabel(Path(result.path).name))
        layout.addLayout(buttons)

        self.cw_button.clicked.connect(
            lambda: self.rotate_requested.emit(self.result, 1)
        )
        self.ccw_button.clicked.connect(
            lambda: self.rotate_requested.emit(self.result, -1)
        )
        self.refresh()

    def refresh(self) -> None:
        self.image_label.setPixmap(make_thumbnail(self.result.path))
        flags = [f for f in self.result.flags if f]
        self.badge.setText(" ".join(flags) if flags else self.result.orientation)

    def mouseDoubleClickEvent(self, event):
        self.inspect_requested.emit(self.result)
        super().mouseDoubleClickEvent(event)


class RotationStore:
    """Keeps the first split image in memory so every rotation starts from it."""

    def __init__(self) -> None:
        self._base: dict[Path, np.ndarray] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _load_base(result: SplitResult) -> np.ndarray:
        with Image.open(result.path) as image:
            array = np.asarray(image.convert("RGB")).copy()
        turns = (int(result.rotation) // 90) % 4
        return np.rot90(array, k=turns).copy() if turns else array

    def register(self, result: SplitResult) -> None:
        self._base[Path(result.path)] = self._load_base(result)

    def rotate(self, result: SplitResult, step: int) -> int:
        with self._lock:
            key = Path(result.path)
            base = self._base.get(key)
            if base is None:
                base = self._load_base(result)
                self._base[key] = base
            new_state = rotate_and_save(
                key, base, step=step, current_state=result.rotation
            )
            result.rotation = new_state
            result.orientation = "manual"
            result.flags = [f for f in result.flags if f != "auto"]
            return new_state


class ResultPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = RotationStore()
        self._cards: list[PhotoCard] = []
        self.last_dialog: QtWidgets.QDialog | None = None

        self.filter_combo = QtWidgets.QComboBox()
        for label, value in _FILTERS:
            self.filter_combo.addItem(label, value)
        self.batch_cw = QtWidgets.QPushButton("选中项批量顺 90°")
        self.batch_ccw = QtWidgets.QPushButton("选中项批量逆 90°")
        self.summary = QtWidgets.QLabel("未加载结果")

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(QtWidgets.QLabel("筛选"))
        toolbar.addWidget(self.filter_combo)
        toolbar.addStretch(1)
        toolbar.addWidget(self.batch_ccw)
        toolbar.addWidget(self.batch_cw)

        self._grid_widget = QtWidgets.QWidget()
        self._grid = QtWidgets.QGridLayout(self._grid_widget)
        self._grid.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_widget)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addLayout(toolbar)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(
            QtWidgets.QLabel(
                "双击缩略图查看大图与元数据；快捷键 ] 顺时针、[ 逆时针（作用于勾选照片）"
            )
        )

        self.filter_combo.currentIndexChanged.connect(
            lambda _: self._apply_filter()
        )
        self.batch_cw.clicked.connect(lambda: self._rotate_selected(1))
        self.batch_ccw.clicked.connect(lambda: self._rotate_selected(-1))
        shortcut_cw = QtGui.QShortcut(QtGui.QKeySequence("]"), self)
        shortcut_cw.activated.connect(lambda: self._rotate_selected(1))
        shortcut_ccw = QtGui.QShortcut(QtGui.QKeySequence("["), self)
        shortcut_ccw.activated.connect(lambda: self._rotate_selected(-1))

    def set_results(self, results: list[SplitResult]) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards.clear()

        for result in results:
            self._store.register(result)
            card = PhotoCard(result)
            card.rotate_requested.connect(self._rotate)
            card.inspect_requested.connect(self._inspect)
            row, column = divmod(len(self._cards), 4)
            self._grid.addWidget(card, row, column)
            self._cards.append(card)
        self.summary.setText(f"共 {len(self._cards)} 张拆分结果")
        self._apply_filter()

    def card_count(self) -> int:
        return len(self._cards)

    def rotate_card(self, index: int, step: int) -> None:
        self._rotate(self._cards[index].result, step)

    def inspect_card(self, index: int) -> None:
        self._inspect(self._cards[index].result)

    def _inspect(self, result: SplitResult) -> None:
        meta = read_metadata(result.path)
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("查看拆分结果")
        dialog.resize(760, 560)
        picture = QtWidgets.QLabel()
        picture.setPixmap(make_thumbnail(result.path, (720, 460)))
        picture.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        info = QtWidgets.QLabel(
            f"来源：{meta.get('source', '')}\n"
            f"扶正角：{meta.get('tilt_deg', '')}°    旋转：{meta.get('rotation', '')}°\n"
            f"方向状态：{meta.get('orientation', '')}    标记：{meta.get('flags', '') or '无'}"
        )
        info.setWordWrap(True)
        close_button = QtWidgets.QPushButton("关闭")
        close_button.clicked.connect(dialog.close)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(picture)
        layout.addWidget(info)
        layout.addWidget(close_button)
        self.last_dialog = dialog
        dialog.show()

    def _rotate(self, result: SplitResult, step: int) -> None:
        self._store.rotate(result, step)
        for card in self._cards:
            if card.result is result:
                card.refresh()
        self._apply_filter()

    def _rotate_selected(self, step: int) -> None:
        for card in self._cards:
            if card.checkbox.isChecked():
                self._rotate(card.result, step)

    def _apply_filter(self) -> None:
        mode = self.filter_combo.currentData()
        for card in self._cards:
            flags = set(card.result.flags)
            if mode == "all":
                visible = True
            elif mode == "review":
                visible = bool(flags) or card.result.orientation != "manual"
            elif mode == "incomplete":
                visible = bool(flags & {"incomplete", "uncertain"})
            elif mode == "unknown":
                visible = card.result.orientation == "unknown"
            else:
                visible = "auto" in flags
            card.setVisible(visible)
