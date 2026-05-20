from __future__ import annotations

import pytest

from quino import ApplicationService
from quino.domain.workspace import (
    Analysis,
    Baseline,
    Case,
    CaseGroup,
    Study,
    StudyConfig,
    StudyMask,
    WorkspacePose,
)


def test_workspace_create_baseline() -> None:
    app = ApplicationService()
    app.new_project("Test")
    # new_project auto-creates baseline "Test"; creating another yields 2 total
    baseline = app.workspace.create_baseline("Reference")
    assert isinstance(baseline, Baseline)
    assert baseline.name == "Reference"
    assert app.project.workspace is not None
    assert len(app.project.workspace.baselines) == 2


def test_workspace_create_case() -> None:
    app = ApplicationService()
    app.new_project("Test")
    case = app.workspace.create_case("Heavy Crank")
    assert isinstance(case, Case)
    assert case.name == "Heavy Crank"
    assert app.project.workspace.cases[0].id == case.id
    assert any(p.case_id == case.id and p.is_default for p in app.project.workspace.poses)


def test_workspace_create_child_case_inherits_baseline() -> None:
    app = ApplicationService()
    app.new_project("Test")
    baseline = app.workspace.create_baseline("Reference")
    parent = app.workspace.create_case("Case A", baseline_id=baseline.id)
    child = app.workspace.create_case("Case B", parent_case_id=parent.id)

    assert child.parent_case_id == parent.id
    assert child.baseline_id == baseline.id


def test_workspace_create_pose_and_analysis() -> None:
    app = ApplicationService()
    app.new_project("Test")
    case = app.workspace.create_case("Case1")
    pose = app.workspace.create_pose("Pose 1", case_id=case.id, project_pose_id="pose_model_001")
    analysis = app.workspace.create_analysis(
        "Dynamic 1",
        analysis_type="dynamic",
        case_id=case.id,
        workspace_pose_id=pose.id,
    )

    assert isinstance(pose, WorkspacePose)
    assert pose.case_id == case.id
    assert isinstance(analysis, Analysis)
    assert analysis.workspace_pose_id == pose.id


def test_workspace_rename_and_delete_pose_and_analysis() -> None:
    app = ApplicationService()
    app.new_project("Test")
    case = app.workspace.create_case("Case1")
    pose = app.workspace.create_pose("Pose 1", case_id=case.id)
    analysis = app.workspace.create_analysis("Dynamic 1", case_id=case.id, workspace_pose_id=pose.id)

    app.workspace.rename_pose(pose.id, "Pose A")
    app.workspace.rename_analysis(analysis.id, "Dyn A")
    assert app.project.workspace.poses[-1].name == "Pose A"
    assert app.project.workspace.analyses[-1].name == "Dyn A"

    app.workspace.delete_analysis(analysis.id)
    assert not any(a.id == analysis.id for a in app.project.workspace.analyses)

    app.workspace.delete_pose(pose.id)
    assert not any(p.id == pose.id for p in app.project.workspace.poses)


def test_workspace_create_study() -> None:
    app = ApplicationService()
    app.new_project("Test")
    study = app.workspace.create_study("Dynamic Sweep", study_type="dynamic")
    assert isinstance(study, Study)
    assert study.study_type == "dynamic"
    assert study.config.duration == 1.0


def test_workspace_create_study_with_config() -> None:
    app = ApplicationService()
    app.new_project("Test")
    config = StudyConfig(duration=2.0, steps=200)
    study = app.workspace.create_study("Sweep", config=config)
    assert study.config.duration == 2.0
    assert study.config.steps == 200


def test_workspace_rename_baseline() -> None:
    app = ApplicationService()
    app.new_project("Test")
    baseline = app.workspace.create_baseline("Ref")
    app.workspace.rename_baseline(baseline.id, "Reference")
    # baselines[0] is auto-created "Test"; baselines[1] is the renamed one
    assert app.project.workspace.baselines[1].name == "Reference"


def test_workspace_delete_case() -> None:
    app = ApplicationService()
    app.new_project("Test")
    case = app.workspace.create_case("Case1")
    app.workspace.delete_case(case.id)
    assert len(app.project.workspace.cases) == 0


def test_workspace_update_case_invariants() -> None:
    app = ApplicationService()
    app.new_project("Test")
    case = app.workspace.create_case("Case1")
    app.workspace.update_case_invariants(
        case.id, {"parameters/foo": "2.5 kg", "bodies/bar/mass": 1.0}
    )
    updated = app.project.workspace.cases[0]
    assert updated.invariant_values["parameters/foo"].value == 2.5
    assert updated.invariant_values["parameters/foo"].unit == "kg"
    assert updated.invariant_values["bodies/bar/mass"].value == 1.0


def test_workspace_create_case_group() -> None:
    app = ApplicationService()
    app.new_project("Test")
    cg = app.workspace.create_case_group("Sweep", baseline_id="b1")
    assert isinstance(cg, CaseGroup)
    assert cg.baseline_id == "b1"


def test_workspace_update_study_config_invalidates() -> None:
    app = ApplicationService()
    app.new_project("Test")
    study = app.workspace.create_study("Study1")
    # Create a run manually to check invalidation
    from quino.domain.workspace import Run, RunEntry

    app.project.workspace.runs.append(
        Run(
            id="run_001",
            study_id=study.id,
            created_at="t",
            entries=[RunEntry(id="e1", scope="baseline", status="ok")],
        )
    )
    app.workspace.update_study_config(study.id, StudyConfig(duration=5.0))
    assert app.project.workspace.runs[0].entries[0].status == "stale"


def test_workspace_update_study_variables() -> None:
    app = ApplicationService()
    app.new_project("Test")
    study = app.workspace.create_study("Study1")
    app.workspace.update_study_variables(study.id, {"drivers/d1/law": "2.5 N"})
    updated = app.project.workspace.studies[0]
    assert updated.variable_values["drivers/d1/law"].value == 2.5
    assert updated.variable_values["drivers/d1/law"].unit == "N"
