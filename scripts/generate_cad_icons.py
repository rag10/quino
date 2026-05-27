from __future__ import annotations

# ruff: noqa: E501
import argparse
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "quino" / "gui" / "icons"
QRC_PATH = ICONS_DIR / "icons.qrc"


PALETTE = {
    "neutral": "#3f4b59",
    "sketch": "#66727e",
    "model": "#2d74a7",
    "dynamic": "#c76f1f",
    "sensor": "#25815f",
    "workspace": "#326399",
    "danger": "#b43a2f",
    "ok": "#25815f",
}
ACCENT = {
    "neutral": "#d58228",
    "sketch": "#d58228",
    "model": "#d58228",
    "dynamic": "#2d74a7",
    "sensor": "#d58228",
    "workspace": "#d58228",
    "danger": "#3f4b59",
    "ok": "#2d74a7",
}
FILLS = {
    "neutral": ("#f4f6f8", "#e8edf2", "#ffffff"),
    "sketch": ("#f4f6f7", "#e7ebee", "#ffffff"),
    "model": ("#e8f3fa", "#cfe4f3", "#f7fbfe"),
    "dynamic": ("#fff1e2", "#f6d3ac", "#fff9f1"),
    "sensor": ("#e7f4ee", "#cde7dc", "#f7fcfa"),
    "workspace": ("#eaf1fa", "#d2e1f1", "#f8fbfe"),
    "danger": ("#fdecea", "#f7d2ce", "#fff7f6"),
    "ok": ("#e7f4ee", "#cde7dc", "#f7fcfa"),
}
COLOR_TOKEN = {
    "p": "__P__",
    "a": "__A__",
    "t": "__T__",
    "s": "__S__",
    "h": "__H__",
    "none": "none",
}


@dataclass(frozen=True)
class IconSpec:
    family: str
    body: str
    accent: str | None = None


def tag(name: str, attrs: str, *, close: bool = True) -> str:
    return f"  <{name} {attrs}/>" if close else f"  <{name} {attrs}>"


def line(x1: float, y1: float, x2: float, y2: float, cls: str = "p", sw: float | None = None) -> str:
    extra = f' stroke-width="{sw}"' if sw else ""
    return tag("line", f'stroke="{COLOR_TOKEN[cls]}" x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}"{extra}')


def poly(points: str, cls: str = "p", fill: str = "none", sw: float | None = None) -> str:
    extra = f' stroke-width="{sw}"' if sw else ""
    return tag("polyline", f'stroke="{COLOR_TOKEN[cls]}" points="{points}" fill="{COLOR_TOKEN[fill]}"{extra}')


def polygon(points: str, cls: str = "p", fill: str = "t", sw: float | None = None) -> str:
    extra = f' stroke-width="{sw}"' if sw else ""
    return tag("polygon", f'stroke="{COLOR_TOKEN[cls]}" points="{points}" fill="{COLOR_TOKEN[fill]}"{extra}')


def path(d: str, cls: str = "p", fill: str = "none", sw: float | None = None) -> str:
    extra = f' stroke-width="{sw}"' if sw else ""
    return tag("path", f'stroke="{COLOR_TOKEN[cls]}" d="{d}" fill="{COLOR_TOKEN[fill]}"{extra}')


def circle(cx: float, cy: float, r: float, cls: str = "p", fill: str = "t", sw: float | None = None) -> str:
    extra = f' stroke-width="{sw}"' if sw else ""
    return tag("circle", f'stroke="{COLOR_TOKEN[cls]}" cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="{COLOR_TOKEN[fill]}"{extra}')


def rect(x: float, y: float, w: float, h: float, cls: str = "p", fill: str = "t", rx: float = 1.2) -> str:
    return tag("rect", f'stroke="{COLOR_TOKEN[cls]}" x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}" fill="{COLOR_TOKEN[fill]}"')


def dot(cx: float, cy: float, r: float = 1.5, cls: str = "p") -> str:
    return tag("circle", f'cx="{cx:g}" cy="{cy:g}" r="{r:g}" fill="{COLOR_TOKEN[cls]}" stroke="none"')


def marker(cx: float, cy: float, r: float = 3.2) -> str:
    return circle(cx, cy, r) + "\n" + dot(cx, cy, 1.1)


def arrow_right(x: float, y: float, cls: str = "p") -> str:
    return polygon(f"{x:g},{y - 3:g} {x + 5:g},{y:g} {x:g},{y + 3:g}", cls=cls, fill="p")


