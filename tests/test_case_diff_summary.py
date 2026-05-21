from __future__ import annotations

import pytest

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.workspace import ScalarValue
from quino.services.case_diff_summary import build_case_diff_summary


@pytest.fixture
def chain():
    svc = ApplicationService()
    svc.new_project("diff")
    body_id = svc.create_bar(
        "Bar",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
    )
    parent = svc.workspace.create_case("Parent", baseline_id=svc.project.workspace.baselines[0].id)
    child = svc.workspace.create_case("Child", parent_case_id=parent.id)
    return svc, body_id, parent, child


def test_summary_marks_local_addition_in_child(chain):
    svc, _body, parent, child = chain
    svc.set_working_context(case_id=child.id)
    svc.add_block(block_type="Constant", name="C", position=(0.0, 0.0))

    summary = build_case_diff_summary(svc.project, child)
    block_adds = [a for a in summary.additions if a.domain == "blocks"]
    assert len(block_adds) == 1
    assert block_adds[0].is_local is True
    assert summary.local_count() == 1
    assert summary.inherited_count() == 0


def test_summary_marks_inherited_addition_from_parent(chain):
    svc, _body, parent, child = chain
    svc.set_working_context(case_id=parent.id)
    pblock = svc.add_block(block_type="Constant", name="P", position=(0.0, 0.0))

    summary = build_case_diff_summary(svc.project, child)
    block_adds = [a for a in summary.additions if a.domain == "blocks"]
    assert len(block_adds) == 1
    assert block_adds[0].entity_id == pblock
    assert block_adds[0].is_local is False
    assert block_adds[0].source_case_id == parent.id


def test_summary_detects_local_invariant_override_shadowing_parent(chain):
    svc, body_id, parent, child = chain
    svc.set_working_context(case_id=parent.id)
    parent.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=1.0, unit="kg")
    svc.set_working_context(case_id=child.id)
    child.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=3.0, unit="kg")

    summary = build_case_diff_summary(svc.project, child)
    overrides = [o for o in summary.invariant_overrides if o.path.endswith("/mass")]
    assert len(overrides) == 1
    assert overrides[0].is_local is True
    assert overrides[0].shadows_inherited is True
    assert overrides[0].value == 3.0


def test_summary_only_lists_inherited_when_child_does_not_override(chain):
    svc, body_id, parent, child = chain
    parent.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=1.0, unit="kg")

    summary = build_case_diff_summary(svc.project, child)
    overrides = [o for o in summary.invariant_overrides if o.path.endswith("/mass")]
    assert len(overrides) == 1
    assert overrides[0].is_local is False
    assert overrides[0].shadows_inherited is False
    assert overrides[0].source_case_id == parent.id


def test_summary_removed_connection_local_vs_inherited(chain):
    svc, _body, parent, child = chain
    parent.removed_connections.append(("a", "out", "b", "in"))
    child.removed_connections.append(("c", "out", "d", "in"))

    summary = build_case_diff_summary(svc.project, child)
    conn_removals = [r for r in summary.removals if r.kind == "connection"]
    by_local = {r.is_local: r.payload for r in conn_removals}
    assert by_local[True] == ("c", "out", "d", "in")
    assert by_local[False] == ("a", "out", "b", "in")


def test_reset_invariant_override_removes_local_only(chain):
    svc, body_id, parent, child = chain
    path = f"bodies/{body_id}/mass"
    parent.invariant_values[path] = ScalarValue(value=1.0, unit="kg")
    child.invariant_values[path] = ScalarValue(value=3.0, unit="kg")
    svc.set_working_context(case_id=child.id)

    removed = svc.reset_override(path=path)

    assert removed is True
    # Child no longer has the local override.
    child_live = next(c for c in svc.project.workspace.cases if c.id == child.id)
    assert path not in child_live.invariant_values
    # Parent still keeps its inherited override.
    parent_live = next(c for c in svc.project.workspace.cases if c.id == parent.id)
    assert path in parent_live.invariant_values
    # Composed view falls back to the parent value.
    composed_body = next(b for b in svc.display_project.model.bodies if b.id == body_id)
    assert "1" in (composed_body.mass.expression or "")


def test_reset_reference_override_removes_local_only(chain):
    svc, body_id, parent, child = chain
    parent.reference_overrides.setdefault(body_id, {})["color"] = "#ff0000"
    child.reference_overrides.setdefault(body_id, {})["color"] = "#0000ff"
    svc.set_working_context(case_id=child.id)

    removed = svc.reset_override(entity_id=body_id, prop="color")

    assert removed is True
    child_live = next(c for c in svc.project.workspace.cases if c.id == child.id)
    assert "color" not in child_live.reference_overrides.get(body_id, {})
    parent_live = next(c for c in svc.project.workspace.cases if c.id == parent.id)
    assert parent_live.reference_overrides[body_id]["color"] == "#ff0000"


def test_reset_override_noop_when_no_local_entry(chain):
    svc, body_id, parent, child = chain
    parent.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=1.0, unit="kg")
    svc.set_working_context(case_id=child.id)
    # Child has no local override; reset should return False.
    assert svc.reset_override(path=f"bodies/{body_id}/mass") is False


def test_summary_reference_override_shadowing(chain):
    svc, body_id, parent, child = chain
    parent.reference_overrides.setdefault(body_id, {})["color"] = "#ff0000"
    child.reference_overrides.setdefault(body_id, {})["color"] = "#0000ff"

    summary = build_case_diff_summary(svc.project, child)
    color_ov = [r for r in summary.reference_overrides if r.prop == "color"]
    assert len(color_ov) == 1
    assert color_ov[0].is_local is True
    assert color_ov[0].shadows_inherited is True
    assert color_ov[0].value == "#0000ff"
