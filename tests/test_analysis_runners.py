from __future__ import annotations

import importlib

import pytest


def test_registry_has_all_four_types():
    from quino.analysis.registry import ANALYSIS_RUNNERS
    from quino.domain.types import AnalysisType

    assert set(ANALYSIS_RUNNERS.keys()) == {t.value for t in AnalysisType}


def test_dynamic_runner_validate_returns_list():
    from quino.analysis.dynamic import DynamicAnalysisRunner
    from quino.application.service import ApplicationService
    from quino.domain.workspace import Analysis

    app = ApplicationService()
    app.new_project("test")
    analysis = Analysis(id="a1", name="A1", analysis_type="dynamic")
    runner = DynamicAnalysisRunner()
    errors = runner.validate(app.project, analysis)
    assert isinstance(errors, list)


def test_dynamic_runner_returns_partial_when_solver_crashes_with_frames(monkeypatch):
    """A crashed solve that produced some frames must be reported as 'partial'
    (not 'failed'), and the frames must be kept for playback."""
    from quino.analysis.dynamic import DynamicAnalysisRunner
    from quino.application.service import ApplicationService
    from quino.domain.model import SimulationResult
    from quino.domain.workspace import Analysis

    app = ApplicationService()
    app.new_project("test")
    analysis = Analysis(id="a1", name="A1", analysis_type="dynamic")
    runner = DynamicAnalysisRunner()

    fake_result = SimulationResult(
        success=False,
        backend="fake",
        time=[0.0, 0.01, 0.02],
        frames=[{}, {}, {}],
        error="Dynamic solve failed after partial trajectory: boom",
    )

    class _FakeRunner:
        def run(self, project, duration=1.0, steps=100, cancel_event=None, initial_pose=None):
            return fake_result

    import quino.simulation.runner as runner_mod
    monkeypatch.setattr(runner_mod, "SimulationRunner", lambda _adapter: _FakeRunner())

    result = runner.run(app.project, analysis)
    assert result.status == "partial"
    assert result.frames == fake_result.frames
    assert "boom" in (result.error_message or "")


def test_dynamic_runner_uses_analysis_pose_id_as_initial_pose(monkeypatch):
    """The analysis's pose_id must be passed to the simulation runner as the
    initial pose when the pose has body_poses data."""
    from quino.analysis.dynamic import DynamicAnalysisRunner
    from quino.application.service import ApplicationService
    from quino.domain.model import SimulationResult, BodyPose
    from quino.domain.workspace import Analysis, Pose

    app = ApplicationService()
    app.new_project("test")
    case = app.current_case()
    # Create a non-empty pose
    pose = Pose(id="p1", name="P1", body_poses={"body-x": BodyPose(body_id="body-x", x=1.0, y=2.0, angle=0.3)})
    case.poses.append(pose)
    analysis = Analysis(id="a1", name="A1", analysis_type="dynamic", pose_id="p1")

    received = {}

    class _FakeRunner:
        def run(self, project, duration=1.0, steps=100, cancel_event=None, initial_pose=None):
            received["pose"] = initial_pose
            return SimulationResult(success=True, backend="fake", time=[0.0], frames=[{}])

    import quino.simulation.runner as runner_mod
    monkeypatch.setattr(runner_mod, "SimulationRunner", lambda _adapter: _FakeRunner())

    runner = DynamicAnalysisRunner()
    runner.run(app.project, analysis)
    assert received["pose"] is not None
    assert received["pose"].id == "p1"


def test_dynamic_runner_returns_failed_when_solver_crashes_with_no_frames(monkeypatch):
    from quino.analysis.dynamic import DynamicAnalysisRunner
    from quino.application.service import ApplicationService
    from quino.domain.model import SimulationResult
    from quino.domain.workspace import Analysis

    app = ApplicationService()
    app.new_project("test")
    analysis = Analysis(id="a1", name="A1", analysis_type="dynamic")
    runner = DynamicAnalysisRunner()

    fake_result = SimulationResult(
        success=False, backend="fake", time=[], frames=[], error="boom",
    )

    class _FakeRunner:
        def run(self, project, duration=1.0, steps=100, cancel_event=None, initial_pose=None):
            return fake_result

    import quino.simulation.runner as runner_mod
    monkeypatch.setattr(runner_mod, "SimulationRunner", lambda _adapter: _FakeRunner())

    result = runner.run(app.project, analysis)
    assert result.status == "failed"


@pytest.mark.parametrize(
    "runner_module,runner_class",
    [
        ("static", "StaticAnalysisRunner"),
        ("kinematic", "KinematicAnalysisRunner"),
        ("equilibrium", "EquilibriumAnalysisRunner"),
    ],
)
def test_non_dynamic_runners_expose_validate(runner_module, runner_class):
    from quino.application.service import ApplicationService
    from quino.domain.workspace import Analysis

    mod = importlib.import_module(f"quino.analysis.{runner_module}")
    runner_cls = getattr(mod, runner_class)
    app = ApplicationService()
    app.new_project("test")
    analysis = Analysis(id="a", name="A", analysis_type=runner_module)
    runner = runner_cls()
    errors = runner.validate(app.project, analysis)
    assert isinstance(errors, list)


def test_application_run_analysis_dispatches_to_dynamic():
    from quino.application.service import ApplicationService
    from quino.domain.workspace import Analysis

    app = ApplicationService()
    app.new_project("test")
    ws = app._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis = Analysis(id="a", name="A", analysis_type="dynamic")
    case.analyses.append(analysis)
    result = app.run_analysis("a")
    assert result.analysis_id == "a"
    assert result.status in ("ok", "failed")


def test_application_run_analysis_returns_analysis_result_for_static():
    from quino.application.service import ApplicationService
    from quino.domain.workspace import Analysis

    app = ApplicationService()
    app.new_project("test")
    ws = app._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis = Analysis(id="a", name="A", analysis_type="static")
    case.analyses.append(analysis)
    result = app.run_analysis("a")
    assert result.analysis_id == "a"
    assert result.status in {"ok", "failed", "partial"}
