from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from quino.domain.workspace import Workspace


def _mark_set_stale(workspace: Workspace, analysis_ids: set[str], reason: str) -> int:
    """Flip every ok / partial run whose analysis_id is in *analysis_ids*
    to status='stale' and append a timestamped reason to its warnings.
    Returns how many runs were affected."""
    if not analysis_ids:
        return 0
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    affected = 0
    for run in workspace.runs:
        if run.analysis_id not in analysis_ids:
            continue
        if run.status not in {"ok", "partial"}:
            continue
        run.status = "stale"
        run.warnings.append(f"[{timestamp}] {reason}")
        affected += 1
    return affected


def mark_runs_stale(workspace: Workspace, case_id: str, *, reason: str) -> int:
    """Stale every run of every analysis attached to *case_id*.

    Kept as a back-compat shim — prefer `mark_runs_stale_for_case` for
    new code; baseline/pose/model scopes have their own helpers below."""
    return _mark_set_stale(
        workspace,
        {a.id for a in workspace.analyses if a.case_id == case_id},
        reason,
    )


def mark_runs_stale_for_case(workspace: Workspace, case_id: str, *, reason: str) -> int:
    return _mark_set_stale(
        workspace,
        {a.id for a in workspace.analyses if a.case_id == case_id},
        reason,
    )


def mark_runs_stale_for_baseline(workspace: Workspace, baseline_id: str, *, reason: str) -> int:
    """Stale every run of every analysis bound directly to *baseline_id*
    (i.e. case_id is None) and of every analysis whose case hangs off
    *baseline_id*. Used when the user edits the shared model while
    sitting on the baseline."""
    case_ids = {c.id for c in workspace.cases if c.baseline_id == baseline_id}
    analysis_ids = {
        a.id for a in workspace.analyses
        if (a.case_id is None and a.baseline_id == baseline_id)
        or (a.case_id in case_ids)
    }
    return _mark_set_stale(workspace, analysis_ids, reason)


def mark_runs_stale_for_pose(workspace: Workspace, project_pose_id: str, *, reason: str) -> int:
    """Stale every run of every analysis whose WorkspacePose binds to the
    project Pose identified by *project_pose_id* (the in-domain Pose
    that pose-mode edits actually mutate)."""
    workspace_pose_ids = {
        wp.id for wp in workspace.poses if wp.project_pose_id == project_pose_id
    }
    if not workspace_pose_ids:
        return 0
    analysis_ids = {
        a.id for a in workspace.analyses
        if a.workspace_pose_id in workspace_pose_ids
    }
    return _mark_set_stale(workspace, analysis_ids, reason)


def mark_all_runs_stale(workspace: Workspace, *, reason: str) -> int:
    """Stale every run in the workspace. Used when something changes that
    affects the entire model (e.g. a shared parameter)."""
    return _mark_set_stale(
        workspace,
        {a.id for a in workspace.analyses},
        reason,
    )


def delete_run(workspace: Workspace, project_dir: Path | None, run_id: str) -> bool:
    """Remove a run from the workspace and unlink its on-disk artifact.
    Returns True if a run was actually removed."""
    target = next((r for r in workspace.runs if r.id == run_id), None)
    if target is None:
        return False
    if project_dir is not None and target.result_ref is not None:
        artifact = project_dir / target.result_ref.artifact_path
        try:
            artifact.unlink(missing_ok=True)
        except OSError:
            pass
    workspace.runs = [r for r in workspace.runs if r.id != run_id]
    return True
