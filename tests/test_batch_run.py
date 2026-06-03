from quino.application.service import ApplicationService
from quino.services.batch_runner import enqueue_case_analyses


def test_batch_run_enqueues_every_analysis_in_a_case():
    svc = ApplicationService()
    svc.new_project("t")
    svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    ws = svc._workspace
    root_case = ws.cases[ws.root_case_ids[0]]
    pose = svc.workspace.create_pose("P", case_id=root_case.id)
    svc.workspace.create_analysis("D1", analysis_type="dynamic", case_id=root_case.id, workspace_pose_id=pose.id)
    svc.workspace.create_analysis("D2", analysis_type="dynamic", case_id=root_case.id, workspace_pose_id=pose.id)
    handles = enqueue_case_analyses(svc, root_case.id)
    try:
        assert len(handles) == 2
        # Run state is flattened onto the Analysis; the handle id IS the analysis id.
        enqueued_ids = {handle.analysis_id for handle in handles}
        analysis_ids = {a.id for a in root_case.analyses}
        assert enqueued_ids == analysis_ids
    finally:
        svc.executor.shutdown()
