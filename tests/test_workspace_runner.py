from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from quino.domain.model import Project, SimulationResult
from quino.domain.workspace import Analysis, Baseline, Case, MetricDefinition, ResultRef, Run, RunEntry, Study, StudyConfig, Workspace, WorkspacePose
from quino.services.workspace_runner import (
    _derive_run_status,
    _evaluate_metric_extractor,
    _extract_metrics,
    _resolve_cases_for_study,
    run_analysis,
    run_study,
)


class FakeAdapter:
    name = "fake"

    def __init__(self, result: SimulationResult | None = None) -> None:
        self._result = result
        self.calls = 0
        self.last_pose_id = None

    def is_available(self) -> bool:
        return True

    def run(self, project: Project, **kwargs: Any) -> SimulationResult:
        self.calls += 1
        self.last_pose_id = project.simulation_initial_pose_id
        if self._result is not None:
            return self._result
        return SimulationResult(
            success=True,
            time=[0.0, 0.5, 1.0],
            frames=[{"body_001.x": 0.0}, {"body_001.x": 0.5}, {"body_001.x": 1.0}],
        )


def _make_fake_runner(result: SimulationResult | None = None):
    from quino.simulation.runner import SimulationRunner
    adapter = FakeAdapter(result)
    return SimulationRunner(adapter), adapter


def test_run_study_with_baseline_and_cases(tmp_path: Path) -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        baselines=[Baseline(id="b1", name="Ref")],
        cases=[
            Case(id="c1", name="Case1"),
            Case(id="c2", name="Case2"),
        ],
        studies=[
            Study(
                id="s1",
                name="Study1",
                config=StudyConfig(duration=1.0, steps=10),
            )
        ],
    )

    runner, _adapter = _make_fake_runner()
    run = run_study(project, "s1", runner, project_dir=tmp_path)

    assert run.study_id == "s1"
    assert run.status == "completed"
    assert len(run.entries) == 3  # baseline + 2 cases
    assert run.entries[0].scope == "baseline"
    assert run.entries[0].status == "ok"
    assert run.entries[1].scope == "case"
    assert run.entries[1].case_id == "c1"


def test_run_study_skips_baseline_when_masked() -> None:
    from quino.domain.workspace import StudyMask

    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        baselines=[Baseline(id="b1", name="Ref")],
        cases=[Case(id="c1", name="Case1")],
        studies=[
            Study(
                id="s1",
                name="Study1",
                config=StudyConfig(duration=1.0, steps=10),
                mask=StudyMask(include_baseline=False),
            )
        ],
    )

    runner, _adapter = _make_fake_runner()
    run = run_study(project, "s1", runner)

    assert len(run.entries) == 1
    assert run.entries[0].scope == "case"


def test_run_study_failed_entry() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        baselines=[Baseline(id="b1", name="Ref")],
        studies=[Study(id="s1", name="Study1", config=StudyConfig(duration=1.0, steps=10))],
    )

    failed_result = SimulationResult(success=False, error="Solver diverged")
    runner, _adapter = _make_fake_runner(failed_result)
    run = run_study(project, "s1", runner)

    assert run.status == "failed"
    assert run.entries[0].status == "failed"
    assert "Solver diverged" in run.entries[0].error_message


def test_derive_run_status() -> None:
    from quino.domain.workspace import Run, RunEntry

    run = Run(id="r1", study_id="s1", created_at="t")
    assert _derive_run_status(run) == "not_run"

    run.entries = [RunEntry(id="e1", scope="baseline", status="ok")]
    assert _derive_run_status(run) == "completed"

    run.entries = [
        RunEntry(id="e1", scope="baseline", status="ok"),
        RunEntry(id="e2", scope="case", status="failed"),
    ]
    assert _derive_run_status(run) == "failed"

    run.entries = [
        RunEntry(id="e1", scope="baseline", status="running"),
    ]
    assert _derive_run_status(run) == "running"


def test_resolve_cases_for_study() -> None:
    from quino.domain.workspace import Case, Study, StudyMask, Workspace

    ws = Workspace(
        cases=[
            Case(id="c1", name="Case1"),
            Case(id="c2", name="Case2"),
            Case(id="c3", name="Case3"),
        ]
    )
    study = Study(id="s1", name="Study1", mask=StudyMask(include_cases=["c1", "c2"]))
    cases = _resolve_cases_for_study(ws, study)
    assert [c.id for c in cases] == ["c1", "c2"]

    study = Study(id="s1", name="Study1", mask=StudyMask(exclude_cases=["c2"]))
    cases = _resolve_cases_for_study(ws, study)
    assert [c.id for c in cases] == ["c1", "c3"]


def test_extract_metrics_with_baseline() -> None:
    baseline = Baseline(
        id="b1",
        name="Ref",
        metrics={
            "final_x": MetricDefinition(
                key="final_x", name="Final X", extractor="frames[-1].body_001.x"
            ),
            "max_x": MetricDefinition(
                key="max_x", name="Max X", extractor="max.body_001.x"
            ),
        },
    )
    result = SimulationResult(
        success=True,
        time=[0.0, 1.0],
        frames=[{"body_001.x": 0.0}, {"body_001.x": 2.0}],
    )
    metrics = _extract_metrics(result, baseline)
    assert metrics["final_x"] == 2.0
    assert metrics["max_x"] == 2.0


