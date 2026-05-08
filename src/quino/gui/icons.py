from __future__ import annotations

from pathlib import Path

from PySide6 import QtGui


ICONS_DIR = Path(__file__).parent / "icons"


def get_icon(name: str, color: str | None = None) -> QtGui.QIcon:
    svg_path = ICONS_DIR / f"{name}.svg"
    if not svg_path.exists():
        return QtGui.QIcon()
    pixmap = QtGui.QPixmap(str(svg_path))
    if pixmap.isNull():
        return QtGui.QIcon()
    return QtGui.QIcon(pixmap)