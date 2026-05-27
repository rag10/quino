from __future__ import annotations

from PySide6 import QtGui, QtWidgets

from quino.gui.icons import ICONS_DIR, get_icon


def _average_opaque_color(icon: QtGui.QIcon) -> QtGui.QColor:
    image = icon.pixmap(32, 32).toImage()
    red = green = blue = count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = QtGui.QColor(image.pixelColor(x, y))
            if color.alpha() < 128:
                continue
            red += color.red()
            green += color.green()
            blue += color.blue()
            count += 1
    assert count > 0
    return QtGui.QColor(red // count, green // count, blue // count)


def _opaque_pixel_count(icon: QtGui.QIcon) -> int:
    image = icon.pixmap(32, 32).toImage()
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() >= 128:
                count += 1
    return count


def test_get_icon_applies_requested_color():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    blue = get_icon("bar", "#2f6f9f", size=32)
    orange = get_icon("bar", "#c7781d", size=32)

    assert not blue.isNull()
    assert not orange.isNull()
    blue_average = _average_opaque_color(blue)
    orange_average = _average_opaque_color(orange)

    assert blue_average.blue() > blue_average.red()
    assert orange_average.red() > orange_average.blue()


def test_all_svg_icons_render_nonblank():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    for svg_path in ICONS_DIR.glob("*.svg"):
        icon = get_icon(svg_path.stem, size=32)
        assert not icon.isNull(), svg_path.name
        assert _opaque_pixel_count(icon) > 0, svg_path.name
