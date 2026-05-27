from quino.domain.workspace import Case, Workspace
from quino.services.workspace_runner import load_result_artifact


def test_load_result_artifact_returns_none_for_missing_run(tmp_path):
    case = Case(id="c1", name="Root")
    ws = Workspace(id="w", name="w", schema_version="0.3.0", root_case_ids=["c1"], cases={"c1": case})
    from quino.domain.workspace import Run
    run = Run(id="r1", analysis_id="a1", created_at="2026-01-01T00:00:00", status="ok")
    result = load_result_artifact(tmp_path, run)
    assert result is None
