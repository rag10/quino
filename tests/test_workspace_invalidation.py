"""Tests for quino.services.workspace_invalidation (case-as-model API).

Run state is flattened onto each Analysis (no separate Run entity / case.runs),
so invalidation flips ``analysis.status`` directly.
"""
from __future__ import annotations

from quino.domain.workspace import Analysis, Case, Workspace
from quino.services.workspace_invalidation import (
    invalidate_on_analysis_change,
    invalidate_on_case_change,
    invalidate_on_model_change,
    invalidate_on_pose_change,
)


def _make_workspace(cases: dict[str, Case] | None = None) -> Workspace:
    ws = Workspace(id="ws1", name="Test", schema_version="0.4.0")
    if cases:
        ws.cases = cases
        ws.root_case_ids = [cid for cid, c in cases.items() if c.parent_case_id is None]
    return ws


def _make_case(case_id: str, parent_id: str | None = None) -> Case:
    return Case(id=case_id, name=case_id, parent_case_id=parent_id)


def _analysis(aid: str, status: str = "ok", pose_id: str | None = None) -> Analysis:
    return Analysis(id=aid, name=aid, analysis_type="dynamic", pose_id=pose_id, status=status)


# --- invalidate_on_model_change -------------------------------------------

def test_invalidate_on_model_change_stales_case_analyses() -> None:
    c1 = _make_case("c1")
    c1.analyses = [
        _analysis("a_ok", "ok"),
        _analysis("a_partial", "partial"),
        _analysis("a_running", "running"),
        _analysis("a_failed", "failed"),
    ]
    ws = _make_workspace({"c1": c1})

    invalidate_on_model_change(ws, "c1")

    by_id = {a.id: a for a in c1.analyses}
    assert by_id["a_ok"].status == "stale"
    assert by_id["a_partial"].status == "stale"
    assert by_id["a_running"].status == "running"   # never staled
    assert by_id["a_failed"].status == "failed"


def test_invalidate_on_model_change_propagates_to_children() -> None:
    c1 = _make_case("c1")
    c2 = _make_case("c2", parent_id="c1")
    c2.analyses = [_analysis("a2", "ok")]
    ws = _make_workspace({"c1": c1, "c2": c2})

    invalidate_on_model_change(ws, "c1")

    assert c2.analyses[0].status == "stale"


# --- invalidate_on_case_change --------------------------------------------

def test_invalidate_on_case_change_propagates_down() -> None:
    c1 = _make_case("c1")
    c2 = _make_case("c2", parent_id="c1")
    c2.analyses = [_analysis("a2", "ok")]
    ws = _make_workspace({"c1": c1, "c2": c2})

    invalidate_on_case_change(ws, "c1")

    assert c2.analyses[0].status == "stale"


# --- invalidate_on_analysis_change ----------------------------------------

def test_invalidate_on_analysis_change_only_targets_matching_analysis() -> None:
    c1 = _make_case("c1")
    c1.analyses = [_analysis("a1", "ok"), _analysis("a2", "ok")]
    ws = _make_workspace({"c1": c1})

    invalidate_on_analysis_change(ws, "a1")

    by_id = {a.id: a for a in c1.analyses}
    assert by_id["a1"].status == "stale"
    assert "analysis_changed:a1" in by_id["a1"].warnings
    assert by_id["a2"].status == "ok"   # different analysis untouched


# --- invalidate_on_pose_change --------------------------------------------

def test_invalidate_on_pose_change_marks_analyses_of_pose() -> None:
    c1 = _make_case("c1")
    c1.analyses = [_analysis("a1", "ok", pose_id="pose_X"),
                   _analysis("a2", "ok", pose_id="pose_Y")]
    ws = _make_workspace({"c1": c1})

    invalidate_on_pose_change(ws, "pose_X")

    by_id = {a.id: a for a in c1.analyses}
    assert by_id["a1"].status == "stale"
    assert by_id["a2"].status == "ok"


def test_running_analyses_are_never_marked_stale() -> None:
    c1 = _make_case("c1")
    c1.analyses = [_analysis("a1", "running", pose_id="pose_X")]
    ws = _make_workspace({"c1": c1})

    invalidate_on_model_change(ws, "c1")
    invalidate_on_case_change(ws, "c1")
    invalidate_on_analysis_change(ws, "a1")
    invalidate_on_pose_change(ws, "pose_X")

    assert c1.analyses[0].status == "running"