def arrow_left(x: float, y: float, cls: str = "p") -> str:
    return polygon(f"{x:g},{y:g} {x + 5:g},{y - 3:g} {x + 5:g},{y + 3:g}", cls=cls, fill="p")


def spring(x1: float = 7, y: float = 16, x2: float = 25) -> str:
    return poly(
        f"{x1:g},{y:g} 9,{y:g} 10.5,11 13.5,21 16.5,11 19.5,21 22.5,11 24,{y:g} {x2:g},{y:g}"
    )


def iso_cube(x: float = 8, y: float = 8, scale: float = 1.0) -> str:
    def p(dx: float, dy: float) -> str:
        return f"{x + dx * scale:g},{y + dy * scale:g}"

    return "\n".join(
        [
            polygon(f"{p(8,0)} {p(17,5)} {p(9,10)} {p(0,5)}", fill="h"),
            polygon(f"{p(0,5)} {p(9,10)} {p(9,20)} {p(0,15)}", fill="t"),
            polygon(f"{p(9,10)} {p(17,5)} {p(17,15)} {p(9,20)}", fill="s"),
            line(x + 8 * scale, y, x + 8 * scale, y + 8 * scale, cls="a", sw=1.1),
        ]
    )


def body_plate() -> str:
    return "\n".join(
        [
            polygon("7,20 9,10 17,7 25,12 24,22 15,25", fill="t"),
            polygon("9,10 17,7 25,12 16,15", fill="h"),
            polygon("16,15 25,12 24,22 15,25", fill="s"),
            line(16, 15, 15, 25, cls="a", sw=1.1),
            marker(9, 10, 2.3),
            marker(25, 12, 2.3),
            marker(15, 25, 2.3),
        ]
    )


def bar() -> str:
    return "\n".join(
        [
            polygon("7,13 25,13 27,16 25,19 7,19 5,16", fill="s", sw=1.5),
            line(7, 16, 25, 16, sw=1.2),
            marker(7, 16),
            marker(25, 16),
        ]
    )


def slider_base() -> str:
    return "\n".join(
        [
            rect(5, 12, 22, 8, fill="s", rx=1.6),
            line(8, 15, 24, 15, sw=1.1),
            line(8, 18, 24, 18, sw=1.1),
            rect(12, 10, 8, 12, fill="h", rx=1.4),
            marker(16, 16, 2.5),
        ]
    )


def ground() -> str:
    return "\n".join(
        [
            line(7, 22, 25, 22),
            line(10, 22, 7.5, 26),
            line(15, 22, 12.5, 26),
            line(20, 22, 17.5, 26),
            line(24, 22, 21.5, 26),
            line(16, 8, 16, 22),
            marker(16, 8, 3),
        ]
    )


def sensor_pair(kind: str) -> str:
    base = [marker(8, 17, 3), marker(24, 17, 3), line(11, 17, 21, 17)]
    if kind == "distance":
        base += [arrow_left(11, 17), arrow_right(21, 17), line(8, 9, 24, 9, sw=1.1), line(8, 9, 8, 12), line(24, 9, 24, 12)]
    elif kind == "angle-h":
        base += [line(8, 23, 24, 23, cls="a"), path("M12 23 A8 8 0 0 1 19.5 18", cls="a"), arrow_right(19.5, 18, cls="a")]
    elif kind == "angle-v":
        base += [line(8, 25, 8, 8, cls="a"), path("M8 21 A8 8 0 0 0 15.5 17", cls="a"), arrow_right(15.5, 17, cls="a")]
    else:
        base += [line(8, 8, 24, 25, cls="a"), path("M12 17 A6 6 0 0 1 16 12", cls="a"), arrow_right(16, 12, cls="a")]
    return "\n".join(base)


def file_icon(save: bool = False, plus: bool = False) -> str:
    parts = [path("M9 5 H20 L25 10 V27 H9 Z", fill="t"), polygon("20,5 25,10 20,10", fill="s")]
    if save:
        parts += [rect(12, 17, 10, 7, fill="s", rx=0.8), line(14, 20, 20, 20)]
    if plus:
        parts += [line(16, 14, 16, 23, cls="a"), line(11.5, 18.5, 20.5, 18.5, cls="a")]
    return "\n".join(parts)


