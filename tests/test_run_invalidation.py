"""Tests for quino.services.run_invalidation (new case-as-model API)."""
from __future__ import annotations

from quino.domain.workspace import Analysis, Case, Run, ResultRef, ArtifactRef


def _make_case(case_id: str = "c1", analyses: list | None = None) -> Case:
    """Helper: build a Case with optional analyses."""
    case = Case(id=case_id, name="Test")
    if analyses:
        case.analyses = analyses
    return case


def _make_analysis(analysis_id: str, pose_id: str | None = None) -> Analysis:
    return Analysis(id=analysis_id, name="A", analysis_type="dynamic", pose_id=pose_id)


def _make_run(run_id: str, analysis_id: str, status: str = "ok") -> Run:
    return Run(id=run_id, analysis_id=analysis_id, created_at="2026-05-22T10:00:00Z",
               status=status)


# ---------------------------------------------------------------------------
# _mark_set_stale
# ---------------------------------------------------------------------------

def test_mark_set_stale_flips_ok_and_partial():
    from quino.services.run_invalidation import _mark_set_stale

    case = _make_case()
    a = _make_analysis("a1")
    case.analyses = [a]
    r_ok = _make_run("r1", "a1", "ok")
    r_partial = _make_run("r2", "a1", "partial")
    r_failed = _make_run("r3", "a1", "failed")
    case.runs = [r_ok, r_partial, r_failed]

    n = _mark_set_stale(case, {"a1"}, "model edited")

    assert n == 2
    assert r_ok.status == "stale"
    assert r_partial.status == "stale"
    assert r_failed.status == "failed"
    assert "model edited" in r_ok.warnings[-1]


def test_mark_set_stale_empty_analysis_ids_returns_zero():
    from quino.services.run_invalidation import _mark_set_stale

    case = _make_case()
    r = _make_run("r1", "a1", "ok")
    case.runs = [r]

    n = _mark_set_stale(case, set(), "x")

    assert n == 0
    assert r.status == "ok"


# ---------------------------------------------------------------------------
# mark_runs_stale_for_case
# ---------------------------------------------------------------------------

def test_mark_runs_stale_for_case_stales_all_case_runs():
    from quino.services.run_invalidation import mark_runs_stale_for_case

    case = _make_case()
    a = _make_analysis("a1")
    case.analyses = [a]
    r1 = _make_run("r1", "a1", "ok")
    r2 = _make_run("r2", "a1", "partial")
    case.runs = [r1, r2]

    n = mark_runs_stale_for_case(case, reason="edit")

    assert n == 2
    assert r1.status == "stale"
    assert r2.status == "stale"


# ---------------------------------------------------------------------------
# mark_all_runs_stale
# ---------------------------------------------------------------------------

def test_mark_all_runs_stale_covers_all_cases():
    from quino.services.run_invalidation import mark_all_runs_stale
    from quino.domain.workspace import Workspace

    ws = Workspace(id="ws1", name="W", schema_version="0.3.0")
    c1 = _make_case("c1")
    c1.analyses = [_make_analysis("a1")]
    c1.runs = [_make_run("r1", "a1", "ok")]
    c2 = _make_case("c2")
    c2.analyses = [_make_analysis("a2")]
    c2.runs = [_make_run("r2", "a2", "ok")]
    ws.cases = {"c1": c1, "c2": c2}

    n = mark_all_runs_stale(ws, reason="global edit")

    assert n == 2
    assert c1.runs[0].status == "stale"
    assert c2.runs[0].status == "stale"


# ---------------------------------------------------------------------------
# mark_runs_stale_for_pose
# ---------------------------------------------------------------------------

def test_mark_runs_stale_for_pose_only_targets_matching_pose():
    from quino.services.run_invalidation import mark_runs_stale_for_pose
    from quino.domain.workspace import Workspace

    ws = Workspace(id="ws1", name="W", schema_version="0.3.0")
    c1 = _make_case("c1")
    a1 = _make_analysis("a1", pose_id="pose_X")
    a2 = _make_analysis("a2", pose_id="pose_Y")
    c1.analyses = [a1, a2]
    r1 = _make_run("r1", "a1", "ok")
    r2 = _make_run("r2", "a2", "ok")
    c1.runs = [r1, r2]
    ws.cases = {"c1": c1}

    n = mark_runs_stale_for_pose(ws, "pose_X", reason="pose edit")

    assert n == 1
    assert r1.status == "stale"
    assert r2.status == "ok"


# ---------------------------------------------------------------------------
# delete_run
# ---------------------------------------------------------------------------

