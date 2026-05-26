from quino.domain.workspace import Run, ResultRef, ArtifactRef


def test_run_default_status_is_to_be_run():
    r = Run(id="r1", analysis_id="a1", created_at="2026-05-22T10:00:00Z")
    assert r.status == "to_be_run"
    assert r.finished_at is None
    assert r.note == ""
    assert r.config_snapshot == {}
    assert r.warnings == []
    assert r.error_message == ""


def test_run_with_result_ref():
    ref = ResultRef(
        run_entry_id="r1", artifact_path="artifacts/r1.json", checksum="sha256:abc"
    )
    r = Run(
        id="r1",
        analysis_id="a1",
        created_at="2026-05-22T10:00:00Z",
        result_ref=ref,
        status="ok",
    )
    assert r.result_ref.artifact_path == "artifacts/r1.json"


def test_run_roundtrip_through_json(tmp_path):
    from quino.application.service import ApplicationService

    svc = ApplicationService()
    svc.new_project("test")
    run = Run(
        id="run_1",
        analysis_id="a1",
        created_at="2026-05-22T10:00:00Z",
        finished_at="2026-05-22T10:00:05Z",
        status="ok",
        note="kp=1800, smooth",
        metrics={"final_x": 1.23},
        warnings=["minor"],
        config_snapshot={"duration": 1.0, "steps": 100},
    )
    svc.project.workspace.runs.append(run)
    path = tmp_path / "p.quino.json"
    svc.save_project(str(path))

    svc2 = ApplicationService()
    svc2.load_project(str(path))
    loaded = next(r for r in svc2.project.workspace.runs if r.id == "run_1")
    assert loaded.analysis_id == "a1"
    assert loaded.status == "ok"
    assert loaded.note == "kp=1800, smooth"
    assert loaded.metrics == {"final_x": 1.23}
    assert loaded.warnings == ["minor"]
    assert loaded.config_snapshot == {"duration": 1.0, "steps": 100}


def test_mark_runs_stale_on_active_case():
    from quino.services.run_invalidation import mark_runs_stale
    from quino.application.service import ApplicationService

    svc = ApplicationService()
    svc.new_project("t")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    a = svc.workspace.create_analysis("D", case_id=case.id, workspace_pose_id=pose.id)
    ok_run = Run(id="r_ok", analysis_id=a.id, created_at="2026-05-22T10:00:00Z",
                 status="ok", result_ref=None)
    partial_run = Run(id="r_p", analysis_id=a.id, created_at="2026-05-22T10:00:05Z",
                      status="partial")
    failed_run = Run(id="r_f", analysis_id=a.id, created_at="2026-05-22T10:00:10Z",
                     status="failed")
    svc.project.workspace.runs.extend([ok_run, partial_run, failed_run])

    n = mark_runs_stale(svc.project.workspace, case.id, reason="model edited")
    assert n == 2  # ok + partial only; failed already won't contribute fresh data
    assert ok_run.status == "stale"
    assert partial_run.status == "stale"
    assert failed_run.status == "failed"  # unchanged
    assert "model edited" in ok_run.warnings[-1]


def test_delete_run_unlinks_artifact_and_removes_record(tmp_path):
    from quino.services.run_invalidation import delete_run
    from quino.application.service import ApplicationService

    svc = ApplicationService()
    svc.new_project("t")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    a = svc.workspace.create_analysis("D", case_id=case.id, workspace_pose_id=pose.id)
    art = tmp_path / "artifacts" / "result.json"
    art.parent.mkdir(parents=True)
    art.write_text("{}")
    run = Run(id="r1", analysis_id=a.id, created_at="...", status="ok",
              result_ref=ResultRef(run_entry_id="r1", artifact_path="artifacts/result.json",
                                   checksum="sha256:0"))
    svc.project.workspace.runs.append(run)

    delete_run(svc.project.workspace, tmp_path, "r1")

    assert not any(r.id == "r1" for r in svc.project.workspace.runs)
    assert not art.exists()


