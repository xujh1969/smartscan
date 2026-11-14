"""Small draft crop previews using the same crop and rotation as export."""

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from smartscan.geometry import tilt_angle
from smartscan.models import PhotoQuad
from smartscan.rotation import apply_state
from smartscan.split import deskew_and_crop


def rotation_icon(clockwise):
    pixmap = QtGui.QPixmap(24, 24)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    if not clockwise:
        painter.translate(24, 0)
        painter.scale(-1, 1)
    painter.setPen(QtGui.QPen(QtGui.QColor("white"), 2.2))
    painter.drawArc(QtCore.QRectF(4, 4, 16, 16), 90 * 16, -270 * 16)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QColor("white"))
    painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(4, 9),
                                       QtCore.QPointF(0, 15), QtCore.QPointF(8, 15)]))
    painter.end()
    return QtGui.QIcon(pixmap)


def preview_array(image):
    rgb = image.convertToFormat(QtGui.QImage.Format.Format_RGB888)
    rows = np.frombuffer(rgb.bits(), np.uint8).reshape(rgb.height(), rgb.bytesPerLine())
    return rows[:, :rgb.width() * 3].reshape(rgb.height(), rgb.width(), 3).copy()


def crop_pixmap(image, source_size, points, rotation, fill_mode, background):
    scale = min(image.shape[1] / source_size[0], image.shape[0] / source_size[1])
    quad = PhotoQuad([(x * scale, y * scale) for x, y in points], tilt_deg=tilt_angle(points))
    crop = deskew_and_crop(image, quad, background, fill_mode=fill_mode)
    crop = apply_state(crop, rotation)
    height, width, channels = crop.shape
    fmt = (QtGui.QImage.Format.Format_RGBA8888 if channels == 4
           else QtGui.QImage.Format.Format_RGB888)
    picture = QtGui.QImage(crop.data, width, height, crop.strides[0], fmt).copy()
    return QtGui.QPixmap.fromImage(picture).scaled(
        160, 130, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation)


class CropPreviewCard(QtWidgets.QFrame):
    rotate_requested = QtCore.Signal(int)

    def __init__(self, index, pixmap, parent=None):
        super().__init__(parent)
        self.setFixedWidth(174)
        self.image_label = QtWidgets.QLabel()
        self.image_label.setFixedSize(160, 130)
        self.image_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background: #303840;")
        self.image_label.setPixmap(pixmap)
        self.ccw_button = QtWidgets.QToolButton(self.image_label)
        self.cw_button = QtWidgets.QToolButton(self.image_label)
        for button, clockwise, hint, x in (
                (self.ccw_button, False, "逆时针旋转 90°", 5),
                (self.cw_button, True, "顺时针旋转 90°", 127)):
            button.setIcon(rotation_icon(clockwise))
            button.setIconSize(QtCore.QSize(22, 22))
            button.setToolTip(hint)
            button.setAccessibleName(hint)
            button.setFixedSize(28, 28)
            button.move(x, 5)
            button.setStyleSheet("QToolButton { background: rgba(20, 25, 30, 180);"
                                 "color: white; border: 1px solid transparent; border-radius: 14px; }"
                                 "QToolButton:hover { border-color: white; }")
        self.ccw_button.clicked.connect(lambda: self.rotate_requested.emit(-1))
        self.cw_button.clicked.connect(lambda: self.rotate_requested.emit(1))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(7, 4, 7, 4)
        layout.setSpacing(3)
        layout.addWidget(self.image_label)
        layout.addWidget(QtWidgets.QLabel(f"照片 {index + 1}"))
