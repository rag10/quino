import math
import pytest
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.model import CoMAnchor


def _bar() -> tuple[ApplicationService, str]:
    app = ApplicationService()
    app.new_project("t")
    body_id = app.create_bar(
        "Bar",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
    )
    return app, body_id


def test_set_com_percent_updates_anchor():
    app, body_id = _bar()
    app.bodies.set_com_percent(body_id, 75.0)
    body = app.get_body(body_id)
    assert body.com.kind == "bar_percent"
    assert body.com.data["percent"] == pytest.approx(75.0)


def test_set_com_offset_swaps_kind_to_local_offset():
    app, body_id = _bar()
    app.bodies.set_com_offset(body_id, 20.0, -3.0)
    body = app.get_body(body_id)
    assert body.com.kind == "local_offset"
    assert body.com.data == {"lx": 20.0, "ly": -3.0}


def test_drag_com_inside_bar_uses_bar_percent():
    app, body_id = _bar()
    # world (40, 0) lies on the segment from (0,0) to (100,0)
    app.bodies.drag_com_to_world(body_id, 40.0, 0.0)
    body = app.get_body(body_id)
    assert body.com.kind == "bar_percent"
    assert body.com.data["percent"] == pytest.approx(40.0)


def test_drag_com_outside_bar_detaches_to_local_offset():
    app, body_id = _bar()
    app.bodies.drag_com_to_world(body_id, 50.0, 10.0)  # off the segment
    body = app.get_body(body_id)
    assert body.com.kind == "local_offset"
    assert body.com.data["lx"] == pytest.approx(50.0)
    assert body.com.data["ly"] == pytest.approx(10.0)


def test_drag_com_inside_triangle_uses_barycentric():
    app = ApplicationService()
    app.new_project("t")
    body_id = app.create_body(
        "Tri",
        [
            MarkerInput("0 mm", "0 mm", "A"),
            MarkerInput("100 mm", "0 mm", "B"),
            MarkerInput("0 mm", "60 mm", "C"),
        ],
        body_type="body",
    )
    # Centroid of the triangle is (~33.33, 20.0)
    app.bodies.drag_com_to_world(body_id, 100.0 / 3.0, 20.0)
    body = app.get_body(body_id)
    assert body.com.kind == "barycentric"
    weights = body.com.data["weights"]
    total = sum(weights.values())
    for w in weights.values():
        assert w / total == pytest.approx(1.0 / 3.0, abs=1e-3)


def test_punctual_mass_rejects_com_edits():
    app = ApplicationService()
    app.new_project("t")
    body_id = app.create_punctual_mass("M", x="0 mm", y="0 mm")
    with pytest.raises(ValueError, match="locked"):
        app.bodies.set_com_offset(body_id, 5.0, 0.0)
