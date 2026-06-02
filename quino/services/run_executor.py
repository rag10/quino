from __future__ import annotations

import copy
import queue
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PySide6 import QtCore

from quino.analysis.registry import get_runner_for_type
from quino.pose.geometry import create_reference_pose
from quino.services.metric_data import build_metric_data
from quino.services.metric_evaluator import evaluate_all
from quino.services.run_artifacts import good_dir
from quino.services.workspace_runner import _CaseAsProject


@dataclass(slots=True)
class RunHandle:
    analysis_id: str
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
    cancel_event: threading.Event
    prev: dict


def _analysis_snapshot(analysis) -> dict:
    return {
        "status": analysis.status,
        "result_ref": copy.deepcopy(analysis.result_ref),
        "artifacts": copy.deepcopy(analysis.artifacts),
        "finished_at": analysis.finished_at,
        "error_message": analysis.error_message,
        "metrics": copy.deepcopy(analysis.metrics),
    }


class RunExecutor(QtCore.QObject):
    run_queued = QtCore.Signal(str)
    run_started = QtCore.Signal(str)
    run_progress = QtCore.Signal(str, int, int)
    run_finished = QtCore.Signal(str, str)
    run_needs_confirmation = QtCore.Signal(str)  # analysis_id: partial over ok

    def __init__(self, app_service, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.app_service = app_service
        self.pending_partial: dict[str, tuple] = {}
        self._queue: queue.Queue[_QueuedJob | None] = queue.Queue()
        self._stopping = threading.Event()
        self._worker = threading.Thread(target=self._loop, name="RunExecutor", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------ public

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
            prev = _analysis_snapshot(analysis)
            analysis.status = "queued"
            analysis.created_at = datetime.now(tz=timezone.utc).isoformat()

        handle = RunHandle(analysis_id=analysis_id)
        self.app_service.pending_run_handles[analysis_id] = handle
        self._queue.put(_QueuedJob(case.id, analysis_id, handle.cancel_event, prev))
        self.run_queued.emit(analysis_id)
        return handle

    def confirm_partial(self, analysis_id: str, overwrite: bool) -> None:
        pending = self.pending_partial.pop(analysis_id, None)
        if pending is None:
            return
        case_id, prev, result, backup_dir = pending
        with self.app_service.workspace_lock:
            analysis = self._find_analysis(case_id, analysis_id)
            if analysis is None:
                return
            if overwrite:
                self._discard_backup(backup_dir)
                self._apply_result(analysis, result, status="partial")
                self._evaluate_metrics(case_id, analysis)
            else:
                self._restore_backup(case_id, analysis_id, backup_dir)
                self._restore_prev(analysis, prev)
        self.run_finished.emit(analysis_id, analysis.status)

    def shutdown(self) -> None:
        self._stopping.set()
        self._queue.put(None)
        self._worker.join(timeout=2.0)

    def pending_count(self) -> int:
        count = self._queue.qsize()
        return max(0, count - 1 if self._stopping.is_set() else count)

    # ------------------------------------------------------------------ worker

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
        analysis = self._find_analysis(job.case_id, job.analysis_id)
        if analysis is None:
            return
        prev = job.prev
        with self.app_service.workspace_lock:
            analysis.status = "running"
        self.run_started.emit(job.analysis_id)

        project_dir = self.app_service.current_project_dir
        backup_dir = self._backup_good(project_dir, job.analysis_id) if project_dir else None

        try:
            ws = self.app_service._workspace
            case = ws.cases.get(job.case_id)
            analysis = next((a for a in case.analyses if a.id == job.analysis_id), None)
            project = _CaseAsProject.from_case(case, ws)
            runner = get_runner_for_type(analysis.analysis_type)
            initial_pose = None
            if getattr(analysis, "pose_id", None):
                candidate = next((p for p in case.poses if p.id == analysis.pose_id), None)
                if candidate is not None and getattr(candidate, "body_poses", None):
                    initial_pose = _complete_pose_for_project(project, candidate)
            result = runner.run(
                project,
                analysis,
                initial_pose=initial_pose,
                cancel_event=job.cancel_event,
                run=analysis,
                project_dir=project_dir,
            )
            status = getattr(result, "status", "ok")
            with self.app_service.workspace_lock:
                if job.cancel_event.is_set() or status == "to_be_run":
                    self._restore_backup(job.case_id, job.analysis_id, backup_dir)
                    self._restore_prev(analysis, prev)
                    analysis.status = "to_be_run"
                elif status == "partial" and prev["status"] == "ok":
                    self.pending_partial[job.analysis_id] = (job.case_id, prev, result, backup_dir)
                    self._restore_prev(analysis, prev)
                    self.run_needs_confirmation.emit(job.analysis_id)
                    return
                else:
                    self._discard_backup(backup_dir)
                    self._apply_result(analysis, result, status=status)
                    if status in {"ok", "partial"}:
                        self._evaluate_metrics(job.case_id, analysis)
        except Exception as exc:  # noqa: BLE001
            with self.app_service.workspace_lock:
                self._restore_backup(job.case_id, job.analysis_id, backup_dir)
                self._restore_prev(analysis, prev)
                analysis.status = "failed"
                analysis.error_message = str(exc)
        finally:
            with self.app_service.workspace_lock:
                if job.analysis_id not in self.pending_partial:
                    analysis.finished_at = datetime.now(tz=timezone.utc).isoformat()
            handle = self.app_service.pending_run_handles.pop(job.analysis_id, None)
            if handle is not None:
                handle.done_event.set()
            if job.analysis_id not in self.pending_partial:
                self.run_finished.emit(job.analysis_id, analysis.status)

    # ------------------------------------------------------------------ helpers

    def _find_analysis(self, case_id: str, analysis_id: str):
        ws = self.app_service._workspace
        if ws is None:
            return None
        case = ws.cases.get(case_id)
        if case is None:
            return None
        return next((a for a in case.analyses if a.id == analysis_id), None)

    def _apply_result(self, analysis, result, *, status: str) -> None:
        analysis.status = status
        msg = getattr(result, "error_message", "") or ""
        if status == "partial":
            analysis.error_message = ""
            if msg and msg not in analysis.warnings:
                analysis.warnings.append(msg)
        else:
            analysis.error_message = msg
        analysis.finished_at = datetime.now(tz=timezone.utc).isoformat()

    def _restore_prev(self, analysis, prev: dict) -> None:
        analysis.status = prev["status"]
        analysis.result_ref = prev["result_ref"]
        analysis.artifacts = prev["artifacts"]
        analysis.finished_at = prev["finished_at"]
        analysis.error_message = prev["error_message"]
        analysis.metrics = prev["metrics"]

    def _evaluate_metrics(self, case_id: str, analysis) -> None:
        if not analysis.metrics:
            return
        case = self.app_service._workspace.cases.get(case_id)
        if case is None:
            return
        name_by_id = {s.id: s.name for s in case.model.sensors}
        meta = self._analysis_meta(analysis)
        data, meta = build_metric_data(case.sensor_outputs, name_by_id, meta)
        evaluate_all(analysis, data, meta)

    def _analysis_meta(self, analysis) -> dict:
        cfg = analysis.config
        meta: dict = {"analysis_type": analysis.analysis_type}
        for attr in ("dt", "duration", "steps"):
            if hasattr(cfg, attr):
                meta[attr] = getattr(cfg, attr)
        if hasattr(cfg, "duration"):
            meta["t_final"] = getattr(cfg, "duration")
        return meta

    def _backup_good(self, project_dir, analysis_id: str):
        base = Path(project_dir) / "artifacts"
        good = good_dir(base, analysis_id)
        if not good.exists():
            return None
        backup = base / f"{analysis_id}__prev_backup"
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(good, backup)
        return backup

    def _discard_backup(self, backup_dir) -> None:
        if backup_dir is not None and Path(backup_dir).exists():
            shutil.rmtree(backup_dir)

    def _restore_backup(self, case_id: str, analysis_id: str, backup_dir) -> None:
        if backup_dir is None or not Path(backup_dir).exists():
            return
        project_dir = self.app_service.current_project_dir
        if project_dir is None:
            return
        base = Path(project_dir) / "artifacts"
        good = good_dir(base, analysis_id)
        if good.exists():
            shutil.rmtree(good)
        shutil.move(str(backup_dir), str(good))


def _complete_pose_for_project(project, pose):
    complete = create_reference_pose(project, pose_id=pose.id, name=pose.name)
    complete.metadata = copy.deepcopy(pose.metadata)
    complete.initial_velocities = dict(getattr(pose, "initial_velocities", {}))
    for body_id, body_pose in getattr(pose, "body_poses", {}).items():
        complete.body_poses[body_id] = copy.deepcopy(body_pose)
    return complete
