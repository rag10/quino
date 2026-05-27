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
