from __future__ import annotations

import threading
import time

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.analysis.runner import AnalysisResult
from quino.gui.widgets.run_status_widget import RunStatusWidget
from quino.services.run_executor import RunExecutor, RunHandle


def _bootstrap():
    svc = ApplicationService()
    svc.new_project("t")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", case_id=case.id, workspace_pose_id=pose.id)
    return svc, analysis


def _analysis(svc, analysis_id):
    case = svc.current_case()
    return next(a for a in case.analyses if a.id == analysis_id)


def test_enqueue_runs_and_sets_status_on_analysis(monkeypatch):
    svc, analysis = _bootstrap()

    class FakeRunner:
        def run(self, project, analysis, **kwargs):
            return AnalysisResult(analysis_id=analysis.id, analysis_type=analysis.analysis_type, status="ok")

    monkeypatch.setattr("quino.services.run_executor.get_runner_for_type", lambda _k: FakeRunner())
    ex = RunExecutor(svc)
    try:
        handle = ex.enqueue(analysis.id)
        assert isinstance(handle, RunHandle)
        assert handle.analysis_id == analysis.id
        handle.done_event.wait(timeout=10)
        assert _analysis(svc, analysis.id).status == "ok"
    finally:
        ex.shutdown()


def test_cancel_during_run_returns_to_be_run(monkeypatch):
    svc, analysis = _bootstrap()
    started = threading.Event()

    class FakeRunner:
        def run(self, project, analysis, *, cancel_event=None, **kwargs):
            started.set()
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    return AnalysisResult(analysis_id=analysis.id, analysis_type=analysis.analysis_type,
                                          status="to_be_run", error_message="Cancelled by user")
                time.sleep(0.02)
            return AnalysisResult(analysis_id=analysis.id, analysis_type=analysis.analysis_type, status="ok")

    monkeypatch.setattr("quino.services.run_executor.get_runner_for_type", lambda _k: FakeRunner())
    ex = RunExecutor(svc)
    try:
        handle = ex.enqueue(analysis.id)
        assert started.wait(timeout=2.0)
        handle.cancel()
        handle.done_event.wait(timeout=5)
        assert _analysis(svc, analysis.id).status == "to_be_run"
    finally:
        ex.shutdown()


def test_partial_over_ok_defers_and_keeps_previous(monkeypatch):
    svc, analysis = _bootstrap()
    # First make it "ok" by hand to simulate a prior successful run.
    _analysis(svc, analysis.id).status = "ok"

    class PartialRunner:
        def run(self, project, analysis, **kwargs):
            return AnalysisResult(analysis_id=analysis.id, analysis_type=analysis.analysis_type,
                                  status="partial", error_message="solver crashed mid-run")

    monkeypatch.setattr("quino.services.run_executor.get_runner_for_type", lambda _k: PartialRunner())
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ex = RunExecutor(svc)
    asked: list[str] = []
    ex.run_needs_confirmation.connect(lambda aid: asked.append(aid))
    try:
        handle = ex.enqueue(analysis.id)
        handle.done_event.wait(timeout=10)
        # previous OK preserved, confirmation requested
        assert _analysis(svc, analysis.id).status == "ok"
        # The signal is emitted from the worker thread; pump the Qt event loop
        # so the queued cross-thread connection delivers it.
        deadline = time.time() + 2.0
        while analysis.id not in asked and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        assert analysis.id in asked
        # reject overwrite -> stays ok
        ex.confirm_partial(analysis.id, overwrite=False)
        assert _analysis(svc, analysis.id).status == "ok"
    finally:
        ex.shutdown()


def test_partial_over_non_ok_applies_directly(monkeypatch):
    svc, analysis = _bootstrap()  # starts to_be_run

    class PartialRunner:
        def run(self, project, analysis, **kwargs):
            return AnalysisResult(analysis_id=analysis.id, analysis_type=analysis.analysis_type,
                                  status="partial", error_message="partial frames")

    monkeypatch.setattr("quino.services.run_executor.get_runner_for_type", lambda _k: PartialRunner())
    ex = RunExecutor(svc)
    try:
        handle = ex.enqueue(analysis.id)
        handle.done_event.wait(timeout=10)
        assert _analysis(svc, analysis.id).status == "partial"
    finally:
        ex.shutdown()


def test_ensure_executor_idempotent():
    svc, _ = _bootstrap()
    a = svc.ensure_executor()
    b = svc.ensure_executor()
    assert a is b
    a.shutdown()
    svc.executor = None


# ---- RunStatusWidget tests (unchanged) ----

def test_status_widget_reflects_running_and_idle(qtbot):
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = RunStatusWidget()
    qtbot.addWidget(widget)
    widget.show_running("r1", "Bump")
    assert "Bump" in widget._label.text()
    widget.show_idle()
    assert widget._label.text() == "Idle"


def test_status_widget_keeps_failed_error_in_tooltip(qtbot):
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = RunStatusWidget()
    qtbot.addWidget(widget)
    long_error = "solver failed: " + ("x" * 500)
    widget.show_finished("failed", "A1", error=long_error)
    assert widget._label.text() == "Failed: A1"
    assert long_error in widget._label.toolTip()


def test_status_label_does_not_force_wide_layout(qtbot):
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = RunStatusWidget()
    qtbot.addWidget(widget)
    widget.show_running("r1", "very long analysis name " * 50)
    assert widget._label.minimumSizeHint().width() == 0
    assert widget._label.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Policy.Ignored
