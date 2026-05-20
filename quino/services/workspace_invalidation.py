from __future__ import annotations

from quino.domain.model import Project
from quino.domain.workspace import Workspace


def _ensure_workspace(project: Project) -> Workspace:
    if project.workspace is None:
        project.workspace = Workspace()
    return project.workspace


def invalidate_on_model_change(project: Project) -> None:
    """Mark every run entry as stale when the base model changes."""
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        for entry in run.entries:
            if entry.status != "running":
                entry.status = "stale"


def invalidate_on_case_change(project: Project, case_id: str) -> None:
    """Mark entries that belong to *case_id* as stale."""
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        for entry in run.entries:
            if entry.status == "running":
                continue
            if entry.case_id == case_id:
                entry.status = "stale"


def invalidate_on_study_change(project: Project, study_id: str) -> None:
    """Mark all entries of runs linked to *study_id* as stale."""
    workspace = _ensure_workspace(project)
    for run in workspace.runs:
        if run.study_id == study_id:
            for entry in run.entries:
                if entry.status != "running":
                    entry.status = "stale"


def invalidate_on_baseline_change(project: Project, baseline_id: str) -> None:
    """Mark entries whose baseline (or case baseline) matches *baseline_id* as stale."""
    workspace = _ensure_workspace(project)
    # Collect case ids linked to this baseline
    case_ids = {c.id for c in workspace.cases if c.baseline_id == baseline_id}
    for run in workspace.runs:
        for entry in run.entries:
            if entry.status == "running":
                continue
            if entry.scope == "baseline" and entry.case_id is None:
                # Baseline entry: mark stale if baseline changed
                # We don't store baseline_id directly on entry; infer from study/case
                # For simplicity, mark all baseline entries stale when any baseline changes
                entry.status = "stale"
            elif entry.case_id in case_ids:
                entry.status = "stale"
