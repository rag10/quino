from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from quino.domain.model import Model, SimulationResult
from quino.domain.workspace import (
    Analysis,
    ArtifactRef,
    Case,
    ResultRef,
    Workspace,
)

# NOTE (Fase 1.10): the ``Run`` domain entity and ``Case.runs`` were removed;
# run state now lives flattened on ``Analysis``. This run-execution machinery
# still constructs ``Run`` objects and appends to ``case.runs`` and has NOT yet
# been migrated to the Analysis-based model. A minimal local placeholder keeps
# the module importable; full migration is deferred to a later Fase.
from dataclasses import field as _field


@dataclass
class Run:  # pragma: no cover - deferred run-machinery placeholder
    id: str
    analysis_id: str
    created_at: str
    finished_at: str | None = None
    status: str = "to_be_run"
    note: str = ""
    result_ref: "ResultRef | None" = None
    artifacts: list = _field(default_factory=list)
    metrics: dict = _field(default_factory=dict)
    warnings: list = _field(default_factory=list)
    error_message: str = ""
    config_snapshot: dict = _field(default_factory=dict)


@dataclass
class _CaseAsProject:
    """Minimal adapter making a Case look like a Project for analysis runners.

    Now delegates to ``_WorkspaceProjectProxy`` so the full set of
    project-like attributes (sensor_outputs, reaction_outputs, sketch, etc.)
    is available to the solver adapter.
    """
    model: Model
    parameters: list
    poses: list
    workspace: None = None

    @classmethod
    def from_case(cls, case: Case, workspace: Workspace):
        from quino.application._context import _WorkspaceProjectProxy
        return _WorkspaceProjectProxy(workspace, case)


def _next_run_id(case: Case) -> str:
    existing = {r.id for r in case.runs}
    n = 1
    while f"run-{n}" in existing:
        n += 1
    return f"run-{n}"


def run_analysis(
    workspace: Workspace,
    case: Case,
    analysis_id: str,
    simulation_runner,
    *,
    cancel_event=None,
    run: Run | None = None,
    project_dir: Path | None = None,
) -> Run:
    analysis = next((a for a in case.analyses if a.id == analysis_id), None)
    if analysis is None:
        raise ValueError(f"Analysis {analysis_id!r} not found in case {case.id!r}")

    if run is None:
        run = Run(
            id=_next_run_id(case),
            analysis_id=analysis.id,
            created_at=datetime.now().isoformat(),
            status="running",
            config_snapshot=asdict(analysis.config),
        )

    # No composition — case.model is the authoritative model
    return _run_with_model(case.model, workspace, case, analysis, simulation_runner, run, cancel_event, project_dir)


def _run_with_model(
    model: Model,
    workspace: Workspace,
    case: Case,
    analysis: Analysis,
    runner,
    run: Run,
    cancel_event,
    project_dir: Path | None,
) -> Run:
    project = _CaseAsProject.from_case(case, workspace)
    try:
        if runner is None:
            raise RuntimeError("No simulation runner available")

        result = runner.run(
            project,
            analysis,
            initial_pose=None,
            cancel_event=cancel_event,
            run=run,
            project_dir=project_dir,
        )

        cancelled = (
            cancel_event is not None and cancel_event.is_set()
        ) or getattr(result, "status", None) == "to_be_run"
        if cancelled:
            run.status = "to_be_run"
            run.error_message = getattr(result, "error_message", None) or "Cancelled by user"
            run.result_ref = None
            run.artifacts.clear()
            run.metrics.clear()
            return run

        if project_dir is not None:
            # Artifact persistence is handled by the runner itself (if it supports it).
            # For legacy SimulationResult objects, persist here.
            if isinstance(result, SimulationResult):
                save_result_artifact(project_dir, run, result)

        run.metrics = {}
        run.status = getattr(result, "status", "ok") if not isinstance(result, SimulationResult) else (
            "ok" if result.success else "failed"
        )
        if isinstance(result, SimulationResult) and not result.success and result.error:
            run.error_message = result.error
        elif hasattr(result, "error_message"):
            run.error_message = result.error_message
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
    finally:
        run.finished_at = datetime.now().isoformat()

    if run not in case.runs:
        case.runs.append(run)
    return run


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


def save_result_artifact(project_dir: Path, run: Run, result: SimulationResult) -> Path:
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
    checksum = _file_checksum(path)
    artifact_path = str(path.relative_to(project_dir))
    run.result_ref = ResultRef(
        run_entry_id=run.id,
        artifact_path=artifact_path,
        checksum=checksum,
    )
    run.artifacts = [
        ArtifactRef(
            kind="simulation_result",
            path=artifact_path,
            checksum=checksum,
        )
    ]
    return path


def _file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"
