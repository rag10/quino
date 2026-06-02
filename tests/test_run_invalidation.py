"""Tests for quino.services.run_invalidation (Analysis-based invalidation)."""
from __future__ import annotations

from quino.domain.model import Model
from quino.domain.workspace import Analysis, Case, Workspace
from quino.services.run_invalidation import mark_runs_stale_for_case, mark_all_runs_stale


def _case_with_ok_analysis():
    a = Analysis(id="an1", name="Dyn", status="ok")
    return Case(id="c", name="c", model=Model(), analyses=[a])


def test_mark_stale_flips_ok_analysis():
    case = _case_with_ok_analysis()
    n = mark_runs_stale_for_case(case, reason="edit")
    assert n == 1
    assert case.analyses[0].status == "stale"


def test_mark_stale_skips_to_be_run():
    case = Case(id="c", name="c", model=Model(), analyses=[Analysis(id="a", name="x")])
    assert mark_runs_stale_for_case(case, reason="edit") == 0


def test_mark_all_stale_across_cases():
    a1 = Analysis(id="an1", name="x", status="ok")
    a2 = Analysis(id="an2", name="y", status="partial")
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   cases={"c1": Case(id="c1", name="c1", model=Model(), analyses=[a1]),
                          "c2": Case(id="c2", name="c2", model=Model(), analyses=[a2])})
    n = mark_all_runs_stale(ws, reason="x")
    assert n == 2
    assert a1.status == "stale" and a2.status == "stale"


def test_mark_stale_flips_partial_analysis():
    case = Case(id="c", name="c", model=Model(),
                analyses=[Analysis(id="a1", name="x", status="partial")])
    n = mark_runs_stale_for_case(case, reason="edit")
    assert n == 1
    assert case.analyses[0].status == "stale"


def test_mark_stale_skips_failed():
    case = Case(id="c", name="c", model=Model(),
                analyses=[Analysis(id="a1", name="x", status="failed")])
    assert mark_runs_stale_for_case(case, reason="edit") == 0


def test_mark_stale_skips_stale():
    case = Case(id="c", name="c", model=Model(),
                analyses=[Analysis(id="a1", name="x", status="stale")])
    assert mark_runs_stale_for_case(case, reason="edit") == 0


def test_mark_stale_appends_warning():
    case = _case_with_ok_analysis()
    mark_runs_stale_for_case(case, reason="param changed")
    assert any("param changed" in w for w in case.analyses[0].warnings)


def test_backward_compat_alias():
    from quino.services.run_invalidation import _mark_set_stale, _stale_analyses
    assert _mark_set_stale is _stale_analyses
