from __future__ import annotations

from quino.domain.workspace import Analysis, Case, Run, Workspace
from quino.services.workspace_staleness import mark_descendants_stale


def test_mark_descendants_stale_single_child() -> None:
    """Test marking a child case and its analysis as stale."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    a1 = Analysis(id="a1", name="Analysis1", case_id="c1")
    a2 = Analysis(id="a2", name="Analysis2", case_id="c2")

    workspace = Workspace(
        cases=[c1, c2],
        analyses=[a1, a2],
        runs=[
            Run(
                id="r1",
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
            Run(
                id="r2",
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c1")

    assert workspace.runs[0].status == "stale"
    assert workspace.runs[1].status == "stale"
    assert count == 2
    assert "ancestor edited" in workspace.runs[0].warnings
    assert "ancestor edited" in workspace.runs[1].warnings


def test_mark_descendants_stale_nested_hierarchy() -> None:
    """Test marking stale through a nested case hierarchy."""
    c1 = Case(id="c1", name="Root")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")
    c3 = Case(id="c3", name="Grandchild", parent_case_id="c2")
    c4 = Case(id="c4", name="Unrelated")

    a1 = Analysis(id="a1", name="A1", case_id="c1")
    a2 = Analysis(id="a2", name="A2", case_id="c2")
    a3 = Analysis(id="a3", name="A3", case_id="c3")
    a4 = Analysis(id="a4", name="A4", case_id="c4")

    workspace = Workspace(
        cases=[c1, c2, c3, c4],
        analyses=[a1, a2, a3, a4],
        runs=[
            Run(
                id="r1",
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
            Run(
                id="r2",
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
            Run(
                id="r3",
                analysis_id="a3",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
            Run(
                id="r4",
                analysis_id="a4",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c2")

    assert workspace.runs[0].status == "ok"
    assert workspace.runs[1].status == "stale"
    assert workspace.runs[2].status == "stale"
    assert workspace.runs[3].status == "ok"
    assert count == 2


def test_mark_descendants_stale_sibling_unaffected() -> None:
    """Test that siblings are not marked as stale."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child1", parent_case_id="c1")
    c3 = Case(id="c3", name="Child2", parent_case_id="c1")

    a2 = Analysis(id="a2", name="A2", case_id="c2")
    a3 = Analysis(id="a3", name="A3", case_id="c3")

    workspace = Workspace(
        cases=[c1, c2, c3],
        analyses=[a2, a3],
        runs=[
            Run(
                id="r2",
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
            Run(
                id="r3",
                analysis_id="a3",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c2")

    assert workspace.runs[0].status == "stale"
    assert workspace.runs[1].status == "ok"
    assert count == 1


def test_mark_descendants_stale_respects_running() -> None:
    """Test that running runs are not marked as stale."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")

    a1 = Analysis(id="a1", name="A1", case_id="c1")
    a2 = Analysis(id="a2", name="A2", case_id="c2")

    workspace = Workspace(
        cases=[c1, c2],
        analyses=[a1, a2],
        runs=[
            Run(
                id="r1",
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
            Run(
                id="r2",
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                status="running",
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c1")

    assert workspace.runs[0].status == "stale"
    assert workspace.runs[1].status == "running"
    assert count == 1


def test_mark_descendants_stale_multiple_runs() -> None:
    """Test handling multiple runs for the same analysis."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")

    a2 = Analysis(id="a2", name="A2", case_id="c2")

    workspace = Workspace(
        cases=[c1, c2],
        analyses=[a2],
        runs=[
            Run(
                id="r1",
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
            Run(
                id="r2",
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                status="ok",
            ),
            Run(
                id="r3",
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                status="running",
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c1")

    assert workspace.runs[0].status == "stale"
    assert workspace.runs[1].status == "stale"
    assert workspace.runs[2].status == "running"
    assert count == 2


def test_mark_descendants_stale_empty_workspace() -> None:
    """Test with empty workspace."""
    workspace = Workspace(cases=[], analyses=[], runs=[])

    count = mark_descendants_stale(workspace, "c1")

    assert count == 0


def test_mark_descendants_stale_already_stale() -> None:
    """Test that already stale runs don't get reason duplicated."""
    c1 = Case(id="c1", name="Parent")

    a1 = Analysis(id="a1", name="A1", case_id="c1")

    workspace = Workspace(
        cases=[c1],
        analyses=[a1],
        runs=[
            Run(
                id="r1",
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                status="stale",
                warnings=["ancestor edited"],
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c1")

    assert workspace.runs[0].status == "stale"
    assert workspace.runs[0].warnings.count("ancestor edited") == 1
    assert count == 0
