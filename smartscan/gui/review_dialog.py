"""Mouse-editable crop boxes with persistent review and one batch export."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from smartscan.detection import detect_quads, estimate_background
from smartscan.pipeline import _read_source
from smartscan.review import load_review, save_review, source_identity, validate_quad
from smartscan.rotation import state_after
from .crop_preview import CropPreviewCard, crop_pixmap, preview_array


class CropBox:
    """Plain native graphics items; all editing is owned by the scene."""

    def __init__(self, canvas, points):
        self.points = points
        self.rotation = 0
        self.polygon = QtWidgets.QGraphicsPolygonItem()
        self.polygon.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        pen = QtGui.QPen(QtGui.QColor("#00a9e0"), 2)
        pen.setCosmetic(True)
        self.polygon.setPen(pen)
        self.polygon.setBrush(QtGui.QColor(0, 150, 220, 18))
        self.polygon.setZValue(1)
        canvas.addItem(self.polygon)
        self.handles = []
        for point in points:
            handle = QtWidgets.QGraphicsEllipseItem(-6, -6, 12, 12, self.polygon)
            handle.setBrush(QtGui.QColor("white"))
            handle.setPen(QtGui.QPen(QtGui.QColor("#087bb5"), 2))
            handle.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            handle.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
            handle.setZValue(2)
            self.handles.append(handle)
        self.update_polygon()

    def update_polygon(self):
        self.polygon.setPolygon(QtGui.QPolygonF([QtCore.QPointF(*p) for p in self.points]))
        for handle, point in zip(self.handles, self.points):
            handle.setPos(*point)

    def isSelected(self):
        return self.polygon.isSelected()

    def setSelected(self, value):
        self.polygon.setSelected(value)


class CropScene(QtWidgets.QGraphicsScene):
    edited = QtCore.Signal()
    draw_mode_changed = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_size = (0, 0)
        self.quad_items = []
        self.draw_mode = False
        self._drag = None
        self._start = None
        self._rubber = None
        self._history = []
        self._drag_before = None
        self.setBackgroundBrush(QtGui.QColor("#303840"))

    def set_image(self, image: QtGui.QImage, source_size=None):
        self.clear()
        self.quad_items = []
        self._history = []
        self._drag_before = None
        self._start = self._rubber = self._drag = None
        self.image_size = source_size or (image.width(), image.height())
        item = self.addPixmap(QtGui.QPixmap.fromImage(image))
        width, height = self.image_size
        item.setTransform(QtGui.QTransform.fromScale(width / image.width(), height / image.height()))
        item.setZValue(-1)
        self.setSceneRect(0, 0, width, height)

    def set_quads(self, boxes, reset_history=True, rotations=None):
        if reset_history:
            self._history = []
        for item in self.quad_items:
            self.removeItem(item.polygon)
        self.quad_items = []
        for index, points in enumerate(boxes):
            item = self.add_quad(points, notify=False)
            item.rotation = rotations[index] if rotations is not None else 0

    def add_quad(self, points, notify=True):
        points = validate_quad(points, self.image_size)
        if notify:
            self._history.append(self._snapshot())
        item = CropBox(self, points)
        self.quad_items.append(item)
        self.clearSelection()
        item.setSelected(True)
        if notify:
            self.edited.emit()
        return item

    def points(self):
        return [list(item.points) for item in self.quad_items]

    def rotations(self):
        return [item.rotation for item in self.quad_items]

    def rotate_quad(self, box, step):
        self.cancel_interaction()
        self._history.append(self._snapshot())
        box.rotation = state_after(box.rotation, step)
        self.edited.emit()

    def _snapshot(self):
        return (self.points(), [i for i, box in enumerate(self.quad_items) if box.isSelected()],
                self.rotations())

    def _finish_drag(self):
        changed = self._drag_before is not None and self._drag_before[0] != self.points()
        if changed:
            self._history.append(self._drag_before)
        self._drag_before = self._drag = None
        if changed:
            self.edited.emit()

    def undo(self):
        self.cancel_interaction()
        if not self._history:
            return
        points, selected, rotations = self._history.pop()
        self.set_quads(points, reset_history=False, rotations=rotations)
        self.clearSelection()
        for index in selected:
            self.quad_items[index].setSelected(True)
        self.edited.emit()

    def set_draw_mode(self, enabled):
        changed = self.draw_mode != enabled
        self.draw_mode = enabled
        if not enabled:
            if self._rubber is not None:
                self.removeItem(self._rubber)
            self._start = self._rubber = None
        if changed:
            self.draw_mode_changed.emit(enabled)

    def cancel_interaction(self):
        self.set_draw_mode(False)
        self._finish_drag()
        grabber = self.mouseGrabberItem()
        if grabber is not None:
            grabber.ungrabMouse()

    def remove_selected(self):
        self._finish_drag()
        selected = [item for item in self.quad_items if item.isSelected()]
        if selected:
            self._history.append(self._snapshot())
        for item in selected:
            self.removeItem(item.polygon)
            self.quad_items.remove(item)
        if selected:
            self.edited.emit()

    def move_corner(self, box, index, point):
        points = list(box.points)
        points[index] = tuple(point)
        try:
            validate_quad(points, self.image_size)
        except ValueError:
            return False
        if points == box.points:
            return False
        if self._drag is None:
            self._history.append(self._snapshot())
        box.points = points
        box.update_polygon()
        self.edited.emit()
        return True

    def _hit_corner(self, point):
        scale = self.views()[0].transform().m11() if self.views() else 1
        hits = []
        for box in reversed(self.quad_items):
            for index, corner in enumerate(box.points):
                distance = QtCore.QLineF(point, QtCore.QPointF(*corner)).length() * scale
                if distance <= 9:
                    hits.append((not box.isSelected(), distance, box, index))
        if not hits:
            return None
        _, _, box, index = min(hits, key=lambda hit: (hit[0], hit[1]))
        return box, index

    def _inside(self, point):
        return QtCore.QPointF(max(0, min(self.image_size[0] - 1, point.x())),
                             max(0, min(self.image_size[1] - 1, point.y())))

    def mousePressEvent(self, event):
        if self.draw_mode and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._start = self._inside(event.scenePos())
            pen = QtGui.QPen(QtGui.QColor("#ffc857"), 2, QtCore.Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._rubber = self.addRect(QtCore.QRectF(self._start, self._start), pen)
            self._rubber.setZValue(3)
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag = self._hit_corner(event.scenePos())
            if self._drag is not None:
                self._drag_before = self._snapshot()
                self.clearSelection()
                self._drag[0].setSelected(True)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._rubber is not None:
            self._rubber.setRect(QtCore.QRectF(self._start, self._inside(event.scenePos())).normalized())
            event.accept()
            return
        if self._drag is not None:
            self.move_corner(*self._drag, (event.scenePos().x(), event.scenePos().y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._rubber is not None:
            rect = QtCore.QRectF(self._start, self._inside(event.scenePos())).normalized()
            self.removeItem(self._rubber)
            self._start = self._rubber = None
            if rect.width() >= 4 and rect.height() >= 4:
                self.add_quad([(rect.left(), rect.top()), (rect.right(), rect.top()),
                               (rect.right(), rect.bottom()), (rect.left(), rect.bottom())])
            self.set_draw_mode(False)
            event.accept()
            return
        if self._drag is not None:
            self.move_corner(*self._drag, (event.scenePos().x(), event.scenePos().y()))
            self._finish_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CropView(QtWidgets.QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumSize(480, 250)
        self._pan_start = None
        self._pan_button = None
        self._space_down = False

    def refresh_cursor(self):
        if self._pan_start is not None:
            cursor = QtCore.Qt.CursorShape.ClosedHandCursor
        elif self._space_down:
            cursor = QtCore.Qt.CursorShape.OpenHandCursor
        elif self.scene() is not None and self.scene().draw_mode:
            cursor = QtCore.Qt.CursorShape.CrossCursor
        else:
            cursor = QtCore.Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)
        self.viewport().setCursor(cursor)

    def set_space_down(self, pressed):
        if pressed == self._space_down:
            return
        self._space_down = pressed
        self.scene().cancel_interaction()
        if not pressed and self._pan_button == QtCore.Qt.MouseButton.LeftButton:
            self._pan_start = self._pan_button = None
        self.refresh_cursor()

    def fit_image(self):
        self.fitInView(self.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        scale = self.transform().m11() * factor
        if 0.01 <= scale <= 20:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        if (event.button() == QtCore.Qt.MouseButton.MiddleButton
                or event.button() == QtCore.Qt.MouseButton.LeftButton
                and self._space_down):
            self._pan_start = event.position()
            self._pan_button = event.button()
            self.refresh_cursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.position() - self._pan_start
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            self._pan_start = event.position()
            event.accept()
            return
        if self._space_down:
            self.refresh_cursor()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan_start is not None and event.button() == self._pan_button:
            self._pan_start = self._pan_button = None
            self.refresh_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self.set_space_down(True)
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.scene().cancel_interaction()
            self.refresh_cursor()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self.set_space_down(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        if not self.window().isActiveWindow():
            self.set_space_down(False)
            self._pan_start = self._pan_button = None
            self.refresh_cursor()
        super().focusOutEvent(event)


class DetectionWorker(QtCore.QThread):
    detected = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source

    def run(self):
        try:
            image, _, _ = _read_source(self.source)
            self.detected.emit([q.points for q in detect_quads(image, estimate_background(image))])
        except Exception as exc:
            self.failed.emit(str(exc))


class ReviewDialog(QtWidgets.QDialog):
    export_requested = QtCore.Signal(list)

    def __init__(self, sources, parent=None, *, fill_mode="background"):
        super().__init__(parent)
        self.sources = [Path(path) for path in sources]
        self.index = 0
        self.confirmed = set()
        self.busy = self.dirty = self.user_edited = self._close_requested = False
        self.current_valid = False
        self.worker = None
        self._source_digest = None
        self._disposed = False
        self._discard_edits = False
        self.fill_mode = fill_mode
        self._preview_array = None
        self.preview_cards = []
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(150)
        self.preview_timer.timeout.connect(self._refresh_crop_previews)
        self.setWindowTitle("预览与校正裁切框 — 保存后一次批量裁切")
        self.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowMaximizeButtonHint, True)
        screen = parent.screen() if parent is not None else QtGui.QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(min(1150, available.width() - 40), min(850, available.height() - 80))
        self.heading = QtWidgets.QLabel()
        self.heading.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                   QtWidgets.QSizePolicy.Policy.Preferred)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.scene = CropScene()
        self.view = CropView(self.scene)
        self.thumbnails = QtWidgets.QListWidget()
        self.thumbnails.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.thumbnails.setFlow(QtWidgets.QListView.Flow.TopToBottom)
        self.thumbnails.setWrapping(False)
        self.thumbnails.setMovement(QtWidgets.QListView.Movement.Static)
        self.thumbnails.setIconSize(QtCore.QSize(128, 96))
        self.thumbnails.setGridSize(QtCore.QSize(144, 126))
        self.thumbnails.setFixedWidth(166)
        self.thumbnails.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)
        self.thumbnails.setWordWrap(False)
        self.thumbnails.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumbnails.setStyleSheet("""
            QListWidget::item { border: 2px solid transparent; border-radius: 4px; }
            QListWidget::item:selected { border: 2px solid #087bb5;
                background: #e2e6ea; color: #18212a; }
        """)
        for index, source in enumerate(self.sources):
            item = QtWidgets.QListWidgetItem(f"{index + 1} · {source.name}")
            item.setSizeHint(self.thumbnails.gridSize())
            item.setToolTip(str(source))
            self.thumbnails.addItem(item)
        self._thumbnail_next = 0
        self.thumbnail_timer = QtCore.QTimer(self)
        self.thumbnail_timer.setInterval(20)
        self.thumbnail_timer.timeout.connect(self._load_thumbnail)
        self.crop_previews = QtWidgets.QScrollArea()
        self.crop_previews.setWidgetResizable(True)
        self.crop_previews.setFixedWidth(198)
        self.crop_previews.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        preview_content = QtWidgets.QWidget()
        self.preview_layout = QtWidgets.QVBoxLayout(preview_content)
        self.preview_layout.setContentsMargins(2, 2, 2, 2)
        self.preview_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.crop_previews.setWidget(preview_content)
        self.add_button = QtWidgets.QPushButton("绘制新框")
        self.add_button.setCheckable(True)
        self.delete_button = QtWidgets.QPushButton("删除框")
        self.delete_button.setToolTip("删除选中的裁切框（Delete）")
        self.undo_button = QtWidgets.QPushButton("撤销")
        self.undo_button.setToolTip("撤销上一次裁切框改动（Ctrl+Z）")
        self.add_button.setToolTip("拖动绘制一个新框；Esc 取消绘制")
        self.view.setToolTip("滚轮缩放；按住空格拖动平移，松开恢复编辑")
        fit = QtWidgets.QPushButton("适应窗口")
        self.previous_button = QtWidgets.QPushButton("<", self.view)
        self.next_button = QtWidgets.QPushButton(">", self.view)
        for button, name in ((self.previous_button, "上一张扫描图"),
                             (self.next_button, "下一张扫描图")):
            button.setAccessibleName(name)
            button.setFixedSize(40, 40)
            button.setStyleSheet("""
                QPushButton { border: 2px solid transparent; border-radius: 20px;
                    background: rgba(25, 32, 40, 130); color: white; font-size: 24px; }
                QPushButton:hover { border-color: rgba(255, 255, 255, 230);
                    background: rgba(25, 32, 40, 195); }
                QPushButton:disabled { color: rgba(255, 255, 255, 65);
                    background: rgba(25, 32, 40, 65); }
            """)
        self.save_button = QtWidgets.QPushButton("保存本张（Ctrl+S）")
        self.export_button = QtWidgets.QPushButton()
        self.return_button = QtWidgets.QPushButton("返回选择扫描图")
        self.return_button.setToolTip("返回主界面添加更多扫描图；实际编辑会自动保存")
        for button in (self.add_button, self.delete_button, self.undo_button, fit, self.previous_button,
                       self.next_button, self.save_button, self.export_button, self.return_button):
            button.setAutoDefault(False)
        tools = QtWidgets.QHBoxLayout()
        tools.addWidget(self.add_button)
        tools.addWidget(self.delete_button)
        tools.addWidget(self.undo_button)
        tools.addWidget(fit)
        tools.addStretch()
        bottom = QtWidgets.QHBoxLayout()
        for button in (self.save_button, self.export_button, self.return_button):
            bottom.addWidget(button)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(tools)
        layout.addWidget(self.heading)
        images = QtWidgets.QHBoxLayout()
        images.addWidget(self.thumbnails)
        images.addWidget(self.view, 1)
        images.addWidget(self.crop_previews)
        layout.addLayout(images, 1)
        layout.addWidget(self.status)
        layout.addLayout(bottom)
        self.scene.edited.connect(self._edited)
        self.scene.selectionChanged.connect(self._controls)
        self.scene.draw_mode_changed.connect(self.add_button.setChecked)
        self.add_button.toggled.connect(self._drawing_mode)
        self.delete_button.clicked.connect(self.scene.remove_selected)
        self.undo_button.clicked.connect(self.scene.undo)
        fit.clicked.connect(self.view.fit_image)
        self.previous_button.clicked.connect(lambda: self._navigate(-1))
        self.next_button.clicked.connect(self.next_source)
        self.thumbnails.currentRowChanged.connect(self._select_source)
        self.thumbnails.itemClicked.connect(lambda item: self._select_source(self.thumbnails.row(item)))
        self.save_button.clicked.connect(self.save_current)
        self.export_button.clicked.connect(self.export_saved)
        self.return_button.clicked.connect(self.reject)
        shortcut_delete = QtGui.QShortcut(QtGui.QKeySequence("Delete"), self)
        shortcut_delete.activated.connect(self.scene.remove_selected)
        shortcut_save = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+S"), self)
        shortcut_save.activated.connect(self.save_current)
        self.undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.scene.undo)
        QtWidgets.QApplication.instance().installEventFilter(self)
        for source in self.sources:
            try:
                if load_review(source) is not None:
                    self.confirmed.add(source)
            except (OSError, ValueError):
                pass
        self._load_current()
        self.thumbnail_timer.start()

    def _load_thumbnail(self):
        if self._thumbnail_next >= len(self.sources):
            self.thumbnail_timer.stop()
            return
        index = self._thumbnail_next
        self._thumbnail_next += 1
        reader = QtGui.QImageReader(str(self.sources[index]))
        reader.setScaledSize(reader.size().scaled(self.thumbnails.iconSize(),
                             QtCore.Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        icon = (QtGui.QIcon(QtGui.QPixmap.fromImage(image)) if not image.isNull()
                else self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning))
        self.thumbnails.item(index).setIcon(icon)

    def _refresh_crop_previews(self):
        self.preview_timer.stop()
        if self.scene._drag is not None:
            self.preview_timer.start()
            return
        while self.preview_layout.count():
            widget = self.preview_layout.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self.preview_cards = []
        if self._disposed or not self.current_valid or self._preview_array is None:
            return
        for index, box in enumerate(self.scene.quad_items):
            pixmap = crop_pixmap(self._preview_array, self.scene.image_size, box.points,
                                 box.rotation, self.fill_mode, self._preview_background)
            card = CropPreviewCard(index, pixmap)
            card.rotate_requested.connect(lambda step, box=box: self._rotate_crop(box, step))
            self.preview_layout.addWidget(card)
            self.preview_cards.append(card)

    def _rotate_crop(self, box, step):
        if not self.busy and self.current_valid and box in self.scene.quad_items:
            self.scene.rotate_quad(box, step)

    def _position_navigation(self):
        area = self.view.viewport().geometry()
        y = area.top() + (area.height() - self.previous_button.height()) // 2
        self.previous_button.move(area.left() + 12, y)
        self.next_button.move(area.left() + area.width() - self.next_button.width() - 12, y)
        self.previous_button.raise_()
        self.next_button.raise_()

    def _controls(self):
        enabled = not self.busy and self.current_valid
        self.add_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled and bool(self.scene.selectedItems()))
        self.undo_button.setEnabled(enabled and bool(self.scene._history))
        self.undo_shortcut.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.previous_button.setEnabled(not self.busy and self.index > 0)
        self.next_button.setEnabled(not self.busy and self.index + 1 < len(self.sources))
        self.previous_button.setToolTip("已经是第一张扫描图" if self.index == 0
                                        else "保存当前编辑，并查看上一张扫描图")
        if self.busy:
            self.next_button.setToolTip("正在识别当前扫描图，完成后可继续")
            self.heading.setToolTip("正在识别当前扫描图内的照片框，请稍候…")
        elif len(self.sources) == 1:
            self.next_button.setToolTip("本次仅添加了一张扫描图，没有下一张")
            self.heading.setToolTip(
                f"当前扫描图内有 {len(self.scene.points())} 个照片裁切框。"
                "本次仅添加了 1 张扫描图，没有下一张；请点“返回选择扫描图”添加更多图片。")
        elif self.index + 1 == len(self.sources):
            self.next_button.setToolTip("已经是最后一张扫描图")
            self.heading.setToolTip(
                f"当前扫描图内有 {len(self.scene.points())} 个照片裁切框。"
                "已到最后一张扫描图；确认后可点下方“保存并批量裁切”。")
        else:
            self.next_button.setToolTip("保存当前扫描图的所有裁切框，并打开下一张扫描图")
            self.heading.setToolTip(
                f"当前扫描图内有 {len(self.scene.points())} 个照片裁切框。"
                "点击右侧 > 或左侧缩略图切换扫描图，本张框会自动保存。")
        pending = set(self.confirmed)
        if self.current_valid:
            pending.add(self.sources[self.index])
        self.export_button.setText(f"保存并批量裁切（{len(pending)}/{len(self.sources)} 张扫描图）")
        self.export_button.setEnabled(not self.busy and bool(pending))
        self.view.setInteractive(enabled)
        self.thumbnails.setEnabled(not self.busy)

    def _load_current(self):
        self.preview_timer.stop()
        self._preview_array = None
        self.current_valid = False
        self.dirty = self.user_edited = False
        self.add_button.setChecked(False)
        self.view.set_space_down(False)
        self.scene.cancel_interaction()
        self.scene._history = []
        self.scene.clear()
        self.scene.quad_items = []
        self.scene.image_size = (0, 0)
        self._source_digest = None
        source = self.sources[self.index]
        with QtCore.QSignalBlocker(self.thumbnails):
            self.thumbnails.setCurrentRow(self.index)
        self.thumbnails.scrollToItem(self.thumbnails.item(self.index))
        self.heading.setText(f"扫描图 {self.index + 1} / {len(self.sources)}：{source.name}")
        try:
            self._source_digest, source_size = source_identity(source)
            reader = QtGui.QImageReader(str(source))
            size = reader.size()
            if not size.isValid():
                raise ValueError(reader.errorString())
            if (size.width(), size.height()) != source_size:
                raise ValueError("原图尺寸已变化，请重新打开此扫描件")
            reader.setScaledSize(size.scaled(1600, 1600, QtCore.Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            if image.isNull():
                raise ValueError(reader.errorString())
            self.scene.set_image(image, (size.width(), size.height()))
            self._preview_array = preview_array(image)
            self._preview_background = estimate_background(self._preview_array)
            self.view.fit_image()
            self.current_valid = True
            reviewed = load_review(source)
            if reviewed is not None:
                if reviewed.digest != self._source_digest:
                    raise ValueError("原图内容已变化，请重新打开此扫描件")
                self.scene.set_quads(reviewed.points, rotations=reviewed.rotations)
                self.status.setText(f"已恢复保存的 {len(reviewed.points)} 个裁切框。")
            else:
                self.busy = True
                self.status.setText("正在后台识别初始裁切框…")
                self.worker = DetectionWorker(source, self)
                self.worker.detected.connect(self._detected)
                self.worker.failed.connect(self._failed)
                self.worker.finished.connect(self._detection_finished)
                self.worker.start()
        except (OSError, ValueError) as exc:
            self.current_valid = False
            self.status.setText(f"无法读取扫描件：{exc}")
        self._controls()
        self._refresh_crop_previews()

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self.view.fit_image)
        self._position_navigation()

    def _drawing_mode(self, checked):
        self.scene.set_draw_mode(checked)
        self.view.refresh_cursor()
        if checked:
            self.view.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched, event):
        if self._disposed or not isinstance(watched, QtWidgets.QWidget):
            return False
        if watched is not self and not self.isAncestorOf(watched):
            return False
        kind = event.type()
        if watched is self.view.viewport() and kind == QtCore.QEvent.Type.Resize:
            self._position_navigation()
        if kind == QtCore.QEvent.Type.WindowDeactivate:
            self.view.set_space_down(False)
        if kind not in (QtCore.QEvent.Type.ShortcutOverride, QtCore.QEvent.Type.KeyPress,
                         QtCore.QEvent.Type.KeyRelease):
            return False
        if event.key() not in (QtCore.Qt.Key.Key_Space, QtCore.Qt.Key.Key_Escape):
            return False
        event.accept()
        if kind == QtCore.QEvent.Type.ShortcutOverride or event.isAutoRepeat():
            return True
        if event.key() == QtCore.Qt.Key.Key_Space:
            self.view.set_space_down(kind == QtCore.QEvent.Type.KeyPress)
        elif kind == QtCore.QEvent.Type.KeyPress:
            self.scene.cancel_interaction()
            self.view.refresh_cursor()
        return True

    def _detected(self, boxes):
        width, height = self.scene.image_size
        valid = []
        for box in boxes:
            clipped = [(max(0, min(width - 1, x)), max(0, min(height - 1, y))) for x, y in box]
            try:
                valid.append(validate_quad(clipped, self.scene.image_size))
            except ValueError:
                continue
        self.scene.set_quads(valid)
        self.dirty = True
        self.preview_timer.start()
        self.status.setText(f"自动候选 {len(valid)} 个框，尚未确认。请检查漏框、误切和四边。")

    def _failed(self, message):
        self.status.setText(f"自动识别失败，可手工绘制裁切框：{message}")

    def _detection_finished(self):
        self.busy = False
        self.worker.deleteLater()
        self.worker = None
        self._controls()
        if self._close_requested:
            self.reject()

    def _edited(self):
        self.dirty = self.user_edited = True
        self.status.setText(f"本张 {len(self.scene.points())} 个框，有未保存的编辑。")
        self._controls()
        self.preview_timer.start()

    def save_current(self):
        if self.busy:
            return False
        if not self.current_valid:
            return True
        try:
            save_review(self.sources[self.index], self.scene.points(),
                        rotations=self.scene.rotations(),
                        expected_digest=self._source_digest)
        except (OSError, ValueError) as exc:
            self.status.setText(f"保存失败，编辑仍保留在窗口中：{exc}")
            return False
        self.confirmed.add(self.sources[self.index])
        self.dirty = self.user_edited = False
        self.status.setText(f"已保存 {len(self.scene.points())} 个框，可继续下一张或批量裁切。")
        self._controls()
        return True

    def _select_source(self, target):
        if target == self.index or not 0 <= target < len(self.sources):
            return
        if self.busy:
            with QtCore.QSignalBlocker(self.thumbnails):
                self.thumbnails.setCurrentRow(self.index)
            return
        self.scene.cancel_interaction()
        self.view.refresh_cursor()
        if self.save_current():
            self.index = target
            self._load_current()
        else:
            with QtCore.QSignalBlocker(self.thumbnails):
                self.thumbnails.setCurrentRow(self.index)

    def _navigate(self, step):
        self._select_source(self.index + step)

    def next_source(self):
        self._navigate(1)

    def export_saved(self):
        if self.busy or not self.save_current():
            return
        sources = [source for source in self.sources if source in self.confirmed]
        stale = []
        for source in sources:
            try:
                if load_review(source) is None:
                    stale.append(source)
            except (OSError, ValueError):
                stale.append(source)
        if stale:
            self.confirmed.difference_update(stale)
            self.status.setText("部分原图已变化或无法读取，请重新校正：" + "、".join(p.name for p in stale))
            self._controls()
            return
        if sources:
            self.export_requested.emit(sources)
            self.accept()

    def discard_and_close(self):
        self._discard_edits = True
        self.reject()

    def reject(self):
        if self.busy:
            self._close_requested = True
            self.status.setText("正在结束本张识别，随后关闭窗口…")
            return
        if not self._discard_edits and self.user_edited and not self.save_current():
            answer = QtWidgets.QMessageBox.warning(
                self, "本张编辑尚未保存", "未能保存本张裁切框。是否放弃未保存的编辑并关闭？",
                QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel)
            if answer != QtWidgets.QMessageBox.StandardButton.Discard:
                return
        super().reject()

    def done(self, result):
        # Release graphics items while Qt and the dialog controls are
        # still alive; their callbacks must not run during interpreter teardown.
        if not self._disposed:
            self.view.set_space_down(False)
            self._disposed = True
            self.thumbnail_timer.stop()
            self.preview_timer.stop()
            QtWidgets.QApplication.instance().removeEventFilter(self)
            self.scene.selectionChanged.disconnect(self._controls)
            self.scene.edited.disconnect(self._edited)
            self.view.setScene(None)
            self.scene.clear()
            self.scene.quad_items = []
        super().done(result)
