# tests/test_case_cascading.py
import copy

import pytest

from quino.domain.model import Body, Marker, Model, ScalarProperty
from quino.domain.types import BodyType, Dimension, MarkerType
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine
from quino.services.case_overlay_validator import validate_overlay
from quino.services.cascade_property_registry import cascadable_properties


def _make_marker(id_: str) -> Marker:
    return Marker(
        id=id_, name=id_, type=MarkerType.STRUCTURAL,
        x=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
        y=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
    )


def _make_body(id_: str = "b1") -> Body:
    return Body(
        id=id_, name="bar", type=BodyType.BAR,
        markers=[_make_marker("m1"), _make_marker("m2")],
        edge_order=["m1", "m2"], closed_shape=False,
        mass=ScalarProperty("2 kg", "kg", Dimension.MASS),
    )


def _ws_with_root_case() -> tuple[Workspace, Case]:
    root = Case(id="P", name="Root", model=Model(bodies=[_make_body()]))
    ws = Workspace(id="w", name="w", schema_version="0.3.0",
                   root_case_ids=["P"], cases={"P": root})
    return ws, root


def test_fork_case_creates_child_identical_to_parent():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    assert child_id in ws.cases
    child = ws.cases[child_id]
    assert child.parent_case_id == parent.id
    assert child.model.bodies[0].mass.expression == parent.model.bodies[0].mass.expression
    # Distinct identity (deep copy)
    assert child.model.bodies[0] is not parent.model.bodies[0]
    validate_overlay(child, parent=parent)


def test_fork_case_initializes_all_entities_as_inherited_fully_linked():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    body_overlay = child.overlay.entities["b1"]
    assert body_overlay.origin == "inherited"
    assert body_overlay.linked_properties == set(cascadable_properties(Body))
    marker_overlay = child.overlay.entities["m1"]
    assert marker_overlay.origin == "inherited"


def test_fork_case_does_not_copy_runs_or_analyses():
    from quino.domain.workspace import Analysis, Pose, Run
    ws, parent = _ws_with_root_case()
    parent.poses.append(Pose(id="p-user", name="Pose"))
    parent.analyses.append(Analysis(id="a1", name="A", analysis_type="static"))
    parent.runs.append(Run(id="r1", analysis_id="a1", created_at="2026-05-26T00:00:00", status="ok"))
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    assert len(child.poses) == 1
    assert child.poses[0].is_default is True
    assert child.poses[0].id != "p-user"
    assert child.analyses == []
    assert child.runs == []


def test_duplicate_case_copies_local_package_without_runs_and_remaps_ids():
    from quino.domain.workspace import Analysis, Pose, Run
    ws, parent = _ws_with_root_case()
    parent.poses = [
        Pose(id="p-default", name="Reference", is_default=True),
        Pose(id="p-user", name="Pose"),
    ]
    parent.analyses.append(Analysis(id="a1", name="A", analysis_type="static", pose_id="p-user"))
    parent.runs.append(Run(id="r1", analysis_id="a1", created_at="2026-05-26T00:00:00", status="ok"))

    engine = CascadingEngine(ws)
    duplicate_id = engine.duplicate_case(parent.id, "Root copy")
    duplicate = ws.cases[duplicate_id]

    assert duplicate.parent_case_id == parent.parent_case_id
    assert duplicate.model is not parent.model
    assert duplicate.model.bodies[0] is not parent.model.bodies[0]
    assert {pose.id for pose in duplicate.poses}.isdisjoint({pose.id for pose in parent.poses})
    assert duplicate.analyses[0].id != parent.analyses[0].id
    assert duplicate.analyses[0].pose_id in {pose.id for pose in duplicate.poses}
    assert duplicate.runs == []


def test_fork_case_copies_tolerances_and_metrics():
    from quino.domain.workspace import MetricDefinition, Tolerance
    ws, parent = _ws_with_root_case()
    parent.tolerances["rms"] = Tolerance(metric_key="rms", absolute=1e-3)
    parent.metrics["peak"] = MetricDefinition(key="peak", name="Peak", extractor="max_abs")
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    assert "rms" in child.tolerances
    assert "peak" in child.metrics
    # Independent copies
    assert child.tolerances["rms"] is not parent.tolerances["rms"]


