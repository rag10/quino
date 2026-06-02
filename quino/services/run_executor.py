from __future__ import annotations

import copy
import queue
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PySide6 import QtCore

from quino.analysis.registry import get_runner_for_type
from quino.pose.geometry import create_reference_pose
# NOTE (Fase 1.10): the ``Run`` domain entity and ``Case.runs`` were removed; run
# state now lives flattened on ``Analysis``. This executor still constructs ``Run``
# objects and appends to ``case.runs`` and has NOT yet been migrated. It imports the
# deferred placeholder ``Run`` from workspace_runner to stay importable; full
# migration to the Analysis-based run model is deferred to a later Fase.
from quino.services.workspace_runner import Run, _CaseAsProject, _next_run_id


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
    case_id: str
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
        ws = self.app_service._workspace
        if ws is None:
            raise ValueError("No active workspace")
        case = self.app_service.current_case()
        if case is None:
            raise ValueError("No active case")
        analysis = next((a for a in case.analyses if a.id == analysis_id), None)
        if analysis is None:
            raise ValueError(f"Analysis {analysis_id!r} not found in case {case.id!r}")

        with self.app_service.workspace_lock:
            run_id = _next_run_id(case)
            run = Run(
                id=run_id,
                analysis_id=analysis_id,
                created_at=datetime.now(tz=timezone.utc).isoformat(),
                status="queued",
                config_snapshot=asdict(analysis.config),
            )
            case.runs.append(run)

        handle = RunHandle(run_id=run_id)
        self.app_service.pending_run_handles[run_id] = handle
        self._queue.put(
            _QueuedJob(
                case_id=case.id,
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

    def pending_count(self) -> int:
        count = self._queue.qsize()
        return max(0, count - 1 if self._stopping.is_set() else count)

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
        run = self._find_run(job.case_id, job.run_id)
        if run is None:
            return

        with self.app_service.workspace_lock:
            run.status = "running"
        self.run_started.emit(job.run_id)

        try:
            ws = self.app_service._workspace
            if ws is None:
                raise ValueError("No active workspace")
            case = ws.cases.get(job.case_id)
            if case is None:
                raise ValueError(f"Case {job.case_id!r} not found")
            analysis = next((a for a in case.analyses if a.id == job.analysis_id), None)
            if analysis is None:
                raise ValueError(f"Analysis {job.analysis_id!r} not found")
            project = _CaseAsProject.from_case(case, ws)
            runner = get_runner_for_type(analysis.analysis_type)
            # Resolve the pose attached to the analysis (set when the user
            # added the analysis under a specific pose in the workspace tree).
            initial_pose = None
            if getattr(analysis, "pose_id", None):
                candidate = next((p for p in case.poses if p.id == analysis.pose_id), None)
                if candidate is not None:
                    initial_pose = _complete_pose_for_project(project, candidate)
            result = runner.run(
                project,
                analysis,
                initial_pose=initial_pose,
                cancel_event=job.cancel_event,
                run=run,
                project_dir=self.app_service.current_project_dir,
            )
            with self.app_service.workspace_lock:
                if job.cancel_event.is_set() or getattr(result, "status", None) == "to_be_run":
                    run.status = "to_be_run"
                    run.error_message = getattr(result, "error_message", None) or "Cancelled by user"
                    run.result_ref = None
                    run.artifacts.clear()
                    run.metrics.clear()
                else:
                    run.status = getattr(result, "status", "ok")
                    msg = getattr(result, "error_message", "") or ""
                    if run.status == "partial":
                        # Partial runs keep their frames; the failure reason
                        # is surfaced as a warning rather than as a hard error.
                        run.error_message = ""
                        if msg and msg not in run.warnings:
                            run.warnings.append(msg)
                    else:
                        run.error_message = msg
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

    def _find_run(self, case_id: str, run_id: str) -> Run | None:
        ws = self.app_service._workspace
        if ws is None:
            return None
        case = ws.cases.get(case_id)
        if case is None:
            return None
        return next((r for r in case.runs if r.id == run_id), None)


def _complete_pose_for_project(project, pose):
    complete = create_reference_pose(project, pose_id=pose.id, name=pose.name)
    complete.metadata = copy.deepcopy(pose.metadata)
    complete.initial_velocities = dict(getattr(pose, "initial_velocities", {}))
    for body_id, body_pose in getattr(pose, "body_poses", {}).items():
        complete.body_poses[body_id] = copy.deepcopy(body_pose)
    return complete
