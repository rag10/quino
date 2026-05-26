"""Tests for quino.services.workspace_staleness (new case-as-model API)."""
from __future__ import annotations

from quino.domain.workspace import Analysis, Case, Run, Workspace
from quino.services.workspace_staleness import mark_descendants_stale


def _make_workspace(cases_dict: dict[str, Case], root_ids: list[str] | None = None) -> Workspace:
    ws = Workspace(id="ws1", name="Test", schema_version="0.3.0")
    ws.cases = cases_dict
    ws.root_case_ids = root_ids or list(cases_dict.keys())
    return ws


def _run(rid: str, analysis_id: str, status: str = "ok") -> Run:
    return Run(id=rid, analysis_id=analysis_id, created_at="2026-05-19T10:00:00Z", status=status)


def _analysis(aid: str) -> Analysis:
    return Analysis(id=aid, name=aid, analysis_type="dynamic")


def test_mark_descendants_stale_single_child() -> None:
    """Root and its child case are both staled."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    a1 = _analysis("a1")
    a2 = _analysis("a2")
    c1.analyses = [a1]
    c2.analyses = [a2]
    r1 = _run("r1", "a1")
    r2 = _run("r2", "a2")
    c1.runs = [r1]
    c2.runs = [r2]
    ws = _make_workspace({"c1": c1, "c2": c2}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c1")

    assert r1.status == "stale"
    assert r2.status == "stale"
    assert count == 2
    assert "ancestor edited" in r1.warnings
    assert "ancestor edited" in r2.warnings


def test_mark_descendants_stale_nested_hierarchy() -> None:
    """Starting at c2 stales c2 and c3 but not c1 or c4."""
    c1 = Case(id="c1", name="Root")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    c3 = Case(id="c3", name="Grandchild", parent_case_id="c2")
    c4 = Case(id="c4", name="Unrelated")
    for c, aid in [(c1, "a1"), (c2, "a2"), (c3, "a3"), (c4, "a4")]:
        a = _analysis(aid)
        c.analyses = [a]
        c.runs = [_run(f"r_{aid}", aid)]
    ws = _make_workspace({"c1": c1, "c2": c2, "c3": c3, "c4": c4}, root_ids=["c1", "c4"])

    count = mark_descendants_stale(ws, "c2")

    assert c1.runs[0].status == "ok"     # parent not affected
    assert c2.runs[0].status == "stale"  # root of subtree
    assert c3.runs[0].status == "stale"  # descendant
    assert c4.runs[0].status == "ok"     # unrelated
    assert count == 2


def test_mark_descendants_stale_sibling_unaffected() -> None:
    """Sibling cases are not affected."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child1", parent_case_id="c1")
    c3 = Case(id="c3", name="Child2", parent_case_id="c1")
    a2, a3 = _analysis("a2"), _analysis("a3")
    c2.analyses = [a2]
    c3.analyses = [a3]
    r2 = _run("r2", "a2")
    r3 = _run("r3", "a3")
    c2.runs = [r2]
    c3.runs = [r3]
    ws = _make_workspace({"c1": c1, "c2": c2, "c3": c3}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c2")

    assert r2.status == "stale"
    assert r3.status == "ok"
    assert count == 1


def test_mark_descendants_stale_respects_running() -> None:
    """Running runs are never marked stale."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    a1, a2 = _analysis("a1"), _analysis("a2")
    c1.analyses = [a1]
    c2.analyses = [a2]
    r1 = _run("r1", "a1", "ok")
    r2 = _run("r2", "a2", "running")
    c1.runs = [r1]
    c2.runs = [r2]
    ws = _make_workspace({"c1": c1, "c2": c2}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c1")

    assert r1.status == "stale"
    assert r2.status == "running"
    assert count == 1


def test_mark_descendants_stale_multiple_runs() -> None:
    """Multiple runs per analysis — all ok/partial staled, running skipped."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    a2 = _analysis("a2")
    c2.analyses = [a2]
    r1 = _run("r1", "a2", "ok")
    r2 = _run("r2", "a2", "ok")
    r3 = _run("r3", "a2", "running")
    c2.runs = [r1, r2, r3]
    ws = _make_workspace({"c1": c1, "c2": c2}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c1")

    assert r1.status == "stale"
    assert r2.status == "stale"
    assert r3.status == "running"
    assert count == 2


def test_mark_descendants_stale_empty_workspace() -> None:
    """Empty workspace — no crash, returns 0."""
    ws = _make_workspace({}, root_ids=[])

    count = mark_descendants_stale(ws, "c1")

    assert count == 0


def test_mark_descendants_stale_already_stale() -> None:
    """Already-stale runs do not get the warning duplicated."""
    c1 = Case(id="c1", name="Parent")
    a1 = _analysis("a1")
    c1.analyses = [a1]
    r1 = _run("r1", "a1", "stale")
    r1.warnings = ["ancestor edited"]
    c1.runs = [r1]
    ws = _make_workspace({"c1": c1}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c1")

    assert r1.status == "stale"
    assert r1.warnings.count("ancestor edited") == 1  # not duplicated
    assert count == 0  # already stale doesn't count
