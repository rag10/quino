from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from quino import ApplicationService, MarkerInput
from quino.domain.model import Project, SimulationResult
from quino.domain.workspace import (
    Baseline,
    Case,
    MetricDefinition,
    ScalarValue,
    Study,
    StudyConfig,
)
from quino.serialization.json_io import JsonMapper
from quino.simulation.runner import SimulationRunner


class FakeAdapter:
    name = "fake"

    def is_available(self) -> bool:
        return True

    def run(self, project: Project, **kwargs: Any) -> SimulationResult:
        return SimulationResult(
            success=True,
            time=[0.0, 0.5, 1.0],
            frames=[
                {"body_001.x": 0.0, "body_001.y": 0.0},
                {"body_001.x": 0.5, "body_001.y": 0.1},
                {"body_001.x": 1.0, "body_001.y": 0.2},
            ],
        )


def test_end_to_end_create_case_study_run_and_roundtrip(tmp_path: Path) -> None:
    # 1. Create project with a body and parameter
    app = ApplicationService()
    project = app.new_project("E2E")
    param_id = app.create_parameter("L1", "120 mm", "mm")
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "A")])

    # 2. Create workspace items via API
    baseline = app.workspace.create_baseline("Reference")
    baseline.metrics = {
        "final_x": MetricDefinition(
            key="final_x", name="Final X", extractor="frames[-1].body_001.x"
        )
    }

    case = app.workspace.create_case("Longer")
    app.workspace.update_case_invariants(
        case.id, {f"parameters/{param_id}": "200 mm"}
    )

    study = app.workspace.create_study("Dynamic", config=StudyConfig(duration=1.0, steps=10))

    # 3. Run study
    runner = SimulationRunner(FakeAdapter())
    run = app.workspace.run_study(study.id, runner, project_dir=tmp_path)

    assert run.status == "completed"
    assert len(run.entries) == 2  # baseline + case
    assert run.entries[0].scope == "baseline"
    assert run.entries[1].scope == "case"
    assert run.entries[0].status == "ok"
    assert run.entries[0].metrics.get("final_x") == 1.0
    assert run.entries[0].result_ref is not None
    artifact = tmp_path / run.entries[0].result_ref.artifact_path
    assert artifact.exists()

    # 4. Verify compose_project works via runner
    from quino.services.workspace_composition import compose_project

    ws = app.project.workspace
    composed = compose_project(app.project, ws.studies[0], ws.cases[0])
    param = next(p for p in composed.parameters if p.id == param_id)
    assert param.expression == "200 mm"

    # 5. JSON round-trip
    mapper = JsonMapper()
    data = mapper.dump(app.project)
    restored = mapper.load(data)

    assert restored.workspace is not None
    assert len(restored.workspace.baselines) == 1
    assert restored.workspace.baselines[0].name == "Reference"
    assert len(restored.workspace.cases) == 1
    assert restored.workspace.cases[0].invariant_values[f"parameters/{param_id}"].value == 200.0
    assert len(restored.workspace.studies) == 1
    assert len(restored.workspace.runs) == 1
    assert restored.workspace.runs[0].entries[0].metrics["final_x"] == 1.0


def test_end_to_end_stale_invalidation_on_case_change(tmp_path: Path) -> None:
    app = ApplicationService()
    project = app.new_project("StaleTest")
    app.create_parameter("L1", "120 mm", "mm")

    case = app.workspace.create_case("Case1")
    study = app.workspace.create_study("Study1")
    runner = SimulationRunner(FakeAdapter())
    run = app.workspace.run_study(study.id, runner, project_dir=tmp_path)
    # baseline + case
    assert len(run.entries) == 2
    assert run.entries[1].status == "ok"
    assert run.entries[1].case_id == case.id

    # Modify case should invalidate its entries
    app.workspace.update_case_invariants(case.id, {"parameters/foo": "2.5"})
    assert run.entries[1].status == "stale"
    # Baseline entry should remain ok
    assert run.entries[0].status == "ok"


def test_end_to_end_legacy_project_no_workspace() -> None:
    app = ApplicationService()
    project = app.new_project("Legacy")
    app.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))

    mapper = JsonMapper()
    data = mapper.dump(project)
    assert "workspace" not in data

    restored = mapper.load(data)
    assert restored.workspace is None
