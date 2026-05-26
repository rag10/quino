from __future__ import annotations

from quino.domain.workspace import Workspace
from quino.services.workspace_staleness import mark_descendants_stale
from quino.services.run_invalidation import mark_all_runs_stale, mark_runs_stale_for_pose


def invalidate_on_model_change(workspace: Workspace, case_id: str) -> None:
    """Stale runs of the given case and all descendants."""
    mark_descendants_stale(workspace, case_id)


def invalidate_on_case_change(workspace: Workspace, case_id: str) -> None:
    """Same as invalidate_on_model_change — case edits propagate down."""
    mark_descendants_stale(workspace, case_id)


def invalidate_on_analysis_change(workspace: Workspace, analysis_id: str) -> None:
    """Stale runs of the specific analysis."""
    for case in workspace.cases.values():
        for run in case.runs:
            if run.analysis_id == analysis_id:
                if run.status in {"ok", "partial"}:
                    run.status = "stale"
                    if f"analysis_changed:{analysis_id}" not in run.warnings:
                        run.warnings.append(f"analysis_changed:{analysis_id}")


def invalidate_on_pose_change(workspace: Workspace, pose_id: str) -> None:
    mark_runs_stale_for_pose(workspace, pose_id, reason=f"pose_changed:{pose_id}")
