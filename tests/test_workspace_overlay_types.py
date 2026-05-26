# tests/test_workspace_overlay_types.py
from quino.domain.workspace import CaseOverlay, EntityOverlay


def test_entity_overlay_local_has_no_linked_properties():
    overlay = EntityOverlay(origin="local")
    assert overlay.linked_properties == set()


def test_entity_overlay_inherited_with_linked_properties():
    overlay = EntityOverlay(origin="inherited", linked_properties={"mass", "name"})
    assert "mass" in overlay.linked_properties


def test_case_overlay_defaults_are_empty():
    overlay = CaseOverlay()
    assert overlay.entities == {}
    assert overlay.deleted_inherited_entity_ids == set()
    assert overlay.inherited_connections == set()
    assert overlay.deleted_inherited_connections == set()
    assert overlay.poses == {}
    assert overlay.deleted_inherited_pose_ids == set()


from quino.domain.workspace import Pose as WorkspacePoseV2


def test_workspace_pose_defaults():
    pose = WorkspacePoseV2(id="p1", name="Default")
    assert pose.is_default is False
    assert pose.requires_recompute is True
    assert pose.solve_failed is False
    assert pose.body_poses == {}
    assert pose.parent_pose_id is None
