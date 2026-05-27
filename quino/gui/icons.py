from __future__ import annotations

import re
from pathlib import Path

from PySide6 import QtCore, QtGui, QtSvg

ICONS_DIR = Path(__file__).parent / "icons"
_ICON_SIZES = (16, 18, 20, 24, 32, 48, 64)
_HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?\b")
_SURFACE_COLORS = {
    "#ddd9cc",
    "#e3eaf3",
    "#e7ebee",
    "#e7eaef",
    "#e7f4ee",
    "#e8f0fb",
    "#e8edf2",
    "#e8f5f0",
    "#e8f3fa",
    "#eaf1fa",
    "#cde7dc",
    "#cfe4f3",
    "#d2e1f1",
    "#f6d3ac",
    "#f7d2ce",
    "#eef3f7",
    "#f0f0f0",
    "#f1f3f4",
    "#f4f6f7",
    "#f4f6f8",
    "#f7fbfe",
    "#f7fcfa",
    "#f8f9fa",
    "#f7f9fb",
    "#fdecea",
    "#fff1e2",
    "#fff7f6",
    "#fff9f1",
    "#faf8f2",
    "#fbfbfb",
    "#fdf0eb",
    "#fff",
    "#ffffff",
}


def _mix_colors(color: QtGui.QColor, target: QtGui.QColor, amount: float) -> QtGui.QColor:
    inverse = 1.0 - amount
    return QtGui.QColor(
        round(color.red() * inverse + target.red() * amount),
        round(color.green() * inverse + target.green() * amount),
        round(color.blue() * inverse + target.blue() * amount),
        color.alpha(),
    )


def _surface_tint(color: QtGui.QColor) -> str:
    return _mix_colors(color, QtGui.QColor("#ffffff"), 0.88).name()


def _recolor_svg(svg: str, color: str) -> bytes:
    primary = QtGui.QColor(color)
    if not primary.isValid():
        return svg.encode("utf-8")
    primary_hex = primary.name()
    tint_hex = _surface_tint(primary)

    def replace(match: re.Match[str]) -> str:
        existing = match.group(0).lower()
        if existing in _SURFACE_COLORS:
            return tint_hex
        return primary_hex

    return _HEX_COLOR_RE.sub(replace, svg).encode("utf-8")


def _render_svg_icon(svg_bytes: bytes, sizes: tuple[int, ...]) -> QtGui.QIcon:
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg_bytes))
    if not renderer.isValid():
        return QtGui.QIcon()
    icon = QtGui.QIcon()
    for logical_size in sizes:
        for scale in (1, 2):
            pixel_size = logical_size * scale
            image = QtGui.QImage(
                pixel_size,
                pixel_size,
                QtGui.QImage.Format.Format_ARGB32_Premultiplied,
            )
            image.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(image)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            renderer.render(painter)
            painter.end()
            pixmap = QtGui.QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(scale)
            icon.addPixmap(pixmap)
    return icon


def get_icon(name: str, color: str | None = None, size: int | None = None) -> QtGui.QIcon:
    svg_path = ICONS_DIR / f"{name}.svg"
    if not svg_path.exists():
        return QtGui.QIcon()
    if color is not None:
        svg = svg_path.read_text(encoding="utf-8")
        sizes = (size,) if size is not None else _ICON_SIZES
        return _render_svg_icon(_recolor_svg(svg, color), sizes)
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
