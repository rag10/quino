"""Tests for the case_diff service — short, human-readable diffs."""
from __future__ import annotations

import copy

from quino.domain.model import (
    Body,
    Driver,
    JointEndpoint,
    Marker,
    Model,
    ScalarProperty,
)
from quino.domain.types import (
    BodyType,
    Dimension,
    DriverType,
    JointEndpointKind,
    JointType,
    MarkerType,
)
from quino.domain.model import Joint
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine
from quino.services.case_diff import (
    DiffEntry,
    diff_case_against,
    format_value,
    label_for,
)


def _scalar(expr: str, unit: str, dim: Dimension) -> ScalarProperty:
    return ScalarProperty(expr, unit, dim)


def _marker(id_: str) -> Marker:
    return Marker(
        id=id_, name=id_, type=MarkerType.STRUCTURAL,
        x=_scalar("0 mm", "mm", Dimension.LENGTH),
        y=_scalar("0 mm", "mm", Dimension.LENGTH),
    )


def _body(id_: str = "b1", name: str = "bar", mass: str = "2 kg") -> Body:
    return Body(
        id=id_, name=name, type=BodyType.BAR,
        markers=[_marker("m1"), _marker("m2")],
        edge_order=["m1", "m2"], closed_shape=False,
        mass=_scalar(mass, "kg", Dimension.MASS),
    )


def _ws() -> tuple[Workspace, Case]:
    root = Case(id="P", name="Root", model=Model(bodies=[_body()]))
    ws = Workspace(id="w", name="w", schema_version="0.3.0",
                   root_case_ids=["P"], cases={"P": root})
    return ws, root


# ---------------------------------------------------------------------------
# format_value
# ---------------------------------------------------------------------------

def test_format_value_scalar_property_uses_expression():
    sp = _scalar("2 kg", "kg", Dimension.MASS)
    assert format_value(sp) == "2 kg"


def test_format_value_none_returns_unset():
    assert format_value(None) == "(unset)"


def test_format_value_bool_yes_no():
    assert format_value(True) == "yes"
    assert format_value(False) == "no"


def test_format_value_enum_uses_lowercase_name():
    assert format_value(JointType.REVOLUTE) == "revolute"
    assert format_value(BodyType.BAR) == "bar"


def test_format_value_float_4_sig_figs():
    assert format_value(0.123456) == "0.1235"


def test_format_value_long_string_truncated():
    s = "x" * 60
    assert format_value(s).endswith("…")
    assert len(format_value(s)) <= 40


def test_format_value_resolves_name_lookup():
    assert format_value("m1", name_lookup={"m1": "knee"}) == "knee"


def test_format_value_list_truncates_after_four():
    assert format_value([1, 2, 3, 4, 5, 6]) == "[1, 2, 3, 4, … (+2)]"


# ---------------------------------------------------------------------------
# label_for
# ---------------------------------------------------------------------------

def test_label_for_known_field():
    assert label_for(Body, "mass") == "Mass"


def test_label_for_metadata_value_uses_table():
    assert label_for(Joint, "metadata.values.friction_coulomb") == "Friction (Coulomb)"


def test_label_for_unknown_falls_back_to_humanised():
    assert label_for(Body, "weird_internal_thing") == "Weird internal thing"


# ---------------------------------------------------------------------------
# diff_case_against — basic equality
# ---------------------------------------------------------------------------

def test_identical_cases_produce_no_diffs():
    ws, root = _ws()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    assert diff_case_against(root, ws.cases[child_id]) == []


def test_changed_mass_emits_one_entry():
    ws, root = _ws()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    child = ws.cases[child_id]
    child.model.bodies[0].mass = _scalar("3 kg", "kg", Dimension.MASS)

    diffs = diff_case_against(root, child)
    assert len(diffs) == 1
    d = diffs[0]
    assert d.kind == "changed"
    assert d.entity_kind == "Body"
    assert d.entity_label == "bar"
    assert d.property_label == "Mass"
    assert d.parent_text == "2 kg"
    assert d.child_text == "3 kg"
    # No raw dataclass dump leaks into the text.
    assert "ScalarProperty" not in d.parent_text + d.child_text


