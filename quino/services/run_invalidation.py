from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from quino.domain.workspace import Workspace


def mark_runs_stale(workspace: Workspace, case_id: str, *, reason: str) -> int:
    """Flip every ok / partial run of every analysis attached to *case_id*
    to status='stale'. Returns how many runs were affected. The reason is
    appended to each run's warnings list with an ISO timestamp."""
    analysis_ids = {a.id for a in workspace.analyses if a.case_id == case_id}
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
