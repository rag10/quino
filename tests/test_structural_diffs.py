"""Tests for structural diffs (added_entities / removed_entity_ids) in cases."""
import pytest
from quino.application.service import ApplicationService


@pytest.fixture
def svc_with_case():
    svc = ApplicationService()
    svc.new_project("test")
    body_id = svc.create_punctual_mass("BaseBody", x="0 mm", y="0 mm")
    baseline = svc.workspace.create_baseline("B1")
    case = svc.workspace.create_case("C1", baseline_id=baseline.id)
    return svc, body_id, baseline, case


def test_create_body_with_case_active_adds_to_case(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    svc.set_working_context(case_id=case.id)

    new_body_id = svc.create_punctual_mass("CaseBody", x="10 mm", y="10 mm")

    # Should NOT be in base model
    assert not any(b.id == new_body_id for b in svc.project.model.bodies)
    # Should be in case added_entities
    assert "bodies" in case.added_entities
    assert any(e["id"] == new_body_id for e in case.added_entities["bodies"])
    # Should appear in display_project
    dp = svc.display_project
    assert any(b.id == new_body_id for b in dp.model.bodies)


def test_delete_base_body_with_case_active_records_removal(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    svc.set_working_context(case_id=case.id)

    svc.delete_entity(base_body_id)

    # Base model should still have the body
    assert any(b.id == base_body_id for b in svc.project.model.bodies)
    # Case should record removal
    assert base_body_id in case.removed_entity_ids
    # Display project should NOT have the body
    dp = svc.display_project
    assert not any(b.id == base_body_id for b in dp.model.bodies)


def test_delete_case_added_body_removes_from_added_entities(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    svc.set_working_context(case_id=case.id)

    new_body_id = svc.create_punctual_mass("CaseBody", x="10 mm", y="10 mm")
    svc.delete_entity(new_body_id)

    # Should be removed from added_entities entirely
    assert not any(e["id"] == new_body_id for e in case.added_entities.get("bodies", []))
    # Should NOT be in removed_entity_ids
    assert new_body_id not in case.removed_entity_ids


def test_create_joint_with_case_active_adds_to_case(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    svc.set_working_context(case_id=case.id)

    body = next(b for b in svc.project.model.bodies if b.id == base_body_id)
    marker = body.markers[0]
    joint_id = svc.connect_marker_to_ground(marker.id, joint_type="revolute", name="J1")

    # Should NOT be in base model
    assert not any(j.id == joint_id for j in svc.project.model.joints)
    # Should be in case added_entities
    assert "joints" in case.added_entities
    assert any(e["id"] == joint_id for e in case.added_entities["joints"])
    # Should appear in display_project
    dp = svc.display_project
    assert any(j.id == joint_id for j in dp.model.joints)


def test_create_driver_with_case_active_adds_to_case(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    body = next(b for b in svc.project.model.bodies if b.id == base_body_id)
    marker = body.markers[0]
    joint_id = svc.connect_marker_to_ground(marker.id, joint_type="revolute", name="J1")

    svc.set_working_context(case_id=case.id)
    driver_id = svc.create_driver("D1", "rotation", joint_id, "0 deg", "deg")

    # Should NOT be in base model
    assert not any(d.id == driver_id for d in svc.project.model.drivers)
    # Should be in case added_entities
    assert "drivers" in case.added_entities
    assert any(e["id"] == driver_id for e in case.added_entities["drivers"])
    # Should appear in display_project
    dp = svc.display_project
    assert any(d.id == driver_id for d in dp.model.drivers)


def test_create_sensor_with_case_active_adds_to_case(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    body = next(b for b in svc.project.model.bodies if b.id == base_body_id)
    marker = body.markers[0]

    svc.set_working_context(case_id=case.id)
    sensor_id = svc.create_sensor("S1", "point", [marker.id])

    # Should NOT be in base model
    assert not any(s.id == sensor_id for s in svc.project.model.sensors)
    # Should be in case added_entities
    assert "sensors" in case.added_entities
    assert any(e["id"] == sensor_id for e in case.added_entities["sensors"])
    # Should appear in display_project
    dp = svc.display_project
    assert any(s.id == sensor_id for s in dp.model.sensors)


def test_create_load_with_case_active_adds_to_case(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    body = next(b for b in svc.project.model.bodies if b.id == base_body_id)
    marker = body.markers[0]

    svc.set_working_context(case_id=case.id)
    load_id = svc.create_load("L1", marker.id, "0 N", "0 N")

    # Should NOT be in base model
    assert not any(ld.id == load_id for ld in svc.project.model.loads)
    # Should be in case added_entities
    assert "loads" in case.added_entities
    assert any(e["id"] == load_id for e in case.added_entities["loads"])
    # Should appear in display_project
    dp = svc.display_project
    assert any(ld.id == load_id for ld in dp.model.loads)


def test_create_slider_with_case_active_adds_to_case(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case

    svc.set_working_context(case_id=case.id)
    from quino.domain.inputs import SliderInput
    slider_id = svc.create_slider("SL1", SliderInput("0 mm", "0 mm", "0 deg", "-10 mm", "10 mm"))

    # Should NOT be in base model
    assert not any(s.id == slider_id for s in svc.project.model.sliders)
    # Should be in case added_entities
    assert "sliders" in case.added_entities
    assert any(e["id"] == slider_id for e in case.added_entities["sliders"])
    # Should appear in display_project
    dp = svc.display_project
    assert any(s.id == slider_id for s in dp.model.sliders)


def test_create_spring_with_case_active_adds_to_case(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    body = next(b for b in svc.project.model.bodies if b.id == base_body_id)
    marker = body.markers[0]

    svc.set_working_context(case_id=case.id)
    from quino.domain.model import SpringEndpoint
    from quino.domain.types import SpringEndpointKind
    spring_id = svc.create_spring(
        "SP1", "linear_spring",
        SpringEndpoint(kind=SpringEndpointKind.MARKER, marker_id=marker.id),
        SpringEndpoint(kind=SpringEndpointKind.GROUND),
    )

    # Should NOT be in base model
    assert not any(sp.id == spring_id for sp in svc.project.model.springs)
    # Should be in case added_entities
    assert "springs" in case.added_entities
    assert any(e["id"] == spring_id for e in case.added_entities["springs"])
    # Should appear in display_project
    dp = svc.display_project
    assert any(sp.id == spring_id for sp in dp.model.springs)


def test_body_removal_cascade_in_composed_project(svc_with_case):
    """Removing a base body from a case should cascade to its joints/drivers in compose."""
    svc, base_body_id, baseline, case = svc_with_case
    body = next(b for b in svc.project.model.bodies if b.id == base_body_id)
    marker = body.markers[0]
    joint_id = svc.connect_marker_to_ground(marker.id, joint_type="revolute", name="J1")
    driver_id = svc.create_driver("D1", "rotation", joint_id, "0 deg", "deg")

    svc.set_working_context(case_id=case.id)
    svc.delete_entity(base_body_id)

    # Base model still has everything
    assert any(b.id == base_body_id for b in svc.project.model.bodies)
    assert any(j.id == joint_id for j in svc.project.model.joints)
    assert any(d.id == driver_id for d in svc.project.model.drivers)

    # Composed project should have none of them (cascade removal)
    dp = svc.display_project
    assert not any(b.id == base_body_id for b in dp.model.bodies)
    assert not any(j.id == joint_id for j in dp.model.joints)
    assert not any(d.id == driver_id for d in dp.model.drivers)


def test_case_adds_block_instance_to_composed_model():
    from quino.domain.blocks import BlockDiagram
    from quino.domain.model import Model, Project
    from quino.domain.workspace import Case, Workspace, Baseline
    from quino.services.workspace_composition import compose_project

    project = Project(id="p", name="test", schema_version="1", model=Model(control_graph=BlockDiagram()))
    project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        cases=[Case(id="c1", name="C1", baseline_id="b",
                    added_entities={"blocks": [{
                        "id": "pid",
                        "block_type": "pid",
                        "parameters": {"kp": 1.0},
                        "input_ports": [],
                        "output_ports": [],
                        "position": [0.0, 0.0],
                    }]})],
    )
    composed = compose_project(project, case=project.workspace.cases[0])
    assert "pid" in composed.model.control_graph.instances
    assert composed.model.control_graph.instances["pid"].parameters["kp"] == 1.0


def test_case_adds_connection_to_composed_model():
    from quino.domain.blocks import BlockDiagram, BlockInstance
    from quino.domain.model import Model, Project
    from quino.domain.workspace import Case, Workspace, Baseline
    from quino.services.workspace_composition import compose_project

    diagram = BlockDiagram()
    diagram.instances["src"] = BlockInstance(instance_id="src", block_type="constant")
    diagram.instances["dst"] = BlockInstance(instance_id="dst", block_type="gain")
    project = Project(id="p", name="test", schema_version="1", model=Model(control_graph=diagram))
    project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        cases=[Case(id="c1", name="C1", baseline_id="b",
                    added_entities={"connections": [{
                        "src_instance": "src", "src_port": "out",
                        "dst_instance": "dst", "dst_port": "in",
                    }]})],
    )
    composed = compose_project(project, case=project.workspace.cases[0])
    assert len(composed.model.control_graph.connections) == 1
    conn = composed.model.control_graph.connections[0]
    assert conn.src_instance == "src"
    assert conn.dst_instance == "dst"


def test_roundtrip_json_preserves_structural_diffs(svc_with_case):
    svc, base_body_id, baseline, case = svc_with_case
    svc.set_working_context(case_id=case.id)
    new_body_id = svc.create_punctual_mass("CaseBody", x="10 mm", y="10 mm")
    svc.delete_entity(base_body_id)

    from quino.serialization.json_io import JsonMapper
    mapper = JsonMapper()
    payload = mapper.dump(svc.project)
    restored = mapper.load(payload)

    restored_case = next(c for c in restored.workspace.cases if c.id == case.id)
    assert "bodies" in restored_case.added_entities
    assert any(e["id"] == new_body_id for e in restored_case.added_entities["bodies"])
    assert base_body_id in restored_case.removed_entity_ids
