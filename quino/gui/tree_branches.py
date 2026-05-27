"""Branch-line and disclosure glyphs for QTreeView, Inventor-style.

Generates 16x16 pixmaps at runtime, writes them to a temp dir on first
use, and returns a CSS snippet referencing them. This way the icons are
crisp, scalable and don't need to be checked into the repo.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6 import QtCore, QtGui

_CACHE_DIR: Path | None = None
_CACHE_TOKEN = "v6-triangle-overlay-halo"
_LINE_COLOR = QtGui.QColor("#b7c5d3")
_TRIANGLE_COLOR = QtGui.QColor("#66727e")
_TRIANGLE_EDGE_COLOR = QtGui.QColor("#3f4f5e")
_TRIANGLE_HALO_COLOR = QtGui.QColor("#fbfdff")
_SIZE = 16


def _ensure_cache() -> Path:
    global _CACHE_DIR
    if _CACHE_DIR is None:
        _CACHE_DIR = Path(tempfile.mkdtemp(prefix=f"quino_branches_{_CACHE_TOKEN}_"))
        _render_all(_CACHE_DIR)
    return _CACHE_DIR


def _render_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cx = _SIZE // 2
    cy = _SIZE // 2

    # Vertical line spanning the whole cell (for parents that still have
    # siblings below).
    _draw(out / "vline.png", lambda p: _vline(p, cx, 0, _SIZE))

    # T-connector: a child that has a sibling below (vline + horizontal stub).
    def _more(p):
        _vline(p, cx, 0, _SIZE)
        _hline(p, cx, _SIZE, cy)

    _draw(out / "more.png", _more)

    # L-connector: the last child in its branch.
    def _end(p):
        _vline(p, cx, 0, cy)
        _hline(p, cx, _SIZE, cy)

    _draw(out / "end.png", _end)

    _draw(out / "closed_triangle.png", lambda p: _triangle(p, cx, cy, closed=True))
    _draw(out / "open_triangle.png", lambda p: _triangle(p, cx, cy, closed=False))


def _draw(path: Path, fn) -> None:
    pix = QtGui.QPixmap(_SIZE, _SIZE)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pix)
    # Triangles benefit from AA; the line helpers turn it off locally for
    # crisp 1-px guides (no half-pixel smearing).
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    fn(painter)
    painter.end()
    pix.save(str(path), "PNG")


def _vline(painter: QtGui.QPainter, x: int, y0: int, y1: int) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
    pen = QtGui.QPen(_LINE_COLOR)
    pen.setWidth(1)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.drawLine(x, y0, x, y1)
    painter.restore()


def _hline(painter: QtGui.QPainter, x0: int, x1: int, y: int) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
    pen = QtGui.QPen(_LINE_COLOR)
    pen.setWidth(1)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.drawLine(x0, y, x1, y)
    painter.restore()


def _triangle(painter: QtGui.QPainter, cx: int, cy: int, *, closed: bool) -> None:
    """Filled triangle pointing right (closed) or down (open).

    The light underlay deliberately covers the hierarchy guide behind the
    disclosure glyph, so the triangle always reads as being above the lines.
    """
    halo = _triangle_polygon(cx, cy, closed=closed, size=6.2)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QBrush(_TRIANGLE_HALO_COLOR))
    painter.drawPolygon(halo)

    triangle = _triangle_polygon(cx, cy, closed=closed, size=5.1)
    pen = QtGui.QPen(_TRIANGLE_EDGE_COLOR)
    pen.setWidthF(0.8)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(QtGui.QBrush(_TRIANGLE_COLOR))
    painter.drawPolygon(triangle)


def _triangle_polygon(cx: int, cy: int, *, closed: bool, size: float) -> QtGui.QPolygonF:
    if closed:
        return QtGui.QPolygonF([
            QtCore.QPointF(cx - 1.4, cy - size),
            QtCore.QPointF(cx + size - 0.8, cy),
            QtCore.QPointF(cx - 1.4, cy + size),
        ])
    return QtGui.QPolygonF([
        QtCore.QPointF(cx - size, cy - 1.2),
        QtCore.QPointF(cx + size, cy - 1.2),
        QtCore.QPointF(cx, cy + size - 0.6),
    ])


def tree_branch_stylesheet() -> str:
    """Return a CSS snippet that draws branch lines + Inventor-style
    disclosure triangles in any QTreeView."""
    cache = _ensure_cache()
    def url(name: str) -> str:
        # Qt's stylesheet parser wants forward slashes even on Windows.
        return (cache / f"{name}.png").as_posix()
    return (
        "QTreeView::branch:has-siblings:!adjoins-item {"
        f" border-image: url({url('vline')}) 0;"
        " }"
        "QTreeView::branch:has-siblings:adjoins-item {"
        f" border-image: url({url('more')}) 0;"
        " }"
        "QTreeView::branch:!has-children:!has-siblings:adjoins-item {"
        f" border-image: url({url('end')}) 0;"
        " }"
        "QTreeView::branch:closed:has-children:has-siblings {"
        f" border-image: url({url('more')}) 0;"
        f" image: url({url('closed_triangle')});"
        " }"
        "QTreeView::branch:open:has-children:has-siblings {"
        f" border-image: url({url('more')}) 0;"
        f" image: url({url('open_triangle')});"
        " }"
        "QTreeView::branch:closed:has-children:!has-siblings {"
        f" border-image: url({url('end')}) 0;"
        f" image: url({url('closed_triangle')});"
        " }"
        "QTreeView::branch:open:has-children:!has-siblings {"
        f" border-image: url({url('end')}) 0;"
        f" image: url({url('open_triangle')});"
        " }"
    )
