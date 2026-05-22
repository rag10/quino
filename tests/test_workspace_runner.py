from __future__ import annotations

from typing import Any

import pytest

from quino.domain.model import Project, SimulationResult
from quino.domain.workspace import (
    Analysis,
    Baseline,
    DynamicConfig,
    MetricDefinition,
    Run,
    Workspace,
)
from quino.services.workspace_runner import (
    _evaluate_metric_extractor,
    _extract_metrics,
    run_analysis,
)
from quino.simulation.runner import SimulationRunner


class FakeAdapter:
    name = "fake"

    def __init__(
        self,
        result: SimulationResult | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._result = result
        self._exc = exc
        self.calls = 0
        self.last_pose_id = None

    def is_available(self) -> bool:
        return True

    def run(self, project: Project, **kwargs: Any) -> SimulationResult:
        self.calls += 1
        self.last_pose_id = project.simulation_initial_pose_id
        if self._exc is not None:
            raise self._exc
        if self._result is not None:
            return self._result
        return SimulationResult(
            success=True,
            time=[0.0, 0.5, 1.0],
            frames=[{"x": 0.0}, {"x": 0.5}, {"x": 1.0}],
        )


def _make_fake_runner(
    result: SimulationResult | None = None,
    exc: Exception | None = None,
) -> SimulationRunner:
    return SimulationRunner(FakeAdapter(result, exc))


# --- _evaluate_metric_extractor ---


def test_evaluate_metric_extractor_time_last() -> None:
    result = SimulationResult(success=True, time=[0.0, 0.5, 1.0])
    assert _evaluate_metric_extractor(result, "time[-1]") == 1.0

    empty = SimulationResult(success=True)
    assert _evaluate_metric_extractor(empty, "time[-1]") is None


def test_evaluate_metric_extractor_frames_last() -> None:
    result = SimulationResult(
        success=True,
        frames=[{"x": 1.0}, {"x": 3.0}],
    )
    assert _evaluate_metric_extractor(result, "frames[-1].x") == 3.0
    assert _evaluate_metric_extractor(result, "frames[-1].missing") is None

    empty = SimulationResult(success=True)
    assert _evaluate_metric_extractor(empty, "frames[-1].x") is None


def test_evaluate_metric_extractor_max() -> None:
    result = SimulationResult(
        success=True,
        frames=[{"x": 1.0}, {"x": 5.0}, {"x": 2.0}],
    )
    assert _evaluate_metric_extractor(result, "max.x") == 5.0
    assert _evaluate_metric_extractor(result, "max.missing") is None


def test_evaluate_metric_extractor_min() -> None:
    result = SimulationResult(
        success=True,
        frames=[{"x": 1.0}, {"x": 5.0}, {"x": 2.0}],
    )
    assert _evaluate_metric_extractor(result, "min.x") == 1.0
    assert _evaluate_metric_extractor(result, "min.missing") is None


# --- _extract_metrics ---


def test_extract_metrics_with_baseline() -> None:
    baseline = Baseline(
        id="b1",
        name="Ref",
        metrics={
            "final_x": MetricDefinition(
                key="final_x", name="Final X", extractor="frames[-1].x"
            ),
            "max_x": MetricDefinition(
                key="max_x", name="Max X", extractor="max.x"
            ),
            "min_x": MetricDefinition(
                key="min_x", name="Min X", extractor="min.x"
            ),
            "final_time": MetricDefinition(
                key="final_time", name="Final Time", extractor="time[-1]"
            ),
        },
    )
    result = SimulationResult(
        success=True,
        time=[0.0, 1.0],
        frames=[{"x": 0.0}, {"x": 2.0}],
    )
    metrics = _extract_metrics(result, baseline)
    assert metrics == {
        "final_x": 2.0,
        "max_x": 2.0,
        "min_x": 0.0,
        "final_time": 1.0,
    }


# --- run_analysis ---


def test_run_analysis_success() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    baseline = Baseline(
        id="b1",
        name="Ref",
        metrics={
            "final_x": MetricDefinition(
                key="final_x", name="Final X", extractor="frames[-1].x"
            ),
            "max_x": MetricDefinition(
                key="max_x", name="Max X", extractor="max.x"
            ),
        },
    )
    project.workspace = Workspace(
        baselines=[baseline],
        analyses=[
            Analysis(
                id="a1",
                name="Dynamic",
                analysis_type="dynamic",
                baseline_id="b1",
                config=DynamicConfig(duration=1.0, steps=10),
            )
        ],
    )

    result = SimulationResult(
        success=True,
        time=[0.0, 0.5, 1.0],
        frames=[{"x": 0.0}, {"x": 0.5}, {"x": 1.0}],
    )
    runner = _make_fake_runner(result)
    run = run_analysis(project, "a1", runner)

    assert isinstance(run, Run)
    assert run.analysis_id == "a1"
    assert run.status == "ok"
    assert run.metrics == {"final_x": 1.0, "max_x": 1.0}
    assert run.error_message == ""
    assert project.workspace.runs[-1] is run


def test_run_analysis_failure() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        analyses=[
            Analysis(
                id="a1",
                name="Dynamic",
                analysis_type="dynamic",
                config=DynamicConfig(duration=1.0, steps=10),
            )
        ],
    )

    runner = _make_fake_runner(exc=RuntimeError("Solver diverged"))
    run = run_analysis(project, "a1", runner)

    assert isinstance(run, Run)
    assert run.analysis_id == "a1"
    assert run.status == "failed"
    assert "Solver diverged" in run.error_message
    assert project.workspace.runs[-1] is run