def test_delete_run_unlinks_artifact_and_removes_record(tmp_path):
    from quino.services.run_invalidation import delete_run
    from quino.domain.workspace import Workspace

    ws = Workspace(id="ws1", name="W", schema_version="0.3.0")
    c1 = _make_case("c1")
    art = tmp_path / "artifacts" / "result.json"
    art.parent.mkdir(parents=True)
    art.write_text("{}")
    run = Run(
        id="r1", analysis_id="a1", created_at="...", status="ok",
        result_ref=ResultRef(run_entry_id="r1", artifact_path="artifacts/result.json",
                             checksum="sha256:0"),
    )
    c1.runs = [run]
    ws.cases = {"c1": c1}

    result = delete_run(ws, tmp_path, "r1")

    assert result is True
    assert not any(r.id == "r1" for r in c1.runs)
    assert not art.exists()


def test_delete_run_returns_false_if_not_found():
    from quino.services.run_invalidation import delete_run
    from quino.domain.workspace import Workspace

    ws = Workspace(id="ws1", name="W", schema_version="0.3.0")
    ws.cases = {"c1": _make_case("c1")}

    result = delete_run(ws, None, "nonexistent")

    assert result is False


# ---------------------------------------------------------------------------
# End-to-end: model edits invalidate ok/partial runs; style edits don't
# ---------------------------------------------------------------------------


def _setup_app_with_ok_run() -> tuple:
    """Build a small workspace with an analysis + an 'ok' run, ready for edits."""
    from quino.application.service import ApplicationService
    from quino.domain.inputs import MarkerInput
    from quino.domain.workspace import Analysis, Run

    app = ApplicationService()
    app.new_workspace("T")
    body_id = app.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    ws = app._workspace
    case = ws.cases[ws.root_case_ids[0]]
    analysis = Analysis(id="a1", name="A", analysis_type="dynamic")
    case.analyses.append(analysis)
    run = Run(id="r1", analysis_id="a1", created_at="2026-05-28T00:00:00", status="ok")
    case.runs.append(run)
    return app, body_id, run


def test_add_gravity_invalidates_runs():
    app, _, run = _setup_app_with_ok_run()
    app.entities.add_gravity()
    assert run.status == "stale"


def test_delete_gravity_invalidates_runs():
    app, _, run = _setup_app_with_ok_run()
    app.entities.add_gravity()
    run.status = "ok"  # reset for the second edit
    app.entities.delete_gravity()
    assert run.status == "stale"


def test_create_body_invalidates_runs():
    app, _, run = _setup_app_with_ok_run()
    from quino.domain.inputs import MarkerInput
    app.create_bar("Bar2", MarkerInput("0 mm", "10 mm", "A"), MarkerInput("100 mm", "10 mm", "B"))
    assert run.status == "stale"


def test_create_load_invalidates_runs():
    app, body_id, run = _setup_app_with_ok_run()
    body = app.get_body(body_id)
    marker_id = next(m.id for m in body.markers if m.name == "A")
    app.forces.create_load("L1", marker_id, "10 N", "0 N")
    assert run.status == "stale"


def test_style_edit_does_NOT_invalidate_runs():
    from quino.domain.inputs import PropertyValueInput
    app, body_id, run = _setup_app_with_ok_run()
    app.update_property(body_id, "style.color", PropertyValueInput("expression", "#ff0000"))
    assert run.status == "ok"


def test_style_line_width_does_NOT_invalidate_runs():
    from quino.domain.inputs import PropertyValueInput
    app, body_id, run = _setup_app_with_ok_run()
    app.update_property(body_id, "style.line_width", PropertyValueInput("expression", "3"))
    assert run.status == "ok"


def test_parameter_create_does_NOT_invalidate_unused_runs():
    app, _, run = _setup_app_with_ok_run()
    app.parameters.create("p1", "1 kg", "kg")
    assert run.status == "ok"


def test_parameter_description_only_does_NOT_invalidate_runs():
    app, _, run = _setup_app_with_ok_run()
    pid = app.parameters.create("p1", "1 kg", "kg")
    run.status = "ok"  # reset
    app.parameters.update(pid, description="just a comment")
    assert run.status == "ok"


def test_parameter_value_change_invalidates_only_cases_that_use_it():
    from quino.domain.inputs import PropertyValueInput
    from quino.domain.workspace import Analysis, Run

    app, body_id, run = _setup_app_with_ok_run()
    pid = app.parameters.create("p1", "1 kg", "kg")
    app.update_property(body_id, "mass", PropertyValueInput("expression", "p1"))
    run.status = "ok"

    ws = app._workspace
    root = ws.cases[ws.root_case_ids[0]]
    child = app.workspace.create_case("Unused")
    child.analyses.append(Analysis(id="a2", name="A2", analysis_type="dynamic"))
    child.runs.append(Run(id="r2", analysis_id="a2", created_at="2026-05-28T00:00:00", status="ok"))

    app.parameters.update(pid, expression="2 kg")

    assert root.runs[0].status == "stale"
    assert child.runs[0].status == "ok"
