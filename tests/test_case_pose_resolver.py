import pytest
from quino.application.service import ApplicationService
from quino.domain.workspace import Workspace, Baseline, Case, WorkspacePose


def _bootstrap():
    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        cases=[Case(id="c", name="C1", baseline_id="b")],
    )
    return app


def test_resolve_default_pose_creates_if_missing():
    from quino.services.case_pose_resolver import resolve_default_pose
    app = _bootstrap()
    ws = app.project.workspace
    pose = resolve_default_pose(ws, case_id="c", app_service=app)
    assert pose.is_default is True
    assert pose.case_id == "c"
    assert pose in ws.poses


def test_resolve_default_pose_returns_existing_if_present():
    from quino.services.case_pose_resolver import resolve_default_pose
    app = _bootstrap()
    ws = app.project.workspace
    existing = WorkspacePose(id="existing-p", name="Default", case_id="c", is_default=True)
    ws.poses.append(existing)
    pose = resolve_default_pose(ws, case_id="c", app_service=app)
    assert pose.id == "existing-p"
    assert len([p for p in ws.poses if p.case_id == "c" and p.is_default]) == 1


def test_resolve_default_pose_inherits_parent_pose_id():
    from quino.services.case_pose_resolver import resolve_default_pose
    app = _bootstrap()
    ws = app.project.workspace
    parent = WorkspacePose(id="pdef", name="Default", baseline_id="b", is_default=True,
                           case_id=None)
    ws.poses.append(parent)
    pose = resolve_default_pose(ws, case_id="c", app_service=app)
    assert pose.parent_pose_id == "pdef"


def test_resolve_default_pose_marks_solve_failed_on_ik_failure(monkeypatch):
    from quino.services import case_pose_resolver
    app = _bootstrap()

    def _fail(*a, **kw):
        raise RuntimeError("IK failed")

    monkeypatch.setattr(case_pose_resolver, "_solve_with_constraints", _fail)
    pose = case_pose_resolver.resolve_default_pose(app.project.workspace, case_id="c", app_service=app)
    assert pose.solve_failed is True
    assert "IK failed" in pose.metadata.get("solve_error", "")


def test_create_case_resolves_default_pose():
    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(baselines=[Baseline(id="b", name="base")])
    app.workspace.create_case("C1", baseline_id="b")
    ws = app.project.workspace
    case = ws.cases[0]
    default_poses = [p for p in ws.poses if p.case_id == case.id and p.is_default]
    assert len(default_poses) == 1
    assert default_poses[0].requires_recompute is False
