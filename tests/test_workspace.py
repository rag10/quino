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
    MetricDefinition,
    ResultRef,
    Run,
    ScalarValue,
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


def test_json_mapper_project_with_workspace_roundtrip() -> None:
    from quino import ApplicationService, MarkerInput

    app = ApplicationService()
    project = app.new_project("WorkspaceDemo")
    app.create_parameter("L1", "120 mm", "mm")
    app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))

    project.workspace = Workspace(
        baselines=[Baseline(id="b1", name="Ref")],
        cases=[Case(id="c1", name="Case1", invariant_values={"parameters/L1": ScalarValue(200.0, "mm")})],
    )

    mapper = JsonMapper()
    data = mapper.dump(project)
    restored = mapper.load(data)

    assert restored.workspace is not None
    assert len(restored.workspace.baselines) == 1
    assert restored.workspace.baselines[0].name == "Ref"
    assert restored.workspace.cases[0].invariant_values["parameters/L1"].value == 200.0


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


def test_analysis_type_enum_values():
    from quino.domain.types import AnalysisType
    assert AnalysisType.DYNAMIC.value == "dynamic"
    assert AnalysisType.STATIC.value == "static"
    assert AnalysisType.KINEMATIC.value == "kinematic"
    assert AnalysisType.EQUILIBRIUM.value == "equilibrium"


def test_analysis_type_from_string():
    from quino.domain.types import AnalysisType
    assert AnalysisType("dynamic") is AnalysisType.DYNAMIC