def test_added_entity_emits_added_entry():
    ws, root = _ws()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    child = ws.cases[child_id]
    new_body = _body(id_="b2", name="link", mass="1 kg")
    child.model.bodies.append(new_body)
    if child.overlay is not None:
        from quino.domain.workspace import EntityOverlay
        child.overlay.entities["b2"] = EntityOverlay(origin="local")
        child.overlay.entities["m1"]  # touch nothing — no-op

    diffs = [d for d in diff_case_against(root, child) if d.entity_id == "b2"]
    # The new body and its two structural markers all count as "added" in child.
    kinds = {d.kind for d in diffs}
    assert kinds == {"added"}


def test_removed_entity_emits_removed_entry():
    ws, root = _ws()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    child = ws.cases[child_id]
    child.model.bodies = []

    diffs = diff_case_against(root, child)
    removed = [d for d in diffs if d.kind == "removed"]
    # The body and its two structural markers all show up as removed.
    assert {d.entity_id for d in removed} == {"b1", "m1", "m2"}
    for d in removed:
        assert d.parent_text == "—"
        assert d.child_text == "—"
        assert d.property_label is None


# ---------------------------------------------------------------------------
# Composite paths
# ---------------------------------------------------------------------------

def _ws_with_joint() -> tuple[Workspace, Case]:
    body = _body("ground", name="ground")
    body2 = _body("thigh", name="thigh")
    joint = Joint(
        id="j1", name="knee", type=JointType.REVOLUTE,
        endpoint_a=JointEndpoint(kind=JointEndpointKind.MARKER, body_id="ground", marker_id="m1"),
        endpoint_b=JointEndpoint(kind=JointEndpointKind.MARKER, body_id="thigh", marker_id="m1"),
    )
    # Marker ids collide; rename body2's markers so the model is consistent.
    body2.markers[0].id = "m3"
    body2.markers[1].id = "m4"
    body2.edge_order = ["m3", "m4"]
    joint.endpoint_b.marker_id = "m3"
    root = Case(id="P", name="Root", model=Model(bodies=[body, body2], joints=[joint]))
    ws = Workspace(id="w", name="w", schema_version="0.3.0",
                   root_case_ids=["P"], cases={"P": root})
    return ws, root


def test_metadata_value_change_descomposed():
    ws, root = _ws_with_joint()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    child = ws.cases[child_id]
    child.model.joints[0].metadata.values["friction_coulomb"] = 0.30

    diffs = [d for d in diff_case_against(root, child) if d.entity_id == "j1"]
    assert len(diffs) == 1
    d = diffs[0]
    assert d.property_label == "Friction (Coulomb)"
    assert d.property_path == "metadata.values.friction_coulomb"
    assert d.parent_text == "(unset)"
    assert d.child_text == "0.3"


def test_endpoint_change_resolves_body_name():
    ws, root = _ws_with_joint()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    child = ws.cases[child_id]
    # Swap endpoint A from ground to thigh.
    child.model.joints[0].endpoint_a.body_id = "thigh"
    child.model.joints[0].endpoint_a.marker_id = "m3"

    diffs = [d for d in diff_case_against(root, child) if d.entity_id == "j1"]
    by_label = {d.property_label: d for d in diffs}
    assert "Endpoint A — body" in by_label
    body_diff = by_label["Endpoint A — body"]
    # body_id values are resolved against the name lookup.
    assert body_diff.parent_text == "ground"
    assert body_diff.child_text == "thigh"


# ---------------------------------------------------------------------------
# Visual filtering
# ---------------------------------------------------------------------------

def test_visual_changes_excluded_by_default():
    ws, root = _ws()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    child = ws.cases[child_id]
    child.model.bodies[0].style.color = "#ff0000"
    child.model.bodies[0].name = "renamed"  # 'name' is VISUAL too

    assert diff_case_against(root, child) == []


def test_visual_changes_included_when_requested():
    ws, root = _ws()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    child = ws.cases[child_id]
    child.model.bodies[0].style.color = "#ff0000"

    diffs = diff_case_against(root, child, include_visual=True)
    assert any(d.property_label == "Style — Color" for d in diffs)


def test_diff_entry_carries_round_trip_metadata():
    ws, root = _ws()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root.id, "Child")
    child = ws.cases[child_id]
    child.model.bodies[0].mass = _scalar("3 kg", "kg", Dimension.MASS)

    d: DiffEntry = diff_case_against(root, child)[0]
    assert d.entity_id == "b1"
    assert d.property_path == "mass"
