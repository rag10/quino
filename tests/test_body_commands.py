"""Regression tests for BodyCommands via ApplicationService public API."""
from __future__ import annotations

import pytest

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.types import BodyType, MarkerType


@pytest.fixture()
def svc():
    s = ApplicationService()
    s.new_project("test")
    return s


# -------------------------------------------------------------------
# create_bar
# -------------------------------------------------------------------

def test_create_bar_produces_bar_body(svc):
    bid = svc.create_bar("LinkA", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = svc.get_body(bid)
    assert body is not None
    assert body.type is BodyType.BAR
    assert len(body.structural_markers()) == 2
    # CoM marker must exist
    com = body.com_marker()
    assert com is not None
    assert com.type is MarkerType.COM


def test_create_bar_com_at_midpoint(svc):
    bid = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = svc.get_body(bid)
    com = body.com_marker()
    # position_percent defaults to 50
    assert com.metadata.values.get("position_percent") == pytest.approx(50.0)


# -------------------------------------------------------------------
# create_punctual_mass
# -------------------------------------------------------------------

def test_create_punctual_mass(svc):
    bid = svc.create_punctual_mass("PM1", "20 mm", "30 mm")
    body = svc.get_body(bid)
    assert body is not None
    assert body.type is BodyType.POINT_MASS
    assert len(body.structural_markers()) == 1


# -------------------------------------------------------------------
# create_ground_anchor
# -------------------------------------------------------------------

def test_create_ground_anchor_returns_body_and_marker(svc):
    body_id, marker_id = svc.create_ground_anchor("GA", "0 mm", "0 mm")
    body = svc.get_body(body_id)
    assert body is not None
    assert body.type is BodyType.POINT_MASS
    # A rigid ground joint should have been created
    assert len(svc.project.model.joints) == 1
    joint = svc.project.model.joints[0]
    assert joint.endpoint_a.marker_id == marker_id
    # Whole operation is one undo step
    svc.undo()
    assert svc.get_body(body_id) is None
    assert len(svc.project.model.joints) == 0


# -------------------------------------------------------------------
# get_marker_deletion_consequence
# -------------------------------------------------------------------

def test_get_marker_deletion_consequence_normal(svc):
    bid = svc.create_bar("B", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("50 mm", "0 mm", "C"))
    body = svc.get_body(bid)
    # Deleting a marker from a 2-marker bar leaves 1 → to_point_mass
    m_id = body.structural_markers()[1].id
    result = svc.get_marker_deletion_consequence(m_id)
    assert result == "to_point_mass"


def test_get_marker_deletion_consequence_to_bar(svc):
    bid = svc.create_body("Tri", [
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
        MarkerInput("50 mm", "80 mm", "C"),
    ])
    body = svc.get_body(bid)
    m_id = body.structural_markers()[0].id
    result = svc.get_marker_deletion_consequence(m_id)
    assert result == "to_bar"


def test_get_marker_deletion_consequence_unknown_id(svc):
    result = svc.get_marker_deletion_consequence("nonexistent-id")
    assert result == "normal"


# -------------------------------------------------------------------
# add_marker_to_body
# -------------------------------------------------------------------

def test_add_marker_to_body_converts_bar_to_body(svc):
    bid = svc.create_bar("B", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    new_mid = svc.add_marker_to_body_at(bid, "50 mm", "60 mm", "C")
    body = svc.get_body(bid)
    assert body.type is BodyType.BODY
    structural_ids = [m.id for m in body.structural_markers()]
    assert new_mid in structural_ids


# -------------------------------------------------------------------
# move_marker
# -------------------------------------------------------------------

def test_move_marker_updates_position(svc):
    bid = svc.create_punctual_mass("PM", "0 mm", "0 mm")
    body = svc.get_body(bid)
    marker = body.structural_markers()[0]
    svc.move_marker(marker.id, "50 mm", "25 mm")
    assert marker.x.expression == "50 mm"
    assert marker.y.expression == "25 mm"


def test_move_marker_syncs_point_mass_com(svc):
    bid = svc.create_punctual_mass("PM", "0 mm", "0 mm")
    body = svc.get_body(bid)
    marker = body.structural_markers()[0]
    svc.move_marker(marker.id, "40 mm", "10 mm")
    com = body.com_marker()
    # CoM of a point mass must track the structural marker
    assert com.x.expression == marker.x.expression
    assert com.y.expression == marker.y.expression


# -------------------------------------------------------------------
# COM marker auto-recompute after bar edit
# -------------------------------------------------------------------

def test_bar_com_recomputed_after_marker_move(svc):
    bid = svc.create_bar("B", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = svc.get_body(bid)
    # Move second endpoint to (200, 0)
    ep_b = body.structural_markers()[1]
    svc.move_marker(ep_b.id, "200 mm", "0 mm")
    com = body.com_marker()
    # position_percent=50 → com x should be near 100 mm
    project = svc.project
    cx = svc.expression_service.evaluate_property(com.x, project.parameters).value
    assert cx == pytest.approx(100.0, abs=1e-4)
