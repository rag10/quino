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
_CACHE_TOKEN = "v2-black-1px"  # bump to invalidate cached PNGs after restyle
_LINE_COLOR = QtGui.QColor("#000000")
_TRIANGLE_COLOR = QtGui.QColor("#333")
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

    # Closed disclosure (right-pointing triangle), with the same T-connector.
    def _closed(p):
        _vline(p, cx, 0, _SIZE)
        _triangle(p, cx, cy, closed=True)

    _draw(out / "closed.png", _closed)

    # Open disclosure (down-pointing triangle).
    def _open(p):
        _vline(p, cx, 0, _SIZE)
        _triangle(p, cx, cy, closed=False)

    _draw(out / "open.png", _open)

    # Closed disclosure at the end of a branch.
    def _closed_end(p):
        _vline(p, cx, 0, cy)
        _triangle(p, cx, cy, closed=True)

    _draw(out / "closed_end.png", _closed_end)

    # Open disclosure at the end of a branch.
    def _open_end(p):
        _vline(p, cx, 0, cy)
        _triangle(p, cx, cy, closed=False)

    _draw(out / "open_end.png", _open_end)


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
    """Filled triangle pointing right (closed) or down (open)."""
    size = 4
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QBrush(_TRIANGLE_COLOR))
    if closed:
        poly = QtGui.QPolygonF([
            QtCore.QPointF(cx - 1, cy - size),
            QtCore.QPointF(cx + size - 1, cy),
            QtCore.QPointF(cx - 1, cy + size),
        ])
    else:
        poly = QtGui.QPolygonF([
            QtCore.QPointF(cx - size, cy - 1),
            QtCore.QPointF(cx + size, cy - 1),
            QtCore.QPointF(cx, cy + size - 1),
        ])
    painter.drawPolygon(poly)


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
        "QTreeView::branch:has-children:!has-siblings:closed,"
        " QTreeView::branch:closed:has-children:has-siblings {"
        " border-image: none;"
        f" image: url({url('closed')});"
        " }"
        "QTreeView::branch:open:has-children:!has-siblings,"
        " QTreeView::branch:open:has-children:has-siblings {"
        " border-image: none;"
        f" image: url({url('open')});"
        " }"
    )
