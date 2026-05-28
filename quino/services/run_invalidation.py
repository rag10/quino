from __future__ import annotations

from datetime import datetime, timezone
import dataclasses
import re

from quino.domain.workspace import Case, Workspace


def _mark_set_stale(case: Case, analysis_ids: set[str], reason: str) -> int:
    """Flip every ok/partial run in *case* whose analysis_id is in *analysis_ids* to 'stale'."""
    if not analysis_ids:
        return 0
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    affected = 0
    for run in case.runs:
        if run.analysis_id not in analysis_ids:
            continue
        if run.status not in {"ok", "partial"}:
            continue
        run.status = "stale"
        run.warnings.append(f"[{timestamp}] {reason}")
        affected += 1
    return affected


def mark_runs_stale_for_case(case: Case, *, reason: str) -> int:
    """Stale every run in the given case."""
    analysis_ids = {a.id for a in case.analyses}
    return _mark_set_stale(case, analysis_ids, reason)


def mark_all_runs_stale(workspace: Workspace, *, reason: str) -> int:
    """Stale every run in every case of the workspace."""
    total = 0
    for case in workspace.cases.values():
        total += mark_runs_stale_for_case(case, reason=reason)
    return total


def mark_runs_stale_for_parameter(workspace: Workspace, parameter_name: str, *, reason: str) -> int:
    """Stale only cases whose model expressions reference *parameter_name*."""
    total = 0
    for case in workspace.cases.values():
        if _case_uses_parameter(case, parameter_name):
            total += mark_runs_stale_for_case(case, reason=reason)
    return total


def mark_runs_stale_for_pose(workspace: Workspace, pose_id: str, *, reason: str) -> int:
    """Stale runs of analyses whose pose_id matches."""
    total = 0
    for case in workspace.cases.values():
        analysis_ids = {a.id for a in case.analyses if a.pose_id == pose_id}
        total += _mark_set_stale(case, analysis_ids, reason)
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
        for field in dataclasses.fields(value):
            if _contains_parameter_token(getattr(value, field.name), token):
                return True
    return False


def delete_run(workspace: Workspace, project_dir, run_id: str) -> bool:
    """Remove a run from its case and unlink the on-disk artifact."""
    from pathlib import Path
    for case in workspace.cases.values():
        target = next((r for r in case.runs if r.id == run_id), None)
        if target is None:
            continue
        if project_dir is not None and target.result_ref is not None:
            artifact = Path(project_dir) / target.result_ref.artifact_path
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                pass
        case.runs = [r for r in case.runs if r.id != run_id]
        return True
    return False
