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
    """Stale the run state of the specific analysis (run state lives on it)."""
    for case in workspace.cases.values():
        for analysis in case.analyses:
            if analysis.id == analysis_id and analysis.status in {"ok", "partial"}:
                analysis.status = "stale"
                warning = f"analysis_changed:{analysis_id}"
                if warning not in analysis.warnings:
                    analysis.warnings.append(warning)


def invalidate_on_pose_change(workspace: Workspace, pose_id: str) -> None:
    mark_runs_stale_for_pose(workspace, pose_id, reason=f"pose_changed:{pose_id}")
