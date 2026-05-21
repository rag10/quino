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


@pytest.mark.parametrize(
    "runner_module,runner_class",
    [
        ("static", "StaticAnalysisRunner"),
        ("kinematic", "KinematicAnalysisRunner"),
        ("equilibrium", "EquilibriumAnalysisRunner"),
    ],
)
def test_unimplemented_runners_raise_with_clear_message(runner_module, runner_class):
    from quino.application.service import ApplicationService
    from quino.domain.workspace import Analysis

    mod = importlib.import_module(f"quino.analysis.{runner_module}")
    runner_cls = getattr(mod, runner_class)
    app = ApplicationService()
    app.new_project("test")
    analysis = Analysis(id="a", name="A", analysis_type=runner_module)
    runner = runner_cls()
    with pytest.raises(NotImplementedError) as exc:
        runner.run(app.project, analysis, initial_pose=None)
    assert "not yet implemented" in str(exc.value).lower()


def test_application_run_analysis_dispatches_to_dynamic():
    from quino.application.service import ApplicationService
    from quino.domain.workspace import Analysis, Baseline, Workspace

    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        analyses=[Analysis(id="a", name="A", analysis_type="dynamic", baseline_id="b")],
        active_baseline_id="b",
    )
    result = app.run_analysis("a")
    assert result.analysis_id == "a"
    assert result.status in ("ok", "failed")


def test_application_run_analysis_returns_failed_for_unimplemented_type():
    from quino.application.service import ApplicationService
    from quino.domain.workspace import Analysis, Baseline, Workspace

    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        analyses=[Analysis(id="a", name="A", analysis_type="static", baseline_id="b")],
        active_baseline_id="b",
    )
    result = app.run_analysis("a")
    assert result.status == "failed"
    assert "not yet implemented" in result.error_message.lower()
