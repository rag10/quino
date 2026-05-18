"""Regression tests for EntityCommands (Task 8 of Fase 2 refactor).

These tests exercise EntityCommands indirectly through ApplicationService's
public API to lock down the behavior of the generic entity dispatchers
(rename_entity, delete_entity, update_property) and gravity CRUD.
"""
from __future__ import annotations

import pytest

from quino import (
    ApplicationService,
    MarkerInput,
    PropertyValueInput,
)
from quino.domain.model import Body, Joint, Marker


def make_app() -> ApplicationService:
    app = ApplicationService()
    app.new_project("Demo")
    return app


def test_rename_entity_renames_body() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    app.rename_entity(body_id, "Coupler")
    body = app.get_body(body_id)
    assert body is not None
    assert body.name == "Coupler"


def test_get_entity_returns_body_and_marker_objects() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app.get_entity(body_id)
    assert isinstance(body, Body)
    marker = body.structural_markers()[0]
    fetched = app.get_entity(marker.id)
    assert isinstance(fetched, Marker)
    # Unknown id returns None (does not raise)
    assert app.get_entity("nonexistent") is None


def test_delete_entity_body_cascades_to_joints_and_drivers() -> None:
    app = make_app()
    body_a = app.create_bar("BarA", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body_b = app.create_bar("BarB", MarkerInput("100 mm", "0 mm", "C"), MarkerInput("200 mm", "0 mm", "D"))
    bar_a = app.get_body(body_a)
    bar_b = app.get_body(body_b)
    marker_a_end = bar_a.structural_markers()[1]
    marker_b_start = bar_b.structural_markers()[0]
    from quino.domain.inputs import JointEndpointInput
    from quino.domain.types import JointEndpointKind
    joint_id = app.create_joint(
        "J1",
        "revolute",
        JointEndpointInput(kind=JointEndpointKind.MARKER, body_id=body_a, marker_id=marker_a_end.id),
        JointEndpointInput(kind=JointEndpointKind.MARKER, body_id=body_b, marker_id=marker_b_start.id),
    )
    assert app.get_joint(joint_id) is not None
    app.delete_entity(body_a)
    assert app.get_body(body_a) is None
    # Joint that depended on body_a's marker must be cascade-deleted
    assert app.get_joint(joint_id) is None


def test_delete_entity_joint_only_removes_joint() -> None:
    app = make_app()
    body_a = app.create_bar("BarA", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body_b = app.create_bar("BarB", MarkerInput("100 mm", "0 mm", "C"), MarkerInput("200 mm", "0 mm", "D"))
    bar_a = app.get_body(body_a)
    bar_b = app.get_body(body_b)
    from quino.domain.inputs import JointEndpointInput
    from quino.domain.types import JointEndpointKind
    joint_id = app.create_joint(
        "J1",
        "revolute",
        JointEndpointInput(kind=JointEndpointKind.MARKER, body_id=body_a, marker_id=bar_a.structural_markers()[1].id),
        JointEndpointInput(kind=JointEndpointKind.MARKER, body_id=body_b, marker_id=bar_b.structural_markers()[0].id),
    )
    app.delete_entity(joint_id)
    assert app.get_joint(joint_id) is None
    # Bodies survive
    assert app.get_body(body_a) is not None
    assert app.get_body(body_b) is not None


def test_update_property_marker_x_moves_marker() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app.get_body(body_id)
    marker_a = body.structural_markers()[0]
    app.update_property(marker_a.id, "x", PropertyValueInput("expression", "25 mm"))
    refreshed = app.get_entity(marker_a.id)
    assert refreshed.x.expression == "25 mm"


def test_update_property_name_renames_via_dispatcher() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    app.update_property(body_id, "name", PropertyValueInput("expression", "Renamed"))
    assert app.get_body(body_id).name == "Renamed"


def test_add_gravity_then_delete_gravity_roundtrip() -> None:
    app = make_app()
    assert app.project.model.gravity is None
    app.add_gravity()
    assert app.project.model.gravity is not None
    # Idempotent: calling add_gravity again is a no-op
    app.add_gravity()
    assert app.project.model.gravity is not None
    # Update a gravity property via the dispatcher
    app.update_property(
        "__gravity__", "magnitude", PropertyValueInput("expression", "9.81")
    )
    assert app.project.model.gravity.magnitude == pytest.approx(9.81)
    # delete_entity with the special __gravity__ id routes to delete_gravity
    app.delete_entity("__gravity__")
    assert app.project.model.gravity is None


def test_update_property_visible_boolean() -> None:
    app = make_app()
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app.get_body(body_id)
    marker = body.structural_markers()[0]
    assert marker.visible is True
    app.update_property(marker.id, "visible", PropertyValueInput("boolean", False))
    refreshed = app.get_entity(marker.id)
    assert refreshed.visible is False
