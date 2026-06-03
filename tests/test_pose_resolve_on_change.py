"""User poses must be RE-SOLVED (not deleted) when the model changes, so their
analyses never get orphaned. The reference pose is untouched."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.domain.model import BodyPose
from quino.application.service import ApplicationService


def _svc_with_user_pose_and_analysis():
    svc = ApplicationService()
    svc.new_project("t")
    case = svc.current_case()
    pose = svc.workspace.create_pose("Working")
    # Give the user pose some solved body data so it is a real (non-empty) pose.
    pose.body_poses["__probe__"] = BodyPose(body_id="__probe__", x=1.0, y=2.0, angle=0.0)
    analysis = svc.workspace.create_analysis(
        "Dyn", case_id=case.id, workspace_pose_id=pose.id
    )
    return svc, case, pose, analysis


def test_invalidate_keeps_user_poses_and_analyses():
    svc, case, pose, analysis = _svc_with_user_pose_and_analysis()
    n_poses_before = len(case.poses)

    # Trigger the invalidation path directly (what a marker move calls).
    svc._invalidate_pose_state()

    # The user pose must STILL be there (not dropped).
    assert len(case.poses) == n_poses_before
    assert any(p.id == pose.id for p in case.poses)
    # Its analysis is still attached to it (not orphaned).
    assert any(a.id == analysis.id and a.pose_id == pose.id for a in case.analyses)


def test_invalidate_preserves_reference_pose():
    svc, case, pose, analysis = _svc_with_user_pose_and_analysis()
    svc._invalidate_pose_state()
    defaults = [p for p in case.poses if p.is_default]
    assert len(defaults) == 1


def test_resolve_all_user_poses_returns_failures_list():
    svc, case, pose, analysis = _svc_with_user_pose_and_analysis()
    # The probe body does not exist in the model, so solving will not produce a
    # valid configuration; the pose must be preserved and reported as failed,
    # never deleted.
    failed = svc.poses.resolve_all_user_poses(reason="test")
    assert isinstance(failed, list)
    assert any(p.id == pose.id for p in case.poses)  # preserved regardless
