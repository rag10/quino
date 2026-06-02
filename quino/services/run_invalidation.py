from __future__ import annotations

from datetime import datetime, timezone
import dataclasses
import re

from quino.domain.workspace import Analysis, Case, Workspace


def _stale_analyses(case: Case, analysis_ids: set[str] | None, reason: str) -> int:
    """Flip every ok/partial Analysis in *case* (filtered by analysis_ids if given) to 'stale'."""
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    affected = 0
    for analysis in case.analyses:
        if analysis_ids is not None and analysis.id not in analysis_ids:
            continue
        if analysis.status not in {"ok", "partial"}:
            continue
        analysis.status = "stale"
        analysis.warnings.append(f"[{timestamp}] {reason}")
        affected += 1
    return affected


# Backward-compat alias (used by _context.py until it is adapted).
_mark_set_stale = _stale_analyses


def mark_runs_stale_for_case(case: Case, *, reason: str) -> int:
    """Stale every ok/partial analysis in the given case."""
    return _stale_analyses(case, None, reason)


def mark_all_runs_stale(workspace: Workspace, *, reason: str) -> int:
    """Stale every ok/partial analysis in every case of the workspace."""
    return sum(mark_runs_stale_for_case(case, reason=reason) for case in workspace.cases.values())


def mark_runs_stale_for_parameter(workspace: Workspace, parameter_name: str, *, reason: str) -> int:
    """Stale only cases whose model expressions reference *parameter_name*."""
    total = 0
    for case in workspace.cases.values():
        if _case_uses_parameter(case, parameter_name):
            total += mark_runs_stale_for_case(case, reason=reason)
    return total


def mark_runs_stale_for_pose(workspace: Workspace, pose_id: str, *, reason: str) -> int:
    """Stale analyses whose pose_id matches."""
    total = 0
    for case in workspace.cases.values():
        ids = {a.id for a in case.analyses if a.pose_id == pose_id}
        total += _stale_analyses(case, ids, reason)
    return total


def _case_uses_parameter(case: Case, parameter_name: str) -> bool:
    token = re.compile(rf"\b{re.escape(parameter_name)}\b")
    return _contains_parameter_token(case.model, token)


def _contains_parameter_token(value, token: re.Pattern[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(token.search(value))
    if isinstance(value, (int, float, bool)):
        return False
    expression = getattr(value, "expression", None)
    if isinstance(expression, str) and token.search(expression):
        return True
    if isinstance(value, dict):
        return any(_contains_parameter_token(item, token) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_parameter_token(item, token) for item in value)
    if dataclasses.is_dataclass(value):
        return any(_contains_parameter_token(getattr(value, f.name), token)
                   for f in dataclasses.fields(value))
    return False


def delete_run(workspace: Workspace, project_dir, analysis_id: str) -> bool:
    """Reset the run state of an analysis and unlink its on-disk artifact."""
    from pathlib import Path
    for case in workspace.cases.values():
        target = next((a for a in case.analyses if a.id == analysis_id), None)
        if target is None:
            continue
        if project_dir is not None and target.result_ref is not None:
            artifact = Path(project_dir) / target.result_ref.artifact_path
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                pass
        target.status = "to_be_run"
        target.result_ref = None
        target.artifacts = []
        target.finished_at = None
        return True
    return False
