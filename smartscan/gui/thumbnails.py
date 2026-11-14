"""Thumbnail rendering for the result grid."""

from __future__ import annotations

import io

from PIL import Image
from PySide6 import QtCore, QtGui

THUMBNAIL_SIZE = (160, 120)


def make_thumbnail(path, size: tuple[int, int] = THUMBNAIL_SIZE) -> QtGui.QPixmap:
    buffer = io.BytesIO()
    try:
        with Image.open(path) as image:
            image.thumbnail(size, Image.Resampling.LANCZOS)
            image.convert("RGB").save(buffer, format="PNG")
    except Exception:
        return QtGui.QPixmap()
    pixmap = QtGui.QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    return pixmap.scaled(
        size[0],
        size[1],
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