def test_fork_case_rejects_unknown_parent():
    ws, _ = _ws_with_root_case()
    engine = CascadingEngine(ws)
    with pytest.raises(KeyError):
        engine.fork_case("nope", "Child")


def test_edit_property_updates_local_and_unlinks_in_owner():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    new_mass = ScalarProperty("5 kg", "kg", Dimension.MASS)
    engine.edit_property(parent.id, "b1", "mass", new_mass)
    assert parent.model.bodies[0].mass.expression == "5 kg"
    # Parent is a root case → overlay is None, no unlinking needed
    assert parent.overlay is None


def test_edit_property_propagates_to_linked_descendant():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    new_mass = ScalarProperty("5 kg", "kg", Dimension.MASS)
    engine.edit_property(parent.id, "b1", "mass", new_mass)

    assert child.model.bodies[0].mass.expression == "5 kg"
    # Still linked
    assert "mass" in child.overlay.entities["b1"].linked_properties


def test_edit_property_returns_conflict_when_descendant_has_override():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    # Step 1: child overrides mass to 3 kg (this unlinks)
    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))
    assert "mass" not in child.overlay.entities["b1"].linked_properties

    # Step 2: parent changes mass to 5 kg -> child must NOT change; conflict is returned, not persisted
    result = engine.edit_property(parent.id, "b1", "mass", ScalarProperty("5 kg", "kg", Dimension.MASS))

    assert child.model.bodies[0].mass.expression == "3 kg"
    assert child.metadata.get("divergence_warnings") is None
    assert any(conflict.case_id == child_id and conflict.path.endswith("/mass") for conflict in result.conflicts)


def test_edit_property_eliminate_diff_relinks_and_applies_parent_change():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))
    result = engine.edit_property(
        parent.id,
        "b1",
        "mass",
        ScalarProperty("5 kg", "kg", Dimension.MASS),
        conflict_resolution={f"{child_id}:entities/b1/mass": "eliminate_diff"},
    )

    assert child.model.bodies[0].mass.expression == "5 kg"
    assert "mass" in child.overlay.entities["b1"].linked_properties
    assert any(conflict.case_id == child_id for conflict in result.conflicts)


def test_edit_property_cancel_leaves_workspace_unchanged():
    ws, parent = _ws_with_root_case()
    before = copy.deepcopy(ws)
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))
    before_conflict = copy.deepcopy(ws)

    with pytest.raises(Exception):
        engine.edit_property(
            parent.id,
            "b1",
            "mass",
            ScalarProperty("5 kg", "kg", Dimension.MASS),
            conflict_resolution={f"{child_id}:entities/b1/mass": "cancel"},
        )

    assert ws == before_conflict
    assert ws != before


def test_edit_property_in_owner_unlinks_from_parent():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    engine.edit_property(child_id, "b1", "mass", ScalarProperty("9 kg", "kg", Dimension.MASS))
    assert "mass" not in child.overlay.entities["b1"].linked_properties
    assert child.model.bodies[0].mass.expression == "9 kg"


# ---------------------------------------------------------------------------
# Task 10: add_entity
# ---------------------------------------------------------------------------

def test_add_entity_in_case_marks_origin_local():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    new_body = _make_body("b2")
    new_body.markers[0].id = "n1"
    new_body.markers[1].id = "n2"
    new_body.edge_order = ["n1", "n2"]
    engine.add_entity(parent.id, new_body, domain="bodies")

    assert any(b.id == "b2" for b in parent.model.bodies)
    # Root case has no overlay
    assert parent.overlay is None


def test_add_entity_in_child_marks_local_and_propagates_to_grandchild():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    grand_id = engine.fork_case(child_id, "Grand")
    child = ws.cases[child_id]
    grand = ws.cases[grand_id]

    new_body = _make_body("b9")
    new_body.markers[0].id = "x1"
    new_body.markers[1].id = "x2"
    new_body.edge_order = ["x1", "x2"]
    engine.add_entity(child_id, new_body, domain="bodies")

    assert any(b.id == "b9" for b in child.model.bodies)
    assert child.overlay.entities["b9"].origin == "local"
    assert any(b.id == "b9" for b in grand.model.bodies)
    assert grand.overlay.entities["b9"].origin == "inherited"


# ---------------------------------------------------------------------------
# Task 11: remove_entity
# ---------------------------------------------------------------------------