def workspace_shape(kind: str) -> str:
    if kind == "baseline":
        return "\n".join([iso_cube(7, 6, 0.9), line(8, 27, 25, 27), line(11, 24, 22, 24)])
    if kind == "case":
        return "\n".join([polygon("16,5 27,16 16,27 5,16"), dot(16, 16, 1.7)])
    if kind == "subcase":
        return "\n".join([polygon("15,7 25,17 15,27 5,17"), polygon("20,5 27,12 20,19 13,12", fill="s")])
    if kind == "pose":
        return "\n".join([marker(10, 22, 2.5), marker(22, 10, 2.5), line(10, 22, 22, 10), path("M9 10 C15 7 20 7 25 11", cls="a"), arrow_right(25, 11, cls="a")])
    if kind == "poses":
        return "\n".join([workspace_shape("pose"), circle(22, 22, 3, cls="a", fill="s")])
    if kind == "analysis":
        return "\n".join([path("M7 23 L12 14 L17 19 L24 8", cls="a"), line(7, 25, 25, 25), line(7, 7, 7, 25)])
    if kind == "analyses":
        return "\n".join([workspace_shape("analysis"), line(12, 10, 18, 10), line(12, 13, 21, 13)])
    if kind == "diffs":
        return "\n".join([rect(6, 7, 10, 16, fill="s"), rect(16, 10, 10, 16, fill="s"), line(9, 14, 13, 14), line(19, 17, 23, 17), line(21, 15, 21, 19)])
    if kind == "blocks":
        return "\n".join([iso_cube(5, 5, 0.55), iso_cube(18, 5, 0.55), iso_cube(11, 18, 0.55), line(11, 15, 15, 20), line(22, 15, 18, 20)])
    return iso_cube(7, 7, 1.0)


