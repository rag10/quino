from __future__ import annotations

from quino.domain.model import Project
from quino.domain.workspace import Analysis, Baseline, Case, Run, RunEntry, Study, Workspace, WorkspacePose
from quino.services.workspace_invalidation import (
    invalidate_on_analysis_change,
    invalidate_on_baseline_change,
    invalidate_on_case_change,
    invalidate_on_model_change,
    invalidate_on_pose_change,
    invalidate_on_study_change,
)


def test_invalidate_on_model_change_marks_all_stale() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        runs=[
            Run(
                id="r1",
                study_id="s1",
                created_at="2026-05-19T10:00:00Z",
                entries=[
                    RunEntry(id="e1", scope="baseline", status="ok"),
                    RunEntry(id="e2", scope="case", case_id="c1", status="ok"),
                    RunEntry(id="e3", scope="case", case_id="c1", status="running"),
                ],
            )
        ]
    )

    invalidate_on_model_change(project)

    assert project.workspace.runs[0].entries[0].status == "stale"
    assert project.workspace.runs[0].entries[1].status == "stale"
    assert project.workspace.runs[0].entries[2].status == "running"  # never mark running as stale


def test_invalidate_on_case_change_only_target_case() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        runs=[
            Run(
                id="r1",
                study_id="s1",
                created_at="2026-05-19T10:00:00Z",
                entries=[
                    RunEntry(id="e1", scope="case", case_id="c1", status="ok"),
                    RunEntry(id="e2", scope="case", case_id="c2", status="ok"),
                ],
            )
        ]
    )

    invalidate_on_case_change(project, "c1")

    assert project.workspace.runs[0].entries[0].status == "stale"
    assert project.workspace.runs[0].entries[1].status == "ok"


def test_invalidate_on_study_change_only_target_study() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        runs=[
            Run(
                id="r1",
                study_id="s1",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e1", scope="baseline", status="ok")],
            ),
            Run(
                id="r2",
                study_id="s2",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e2", scope="baseline", status="ok")],
            ),
        ]
    )

    invalidate_on_study_change(project, "s1")

    assert project.workspace.runs[0].entries[0].status == "stale"
    assert project.workspace.runs[1].entries[0].status == "ok"


def test_invalidate_on_baseline_change() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        active_baseline_id="b1",
        baselines=[Baseline(id="b1", name="Ref")],
        cases=[Case(id="c1", name="Case1", baseline_id="b1")],
        runs=[
            Run(
                id="r1",
                study_id="s1",
                created_at="2026-05-19T10:00:00Z",
                entries=[
                    RunEntry(id="e1", scope="baseline", baseline_id="b1", status="ok"),
                    RunEntry(id="e2", scope="case", baseline_id="b1", case_id="c1", status="ok"),
                    RunEntry(id="e3", scope="case", baseline_id="b2", case_id="c2", status="ok"),
                ],
            )
        ]
    )

    invalidate_on_baseline_change(project, "b1")

    assert project.workspace.runs[0].entries[0].status == "stale"  # baseline entry
    assert project.workspace.runs[0].entries[1].status == "stale"  # case with baseline b1
    assert project.workspace.runs[0].entries[2].status == "ok"     # unrelated case
    assert "baseline_changed:b1" in project.workspace.runs[0].entries[0].stale_reasons


def test_invalidate_on_analysis_change_only_target_analysis() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        runs=[
            Run(
                id="r1",
                study_id=None,
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e1", scope="case", status="ok")],
            ),
            Run(
                id="r2",
                study_id=None,
                analysis_id="a2",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e2", scope="case", status="ok")],
            ),
        ]
    )

    invalidate_on_analysis_change(project, "a1")

    assert project.workspace.runs[0].entries[0].status == "stale"
    assert project.workspace.runs[1].entries[0].status == "ok"


def test_invalidate_on_pose_change_marks_runs_of_pose_analyses() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        poses=[WorkspacePose(id="wp1", name="Pose 1", case_id="c1")],
        analyses=[Analysis(id="a1", name="Dyn", case_id="c1", workspace_pose_id="wp1")],
        runs=[
            Run(
                id="r1",
                study_id=None,
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                entries=[RunEntry(id="e1", scope="case", status="ok")],
            )
        ],
    )

    invalidate_on_pose_change(project, "wp1")

    assert project.workspace.runs[0].entries[0].status == "stale"
    assert "pose_changed:wp1" in project.workspace.runs[0].entries[0].stale_reasons
