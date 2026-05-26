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
    from quino.domain.workspace import Analysis, Run
    ws, parent = _ws_with_root_case()
    parent.analyses.append(Analysis(id="a1", name="A", analysis_type="static"))
    parent.runs.append(Run(id="r1", analysis_id="a1", created_at="2026-05-26T00:00:00", status="ok"))
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]
    assert child.analyses == []
    assert child.runs == []


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


def test_edit_property_records_warning_when_descendant_has_override():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    # Step 1: child overrides mass to 3 kg (this unlinks)
    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))
    assert "mass" not in child.overlay.entities["b1"].linked_properties

    # Step 2: parent changes mass to 5 kg → child must NOT change, must record warning
    engine.edit_property(parent.id, "b1", "mass", ScalarProperty("5 kg", "kg", Dimension.MASS))

    assert child.model.bodies[0].mass.expression == "3 kg"
    warnings = child.metadata.get("divergence_warnings", [])
    assert any(w["path"].endswith("/mass") for w in warnings)


def test_edit_property_in_owner_unlinks_from_parent():
    ws, parent = _ws_with_root_case()
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(parent.id, "Child")
    child = ws.cases[child_id]

    engine.edit_property(child_id, "b1", "mass", ScalarProperty("9 kg", "kg", Dimension.MASS))
    assert "mass" not in child.overlay.entities["b1"].linked_properties
    assert child.model.bodies[0].mass.expression == "9 kg"