def specs() -> dict[str, IconSpec]:
    p: dict[str, IconSpec] = {}

    def add(name: str, family: str, body: str, accent: str | None = None) -> None:
        p[name] = IconSpec(family, body, accent)

    # Common commands
    add("file-new", "neutral", file_icon(plus=True))
    add("folder-open", "neutral", "\n".join([path("M5 11 H13 L15 14 H27 L24 25 H6 Z", fill="s"), path("M6 11 V8 H14 L16 11", fill="none")]))
    add("content-save", "neutral", "\n".join([path("M7 6 H22 L25 9 V26 H7 Z", fill="s"), rect(11, 7, 9, 6, fill="t", rx=0.6), rect(11, 18, 10, 6, fill="t", rx=0.6)]))
    add("content-save-as", "neutral", "\n".join([path("M7 6 H22 L25 9 V26 H7 Z", fill="s"), rect(11, 18, 10, 6, fill="t", rx=0.6), path("M20 8 L25 13", cls="a"), path("M23 7 L26 10 L15 21 L12 22 L13 19 Z", cls="a", fill="s")]))
    add("undo", "neutral", "\n".join([path("M13 10 H8 V5", fill="none"), path("M8 10 C11 6 18 6 22 10 C26 14 24 21 19 23", fill="none")]))
    add("redo", "neutral", "\n".join([path("M19 10 H24 V5", fill="none"), path("M24 10 C21 6 14 6 10 10 C6 14 8 21 13 23", fill="none")]))
    add("refresh", "neutral", "\n".join([path("M23 11 A8 8 0 0 0 9 10", fill="none"), path("M9 10 H7 V6", fill="none"), path("M9 21 A8 8 0 0 0 23 22", fill="none"), path("M23 22 H25 V26", fill="none")]))
    add("preferences", "neutral", "\n".join([circle(16, 16, 4, fill="s"), path("M16 5 V9 M16 23 V27 M5 16 H9 M23 16 H27 M8.2 8.2 L11 11 M21 21 L23.8 23.8 M23.8 8.2 L21 11 M11 21 L8.2 23.8", fill="none")]))
    add("fit-view", "neutral", "\n".join([poly("12,6 6,6 6,12"), poly("20,6 26,6 26,12"), poly("6,20 6,26 12,26"), poly("26,20 26,26 20,26"), rect(11, 11, 10, 10, fill="s")]))
    add("select", "neutral", polygon("8,5 24,17 17,19 14,27", fill="s"))
    add("grid", "neutral", "\n".join([rect(6, 6, 20, 20, fill="none"), line(12.7, 6, 12.7, 26, sw=1.1), line(19.3, 6, 19.3, 26, sw=1.1), line(6, 12.7, 26, 12.7, sw=1.1), line(6, 19.3, 26, 19.3, sw=1.1)]))
    add("origin", "neutral", "\n".join([line(16, 25, 16, 7), line(7, 16, 25, 16), arrow_right(22, 16), polygon("16,7 13,12 19,12", fill="p"), dot(16, 16, 1.3)]))
    add("add", "ok", "\n".join([circle(16, 16, 10, fill="s"), line(16, 10, 16, 22), line(10, 16, 22, 16)]))
    add("remove", "danger", "\n".join([circle(16, 16, 10, fill="s"), line(10, 16, 22, 16)]))
    add("delete", "danger", "\n".join([line(8, 10, 24, 10), path("M12 10 V7 H20 V10", fill="none"), path("M10 10 L11 26 H21 L22 10", fill="s"), line(14, 14, 14, 23), line(18, 14, 18, 23)]))
    add("check-circle", "ok", "\n".join([circle(16, 16, 10, fill="s"), poly("10.5,16.5 14,20 22,12")]))
    add("play", "dynamic", polygon("11,8 24,16 11,24", fill="s"))
    add("pause", "dynamic", "\n".join([rect(10, 8, 4.5, 16, fill="s", rx=1), rect(17.5, 8, 4.5, 16, fill="s", rx=1)]))
    add("stop", "dynamic", rect(10, 10, 12, 12, fill="s", rx=1.2))

    # Model entities
    add("bar", "model", bar())
    add("body", "model", body_plate())
    add("point-mass", "model", "\n".join([circle(16, 16, 6, fill="s"), line(16, 8, 16, 24), line(8, 16, 24, 16)]))
    add("marker", "model", marker(16, 16, 5))
    add("marker-plus", "model", "\n".join([marker(13, 16, 4), circle(22, 10, 5, cls="a", fill="s"), line(22, 7, 22, 13, cls="a"), line(19, 10, 25, 10, cls="a")]))
    add("revolute", "model", "\n".join([circle(16, 16, 7, fill="s"), circle(16, 16, 3, fill="t"), line(5, 16, 9, 16), line(23, 16, 27, 16)]))
    add("rigid", "model", "\n".join([rect(8, 10, 16, 12, fill="s", rx=2), line(11, 13, 21, 19), line(21, 13, 11, 19)]))
    add("slider", "model", slider_base())
    add("ground", "model", ground())
    add("slider-connect", "model", "\n".join([slider_base(), line(16, 8, 16, 13, cls="a"), marker(16, 8, 2.5)]))
    add("four-bar", "model", "\n".join([line(7, 22, 14, 10), line(14, 10, 23, 12), line(23, 12, 25, 22), line(7, 22, 25, 22), marker(7, 22, 2.5), marker(14, 10, 2.5), marker(23, 12, 2.5), marker(25, 22, 2.5)]))
    add("slider-crank", "model", "\n".join([marker(8, 20, 2.8), line(8, 20, 15, 11), marker(15, 11, 2.8), line(15, 11, 24, 16), rect(22, 12, 6, 8, fill="s", rx=1.2), line(21, 22, 29, 22)]))

    # Sketch and constraints
    add("sketch-point", "sketch", marker(16, 16, 3))
    add("sketch-line", "sketch", "\n".join([line(7, 23, 25, 9), marker(7, 23, 2), marker(25, 9, 2)]))
    add("sketch-rectangle", "sketch", rect(8, 9, 16, 14, fill="none"))
    add("sketch-circle", "sketch", circle(16, 16, 8, fill="none"))
    add("sketch-arc", "sketch", "\n".join([path("M9 22 A10 10 0 0 1 23 8", fill="none"), marker(9, 22, 2), marker(23, 8, 2)]))
    add("sketch-infinite-line", "sketch", "\n".join([line(5, 24, 27, 8), line(7, 22, 10, 25, sw=1), line(22, 7, 25, 10, sw=1)]))
    add("constraint-fix", "sketch", "\n".join([marker(16, 10, 2.5), line(16, 12, 16, 22), line(10, 22, 22, 22), line(12, 22, 10, 26), line(17, 22, 15, 26), line(22, 22, 20, 26)]))
    add("constraint-horizontal", "sketch", "\n".join([line(7, 16, 25, 16), marker(7, 16, 2.3), marker(25, 16, 2.3), line(11, 11, 21, 11, cls="a")]))
    add("constraint-vertical", "sketch", "\n".join([line(16, 7, 16, 25), marker(16, 7, 2.3), marker(16, 25, 2.3), line(22, 11, 22, 21, cls="a")]))
    add("constraint-distance", "sketch", "\n".join([line(8, 20, 24, 12), marker(8, 20, 2.3), marker(24, 12, 2.3), line(9, 9, 23, 9, cls="a"), arrow_left(9, 9, cls="a"), arrow_right(23, 9, cls="a")]))
    add("constraint-coincident", "sketch", "\n".join([circle(16, 16, 7, fill="none"), circle(16, 16, 3, cls="a", fill="none")]))
    add("parallel", "sketch", "\n".join([line(9, 22, 19, 10), line(14, 24, 24, 12)]))
    add("perpendicular", "sketch", "\n".join([line(10, 22, 22, 10), line(10, 22, 22, 22), poly("14,22 14,18 18,18", cls="a")]))
    add("equal-length", "sketch", "\n".join([line(8, 11, 23, 11), line(9, 22, 24, 22), line(15, 8, 16, 14, cls="a"), line(16, 19, 17, 25, cls="a")]))
    add("angle-constraint", "sketch", "\n".join([line(9, 23, 16, 10), line(9, 23, 24, 21), path("M12 22 A8 8 0 0 1 17 16", cls="a")]))
    add("midpoint", "sketch", "\n".join([line(8, 22, 24, 10), marker(8, 22, 2), marker(24, 10, 2), circle(16, 16, 3, cls="a", fill="s")]))
    add("collinear", "sketch", "\n".join([line(7, 23, 25, 9), marker(8, 22, 2), marker(16, 16, 2), marker(24, 10, 2)]))
    add("symmetric", "sketch", "\n".join([line(16, 6, 16, 26, cls="a"), marker(9, 16, 2.5), marker(23, 16, 2.5), line(9, 16, 23, 16, sw=1.1)]))
    add("tangent", "sketch", "\n".join([circle(12, 17, 6, fill="none"), line(17, 12, 25, 4), marker(17, 12, 1.9)]))
    add("concentric", "sketch", "\n".join([circle(16, 16, 8, fill="none"), circle(16, 16, 4, cls="a", fill="none"), dot(16, 16, 1.2)]))
    add("on-circle", "sketch", "\n".join([circle(16, 16, 8, fill="none"), marker(22, 10, 2.4)]))
    add("arc-center", "sketch", "\n".join([path("M9 22 A10 10 0 0 1 23 8", fill="none"), line(16, 16, 23, 8, cls="a"), marker(16, 16, 2.2)]))
    add("sketch-solve", "sketch", "\n".join([circle(16, 16, 10, fill="s"), poly("10.5,16.5 14,20 22,12")]))
    add("sketch-visible", "sketch", "\n".join([path("M5 16 C9 9 23 9 27 16 C23 23 9 23 5 16 Z", fill="s"), circle(16, 16, 3.5, fill="t")]))

    # Dynamic, loads, sensors
    add("gravity", "dynamic", "\n".join([line(16, 5, 16, 23), polygon("12,20 16,27 20,20", fill="p"), line(11, 8, 21, 8, cls="a")]))
    add("load-gravity", "dynamic", "\n".join([marker(16, 7, 2.5), line(16, 10, 16, 24), polygon("12,21 16,28 20,21", fill="p")]))
    add("torque", "dynamic", "\n".join([path("M22 11 A8 8 0 1 0 23 21", fill="none"), arrow_right(23, 21), marker(16, 16, 2.8)]))
    add("rotate-driver", "dynamic", "\n".join([circle(16, 16, 6, fill="s"), path("M22 9 A9 9 0 0 1 24 21", cls="a"), arrow_right(24, 21, cls="a")]))
    add("translate-driver", "dynamic", "\n".join([slider_base(), line(7, 8, 23, 8, cls="a"), arrow_left(7, 8, cls="a"), arrow_right(23, 8, cls="a")]))
    add("spring", "dynamic", spring())
    add("rot-spring", "dynamic", "\n".join([circle(16, 16, 4, fill="s"), path("M20 10 C26 13 26 20 20 23 C14 26 8 22 9 16 C9.5 11 14 9 18 11", fill="none")]))
    add("actuator", "dynamic", "\n".join([line(5, 16, 10, 16), rect(10, 12, 9, 8, fill="s", rx=1.5), line(19, 16, 27, 16), arrow_right(22, 16, cls="a")]))
    add("rot-actuator", "dynamic", "\n".join([circle(16, 16, 5, fill="s"), path("M21 8 A10 10 0 0 1 25 18", cls="a"), arrow_right(25, 18, cls="a"), line(16, 16, 22, 12)]))
    add("run-simulation", "dynamic", "\n".join([circle(14, 15, 7, fill="s"), path("M14 8 L15 5 L19 6 L18 9", fill="none"), circle(23, 23, 6, cls="a", fill="s"), polygon("21,20 26,23 21,26", cls="a", fill="p")]))
    add("new-graph", "sensor", "\n".join([line(7, 25, 25, 25), line(7, 7, 7, 25), path("M8 21 C12 12 15 24 19 14 C21 9 23 10 25 8", cls="a"), line(21, 8, 27, 8, cls="a"), line(24, 5, 24, 11, cls="a")]))
    add("trajectories", "sensor", "\n".join([path("M7 23 C12 8 20 24 25 8", cls="a"), marker(7, 23, 2), marker(16, 16, 2), marker(25, 8, 2)]))
    add("sensor-point", "sensor", "\n".join([marker(16, 16, 4), circle(16, 16, 9, cls="a", fill="none")]))
    add("sensor-distance", "sensor", sensor_pair("distance"))
    add("sensor-angle-h", "sensor", sensor_pair("angle-h"))
    add("sensor-angle-v", "sensor", sensor_pair("angle-v"))
    add("sensor-angle-vec", "sensor", sensor_pair("angle-vec"))

    # Sections and workspace browser
    for name, body in {
        "section-bodies": body_plate(),
        "section-joints": "\n".join([circle(16, 16, 7, fill="s"), circle(16, 16, 3, fill="t")]),
        "section-loads": "\n".join([line(16, 6, 16, 23), polygon("12,20 16,27 20,20", fill="p")]),
        "section-reactions": "\n".join([line(16, 26, 16, 9), polygon("12,12 16,5 20,12", fill="p"), ground()]),
        "section-sensors": "\n".join([marker(16, 16, 4), circle(16, 16, 9, cls="a", fill="none")]),
        "section-sketch": "\n".join([line(8, 23, 24, 9), circle(20, 13, 7, fill="none")]),
        "section-drivers": "\n".join([slider_base(), arrow_right(22, 8, cls="a")]),
        "section-sliders": slider_base(),
        "section-springs": spring(),
    }.items():
        family = "sensor" if "sensor" in name else "sketch" if "sketch" in name else "dynamic" if any(k in name for k in ("load", "reaction", "driver", "spring")) else "model"
        add(name, family, body)

    for kind in ("baseline", "case", "subcase", "pose", "poses", "analysis", "analyses", "diffs", "blocks"):
        add(f"workspace-{kind}", "workspace", workspace_shape(kind))
    add("block-instance", "workspace", "\n".join([rect(7, 9, 18, 14, fill="s"), line(11, 13, 21, 13), line(11, 18, 18, 18)]))

    return p