def test_edit_in_active_case_flips_runs_to_stale_not_deleted():
    from quino.application.service import ApplicationService
    from quino.domain.inputs import PropertyValueInput

    svc = ApplicationService()
    svc.new_project("t")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    a = svc.workspace.create_analysis("D", case_id=case.id, workspace_pose_id=pose.id)
    run = Run(id="r1", analysis_id=a.id, created_at="...", status="ok")
    svc.project.workspace.runs.append(run)
    svc.set_working_context(case_id=case.id)

    # Auto-confirm any GUI prompt and trigger a numeric edit on the case.
    svc._service_context.confirm_run_invalidation = lambda: True
    body_id = svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    svc.update_property(body_id, "mass", PropertyValueInput(kind="expression", value="3 kg"))

    # The run is still present, just stale.
    assert any(r.id == "r1" for r in svc.project.workspace.runs)
    assert run.status == "stale"


def test_edit_in_baseline_scope_flips_runs_to_stale():
    """Regression: editing the shared model while sitting on the baseline
    (active_case_id is None) used to leave runs in 'ok' silently because
    `discard_runs_for_active_case` short-circuited. The fix generalises the
    scope to 'active case OR active baseline OR whole workspace'."""
    from quino.application.service import ApplicationService
    from quino.domain.inputs import PropertyValueInput

    svc = ApplicationService()
    svc.new_project("t")
    ws = svc.project.workspace
    baseline = ws.baselines[0]
    pose = svc.workspace.create_pose("P", baseline_id=baseline.id)
    a = svc.workspace.create_analysis(
        "A", analysis_type="dynamic",
        baseline_id=baseline.id, workspace_pose_id=pose.id,
    )
    run = Run(id="r1", analysis_id=a.id, created_at="...", status="ok")
    ws.runs.append(run)
    # No active case: working context defaults to baseline scope.
    assert ws.active_case_id is None

    svc._service_context.confirm_run_invalidation = lambda: True
    body_id = svc.create_punctual_mass("M", x="0 mm", y="0 mm")
    svc.update_property(body_id, "mass", PropertyValueInput(kind="expression", value="3 kg"))

    assert run.status == "stale"


def test_pose_edit_flips_runs_of_that_pose_to_stale():
    """Regression: mutating a Pose used to leave linked runs untouched.
    `set_current_pose` now calls `mark_runs_stale_for_pose`."""
    from copy import deepcopy
    from quino.application.service import ApplicationService
    from quino.domain.model import BodyPose, Pose
    from quino.domain.inputs import MarkerInput

    svc = ApplicationService()
    svc.new_project("t")
    bar = svc.create_bar(
        "Bar",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
    )
    ws = svc.project.workspace
    baseline = ws.baselines[0]
    wp = svc.workspace.create_pose("P", baseline_id=baseline.id)
    a = svc.workspace.create_analysis(
        "A", analysis_type="dynamic",
        baseline_id=baseline.id, workspace_pose_id=wp.id,
    )
    run = Run(id="r1", analysis_id=a.id, created_at="...", status="ok")
    ws.runs.append(run)

    svc.set_current_pose_id(wp.project_pose_id)
    current = svc.get_current_pose()
    mutated = deepcopy(current)
    mutated.body_poses[bar] = BodyPose(body_id=bar, x=10.0, y=20.0, angle=0.5)
    svc.set_current_pose(mutated)

    assert run.status == "stale"
    assert any("pose edited" in w for w in run.warnings)


def test_mark_runs_stale_for_pose_only_targets_bound_analyses():
    """`mark_runs_stale_for_pose` must NOT touch runs of analyses that
    don't bind to the affected pose."""
    from quino.application.service import ApplicationService
    from quino.services.run_invalidation import mark_runs_stale_for_pose

    svc = ApplicationService()
    svc.new_project("t")
    ws = svc.project.workspace
    baseline = ws.baselines[0]
    wp1 = svc.workspace.create_pose("P1", baseline_id=baseline.id)
    wp2 = svc.workspace.create_pose("P2", baseline_id=baseline.id)
    a1 = svc.workspace.create_analysis(
        "A1", baseline_id=baseline.id, workspace_pose_id=wp1.id,
    )
    a2 = svc.workspace.create_analysis(
        "A2", baseline_id=baseline.id, workspace_pose_id=wp2.id,
    )
    r1 = Run(id="r1", analysis_id=a1.id, created_at="...", status="ok")
    r2 = Run(id="r2", analysis_id=a2.id, created_at="...", status="ok")
    ws.runs.extend([r1, r2])

    n = mark_runs_stale_for_pose(ws, wp1.project_pose_id, reason="x")
    assert n == 1
    assert r1.status == "stale"
    assert r2.status == "ok"