def test_remove_local_entity_clears_overlay_entry():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    new_body = _make_body("b9")
    new_body.markers[0].id = "x1"
    new_body.markers[1].id = "x2"
    new_body.edge_order = ["x1", "x2"]
    engine.add_entity(child_id, new_body, domain="bodies")
    assert "b9" in child.overlay.entities

    engine.remove_entity(child_id, "b9")
    assert all(b.id != "b9" for b in child.model.bodies)
    assert "b9" not in child.overlay.entities


def test_remove_inherited_entity_records_deletion():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    engine.remove_entity(child_id, "b1")
    assert all(b.id != "b1" for b in child.model.bodies)
    assert "b1" in child.overlay.deleted_inherited_entity_ids


def test_remove_propagates_to_clean_descendant():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    engine.remove_entity(parent.id, "b1")
    assert all(b.id != "b1" for b in child.model.bodies)


def test_remove_in_parent_keeps_customised_descendant_with_conflict():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    # Child customises mass first
    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))

    # Parent removes b1 -> child must keep it, mark origin=local, return conflict
    result = engine.remove_entity(parent.id, "b1")
    assert any(b.id == "b1" for b in child.model.bodies)
    assert child.overlay.entities["b1"].origin == "local"
    assert child.overlay.entities["b1"].linked_properties == set()
    assert child.metadata.get("divergence_warnings") is None
    assert any(conflict.case_id == child_id and "removal" in conflict.reason for conflict in result.conflicts)


# ---------------------------------------------------------------------------
# Task 12: reparent_case
# ---------------------------------------------------------------------------

def test_reparent_case_to_none_drops_overlay():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    engine.reparent_case(child_id, new_parent_case_id=None)
    assert ws.cases[child_id].parent_case_id is None
    assert ws.cases[child_id].overlay is None
    assert child_id in ws.root_case_ids


def test_reparent_case_rejects_cycle():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    c1 = engine.fork_case(parent.id, "C1")
    c2 = engine.fork_case(c1, "C2")
    # Reparenting parent under c2 would create a cycle
    with pytest.raises(ValueError):
        engine.reparent_case(parent.id, new_parent_case_id=c2)


def test_reparent_case_marks_runs_stale():
    from quino.domain.workspace import Analysis, Run

    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    c1 = engine.fork_case(parent.id, "C1")
    c2 = engine.fork_case(parent.id, "C2")
    grandchild = engine.fork_case(c1, "GC")

    # Seed each fork-affected case with one ok run.
    for case_id in (c1, grandchild):
        case = ws.cases[case_id]
        analysis = Analysis(id=f"a-{case_id}", name="dyn", analysis_type="dynamic")
        case.analyses.append(analysis)
        case.runs.append(
            Run(id=f"r-{case_id}", analysis_id=analysis.id, created_at="2026-01-01T00:00:00Z",
                status="ok")
        )

    # Sibling c2 should not be affected.
    case_c2 = ws.cases[c2]
    analysis_c2 = Analysis(id="a-c2", name="dyn", analysis_type="dynamic")
    case_c2.analyses.append(analysis_c2)
    case_c2.runs.append(
        Run(id="r-c2", analysis_id=analysis_c2.id, created_at="2026-01-01T00:00:00Z", status="ok")
    )

    result = engine.reparent_case(c1, new_parent_case_id=None)
    assert c1 in result.stale_case_ids
    assert grandchild in result.stale_case_ids
    assert ws.cases[c1].runs[0].status == "stale"
    assert ws.cases[grandchild].runs[0].status == "stale"
    # Sibling untouched.
    assert ws.cases[c2].runs[0].status == "ok"


# ---------------------------------------------------------------------------
# Task 13: end-to-end engine validation
# ---------------------------------------------------------------------------

def test_engine_operations_keep_overlay_valid():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    c1 = engine.fork_case(parent.id, "C1")
    c2 = engine.fork_case(c1, "C2")

    engine.edit_property(parent.id, "b1", "mass", ScalarProperty("4 kg", "kg", Dimension.MASS))
    engine.edit_property(c1, "b1", "name", "renamed bar")
    engine.remove_entity(c2, "m1")

    validate_overlay(ws.cases[c1], parent=ws.cases[parent.id])
    validate_overlay(ws.cases[c2], parent=ws.cases[c1])
