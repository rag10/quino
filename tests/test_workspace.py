from __future__ import annotations

import json
from copy import deepcopy

import pytest

from quino.domain.model import Project
from quino.domain.workspace import (
    Analysis,
    ArtifactRef,
    Baseline,
    Case,
    CaseGroup,
    MetricDefinition,
    ResultRef,
    Run,
    RunEntry,
    ScalarValue,
    Study,
    StudyConfig,
    StudyMask,
    StudyOverlay,
    SweepParameter,
    Tolerance,
    Workspace,
    WorkspacePose,
)
from quino.serialization.json_io import JsonMapper


def test_workspace_empty_is_valid() -> None:
    ws = Workspace()
    assert ws.is_empty()
    assert ws.next_sequence == 1


def test_workspace_not_empty_with_baseline() -> None:
    ws = Workspace(baselines=[Baseline(id="b1", name="Ref")])
    assert not ws.is_empty()


def test_scalar_value_roundtrip() -> None:
    sv = ScalarValue(value=2.5, unit="kg")
    assert sv.value == 2.5
    assert sv.unit == "kg"


def test_baseline_creation() -> None:
    baseline = Baseline(
        id="baseline_001",
        name="Reference",
        tolerances={"max_stress": Tolerance(metric_key="max_stress", relative=0.05)},
        metrics={
            "max_stress": MetricDefinition(
                key="max_stress", name="Max Stress", extractor="frames[-1].body_001.stress", unit="MPa"
            )
        },
    )
    assert baseline.id == "baseline_001"
    assert baseline.tolerances["max_stress"].relative == 0.05


def test_case_with_overrides() -> None:
    case = Case(
        id="case_001",
        name="Heavy Crank",
        baseline_id="baseline_001",
        parent_case_id="case_root",
        invariant_values={
            "bodies/crank/mass": ScalarValue(value=2.5, unit="kg"),
            "parameters/L1": ScalarValue(value=150.0, unit="mm"),
        },
    )
    assert case.invariant_values["bodies/crank/mass"].value == 2.5
    assert case.parent_case_id == "case_root"


def test_case_group_cartesian_product() -> None:
    cg = CaseGroup(
        id="cg_001",
        name="Sweep",
        baseline_id="baseline_001",
        sweep_parameters=[
            SweepParameter(
                parameter_path="bodies/crank/mass",
                values=[ScalarValue(v, "kg") for v in [1.0, 2.0, 3.0]],
            ),
            SweepParameter(
                parameter_path="springs/s1/stiffness",
                values=[ScalarValue(v, "N/m") for v in [100.0, 200.0]],
            ),
        ],
    )
    assert len(cg.sweep_parameters) == 2
    assert len(cg.sweep_parameters[0].values) == 3


def test_study_defaults() -> None:
    study = Study(id="study_001", name="Dynamic Sweep")
    assert study.study_type == "dynamic"
    assert study.config.duration == 1.0
    assert study.config.steps == 100
    assert study.mask.include_baseline is True


def test_run_entry_lifecycle() -> None:
    entry = RunEntry(id="entry_001", scope="baseline")
    assert entry.status == "not_run"
    entry.status = "running"
    assert entry.status == "running"
    entry.status = "ok"
    assert entry.status == "ok"


def test_run_derived_status() -> None:
    run = Run(
        id="run_001",
        study_id="study_001",
        created_at="2026-05-19T10:00:00Z",
        entries=[
            RunEntry(id="e1", scope="baseline", status="ok"),
            RunEntry(id="e2", scope="case", case_id="c1", status="ok"),
        ],
    )
    assert all(e.status == "ok" for e in run.entries)