def svg_document(spec: IconSpec) -> str:
    primary = PALETTE[spec.family]
    accent = spec.accent or ACCENT[spec.family]
    tint, soft, highlight = FILLS[spec.family]
    body = (
        spec.body.replace("__P__", primary)
        .replace("__A__", accent)
        .replace("__T__", tint)
        .replace("__S__", soft)
        .replace("__H__", highlight)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" '
        'viewBox="0 0 32 32" fill="none">\n'
        '  <g stroke-width="1.7" stroke-linecap="round" '
        'stroke-linejoin="round" vector-effect="non-scaling-stroke">\n'
        f"{body}\n"
        "  </g>\n"
        "</svg>\n"
    )


def backup_existing_icons() -> Path | None:
    svg_files = sorted(ICONS_DIR.glob("*.svg"))
    if not svg_files:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = ICONS_DIR / f"backup-{stamp}-original-svg"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for svg_path in svg_files:
        shutil.move(str(svg_path), str(backup_dir / svg_path.name))
    return backup_dir


def write_qrc(icon_names: list[str]) -> None:
    lines = ["<RCC>", '  <qresource prefix="/icons">']
    lines.extend(f"    <file>{name}.svg</file>" for name in icon_names)
    lines.extend(["  </qresource>", "</RCC>", ""])
    QRC_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", action="store_true", help="Move existing SVGs to a backup folder first.")
    args = parser.parse_args()

    if args.backup:
        backup_dir = backup_existing_icons()
        if backup_dir:
            print(f"Backed up existing SVGs to {backup_dir.relative_to(ROOT)}")

    all_specs = specs()
    for name, spec in sorted(all_specs.items()):
        (ICONS_DIR / f"{name}.svg").write_text(svg_document(spec), encoding="utf-8")
    write_qrc(sorted(all_specs))
    print(f"Generated {len(all_specs)} CAD icons in {ICONS_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
