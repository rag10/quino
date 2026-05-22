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
