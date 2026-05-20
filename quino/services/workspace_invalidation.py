from __future__ import annotations

from quino.domain.model import Project
from quino.domain.workspace import Workspace


def _mark_stale(entry, reason: str) -> None:
    if entry.status == "running":
        return
    entry.status = "stale"
    if reason not in entry.stale_reasons:
        entry.stale_reasons.append(reason)


def _ensure_workspace(project: Project) -> Workspace:
    if project.workspace is None:
        project.workspace = Workspace()
    return project.workspace


def invalidate_on_model_change(project: Project) -> None:
    """Mark every run entry as stale when the base model changes."""
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        for entry in run.entries:
            _mark_stale(entry, "model_changed")


def invalidate_on_case_change(project: Project, case_id: str) -> None:
    """Mark entries that belong to *case_id* as stale."""
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        for entry in run.entries:
            if entry.case_id == case_id:
                _mark_stale(entry, f"case_changed:{case_id}")


def invalidate_on_study_change(project: Project, study_id: str) -> None:
    """Mark all entries of runs linked to *study_id* as stale."""
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        if run.study_id == study_id:
            for entry in run.entries:
                _mark_stale(entry, f"study_changed:{study_id}")


def invalidate_on_analysis_change(project: Project, analysis_id: str) -> None:
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        if run.analysis_id == analysis_id:
            for entry in run.entries:
                _mark_stale(entry, f"analysis_changed:{analysis_id}")


def invalidate_on_pose_change(project: Project, workspace_pose_id: str) -> None:
    workspace = _ensure_workspace(project)
    analysis_ids = {
        analysis.id for analysis in workspace.analyses
        if analysis.workspace_pose_id == workspace_pose_id
    }
    for run in workspace.runs:
        if run.analysis_id in analysis_ids:
            for entry in run.entries:
                _mark_stale(entry, f"pose_changed:{workspace_pose_id}")


def invalidate_on_baseline_change(project: Project, baseline_id: str) -> None:
    """Mark entries whose baseline (or case baseline) matches *baseline_id* as stale."""
    workspace = _ensure_workspace(project)
    case_ids = {c.id for c in workspace.cases if c.baseline_id == baseline_id}
    for run in workspace.runs:
        for entry in run.entries:
            if entry.baseline_id == baseline_id and entry.scope == "baseline":
                _mark_stale(entry, f"baseline_changed:{baseline_id}")
            elif entry.case_id in case_ids:
                _mark_stale(entry, f"baseline_changed:{baseline_id}")
