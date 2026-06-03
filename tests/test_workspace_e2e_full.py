"""Comprehensive end-to-end smoke test of the workspace flow (Fase 5 QA).

Exercises the real high-level ApplicationService API across the full lifecycle
of the case-as-model-without-overlays redesign:

  create model -> fork (no copy of poses/analyses) -> cascade edit (tracking
  child follows) -> diverge child (override respected) -> add pose+analysis ->
  edit model (poses re-solved, not orphaned) -> save -> reload at schema 0.4.0.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.model import BodyPose, ScalarProperty
from quino.domain.types import Dimension
from quino.services.case_cascading import CascadingEngine


def _mass(expr: str) -> ScalarProperty:
    unit = expr.split()[1]
    return ScalarProperty(expression=expr, unit=unit, expected_dimension=Dimension.MASS)


def _bar(svc: ApplicationService, case_id: str, bar_id: str):
    case = svc._workspace.cases[case_id]
    return next(b for b in case.model.bodies if b.id == bar_id)


def _new_service_with_bar():
    svc = ApplicationService()
    svc.new_workspace("E2E")
    bar_id = svc.create_bar(
        "link", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B")
    )
    return svc, svc.current_case().id, bar_id


def test_fork_inherits_only_model_and_reference_pose():
    svc, root_id, bar_id = _new_service_with_bar()
    ws = svc._workspace
    child_id = CascadingEngine(ws).fork_case(root_id, "Variant")
    child = ws.cases[child_id]
    assert child.parent_case_id == root_id
    assert [b.id for b in child.model.bodies] == [bar_id]
    assert child.analyses == []
    assert len(child.poses) == 1 and child.poses[0].is_default


def test_cascade_follows_tracking_child_but_respects_override():
    svc, root_id, bar_id = _new_service_with_bar()
    ws = svc._workspace
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root_id, "Variant")

    # forked child tracks the parent value
    assert _bar(svc, child_id, bar_id).mass == _bar(svc, root_id, bar_id).mass

    # edit parent -> tracking child follows
    engine.edit_property(root_id, bar_id, "mass", _mass("8 kg"))
    assert _bar(svc, child_id, bar_id).mass == _mass("8 kg")

    # child diverges, parent edited again -> override kept
    _bar(svc, child_id, bar_id).mass = _mass("2 kg")
    engine.edit_property(root_id, bar_id, "mass", _mass("9 kg"))
    assert _bar(svc, child_id, bar_id).mass == _mass("2 kg")
    assert _bar(svc, root_id, bar_id).mass == _mass("9 kg")


def test_model_edit_preserves_poses_and_analyses():
    svc, root_id, bar_id = _new_service_with_bar()
    ws = svc._workspace
    pose = svc.workspace.create_pose("Working", case_id=root_id)
    pose.body_poses[bar_id] = BodyPose(body_id=bar_id, x=0.0, y=0.0, angle=0.0)
    analysis = svc.workspace.create_analysis(
        "Dyn", case_id=root_id, workspace_pose_id=pose.id
    )
    n_poses = len(ws.cases[root_id].poses)

    svc._invalidate_pose_state()  # what a marker move triggers

    rc = ws.cases[root_id]
    assert len(rc.poses) == n_poses                      # not deleted
    assert any(p.id == pose.id for p in rc.poses)
    assert any(a.id == analysis.id and a.pose_id == pose.id for a in rc.analyses)


def test_save_reload_roundtrips_at_0_4_0(tmp_path):
    svc, root_id, bar_id = _new_service_with_bar()
    ws = svc._workspace
    engine = CascadingEngine(ws)
    child_id = engine.fork_case(root_id, "Variant")
    _bar(svc, child_id, bar_id).mass = _mass("2 kg")
    engine.edit_property(root_id, bar_id, "mass", _mass("9 kg"))

    pose = svc.workspace.create_pose("Working", case_id=root_id)
    pose.body_poses[bar_id] = BodyPose(body_id=bar_id, x=0.0, y=0.0, angle=0.0)
    analysis = svc.workspace.create_analysis(
        "Dyn", case_id=root_id, workspace_pose_id=pose.id
    )

    path = tmp_path / "e2e.quino.json"
    svc.save_workspace(str(path))
    blob = path.read_text(encoding="utf-8")
    assert '"overlay"' not in blob and '"runs"' not in blob

    svc2 = ApplicationService()
    svc2.load_workspace(str(path))
    ws2 = svc2._workspace
    assert ws2.schema_version == "0.4.0"
    assert set(ws2.cases) == {root_id, child_id}
    # override + parent value survive the round-trip
    assert _bar(svc2, child_id, bar_id).mass == _mass("2 kg")
    assert _bar(svc2, root_id, bar_id).mass == _mass("9 kg")
    # pose + analysis survive
    rc2 = ws2.cases[root_id]
    assert any(a.id == analysis.id for a in rc2.analyses)
    assert any(p.id == pose.id for p in rc2.poses)
