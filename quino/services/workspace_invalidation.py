from __future__ import annotations

from quino.domain.workspace import Workspace
from quino.services.workspace_staleness import mark_descendants_stale


def _ensure_workspace(project) -> Workspace:
    if project.workspace is None:
        project.workspace = Workspace()
    return project.workspace


def _mark_run_stale(run, reason: str) -> None:
    if run.status in {"ok", "partial"}:
        run.status = "stale"
        if reason not in run.warnings:
            run.warnings.append(reason)


def invalidate_on_model_change(project) -> None:
    """Mark every ok / partial run as stale when the base model changes."""
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        _mark_run_stale(run, "model_changed")


def invalidate_on_case_change(project, case_id: str) -> None:
    """Mark runs of analyses attached to *case_id* as stale."""
    workspace = _ensure_workspace(project)
    analysis_ids = {a.id for a in workspace.analyses if a.case_id == case_id}
    for run in workspace.runs:
        if run.analysis_id in analysis_ids:
            _mark_run_stale(run, f"case_changed:{case_id}")
    mark_descendants_stale(workspace, case_id)


def invalidate_on_analysis_change(project, analysis_id: str) -> None:
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        if run.analysis_id == analysis_id:
            _mark_run_stale(run, f"analysis_changed:{analysis_id}")


def invalidate_on_pose_change(project, workspace_pose_id: str) -> None:
    workspace = _ensure_workspace(project)
    analysis_ids = {
        analysis.id for analysis in workspace.analyses
        if analysis.workspace_pose_id == workspace_pose_id
    }
    for run in workspace.runs:
        if run.analysis_id in analysis_ids:
            _mark_run_stale(run, f"pose_changed:{workspace_pose_id}")


def invalidate_on_baseline_change(project, baseline_id: str) -> None:
    """Mark runs whose analysis baseline (or case baseline) matches *baseline_id* as stale."""
    workspace = _ensure_workspace(project)
    case_ids = {c.id for c in workspace.cases if c.baseline_id == baseline_id}
    analysis_ids = {
        a.id for a in workspace.analyses
        if a.baseline_id == baseline_id or a.case_id in case_ids
    }
    for run in workspace.runs:
        if run.analysis_id in analysis_ids:
            _mark_run_stale(run, f"baseline_changed:{baseline_id}")
