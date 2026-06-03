"""Tests for quino.services.workspace_staleness (case-as-model, Analysis run state).

Run state is flattened onto each Analysis (one run per analysis); there is no
separate Run entity or ``case.runs`` list. ``mark_descendants_stale`` flips
``analysis.status`` ok/partial -> stale and leaves running/failed/to_be_run/stale
untouched.
"""
from __future__ import annotations

from quino.domain.workspace import Analysis, Case, Workspace


def _make_workspace(cases_dict: dict[str, Case], root_ids: list[str] | None = None) -> Workspace:
    ws = Workspace(id="ws1", name="Test", schema_version="0.4.0")
    ws.cases = cases_dict
    ws.root_case_ids = root_ids or list(cases_dict.keys())
    return ws


def _analysis(aid: str, status: str = "ok") -> Analysis:
    return Analysis(id=aid, name=aid, analysis_type="dynamic", status=status)


from quino.services.workspace_staleness import mark_descendants_stale


def test_mark_descendants_stale_single_child() -> None:
    """Root and its child case are both staled."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    a1 = _analysis("a1")
    a2 = _analysis("a2")
    c1.analyses = [a1]
    c2.analyses = [a2]
    ws = _make_workspace({"c1": c1, "c2": c2}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c1")

    assert a1.status == "stale"
    assert a2.status == "stale"
    assert count == 2
    assert "ancestor edited" in a1.warnings
    assert "ancestor edited" in a2.warnings


def test_mark_descendants_stale_nested_hierarchy() -> None:
    """Starting at c2 stales c2 and c3 but not c1 or c4."""
    c1 = Case(id="c1", name="Root")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    c3 = Case(id="c3", name="Grandchild", parent_case_id="c2")
    c4 = Case(id="c4", name="Unrelated")
    for c, aid in [(c1, "a1"), (c2, "a2"), (c3, "a3"), (c4, "a4")]:
        c.analyses = [_analysis(aid)]
    ws = _make_workspace({"c1": c1, "c2": c2, "c3": c3, "c4": c4}, root_ids=["c1", "c4"])

    count = mark_descendants_stale(ws, "c2")

    assert c1.analyses[0].status == "ok"     # parent not affected
    assert c2.analyses[0].status == "stale"  # root of subtree
    assert c3.analyses[0].status == "stale"  # descendant
    assert c4.analyses[0].status == "ok"     # unrelated
    assert count == 2


def test_mark_descendants_stale_sibling_unaffected() -> None:
    """Sibling cases are not affected."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child1", parent_case_id="c1")
    c3 = Case(id="c3", name="Child2", parent_case_id="c1")
    c2.analyses = [_analysis("a2")]
    c3.analyses = [_analysis("a3")]
    ws = _make_workspace({"c1": c1, "c2": c2, "c3": c3}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c2")

    assert c2.analyses[0].status == "stale"
    assert c3.analyses[0].status == "ok"
    assert count == 1


def test_mark_descendants_stale_respects_running() -> None:
    """Running analyses are never marked stale."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    c1.analyses = [_analysis("a1", "ok")]
    c2.analyses = [_analysis("a2", "running")]
    ws = _make_workspace({"c1": c1, "c2": c2}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c1")

    assert c1.analyses[0].status == "stale"
    assert c2.analyses[0].status == "running"
    assert count == 1


def test_mark_descendants_stale_multiple_analyses() -> None:
    """Multiple analyses per case — all ok/partial staled, running/failed skipped."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    a1 = _analysis("a1", "ok")
    a2 = _analysis("a2", "partial")
    a3 = _analysis("a3", "running")
    a4 = _analysis("a4", "failed")
    c2.analyses = [a1, a2, a3, a4]
    ws = _make_workspace({"c1": c1, "c2": c2}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c1")

    assert a1.status == "stale"
    assert a2.status == "stale"
    assert a3.status == "running"
    assert a4.status == "failed"
    assert count == 2


def test_mark_descendants_stale_empty_workspace() -> None:
    """Empty workspace — no crash, returns 0."""
    ws = _make_workspace({}, root_ids=[])

    count = mark_descendants_stale(ws, "c1")

    assert count == 0


def test_mark_descendants_stale_already_stale() -> None:
    """Already-stale analyses do not get the warning duplicated."""
    c1 = Case(id="c1", name="Parent")
    a1 = _analysis("a1", "stale")
    a1.warnings = ["ancestor edited"]
    c1.analyses = [a1]
    ws = _make_workspace({"c1": c1}, root_ids=["c1"])

    count = mark_descendants_stale(ws, "c1")

    assert a1.status == "stale"
    assert a1.warnings.count("ancestor edited") == 1  # not duplicated
    assert count == 0  # already stale doesn't count
