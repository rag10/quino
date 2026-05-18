"""Regression tests for ForceCommands extraction (Fase 2 Task 3)."""
from __future__ import annotations

from quino import ApplicationService, MarkerInput, PropertyValueInput
from quino.domain.model import SpringEndpoint
from quino.domain.types import SpringEndpointKind


def _make_app_with_marker() -> tuple[ApplicationService, str, str]:
    app = ApplicationService()
    app.new_project("T")
    body_id = app.create_bar(
        "Arm",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
    )
    marker_id = next(
        m.id for m in app._find_body(body_id).markers if m.name == "B"
    )
    return app, body_id, marker_id


def test_create_and_delete_load() -> None:
    app, _, marker_id = _make_app_with_marker()
    load_id = app.create_load("Wind", marker_id, "10 N", "-5 N")
    assert any(l.id == load_id for l in app.project.model.loads)
    app.delete_load(load_id)
    assert not any(l.id == load_id for l in app.project.model.loads)


def test_rename_and_update_load_property() -> None:
    app, _, marker_id = _make_app_with_marker()
    load_id = app.create_load("Wind", marker_id, "10 N", "-5 N")
    app.rename_load(load_id, "Gust")
    assert app.project.model.loads[0].name == "Gust"
    app.update_load_property(load_id, "fx", "20 N")
    assert app.project.model.loads[0].fx.expression == "20 N"


def test_create_and_delete_sensor() -> None:
    app, body_id, _ = _make_app_with_marker()
    marker_a = next(m.id for m in app._find_body(body_id).markers if m.name == "A")
    marker_b = next(m.id for m in app._find_body(body_id).markers if m.name == "B")
    sensor_id = app.create_sensor("Gap", "distance", [marker_a, marker_b])
    assert any(s.id == sensor_id for s in app.project.model.sensors)
    app.rename_sensor(sensor_id, "Distance")
    assert app.project.model.sensors[0].name == "Distance"
    app.delete_sensor(sensor_id)
    assert not any(s.id == sensor_id for s in app.project.model.sensors)


def test_create_and_update_spring() -> None:
    app, body_id, marker_id = _make_app_with_marker()
    marker_a = next(m.id for m in app._find_body(body_id).markers if m.name == "A")
    ep_a = SpringEndpoint(kind=SpringEndpointKind.MARKER, marker_id=marker_a)
    ep_b = SpringEndpoint(kind=SpringEndpointKind.MARKER, marker_id=marker_id)
    spring_id = app.create_spring("Sp1", "linear_spring", ep_a, ep_b)
    assert any(sp.id == spring_id for sp in app.project.model.springs)

    spring = app.get_spring(spring_id)
    assert spring.name == "Sp1"

    app.update_spring_property(
        spring_id, "stiffness", PropertyValueInput(kind="expression", value="42")
    )
    assert app.spring_stiffness(app.get_spring(spring_id)) == 42.0

    app.update_spring_property(
        spring_id, "rest_value", PropertyValueInput(kind="expression", value="15 mm")
    )
    assert app.get_spring(spring_id).rest_value.expression == "15 mm"

    app.rename_spring(spring_id, "Sp1b")
    assert app.get_spring(spring_id).name == "Sp1b"

    app.delete_spring(spring_id)
    assert not any(sp.id == spring_id for sp in app.project.model.springs)
