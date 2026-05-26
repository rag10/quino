"""Tests for quino.services.workspace_invalidation (new case-as-model API)."""
from __future__ import annotations

from quino.domain.workspace import Analysis, Case, Run, Workspace
from quino.services.workspace_invalidation import (
    invalidate_on_analysis_change,
    invalidate_on_case_change,
    invalidate_on_model_change,
    invalidate_on_pose_change,
)


def _make_workspace(cases: dict[str, Case] | None = None) -> Workspace:
    ws = Workspace(id="ws1", name="Test", schema_version="0.3.0")
    if cases:
        ws.cases = cases
        ws.root_case_ids = list(cases.keys())
    return ws


def _make_case(case_id: str, parent_id: str | None = None) -> Case:
    return Case(id=case_id, name=case_id, parent_case_id=parent_id)


def _make_analysis(aid: str, pose_id: str | None = None) -> Analysis:
    return Analysis(id=aid, name=aid, analysis_type="dynamic", pose_id=pose_id)


def _make_run(rid: str, analysis_id: str, status: str = "ok") -> Run:
    return Run(id=rid, analysis_id=analysis_id, created_at="2026-05-19T10:00:00Z",
               status=status)


# ---------------------------------------------------------------------------
# invalidate_on_model_change
# ---------------------------------------------------------------------------

def test_invalidate_on_model_change_stales_root_case_runs() -> None:
    c1 = _make_case("c1")
    a1 = _make_analysis("a1")
    c1.analyses = [a1]
    r_ok = _make_run("r1", "a1", "ok")
    r_partial = _make_run("r2", "a1", "partial")
    r_running = _make_run("r3", "a1", "running")
    r_failed = _make_run("r4", "a1", "failed")
    c1.runs = [r_ok, r_partial, r_running, r_failed]
    ws = _make_workspace({"c1": c1})

    invalidate_on_model_change(ws, "c1")

    assert r_ok.status == "stale"
    assert r_partial.status == "stale"
    assert r_running.status == "running"   # never staled
    assert r_failed.status == "failed"


def test_invalidate_on_model_change_propagates_to_children() -> None:
    """Children (descendants) of the affected case are also staled."""
    c1 = _make_case("c1")
    c2 = _make_case("c2", parent_id="c1")
    a2 = _make_analysis("a2")
    c2.analyses = [a2]
    r2 = _make_run("r2", "a2", "ok")
    c2.runs = [r2]
    ws = _make_workspace({"c1": c1, "c2": c2})

    invalidate_on_model_change(ws, "c1")

    assert r2.status == "stale"


# ---------------------------------------------------------------------------
# invalidate_on_case_change
# ---------------------------------------------------------------------------

def test_invalidate_on_case_change_propagates_down() -> None:
    c1 = _make_case("c1")
    c2 = _make_case("c2", parent_id="c1")
    a2 = _make_analysis("a2")
    c2.analyses = [a2]
    r2 = _make_run("r2", "a2", "ok")
    c2.runs = [r2]
    ws = _make_workspace({"c1": c1, "c2": c2})

    invalidate_on_case_change(ws, "c1")

    assert r2.status == "stale"


# ---------------------------------------------------------------------------
# invalidate_on_analysis_change
# ---------------------------------------------------------------------------

def test_invalidate_on_analysis_change_only_targets_matching_runs() -> None:
    c1 = _make_case("c1")
    a1 = _make_analysis("a1")
    a2 = _make_analysis("a2")
    c1.analyses = [a1, a2]
    r1 = _make_run("r1", "a1", "ok")
    r2 = _make_run("r2", "a2", "ok")
    r3 = _make_run("r3", "a1", "running")
    c1.runs = [r1, r2, r3]
    ws = _make_workspace({"c1": c1})

    invalidate_on_analysis_change(ws, "a1")

    assert r1.status == "stale"
    assert f"analysis_changed:a1" in r1.warnings
    assert r2.status == "ok"    # different analysis
    assert r3.status == "running"  # running is not staled


# ---------------------------------------------------------------------------
# invalidate_on_pose_change
# ---------------------------------------------------------------------------

def test_invalidate_on_pose_change_marks_runs_of_pose_analyses() -> None:
    c1 = _make_case("c1")
    a1 = _make_analysis("a1", pose_id="pose_X")
    a2 = _make_analysis("a2", pose_id="pose_Y")
    c1.analyses = [a1, a2]
    r1 = _make_run("r1", "a1", "ok")
    r2 = _make_run("r2", "a2", "ok")
    c1.runs = [r1, r2]
    ws = _make_workspace({"c1": c1})

    invalidate_on_pose_change(ws, "pose_X")

    assert r1.status == "stale"
    assert r2.status == "ok"


def test_running_runs_are_never_marked_stale() -> None:
    """Running-status runs must stay running across all invalidation reasons."""
    c1 = _make_case("c1")
    a1 = _make_analysis("a1", pose_id="pose_X")
    c1.analyses = [a1]
    r1 = _make_run("r1", "a1", "running")
    c1.runs = [r1]
    ws = _make_workspace({"c1": c1})

    invalidate_on_model_change(ws, "c1")
    assert r1.status == "running"

    invalidate_on_case_change(ws, "c1")
    assert r1.status == "running"

    invalidate_on_analysis_change(ws, "a1")
    assert r1.status == "running"

    invalidate_on_pose_change(ws, "pose_X")
    assert r1.status == "running"
