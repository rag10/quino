from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from quino.domain.model import Project, SimulationResult
from quino.domain.workspace import (
    Analysis,
    ArtifactRef,
    Baseline,
    Case,
    MetricDefinition,
    ResultRef,
    Run,
    RunEntry,
    Study,
    Workspace,
    WorkspacePose,
)
from quino.simulation.runner import SimulationRunner

from .workspace_composition import compose_project, compose_project_hash


def run_study(
    project: Project,
    study_id: str,
    simulation_runner: SimulationRunner,
    project_dir: Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Run:
    """Execute a study incrementally and return a new Run.

    Entries that are already *ok* and not *stale* are skipped.
    """
    workspace = project.workspace
    if workspace is None:
        raise ValueError("Project has no workspace")

    study = _find_study(workspace, study_id)
    cases = _resolve_cases_for_study(workspace, study)
    baseline = _find_baseline_for_study(workspace, study)

    run = Run(
        id=_next_id(workspace, "run"),
        study_id=study_id,
        created_at=datetime.now().isoformat(),
        status="running",
        entries=[],
    )

    total_entries = (1 if study.mask.include_baseline else 0) + len(cases)
    completed = 0

    # Baseline entry
    if study.mask.include_baseline:
        entry = _execute_entry(
            project, study, baseline_obj=baseline, simulation_runner=simulation_runner, project_dir=project_dir
        )
        run.entries.append(entry)
        completed += 1
        if progress_callback:
            progress_callback(completed, total_entries)

    # Case entries
    for case in cases:
        entry = _execute_entry(
            project, study, case=case, simulation_runner=simulation_runner, project_dir=project_dir
        )
        run.entries.append(entry)
        completed += 1
        if progress_callback:
            progress_callback(completed, total_entries)

    run.status = _derive_run_status(run)
    workspace.runs.append(run)
    return run


def run_analysis(
    project: Project,
    analysis_id: str,
    simulation_runner: SimulationRunner,
    project_dir: Path | None = None,
) -> Run:
    workspace = project.workspace
    if workspace is None:
        raise ValueError("Project has no workspace")

    analysis = _find_analysis(workspace, analysis_id)
    case = _find_case(workspace, analysis.case_id) if analysis.case_id is not None else None
    baseline = _find_baseline(workspace, analysis.baseline_id) if analysis.baseline_id is not None else None
    pose = _find_workspace_pose(workspace, analysis.workspace_pose_id) if analysis.workspace_pose_id is not None else None
    study = Study(
        id=f"analysis::{analysis.id}",
        name=analysis.name,
        study_type=analysis.analysis_type,
        config=analysis.config,
    )

    run = Run(
        id=_next_id(workspace, "run"),
        study_id=None,
        analysis_id=analysis.id,
        created_at=datetime.now().isoformat(),
        status="running",
        entries=[],
    )
    entry = _execute_entry(
        project,
        study,
        case=case,
        baseline_obj=baseline,
        workspace_pose=pose,
        simulation_runner=simulation_runner,
        project_dir=project_dir,
    )
    run.entries.append(entry)
    run.status = _derive_run_status(run)
    workspace.runs.append(run)
    return run


def _execute_entry(
    project: Project,
    study: Study,
    case: Case | None = None,
    baseline_obj: Baseline | None = None,
    workspace_pose: WorkspacePose | None = None,
    simulation_runner: SimulationRunner | None = None,
    project_dir: Path | None = None,
) -> RunEntry:
    workspace = project.workspace or Workspace()
    entry = RunEntry(
        id=_next_id(workspace, "entry"),
        scope="baseline" if case is None else "case",
        baseline_id=baseline_obj.id if baseline_obj is not None else _resolve_entry_baseline_id(project, case),
        case_id=case.id if case else None,
        status="running",
        started_at=datetime.now().isoformat(),
    )

    try:
        composed = compose_project(project, study, case)
        _apply_workspace_pose(composed, workspace_pose)
        entry.fingerprint = _compute_entry_fingerprint(composed, study)
        previous = _find_previous_entry(workspace, study.id, entry)
        if previous is not None and previous.fingerprint == entry.fingerprint and previous.status == "ok":
            entry.status = "ok"
            entry.finished_at = datetime.now().isoformat()
            entry.updated_at = entry.finished_at
            entry.result_ref = previous.result_ref
            entry.artifacts = list(previous.artifacts)
            entry.metrics = dict(previous.metrics)
            return entry

        runner = simulation_runner
        if runner is None:
            raise RuntimeError("No simulation runner available")
        result = runner.run(
            composed,
            duration=study.config.duration,
            steps=study.config.steps,
        )

        if project_dir is not None:
            artifact_path = _save_result_artifact(project_dir, entry, result)
            entry.result_ref = ResultRef(
                run_entry_id=entry.id,
                artifact_path=str(artifact_path.relative_to(project_dir)),
                checksum=_file_checksum(artifact_path),
            )
            entry.artifacts.append(
                ArtifactRef(
                    kind="simulation_result",
                    path=entry.result_ref.artifact_path,
                    checksum=entry.result_ref.checksum,
                )
            )

        entry.metrics = _extract_metrics(result, baseline_obj)
        entry.status = "ok" if result.success else "failed"
        if not result.success and result.error:
            entry.error_message = result.error
    except Exception as exc:
        entry.status = "failed"
        entry.error_message = str(exc)
    finally:
        finished_at = datetime.now().isoformat()
        entry.finished_at = finished_at
        entry.updated_at = finished_at

    return entry


def _extract_metrics(result: SimulationResult, baseline: Baseline | None) -> dict[str, float]:
    """Extract metrics from a simulation result using baseline definitions."""
    if baseline is None or not baseline.metrics:
        return {}

    metrics: dict[str, float] = {}
    for key, definition in baseline.metrics.items():
        value = _evaluate_metric_extractor(result, definition.extractor)
        if value is not None:
            metrics[key] = value
    return metrics


def _evaluate_metric_extractor(result: SimulationResult, extractor: str) -> float | None:
    """Evaluate a simple metric extractor string against a SimulationResult.

    Supported patterns:
    - ``frames[-1].<key>``  → value of <key> in last frame
    - ``time[-1]``          → last time value
    - ``max.<key>``         → maximum of <key> across all frames
    - ``min.<key>``         → minimum of <key> across all frames
    """
    try:
        if extractor == "time[-1]":
            return result.time[-1] if result.time else None

        if extractor.startswith("frames[-1]."):
            key = extractor[len("frames[-1].") :]
            if result.frames:
                return result.frames[-1].get(key)
            return None

        if extractor.startswith("max."):
            key = extractor[len("max.") :]
            values = [frame.get(key) for frame in result.frames if key in frame]
            return max(values) if values else None

        if extractor.startswith("min."):
            key = extractor[len("min.") :]
            values = [frame.get(key) for frame in result.frames if key in frame]
            return min(values) if values else None

        return None
    except Exception:
        return None


def _derive_run_status(run: Run) -> str:
    if not run.entries:
        return "not_run"
    statuses = {e.status for e in run.entries}
    if "running" in statuses:
        return "running"
    if "failed" in statuses:
        return "failed"
    if all(s == "ok" for s in statuses):
        return "completed"
    return "not_run"


def _resolve_cases_for_study(workspace: Workspace, study: Study) -> list[Case]:
    """Return the list of cases that should be executed for this study."""
    cases = list(workspace.cases)
    if study.mask.include_cases is not None:
        cases = [c for c in cases if c.id in study.mask.include_cases]
    if study.mask.exclude_cases is not None:
        cases = [c for c in cases if c.id not in study.mask.exclude_cases]
    return cases


def _find_study(workspace: Workspace, study_id: str) -> Study:
    for study in workspace.studies:
        if study.id == study_id:
            return study
    raise ValueError(f"Study {study_id!r} not found")


def _find_analysis(workspace: Workspace, analysis_id: str) -> Analysis:
    for analysis in workspace.analyses:
        if analysis.id == analysis_id:
            return analysis
    raise ValueError(f"Analysis {analysis_id!r} not found")


def _find_case(workspace: Workspace, case_id: str) -> Case:
    for case in workspace.cases:
        if case.id == case_id:
            return case
    raise ValueError(f"Case {case_id!r} not found")


def _find_baseline(workspace: Workspace, baseline_id: str) -> Baseline:
    for baseline in workspace.baselines:
        if baseline.id == baseline_id:
            return baseline
    raise ValueError(f"Baseline {baseline_id!r} not found")


def _find_workspace_pose(workspace: Workspace, pose_id: str) -> WorkspacePose:
    for pose in workspace.poses:
        if pose.id == pose_id:
            return pose
    raise ValueError(f"Workspace pose {pose_id!r} not found")


def _find_baseline_for_study(workspace: Workspace, study: Study) -> Baseline | None:
    if not workspace.baselines:
        return None
    if workspace.active_baseline_id is not None:
        for baseline in workspace.baselines:
            if baseline.id == workspace.active_baseline_id:
                return baseline
    return workspace.baselines[0]


def _next_id(workspace: Workspace, prefix: str) -> str:
    seq = workspace.next_sequence
    workspace.next_sequence = seq + 1
    return f"{prefix}_{seq:03d}"


def _save_result_artifact(project_dir: Path, entry: RunEntry, result: SimulationResult) -> Path:
    artifact_dir = project_dir / "artifacts" / f"run_{entry.id}" / entry.id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / "result.json"
    data = {
        "success": result.success,
        "time": result.time,
        "frames": result.frames,
        "states": result.states,
        "warnings": result.warnings,
        "messages": result.messages,
        "error": result.error,
        "backend": result.backend,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def _compute_entry_fingerprint(project: Project, study: Study) -> str:
    payload = {
        "composed_model_hash": compose_project_hash(project),
        "study_config": {
            "duration": study.config.duration,
            "steps": study.config.steps,
            "translation_driver_mode": study.config.translation_driver_mode,
            "solver_settings": dict(study.config.solver_settings),
            "study_type": study.study_type,
        },
        "schema_version": project.schema_version,
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _find_previous_entry(workspace: Workspace, study_id: str, current: RunEntry) -> RunEntry | None:
    analysis_id = study_id[len("analysis::") :] if study_id.startswith("analysis::") else None
    for run in reversed(workspace.runs):
        if analysis_id is not None:
            if run.analysis_id != analysis_id:
                continue
        elif run.study_id != study_id:
            continue
        for entry in run.entries:
            if entry.scope != current.scope:
                continue
            if entry.baseline_id != current.baseline_id:
                continue
            if entry.case_id != current.case_id:
                continue
            return entry
    return None


def _apply_workspace_pose(project: Project, workspace_pose: WorkspacePose | None) -> None:
    if workspace_pose is None or workspace_pose.is_default:
        project.simulation_initial_pose_id = None
        return
    project.simulation_initial_pose_id = workspace_pose.project_pose_id


def _resolve_entry_baseline_id(project: Project, case: Case | None) -> str | None:
    workspace = project.workspace
    if case is not None and case.baseline_id is not None:
        return case.baseline_id
    if workspace is None:
        return None
    if workspace.active_baseline_id is not None:
        return workspace.active_baseline_id
    if workspace.baselines:
        return workspace.baselines[0].id
    return None