def test_json_mapper_roundtrip_workspace() -> None:
    mapper = JsonMapper()
    ws = Workspace(
        baselines=[Baseline(id="b1", name="Ref", description="desc")],
        cases=[
            Case(
                id="c1",
                name="Case1",
                baseline_id="b1",
                parent_case_id="c0",
                invariant_values={"parameters/L1": ScalarValue(150.0, "mm")},
            )
        ],
        poses=[
            WorkspacePose(id="wp1", name="Pose default", baseline_id="b1", is_default=True),
            WorkspacePose(id="wp2", name="Pose 1", case_id="c1", project_pose_id="pose_001"),
        ],
        analyses=[
            Analysis(
                id="a1",
                name="Dynamic",
                analysis_type="dynamic",
                case_id="c1",
                workspace_pose_id="wp2",
                config=StudyConfig(duration=3.0, steps=300),
            )
        ],
        studies=[
            Study(
                id="s1",
                name="Study1",
                study_type="dynamic",
                config=StudyConfig(duration=2.0, steps=200),
                mask=StudyMask(include_baseline=True, include_cases=["c1"]),
            )
        ],
        runs=[
            Run(
                id="r1",
                study_id="s1",
                created_at="2026-05-19T10:00:00Z",
                entries=[
                    RunEntry(
                        id="e1",
                        scope="baseline",
                        baseline_id="b1",
                        status="ok",
                        fingerprint="fp-1",
                        stale_reasons=["baseline_changed:b1"],
                        started_at="2026-05-19T10:00:00Z",
                        finished_at="2026-05-19T10:00:01Z",
                        updated_at="2026-05-19T10:00:01Z",
                        result_ref=ResultRef(
                            run_entry_id="e1",
                            artifact_path="artifacts/run_001/entry_001_result.json",
                            checksum="sha256:abc123",
                        ),
                        artifacts=[
                            ArtifactRef(
                                kind="simulation_result",
                                path="artifacts/run_001/entry_001_result.json",
                                checksum="sha256:abc123",
                            )
                        ],
                        metrics={"max_stress": 45.2},
                    )
                ],
            )
        ],
        next_sequence=5,
    )

    data = mapper._workspace_to_dict(ws)
    restored = mapper._workspace_from_dict(data)

    assert restored.next_sequence == 5
    assert len(restored.baselines) == 1
    assert restored.baselines[0].name == "Ref"
    assert len(restored.cases) == 1
    assert restored.cases[0].invariant_values["parameters/L1"].value == 150.0
    assert restored.cases[0].parent_case_id == "c0"
    assert len(restored.poses) == 2
    assert restored.poses[0].is_default is True
    assert len(restored.analyses) == 1
    assert restored.analyses[0].workspace_pose_id == "wp2"
    assert len(restored.studies) == 1
    assert restored.studies[0].config.duration == 2.0
    assert len(restored.runs) == 1
    assert restored.runs[0].entries[0].metrics["max_stress"] == 45.2
    assert restored.runs[0].entries[0].baseline_id == "b1"
    assert restored.runs[0].entries[0].fingerprint == "fp-1"
    assert restored.runs[0].entries[0].artifacts[0].kind == "simulation_result"
    assert restored.runs[0].entries[0].result_ref is not None
    assert restored.runs[0].entries[0].result_ref.checksum == "sha256:abc123"


def test_json_mapper_project_with_workspace_roundtrip() -> None:
    from quino import ApplicationService, MarkerInput

    app = ApplicationService()
    project = app.new_project("WorkspaceDemo")
    app.create_parameter("L1", "120 mm", "mm")
    app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))

    project.workspace = Workspace(
        baselines=[Baseline(id="b1", name="Ref")],
        cases=[Case(id="c1", name="Case1", invariant_values={"parameters/L1": ScalarValue(200.0, "mm")})],
        studies=[Study(id="s1", name="Study1")],
    )

    mapper = JsonMapper()
    data = mapper.dump(project)
    restored = mapper.load(data)

    assert restored.workspace is not None
    assert len(restored.workspace.baselines) == 1
    assert restored.workspace.baselines[0].name == "Ref"
    assert restored.workspace.cases[0].invariant_values["parameters/L1"].value == 200.0
    assert restored.workspace.studies[0].name == "Study1"


