"""Regression tests for JointCommands via ApplicationService public API."""
from __future__ import annotations

import pytest

from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput, SliderInput
from quino.domain.types import JointEndpointKind, JointType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def svc():
    s = ApplicationService()
    s.new_project("test")
    return s


@pytest.fixture()
def two_bar_svc(svc):
    """Service with two bars whose first markers can be jointed."""
    bid_a = svc.create_bar("BarA", MarkerInput("0 mm", "0 mm", "A1"), MarkerInput("100 mm", "0 mm", "A2"))
    bid_b = svc.create_bar("BarB", MarkerInput("100 mm", "0 mm", "B1"), MarkerInput("200 mm", "0 mm", "B2"))
    body_a = svc.get_body(bid_a)
    body_b = svc.get_body(bid_b)
    ma = body_a.structural_markers()[0]
    mb = body_b.structural_markers()[0]
    return svc, body_a, body_b, ma, mb


# ---------------------------------------------------------------------------
# create_joint — revolute between two body markers
# ---------------------------------------------------------------------------

def test_create_revolute_joint(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    joint = svc.get_joint(jid)
    assert joint is not None
    assert joint.type is JointType.REVOLUTE
    assert joint.endpoint_a.marker_id == ma.id
    assert joint.endpoint_b.marker_id == mb.id


def test_create_joint_duplicate_raises(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    ep_a = JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id)
    ep_b = JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id)
    svc.create_joint("J1", "revolute", ep_a, ep_b)
    with pytest.raises(ValueError, match="Duplicate"):
        svc.create_joint("J2", "revolute", ep_a, ep_b)


def test_create_joint_undo(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1", "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    svc.undo()
    assert svc.get_joint(jid) is None


# ---------------------------------------------------------------------------
# create_slider + slider joint
# ---------------------------------------------------------------------------

def test_create_slider(svc):
    sid = svc.create_slider("S1", SliderInput("50 mm", "0 mm", "0 deg", "-100 mm", "100 mm"))
    slider = svc.get_entity(sid)
    from quino.domain.model import Slider
    assert isinstance(slider, Slider)
    assert slider.name == "S1"


def test_create_slider_from_points(svc):
    sid = svc.create_slider_from_points("SFromPts", "0 mm", "0 mm", "100 mm", "0 mm")
    slider = svc.get_entity(sid)
    assert slider is not None
    # Origin should be at midpoint (50 mm, 0 mm)
    assert "50.000" in slider.origin_x.expression
    assert "0.000" in slider.origin_y.expression
    # Angle should be 0 deg (horizontal)
    assert "0.000000" in slider.angle.expression


def test_connect_marker_to_slider(svc):
    bid = svc.create_bar("Bar", MarkerInput("50 mm", "0 mm", "P"), MarkerInput("150 mm", "0 mm", "Q"))
    body = svc.get_body(bid)
    marker = body.structural_markers()[0]
    sid = svc.create_slider("Rail", SliderInput("50 mm", "0 mm", "0 deg", "-100 mm", "100 mm"))
    jid = svc.connect_marker_to_slider(marker.id, sid, joint_type="revolute", align="none")
    joint = svc.get_joint(jid)
    assert joint is not None
    assert joint.endpoint_b.slider_id == sid


# ---------------------------------------------------------------------------
# create_driver
# ---------------------------------------------------------------------------

def test_create_driver_on_revolute_joint(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1", "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    did = svc.create_driver("D1", "rotation", jid, "90 deg * t / 1 s", "deg")
    assert any(d.id == did for d in svc.project.model.drivers)


def test_create_driver_wrong_type_raises(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1", "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    with pytest.raises(ValueError, match="Translation drivers require a slider"):
        svc.create_driver("D1", "translation", jid, "10 mm * t / 1 s", "mm")


# ---------------------------------------------------------------------------
# set_joint_type
# ---------------------------------------------------------------------------

def test_set_joint_type_revolute_to_rigid(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1", "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    svc.set_joint_type(jid, "rigid")
    assert svc.get_joint(jid).type is JointType.RIGID


def test_set_joint_type_noop_when_same(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1", "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    undo_depth = len(svc._undo_stack)
    svc.set_joint_type(jid, "revolute")  # no-op
    assert len(svc._undo_stack) == undo_depth  # no snapshot taken


# ---------------------------------------------------------------------------
# connect_marker_to_ground
# ---------------------------------------------------------------------------

def test_connect_marker_to_ground(svc):
    bid = svc.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = svc.get_body(bid)
    marker = body.structural_markers()[0]
    jid = svc.connect_marker_to_ground(marker.id, joint_type="revolute")
    joint = svc.get_joint(jid)
    assert joint is not None
    assert joint.endpoint_b.kind is JointEndpointKind.GROUND
    assert joint.endpoint_a.marker_id == marker.id


# ---------------------------------------------------------------------------
# Joint friction accessors / update
# ---------------------------------------------------------------------------

def test_joint_friction_mode_revolute(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1", "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    joint = svc.get_joint(jid)
    assert svc.joint_friction_mode(joint) == "rotation"


def test_joint_friction_values_default(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1", "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    joint = svc.get_joint(jid)
    coulomb, viscous = svc.joint_friction_values(joint)
    assert coulomb == pytest.approx(0.0)
    assert viscous == pytest.approx(0.0)


def test_update_joint_friction_via_update_property(two_bar_svc):
    svc, body_a, body_b, ma, mb = two_bar_svc
    jid = svc.create_joint(
        "J1", "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_a.id, marker_id=ma.id),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_b.id, marker_id=mb.id),
    )
    svc.update_property(jid, "friction_coulomb", PropertyValueInput("expression", "0.3"))
    joint = svc.get_joint(jid)
    coulomb, _ = svc.joint_friction_values(joint)
    assert coulomb == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# update_slider_geometry
# ---------------------------------------------------------------------------

def test_update_slider_geometry_translates_linked_marker(svc):
    """Moving a slider origin should translate markers linked via joints."""
    bid = svc.create_bar("Bar", MarkerInput("50 mm", "0 mm", "P"), MarkerInput("150 mm", "0 mm", "Q"))
    body = svc.get_body(bid)
    marker = body.structural_markers()[0]
    sid = svc.create_slider("Rail", SliderInput("50 mm", "0 mm", "0 deg", "-100 mm", "100 mm"))
    svc.connect_marker_to_slider(marker.id, sid, joint_type="revolute", align="none")

    svc.update_slider_geometry(sid, origin_x="80 mm")
    slider = svc.get_entity(sid)
    assert "80" in slider.origin_x.expression


def test_update_slider_geometry_undo(svc):
    sid = svc.create_slider("Rail", SliderInput("50 mm", "0 mm", "0 deg", "-100 mm", "100 mm"))
    svc.update_slider_geometry(sid, origin_x="80 mm", origin_y="10 mm")
    svc.undo()
    slider = svc.get_entity(sid)
    assert "80" not in slider.origin_x.expression
    assert "10" not in slider.origin_y.expression