def test_evaluate_metric_extractor_frames_last() -> None:
    result = SimulationResult(
        success=True,
        frames=[{"a": 1.0}, {"a": 3.0}],
    )
    assert _evaluate_metric_extractor(result, "frames[-1].a") == 3.0
    assert _evaluate_metric_extractor(result, "frames[-1].b") is None


def test_evaluate_metric_extractor_max_min() -> None:
    result = SimulationResult(
        success=True,
        frames=[{"a": 1.0}, {"a": 5.0}, {"a": 2.0}],
    )
    assert _evaluate_metric_extractor(result, "max.a") == 5.0
    assert _evaluate_metric_extractor(result, "min.a") == 1.0


def test_evaluate_metric_extractor_time() -> None:
    result = SimulationResult(success=True, time=[0.0, 0.5, 1.0])
    assert _evaluate_metric_extractor(result, "time[-1]") == 1.0


def test_run_study_saves_artifact(tmp_path: Path) -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        baselines=[Baseline(id="b1", name="Ref")],
        studies=[Study(id="s1", name="Study1", config=StudyConfig(duration=1.0, steps=10))],
    )

    runner, _adapter = _make_fake_runner()
    run = run_study(project, "s1", runner, project_dir=tmp_path)

    assert run.entries[0].result_ref is not None
    artifact = tmp_path / run.entries[0].result_ref.artifact_path
    assert artifact.exists()
    assert run.entries[0].result_ref.checksum.startswith("sha256:")


def test_run_study_reuses_previous_ok_entry_when_fingerprint_matches() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        active_baseline_id="b1",
        baselines=[Baseline(id="b1", name="Ref")],
        studies=[Study(id="s1", name="Study1", config=StudyConfig(duration=1.0, steps=10))],
        runs=[
            Run(
                id="r0",
                study_id="s1",
                created_at="2026-05-19T10:00:00Z",
                status="completed",
                entries=[
                    RunEntry(
                        id="e0",
                        scope="baseline",
                        baseline_id="b1",
                        status="ok",
                        fingerprint="",
                        result_ref=ResultRef(
                            run_entry_id="e0",
                            artifact_path="artifacts/run_old/e0/result.json",
                            checksum="sha256:old",
                        ),
                        metrics={"final_x": 1.0},
                    )
                ],
            )
        ],
    )

    runner, adapter = _make_fake_runner()
    previous_entry = project.workspace.runs[0].entries[0]
    from quino.services.workspace_runner import _compute_entry_fingerprint

    previous_entry.fingerprint = _compute_entry_fingerprint(project, project.workspace.studies[0])
    run = run_study(project, "s1", runner)

    assert adapter.calls == 0
    assert run.entries[0].status == "ok"
    assert run.entries[0].result_ref is not None
    assert run.entries[0].result_ref.artifact_path == "artifacts/run_old/e0/result.json"


def test_run_analysis_uses_workspace_pose_and_case(tmp_path: Path) -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        baselines=[Baseline(id="b1", name="Ref")],
        cases=[Case(id="c1", name="Case1", baseline_id="b1")],
        poses=[WorkspacePose(id="wp1", name="Pose 1", case_id="c1", project_pose_id="pose_model_001")],
        analyses=[
            Analysis(
                id="a1",
                name="Dyn",
                analysis_type="dynamic",
                case_id="c1",
                baseline_id="b1",
                workspace_pose_id="wp1",
                config=StudyConfig(duration=1.0, steps=10),
            )
        ],
    )

    runner, adapter = _make_fake_runner()
    run = run_analysis(project, "a1", runner, project_dir=tmp_path)

    assert run.analysis_id == "a1"
    assert run.study_id is None
    assert len(run.entries) == 1
    assert run.entries[0].case_id == "c1"
    assert adapter.last_pose_id == "pose_model_001"


def test_run_analysis_reuses_previous_ok_entry_when_fingerprint_matches() -> None:
    project = Project(id="p1", name="Test", schema_version="0.2.0")
    project.workspace = Workspace(
        baselines=[Baseline(id="b1", name="Ref")],
        analyses=[Analysis(id="a1", name="Dyn", baseline_id="b1", config=StudyConfig(duration=1.0, steps=10))],
        runs=[
            Run(
                id="r0",
                study_id=None,
                analysis_id="a1",
                created_at="2026-05-19T10:00:00Z",
                status="completed",
                entries=[
                    RunEntry(
                        id="e0",
                        scope="baseline",
                        baseline_id="b1",
                        status="ok",
                        fingerprint="",
                        result_ref=ResultRef(
                            run_entry_id="e0",
                            artifact_path="artifacts/run_old/e0/result.json",
                            checksum="sha256:old",
                        ),
                        metrics={"final_x": 1.0},
                    )
                ],
            )
        ],
    )

    from quino.services.workspace_runner import _compute_entry_fingerprint

    synthetic_study = Study(id="analysis::a1", name="Dyn", study_type="dynamic", config=StudyConfig(duration=1.0, steps=10))
    project.workspace.runs[0].entries[0].fingerprint = _compute_entry_fingerprint(project, synthetic_study)
    runner, adapter = _make_fake_runner()

    run = run_analysis(project, "a1", runner)

    assert adapter.calls == 0
    assert run.entries[0].result_ref is not None
    assert run.entries[0].result_ref.artifact_path == "artifacts/run_old/e0/result.json"