def test_json_mapper_project_without_workspace_loads_legacy() -> None:
    from quino import ApplicationService, MarkerInput

    app = ApplicationService()
    project = app.new_project("Legacy")
    app.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))

    mapper = JsonMapper()
    data = mapper.dump(project)
    # Simulate legacy file without workspace
    data.pop("workspace", None)
    restored = mapper.load(data)

    assert restored.workspace is None


def test_json_mapper_loads_legacy_project_block_diagram_into_control_graph() -> None:
    mapper = JsonMapper()
    data = {
        "schema_version": "0.1.0",
        "project": {"id": "p1", "name": "Legacy", "metadata": {}},
        "parameters": [],
        "sketch": None,
        "model": {
            "bodies": [],
            "sliders": [],
            "joints": [],
            "drivers": [],
            "loads": [],
            "sensors": [],
            "springs": [],
            "gravity": None,
        },
        "view_state": {},
        "block_diagram": {
            "instances": {
                "k1": {
                    "block_type": "Gain",
                    "parameters": {"k": 2.0},
                    "input_ports": [{"name": "in", "shape": [1]}],
                    "output_ports": [{"name": "out", "shape": [1]}],
                    "position": [0.0, 0.0],
                }
            },
            "connections": [],
        },
    }

    restored = mapper.load(data)

    assert restored.model.control_graph is not None
    assert restored.model.control_graph.instances["k1"].parameters["k"] == 2.0
    assert restored.block_diagram is restored.model.control_graph


def test_json_mapper_includes_workspace_with_baseline() -> None:
    from quino import ApplicationService

    app = ApplicationService()
    project = app.new_project("HasWorkspace")

    mapper = JsonMapper()
    data = mapper.dump(project)

    # new_project always creates a baseline, so workspace is always serialized
    assert "workspace" in data
    assert len(data["workspace"]["baselines"]) == 1
    assert data["workspace"]["baselines"][0]["name"] == "HasWorkspace"


def test_json_mapper_study_with_overlay_roundtrip() -> None:
    mapper = JsonMapper()
    study = Study(
        id="s1",
        name="OverlayStudy",
        overlay=StudyOverlay(
            parameter_overrides={"parameters/L2": ScalarValue(300.0, "mm")},
        ),
    )
    data = mapper._study_to_dict(study)
    restored = mapper._study_from_dict(data)
    assert restored.overlay is not None
    assert restored.overlay.parameter_overrides["parameters/L2"].value == 300.0


def test_json_mapper_run_entry_without_result_ref() -> None:
    mapper = JsonMapper()
    entry = RunEntry(id="e1", scope="case", case_id="c1", status="not_run")
    data = mapper._run_entry_to_dict(entry)
    restored = mapper._run_entry_from_dict(data)
    assert restored.result_ref is None
    assert restored.status == "not_run"


def test_workspace_pose_has_inheritance_fields():
    from quino.domain.workspace import WorkspacePose
    pose = WorkspacePose(id="p1", name="Default", is_default=True)
    assert pose.parent_pose_id is None
    assert pose.requires_recompute is True
    assert pose.solve_failed is False


def test_workspace_pose_roundtrip_with_inheritance_fields():
    from quino.domain.workspace import WorkspacePose, Workspace
    from quino.domain.model import Project
    from quino.serialization.json_io import JsonMapper
    pose = WorkspacePose(
        id="p1", name="Default", is_default=True,
        parent_pose_id="p0", requires_recompute=False, solve_failed=True,
        metadata={"solved_state": {"m1": [1.0, 2.0]}},
    )
    ws = Workspace(poses=[pose])
    project = Project(id="proj1", name="Test", schema_version="0.1.0", workspace=ws)
    payload = JsonMapper().dump(project)
    restored = JsonMapper().load(payload)
    restored_pose = restored.workspace.poses[0]
    assert restored_pose.parent_pose_id == "p0"
    assert restored_pose.requires_recompute is False
    assert restored_pose.solve_failed is True
    assert restored_pose.metadata["solved_state"]["m1"] == [1.0, 2.0]
