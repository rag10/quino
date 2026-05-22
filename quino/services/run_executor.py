from __future__ import annotations

import queue
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PySide6 import QtCore

from quino.analysis.registry import get_runner_for_type
from quino.domain.workspace import Run
from quino.services.workspace_composition import compose_project


@dataclass(slots=True)
class RunHandle:
    run_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self.cancel_event.set()

    def is_done(self) -> bool:
        return self.done_event.is_set()


@dataclass(slots=True)
class _QueuedJob:
    analysis_id: str
    run_id: str
    config_snapshot: dict
    cancel_event: threading.Event


class RunExecutor(QtCore.QObject):
    run_queued = QtCore.Signal(str)
    run_started = QtCore.Signal(str)
    run_progress = QtCore.Signal(str, int, int)
    run_finished = QtCore.Signal(str, str)

    def __init__(self, app_service, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.app_service = app_service
        self._queue: queue.Queue[_QueuedJob | None] = queue.Queue()
        self._stopping = threading.Event()
        self._worker = threading.Thread(target=self._loop, name="RunExecutor", daemon=True)
        self._worker.start()

    def enqueue(self, analysis_id: str) -> RunHandle:
        project = self.app_service.project
        if project is None or project.workspace is None:
            raise ValueError("No active workspace")
        workspace = project.workspace
        analysis = next((a for a in workspace.analyses if a.id == analysis_id), None)
        if analysis is None:
            raise ValueError(f"Analysis {analysis_id!r} not found")

        with self.app_service.workspace_lock:
            run_id = f"run_{workspace.next_sequence:03d}"
            workspace.next_sequence += 1
            run = Run(
                id=run_id,
                analysis_id=analysis_id,
                created_at=datetime.now(tz=timezone.utc).isoformat(),
                status="queued",
                config_snapshot=asdict(analysis.config),
            )
            workspace.runs.append(run)

        handle = RunHandle(run_id=run_id)
        self.app_service.pending_run_handles[run_id] = handle
        self._queue.put(
            _QueuedJob(
                analysis_id=analysis_id,
                run_id=run_id,
                config_snapshot=run.config_snapshot,
                cancel_event=handle.cancel_event,
            )
        )
        self.run_queued.emit(run_id)
        return handle

    def shutdown(self) -> None:
        self._stopping.set()
        self._queue.put(None)
        self._worker.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                job = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if job is None:
                break
            self._run_one(job)

    def _run_one(self, job: _QueuedJob) -> None:
        run = self._find_run(job.run_id)
        if run is None:
            return

        with self.app_service.workspace_lock:
            run.status = "running"
        self.run_started.emit(job.run_id)

        try:
            project = self.app_service.project
            if project is None or project.workspace is None:
                raise ValueError("No active workspace")
            workspace = project.workspace
            analysis = next((a for a in workspace.analyses if a.id == job.analysis_id), None)
            if analysis is None:
                raise ValueError(f"Analysis {job.analysis_id!r} not found")
            case = next((c for c in workspace.cases if c.id == analysis.case_id), None) if analysis.case_id else None
            composed = compose_project(project, case=case)
            runner = get_runner_for_type(analysis.analysis_type)
            result = runner.run(
                composed,
                analysis,
                initial_pose=None,
                cancel_event=job.cancel_event,
                run=run,
                project_dir=self.app_service.current_project_dir,
            )
            with self.app_service.workspace_lock:
                if job.cancel_event.is_set() or result.status == "to_be_run":
                    run.status = "to_be_run"
                    run.error_message = result.error_message or "Cancelled by user"
                    run.result_ref = None
                    run.artifacts.clear()
                    run.metrics.clear()
                else:
                    run.status = result.status
                    run.error_message = result.error_message
        except Exception as exc:
            with self.app_service.workspace_lock:
                run.status = "failed"
                run.error_message = str(exc)
        finally:
            with self.app_service.workspace_lock:
                run.finished_at = datetime.now(tz=timezone.utc).isoformat()
            handle = self.app_service.pending_run_handles.pop(job.run_id, None)
            if handle is not None:
                handle.done_event.set()
            self.run_finished.emit(job.run_id, run.status)

    def _find_run(self, run_id: str) -> Run | None:
        project = self.app_service.project
        if project is None or project.workspace is None:
            return None
        return next((run for run in project.workspace.runs if run.id == run_id), None)
