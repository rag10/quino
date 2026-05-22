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
    Workspace,
    WorkspacePose,
)
from quino.simulation.runner import SimulationRunner

from .workspace_composition import compose_project, compose_project_hash


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

    run = Run(
        id=_next_id(workspace, "run"),
        analysis_id=analysis.id,
        created_at=datetime.now().isoformat(),
        status="running",
        config_snapshot={f.name: getattr(analysis.config, f.name) for f in analysis.config.__dataclass_fields__.values()},
    )

    try:
        composed = compose_project(project, case=case)
        _apply_workspace_pose(composed, pose)

        runner = simulation_runner
        if runner is None:
            raise RuntimeError("No simulation runner available")
        result = runner.run(
            composed,
            duration=analysis.config.duration,
            steps=analysis.config.steps,
        )

        if project_dir is not None:
            artifact_path = _save_result_artifact(project_dir, run, result)
            run.result_ref = ResultRef(
                run_entry_id=run.id,
                artifact_path=str(artifact_path.relative_to(project_dir)),
                checksum=_file_checksum(artifact_path),
            )
            run.artifacts.append(
                ArtifactRef(
                    kind="simulation_result",
                    path=run.result_ref.artifact_path,
                    checksum=run.result_ref.checksum,
                )
            )

        run.metrics = _extract_metrics(result, baseline)
        run.status = "ok" if result.success else "failed"
        if not result.success and result.error:
            run.error_message = result.error
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
    finally:
        run.finished_at = datetime.now().isoformat()

    workspace.runs.append(run)
    return run


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


def _next_id(workspace: Workspace, prefix: str) -> str:
    seq = workspace.next_sequence
    workspace.next_sequence = seq + 1
    return f"{prefix}_{seq:03d}"


def load_result_artifact(project_dir: Path, run: Run) -> SimulationResult | None:
    """Re-hydrate the SimulationResult that a Run produced.

    Returns ``None`` when the run has no result_ref, when the artifact
    file is missing, or when the JSON is corrupt.
    """
    if run.result_ref is None or project_dir is None:
        return None
    artifact_path = project_dir / run.result_ref.artifact_path
    if not artifact_path.exists():
        return None
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return SimulationResult(
        success=bool(data.get("success", False)),
        time=list(data.get("time", [])),
        frames=list(data.get("frames", [])),
        states=list(data.get("states", [])),
        messages=list(data.get("messages", [])),
        error=data.get("error"),
        backend=data.get("backend"),
    )


def _save_result_artifact(project_dir: Path, run: Run, result: SimulationResult) -> Path:
    artifact_dir = project_dir / "artifacts" / f"run_{run.id}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / "result.json"
    data = {
        "success": result.success,
        "time": result.time,
        "frames": result.frames,
        "states": result.states,
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
