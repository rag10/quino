from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from quino.domain.model import Project, SimulationResult
from quino.domain.workspace import (
    Baseline,
    Case,
    MetricDefinition,
    ResultRef,
    Run,
    RunEntry,
    Study,
    Workspace,
)
from quino.simulation.runner import SimulationRunner

from .workspace_composition import compose_project


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


def _execute_entry(
    project: Project,
    study: Study,
    case: Case | None = None,
    baseline_obj: Baseline | None = None,
    simulation_runner: SimulationRunner | None = None,
    project_dir: Path | None = None,
) -> RunEntry:
    entry = RunEntry(
        id=_next_id(project.workspace or Workspace(), "entry"),
        scope="baseline" if case is None else "case",
        case_id=case.id if case else None,
        status="running",
    )

    # Check if we can skip (incremental execution)
    # In practice, runs are new objects; skipping would require checking the
    # previous run of the same study. For simplicity in Fase 1, we always
    # execute. A more sophisticated implementation would compare checksums.
    try:
        composed = compose_project(project, study, case)
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

        entry.metrics = _extract_metrics(result, baseline_obj)
        entry.status = "ok" if result.success else "failed"
        if not result.success and result.error:
            entry.error_message = result.error
    except Exception as exc:
        entry.status = "failed"
        entry.error_message = str(exc)

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


def _find_baseline_for_study(workspace: Workspace, study: Study) -> Baseline | None:
    # For now, pick the first baseline if any. A more advanced implementation
    # could link baselines to studies explicitly.
    if not workspace.baselines:
        return None
    return workspace.baselines[0]


def _next_id(workspace: Workspace, prefix: str) -> str:
    seq = workspace.next_sequence
    workspace.next_sequence = seq + 1
    return f"{prefix}_{seq:03d}"


def _save_result_artifact(project_dir: Path, entry: RunEntry, result: SimulationResult) -> Path:
    artifact_dir = project_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{entry.id}_result.json"
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
