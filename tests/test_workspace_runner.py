from __future__ import annotations

from quino.domain.model import SimulationResult
from quino.domain.workspace import Analysis, Case, Workspace
from quino.services.workspace_runner import (
    load_result_artifact,
    save_result_artifact,
)


def _ws_with_case():
    case = Case(id="c1", name="Root")
    ws = Workspace(
        id="w", name="w", schema_version="0.4.0", root_case_ids=["c1"], cases={"c1": case}
    )
    return ws, case


def test_load_result_artifact_returns_none_for_missing_run(tmp_path):
    analysis = Analysis(id="a1", name="A", status="ok")
    result = load_result_artifact(tmp_path, analysis)
    assert result is None


def test_save_then_load_round_trips_through_analysis(tmp_path):
    _ws, case = _ws_with_case()
    analysis = Analysis(id="a1", name="A", status="ok")
    case.analyses.append(analysis)

    result = SimulationResult(
        success=True,
        time=[0.0, 1.0],
        frames=[],
        states=[],
        messages=["done"],
        error=None,
        backend="exudyn",
    )
    save_result_artifact(tmp_path, analysis, result)

    assert analysis.result_ref is not None
    assert analysis.result_ref.run_entry_id == analysis.id
    assert analysis.artifacts and analysis.artifacts[0].kind == "simulation_result"

    loaded = load_result_artifact(tmp_path, analysis)
    assert loaded is not None
    assert loaded.success is True
    assert loaded.time == [0.0, 1.0]
    assert loaded.backend == "exudyn"


def test_load_result_artifact_returns_none_when_file_deleted(tmp_path):
    analysis = Analysis(id="a2", name="A", status="ok")
    result = SimulationResult(success=True, time=[], frames=[], states=[], messages=[])
    path = save_result_artifact(tmp_path, analysis, result)
    path.unlink()
    assert load_result_artifact(tmp_path, analysis) is None
