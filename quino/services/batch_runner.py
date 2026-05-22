from __future__ import annotations

from typing import Iterable

from quino.application.service import ApplicationService


def enqueue_case_analyses(app: ApplicationService, case_id: str) -> list:
    workspace = app.project.workspace
    targets = [analysis for analysis in workspace.analyses if analysis.case_id == case_id]
    return _enqueue_many(app, targets)


def enqueue_baseline_analyses(app: ApplicationService, baseline_id: str) -> list:
    workspace = app.project.workspace
    case_ids = {case.id for case in workspace.cases if case.baseline_id == baseline_id}
    targets = [
        analysis for analysis in workspace.analyses
        if analysis.baseline_id == baseline_id or analysis.case_id in case_ids
    ]
    return _enqueue_many(app, targets)


def enqueue_workspace_analyses(app: ApplicationService) -> list:
    return _enqueue_many(app, list(app.project.workspace.analyses))


def _enqueue_many(app: ApplicationService, analyses: Iterable) -> list:
    executor = app.ensure_executor()
    return [executor.enqueue(analysis.id) for analysis in analyses]
