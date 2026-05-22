from __future__ import annotations

from quino.domain.model import Project
from quino.domain.workspace import (
    Analysis,
    Baseline,
    Case,
    Run,
    Workspace,
    WorkspacePose,
)
from quino.services.workspace_invalidation import (
    invalidate_on_analysis_change,
    invalidate_on_baseline_change,
    invalidate_on_case_change,
    invalidate_on_model_change,
    invalidate_on_pose_change,
)


def _make_project(**workspace_kwargs) -> Project:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(**workspace_kwargs)
    return project


def test_invalidate_on_model_change_marks_ok_and_partial_as_stale() -> None:
    project = _make_project(
        runs=[
            Run(id="r1", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="ok"),
            Run(id="r2", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="partial"),
            Run(id="r3", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="running"),
            Run(id="r4", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="failed"),
            Run(id="r5", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="stale"),
            Run(id="r6", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="to_be_run"),
        ]
    )

    invalidate_on_model_change(project)

    assert project.workspace.runs[0].status == "stale"
    assert "model_changed" in project.workspace.runs[0].warnings
    assert project.workspace.runs[1].status == "stale"
    assert "model_changed" in project.workspace.runs[1].warnings
    assert project.workspace.runs[2].status == "running"
    assert project.workspace.runs[3].status == "failed"
    assert project.workspace.runs[4].status == "stale"
    assert project.workspace.runs[5].status == "to_be_run"


def test_invalidate_on_case_change_only_target_case() -> None:
    project = _make_project(
        cases=[
            Case(id="c1", name="Case 1"),
            Case(id="c2", name="Case 2"),
        ],
        analyses=[
            Analysis(id="a1", name="Dyn 1", case_id="c1"),
            Analysis(id="a2", name="Dyn 2", case_id="c2"),
        ],
        runs=[
            Run(id="r1", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="ok"),
            Run(id="r2", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="running"),
            Run(id="r3", analysis_id="a2", created_at="2026-05-19T10:00:00Z", status="ok"),
        ],
    )

    invalidate_on_case_change(project, "c1")

    assert project.workspace.runs[0].status == "stale"
    assert "case_changed:c1" in project.workspace.runs[0].warnings
    assert project.workspace.runs[1].status == "running"
    assert project.workspace.runs[2].status == "ok"


def test_invalidate_on_analysis_change_only_target_analysis() -> None:
    project = _make_project(
        analyses=[
            Analysis(id="a1", name="Dyn 1"),
            Analysis(id="a2", name="Dyn 2"),
        ],
        runs=[
            Run(id="r1", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="ok"),
            Run(id="r2", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="running"),
            Run(id="r3", analysis_id="a2", created_at="2026-05-19T10:00:00Z", status="ok"),
        ],
    )

    invalidate_on_analysis_change(project, "a1")

    assert project.workspace.runs[0].status == "stale"
    assert "analysis_changed:a1" in project.workspace.runs[0].warnings
    assert project.workspace.runs[1].status == "running"
    assert project.workspace.runs[2].status == "ok"


def test_invalidate_on_pose_change_marks_runs_of_pose_analyses() -> None:
    project = _make_project(
        poses=[
            WorkspacePose(id="wp1", name="Pose 1", case_id="c1"),
        ],
        cases=[
            Case(id="c1", name="Case 1"),
        ],
        analyses=[
            Analysis(id="a1", name="Dyn 1", case_id="c1", workspace_pose_id="wp1"),
            Analysis(id="a2", name="Dyn 2", case_id="c1"),
        ],
        runs=[
            Run(id="r1", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="ok"),
            Run(id="r2", analysis_id="a2", created_at="2026-05-19T10:00:00Z", status="ok"),
        ],
    )

    invalidate_on_pose_change(project, "wp1")

    assert project.workspace.runs[0].status == "stale"
    assert "pose_changed:wp1" in project.workspace.runs[0].warnings
    assert project.workspace.runs[1].status == "ok"


def test_invalidate_on_baseline_change_marks_matching_runs() -> None:
    project = _make_project(
        baselines=[
            Baseline(id="b1", name="Ref 1"),
            Baseline(id="b2", name="Ref 2"),
        ],
        cases=[
            Case(id="c1", name="Case 1", baseline_id="b1"),
            Case(id="c2", name="Case 2", baseline_id="b2"),
        ],
        analyses=[
            Analysis(id="a1", name="Dyn 1", baseline_id="b1"),
            Analysis(id="a2", name="Dyn 2", case_id="c1"),
            Analysis(id="a3", name="Dyn 3", case_id="c2"),
            Analysis(id="a4", name="Dyn 4", baseline_id="b2"),
        ],
        runs=[
            Run(id="r1", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="ok"),
            Run(id="r1b", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="running"),
            Run(id="r2", analysis_id="a2", created_at="2026-05-19T10:00:00Z", status="ok"),
            Run(id="r3", analysis_id="a3", created_at="2026-05-19T10:00:00Z", status="ok"),
            Run(id="r4", analysis_id="a4", created_at="2026-05-19T10:00:00Z", status="ok"),
        ],
    )

    invalidate_on_baseline_change(project, "b1")

    assert project.workspace.runs[0].status == "stale"
    assert "baseline_changed:b1" in project.workspace.runs[0].warnings
    assert project.workspace.runs[1].status == "running"
    assert project.workspace.runs[2].status == "stale"
    assert "baseline_changed:b1" in project.workspace.runs[2].warnings
    assert project.workspace.runs[3].status == "ok"
    assert project.workspace.runs[4].status == "ok"


def test_running_runs_are_never_marked_stale() -> None:
    """Running-status runs must stay running across all invalidation reasons."""
    project = _make_project(
        baselines=[Baseline(id="b1", name="Ref")],
        cases=[Case(id="c1", name="Case 1", baseline_id="b1")],
        poses=[WorkspacePose(id="wp1", name="Pose 1", case_id="c1")],
        analyses=[
            Analysis(id="a1", name="Dyn 1", case_id="c1", baseline_id="b1", workspace_pose_id="wp1"),
        ],
        runs=[
            Run(id="r1", analysis_id="a1", created_at="2026-05-19T10:00:00Z", status="running"),
        ],
    )

    invalidate_on_model_change(project)
    assert project.workspace.runs[0].status == "running"

    invalidate_on_baseline_change(project, "b1")
    assert project.workspace.runs[0].status == "running"

    invalidate_on_case_change(project, "c1")
    assert project.workspace.runs[0].status == "running"

    invalidate_on_analysis_change(project, "a1")
    assert project.workspace.runs[0].status == "running"

    invalidate_on_pose_change(project, "wp1")
    assert project.workspace.runs[0].status == "running"
