from quino.application.service import ApplicationService
from quino.services.batch_runner import enqueue_case_analyses


def test_batch_run_enqueues_every_analysis_in_a_case():
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    svc.workspace.create_analysis("D1", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)
    svc.workspace.create_analysis("D2", analysis_type="dynamic", case_id=case.id, workspace_pose_id=pose.id)
    handles = enqueue_case_analyses(svc, case.id)
    try:
        assert len(handles) == 2
        ids = {handle.run_id for handle in handles}
        run_records = {run.id for run in svc.project.workspace.runs}
        assert ids.issubset(run_records)
    finally:
        svc.executor.shutdown()
