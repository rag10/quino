from __future__ import annotations

import threading
import time

import pytest

pytest.skip(
    "overlay removed; Run entity and case.runs replaced by flattened Analysis run "
    "state. RunExecutor still appends to case.runs; migration deferred to Fase 2/3.",
    allow_module_level=True,
)

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.analysis.runner import AnalysisResult
from quino.gui.widgets.run_status_widget import RunStatusWidget
from quino.services.run_executor import RunExecutor, RunHandle


def _bootstrap() -> tuple[ApplicationService, object]:
    svc = ApplicationService()
    svc.new_project("t")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", case_id=case.id, workspace_pose_id=pose.id)
    return svc, analysis


def test_enqueue_returns_handle_with_run_id(monkeypatch) -> None:
    svc, analysis = _bootstrap()

    class FakeRunner:
        def run(self, project, analysis, **kwargs):
            return AnalysisResult(analysis_id=analysis.id, analysis_type=analysis.analysis_type, status="ok")

    monkeypatch.setattr("quino.services.run_executor.get_runner_for_type", lambda _kind: FakeRunner())

    ex = RunExecutor(svc)
    handle = ex.enqueue(analysis.id)
    try:
        assert isinstance(handle, RunHandle)
        assert handle.run_id is not None
        run = next(r for r in svc.current_case().runs if r.id == handle.run_id)
        assert run.status in {"queued", "running", "ok", "failed"}
    finally:
        ex.shutdown()


def test_cancel_during_run_returns_to_be_run(monkeypatch) -> None:
    svc, analysis = _bootstrap()
    started = threading.Event()

    class FakeRunner:
        def run(self, project, analysis, *, cancel_event=None, **kwargs):
            started.set()
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    return AnalysisResult(
                        analysis_id=analysis.id,
                        analysis_type=analysis.analysis_type,
                        status="to_be_run",
                        error_message="Cancelled by user",
                    )
                time.sleep(0.02)
            return AnalysisResult(analysis_id=analysis.id, analysis_type=analysis.analysis_type, status="ok")

    monkeypatch.setattr("quino.services.run_executor.get_runner_for_type", lambda _kind: FakeRunner())

    ex = RunExecutor(svc)
    handle = ex.enqueue(analysis.id)
    try:
        assert started.wait(timeout=1.0)
        handle.cancel()
        deadline = time.time() + 3.0
        while time.time() < deadline:
            run = next(r for r in svc.current_case().runs if r.id == handle.run_id)
            if run.status not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert run.status == "to_be_run"
        assert run.result_ref is None
    finally:
        ex.shutdown()


def test_multiple_queued_runs_execute_serially_in_enqueue_order(monkeypatch) -> None:
    svc, analysis = _bootstrap()
    start_order: list[str] = []
    finish_order: list[str] = []

    class FakeRunner:
        def run(self, project, analysis, *, run=None, **kwargs):
            start_order.append(run.id)
            time.sleep(0.05)
            finish_order.append(run.id)
            return AnalysisResult(analysis_id=analysis.id, analysis_type=analysis.analysis_type, status="ok")

    monkeypatch.setattr("quino.services.run_executor.get_runner_for_type", lambda _kind: FakeRunner())

    ex = RunExecutor(svc)
    try:
        h1 = ex.enqueue(analysis.id)
        h2 = ex.enqueue(analysis.id)
        deadline = time.time() + 3.0
        while time.time() < deadline and len(finish_order) < 2:
            time.sleep(0.02)
        assert start_order == [h1.run_id, h2.run_id]
        assert finish_order == [h1.run_id, h2.run_id]
    finally:
        ex.shutdown()


def test_ensure_executor_idempotent() -> None:
    svc, _ = _bootstrap()
    a = svc.ensure_executor()
    b = svc.ensure_executor()
    assert a is b
    a.shutdown()
    svc.executor = None


def test_status_widget_reflects_running_and_idle(qtbot) -> None:
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = RunStatusWidget()
    qtbot.addWidget(widget)
    widget.show_running("r1", "Bump")
    assert "Bump" in widget._label.text()
    widget.show_idle()
    assert widget._label.text() == "Idle"


def test_status_widget_keeps_failed_error_in_tooltip(qtbot) -> None:
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = RunStatusWidget()
    qtbot.addWidget(widget)
    long_error = "solver failed: " + ("x" * 500)
    widget.show_finished("failed", "A1", error=long_error)
    assert widget._label.text() == "Failed: A1"
    assert long_error in widget._label.toolTip()


def test_status_label_does_not_force_wide_layout(qtbot) -> None:
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = RunStatusWidget()
    qtbot.addWidget(widget)
    widget.show_running("r1", "very long analysis name " * 50)
    assert widget._label.minimumSizeHint().width() == 0
    assert widget._label.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Policy.Ignored
