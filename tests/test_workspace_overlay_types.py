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
    assert not hasattr(overlay, "poses")
    assert not hasattr(overlay, "deleted_inherited_pose_ids")


from quino.domain.workspace import Pose as WorkspacePoseV2


def test_workspace_pose_defaults():
    pose = WorkspacePoseV2(id="p1", name="Default")
    assert pose.is_default is False
    assert pose.requires_recompute is True
    assert pose.solve_failed is False
    assert pose.body_poses == {}
    assert pose.parent_pose_id is None


from quino.domain.workspace import Analysis, Case, Run, Workspace


def test_case_defaults():
    case = Case(id="c1", name="Root")
    assert case.parent_case_id is None
    assert case.overlay is None
    assert case.runs == []
    assert case.analyses == []
    assert case.poses == []


def test_workspace_defaults():
    ws = Workspace(id="w1", name="Test", schema_version="0.3.0")
    assert ws.root_case_ids == []
    assert ws.cases == {}
    assert ws.selected_case_id is None


def test_analysis_no_baseline_id_or_case_id():
    a = Analysis(id="a1", name="A", analysis_type="static")
    assert not hasattr(a, "baseline_id")
    assert not hasattr(a, "case_id")
    assert not hasattr(a, "workspace_pose_id")
    assert a.pose_id is None


import pytest


def test_project_removed_from_model():
    import quino.domain.model as m
    with pytest.raises(ImportError):
        m.Project


def test_pose_removed_from_model():
    import quino.domain.model as m
    with pytest.raises(ImportError):
        m.Pose
