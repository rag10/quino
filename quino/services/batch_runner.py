from __future__ import annotations

from typing import Iterable

from quino.application.service import ApplicationService


def enqueue_case_analyses(app: ApplicationService, case_id: str) -> list:
    ws = app._workspace
    case = ws.cases.get(case_id)
    if case is None:
        return []
    return _enqueue_many(app, case.analyses)


def enqueue_workspace_analyses(app: ApplicationService) -> list:
    ws = app._workspace
    if ws is None:
        return []
    all_analyses = [a for case in ws.cases.values() for a in case.analyses]
    return _enqueue_many(app, all_analyses)


def _enqueue_many(app: ApplicationService, analyses: Iterable) -> list:
    executor = app.ensure_executor()
    return [executor.enqueue(analysis.id) for analysis in analyses]
