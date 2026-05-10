from __future__ import annotations

from quino.domain.model import Expression, Sketch, SketchLineSegment, SketchPoint
from quino.domain.sketch_evaluated import BBox, EvaluatedLineSegment, EvaluatedPoint, Vec2
from quino.domain.types import SketchEntityType
from quino.services.sketch_cache import SketchGeometryCache, SketchInvalidationController


def _ep(x: float = 0.0, y: float = 0.0) -> EvaluatedPoint:
    return EvaluatedPoint(position=Vec2(x, y), bbox=BBox(x, y, x, y))


def _pt(pid: str, x: str = "0", y: str = "0") -> SketchPoint:
    return SketchPoint(id=pid, name=pid, type=SketchEntityType.POINT,
                       x=Expression(x), y=Expression(y))


def _line(lid: str, s: str, e: str) -> SketchLineSegment:
    return SketchLineSegment(id=lid, name=lid, type=SketchEntityType.LINE_SEGMENT,
                             start_point_id=s, end_point_id=e)


# --- SketchGeometryCache ---

def test_cache_miss_returns_none() -> None:
    cache = SketchGeometryCache()
    assert cache.get("p1") is None


def test_cache_hit_returns_stored_geometry() -> None:
    cache = SketchGeometryCache()
    ep = _ep(1.0, 2.0)
    cache.put("p1", ep)
    assert cache.get("p1") is ep


def test_cache_invalidate_removes_single_entry() -> None:
    cache = SketchGeometryCache()
    cache.put("p1", _ep())
    cache.put("p2", _ep())
    cache.invalidate("p1")
    assert cache.get("p1") is None
    assert cache.get("p2") is not None


def test_cache_invalidate_all_clears_every_entry() -> None:
    cache = SketchGeometryCache()
    cache.put("p1", _ep())
    cache.put("p2", _ep())
    cache.invalidate_all()
    assert cache.get("p1") is None
    assert cache.get("p2") is None


def test_cache_overwrite_updates_stored_value() -> None:
    cache = SketchGeometryCache()
    ep1 = _ep(0.0, 0.0)
    ep2 = _ep(5.0, 5.0)
    cache.put("p1", ep1)
    cache.put("p1", ep2)
    assert cache.get("p1") is ep2


# --- SketchInvalidationController ---

def test_controller_invalidates_point_on_parameter_change() -> None:
    cache = SketchGeometryCache()
    sketch = Sketch(id="sk", name="T", entities={"p1": _pt("p1")})
    controller = SketchInvalidationController(cache)
    controller.rebuild(sketch)

    cache.put("p1", _ep())
    controller.on_parameter_changed("p1.x")

    assert cache.get("p1") is None


def test_controller_invalidates_line_when_endpoint_changes() -> None:
    cache = SketchGeometryCache()
    p1, p2 = _pt("p1"), _pt("p2")
    line = _line("l1", "p1", "p2")
    sketch = Sketch(id="sk", name="T", entities={"p1": p1, "p2": p2, "l1": line})
    controller = SketchInvalidationController(cache)
    controller.rebuild(sketch)

    cache.put("p1", _ep())
    cache.put("l1", EvaluatedLineSegment(start=Vec2(0, 0), end=Vec2(10, 0), bbox=BBox(0, 0, 10, 0)))
    controller.on_parameter_changed("p1.y")

    assert cache.get("p1") is None
    assert cache.get("l1") is None


def test_controller_without_rebuild_invalidates_all() -> None:
    cache = SketchGeometryCache()
    cache.put("p1", _ep())
    cache.put("p2", _ep())
    controller = SketchInvalidationController(cache)
    controller.on_parameter_changed("p1.x")
    assert cache.get("p1") is None
    assert cache.get("p2") is None
