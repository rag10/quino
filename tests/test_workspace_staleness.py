from __future__ import annotations

from quino.domain.workspace import Analysis, Case, Run, RunEntry, Workspace
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
                study_id=None,
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e1", scope="case", case_id="c1", status="ok")],
            ),
            Run(
                id="r2",
                study_id=None,
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e2", scope="case", case_id="c2", status="ok")],
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c1")

    # Both c1 and c2 (descendant of c1) should have stale entries
    assert workspace.runs[0].entries[0].status == "stale"
    assert workspace.runs[1].entries[0].status == "stale"
    assert count == 2
    assert "ancestor edited" in workspace.runs[0].entries[0].stale_reasons
    assert "ancestor edited" in workspace.runs[1].entries[0].stale_reasons


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
                study_id=None,
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e1", scope="case", case_id="c1", status="ok")],
            ),
            Run(
                id="r2",
                study_id=None,
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e2", scope="case", case_id="c2", status="ok")],
            ),
            Run(
                id="r3",
                study_id=None,
                analysis_id="a3",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e3", scope="case", case_id="c3", status="ok")],
            ),
            Run(
                id="r4",
                study_id=None,
                analysis_id="a4",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e4", scope="case", case_id="c4", status="ok")],
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c2")

    # c1 (parent) should NOT be stale, c2 and c3 (descendants) should be
    assert workspace.runs[0].entries[0].status == "ok"
    assert workspace.runs[1].entries[0].status == "stale"
    assert workspace.runs[2].entries[0].status == "stale"
    assert workspace.runs[3].entries[0].status == "ok"
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
                study_id=None,
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e2", scope="case", case_id="c2", status="ok")],
            ),
            Run(
                id="r3",
                study_id=None,
                analysis_id="a3",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e3", scope="case", case_id="c3", status="ok")],
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c2")

    # Only c2 and its descendants should be stale; c3 (sibling) should not
    assert workspace.runs[0].entries[0].status == "stale"
    assert workspace.runs[1].entries[0].status == "ok"
    assert count == 1


def test_mark_descendants_stale_respects_running() -> None:
    """Test that running entries are not marked as stale."""
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
                study_id=None,
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e1", scope="case", case_id="c1", status="ok")],
            ),
            Run(
                id="r2",
                study_id=None,
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e2", scope="case", case_id="c2", status="running")],
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c1")

    # ok entry should be stale, running should stay running
    assert workspace.runs[0].entries[0].status == "stale"
    assert workspace.runs[1].entries[0].status == "running"
    assert count == 1


def test_mark_descendants_stale_multiple_entries_per_run() -> None:
    """Test handling multiple entries in a single run."""
    c1 = Case(id="c1", name="Parent")
    c2 = Case(id="c2", name="Child", parent_case_id="c1")

    a2 = Analysis(id="a2", name="A2", case_id="c2")

    workspace = Workspace(
        cases=[c1, c2],
        analyses=[a2],
        runs=[
            Run(
                id="r1",
                study_id=None,
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                entries=[
                    RunEntry(id="e1", scope="case", case_id="c2", status="ok"),
                    RunEntry(id="e2", scope="case", case_id="c2", status="ok"),
                    RunEntry(id="e3", scope="case", case_id="c2", status="running"),
                ],
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c1")

    # First two should be stale, third should remain running
    assert workspace.runs[0].entries[0].status == "stale"
    assert workspace.runs[0].entries[1].status == "stale"
    assert workspace.runs[0].entries[2].status == "running"
    assert count == 2


def test_mark_descendants_stale_empty_workspace() -> None:
    """Test with empty workspace."""
    workspace = Workspace(cases=[], analyses=[], runs=[])

    count = mark_descendants_stale(workspace, "c1")

    assert count == 0


def test_mark_descendants_stale_already_stale() -> None:
    """Test that already stale entries don't get reason duplicated."""
    c1 = Case(id="c1", name="Parent")

    a1 = Analysis(id="a1", name="A1", case_id="c1")

    workspace = Workspace(
        cases=[c1],
        analyses=[a1],
        runs=[
            Run(
                id="r1",
                study_id=None,
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                entries=[
                    RunEntry(
                        id="e1",
                        scope="case",
                        case_id="c1",
                        status="stale",
                        stale_reasons=["ancestor edited"]
                    )
                ],
            ),
        ],
    )

    count = mark_descendants_stale(workspace, "c1")

    # Should still be stale, no change
    assert workspace.runs[0].entries[0].status == "stale"
    # Reason should not be duplicated
    assert workspace.runs[0].entries[0].stale_reasons.count("ancestor edited") == 1
    assert count == 0  # No entries flipped from "ok" to "stale"
