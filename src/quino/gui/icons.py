from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui


ICONS_DIR = Path(__file__).parent / "icons"


def get_icon(name: str, color: str | None = None, size: int | None = None) -> QtGui.QIcon:
    svg_path = ICONS_DIR / f"{name}.svg"
    if not svg_path.exists():
        return QtGui.QIcon()
    if size is not None:
        renderer = QtGui.QImageReader(str(svg_path))
        renderer.setScaledSize(QtCore.QSize(size, size))
        image = renderer.read()
        if image.isNull():
            return QtGui.QIcon()
        return QtGui.QIcon(QtGui.QPixmap.fromImage(image))
    pixmap = QtGui.QPixmap(str(svg_path))
    if pixmap.isNull():
        return QtGui.QIcon()
    return QtGui.QIcon(pixmap)
