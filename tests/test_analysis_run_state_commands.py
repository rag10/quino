from quino.application.service import ApplicationService


def _svc_with_analysis():
    svc = ApplicationService()
    svc.new_project("t")
    ws = svc._workspace
    case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=case.id)
    analysis = svc.workspace.create_analysis("D", case_id=case.id, workspace_pose_id=pose.id)
    return svc, case, analysis


def test_delete_run_resets_analysis_state():
    svc, case, analysis = _svc_with_analysis()
    analysis.status = "ok"
    analysis.error_message = "x"
    svc.delete_run(analysis.id)
    assert analysis.status == "to_be_run"
    assert analysis.result_ref is None
    assert analysis.artifacts == []


def test_duplicate_analysis_starts_with_clean_run_state():
    from quino.domain.workspace import Metric, MetricResult
    svc, case, analysis = _svc_with_analysis()
    analysis.status = "ok"
    analysis.metrics = [Metric(id="m", name="x", result=MetricResult(value=1.0, status="ok"))]
    dup = svc.duplicate_analysis(analysis.id, new_name="copy")
    assert dup.status == "to_be_run"
    assert dup.result_ref is None
    assert dup.artifacts == []
    assert dup.finished_at is None
    assert dup.metrics and dup.metrics[0].result is None  # metric def copied, result cleared
