import pytest
from quino.application.service import ApplicationService
from quino.domain.workspace import Workspace, Baseline, Case


def _bootstrap_with_case():
    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        cases=[Case(id="c", name="C1", baseline_id="b")],
        active_baseline_id="b",
        active_case_id="c",
    )
    return app


def test_add_block_with_case_active_writes_to_case():
    app = _bootstrap_with_case()
    app.add_block(block_type="Constant", name="Source", position=(0.0, 0.0))
    case = app.project.workspace.cases[0]
    assert "blocks" in case.added_entities
    assert len(case.added_entities["blocks"]) == 1
    assert case.added_entities["blocks"][0]["block_type"] == "Constant"
    # Baseline diagram should be untouched
    cg = app.project.model.control_graph
    assert cg is None or len(cg.instances) == 0


def test_add_block_no_case_active_writes_to_baseline():
    app = ApplicationService()
    app.new_project("test")
    app.project.workspace = Workspace(
        baselines=[Baseline(id="b", name="base")],
        active_baseline_id="b",
    )
    app.add_block(block_type="Constant", name="Source", position=(0.0, 0.0))
    diagram = app.project.model.control_graph
    assert diagram is not None
    assert len(diagram.instances) == 1
    inst = next(iter(diagram.instances.values()))
    assert [port.name for port in inst.output_ports] == ["out"]


def test_add_block_with_case_active_serializes_registry_ports():
    app = _bootstrap_with_case()
    app.add_block(block_type="Gain", name="Gain", position=(0.0, 0.0))
    case = app.project.workspace.cases[0]
    block = case.added_entities["blocks"][0]
    assert [port["name"] for port in block["input_ports"]] == ["in"]
    assert [port["name"] for port in block["output_ports"]] == ["out"]


def test_set_block_parameter_with_case_active_writes_invariant_value():
    from quino.domain.blocks import BlockDiagram, BlockInstance
    app = _bootstrap_with_case()
    diagram = BlockDiagram()
    diagram.instances["pid"] = BlockInstance(instance_id="pid", block_type="pid", parameters={"kp": 1.0})
    app.project.model.control_graph = diagram
    app.set_block_parameter("pid", "kp", 2.5)
    case = app.project.workspace.cases[0]
    path = "model/control_graph/instances/pid/parameters/kp"
    assert path in case.invariant_values
    # Original kp untouched
    assert diagram.instances["pid"].parameters["kp"] == 1.0


def test_set_block_string_parameter_with_case_active_writes_reference_override():
    from quino.domain.blocks import BlockDiagram, BlockInstance
    app = _bootstrap_with_case()
    diagram = BlockDiagram()
    diagram.instances["sensor_block"] = BlockInstance(
        instance_id="sensor_block",
        block_type="ModelSensor",
        parameters={"sensor_id": ""},
    )
    app.project.model.control_graph = diagram

    app.set_block_parameter("sensor_block", "sensor_id", "sensor_001")

    case = app.project.workspace.cases[0]
    assert case.reference_overrides["sensor_block"]["parameters"]["sensor_id"] == "sensor_001"
    assert diagram.instances["sensor_block"].parameters["sensor_id"] == ""
    assert (
        app.display_project.model.control_graph.instances["sensor_block"].parameters["sensor_id"]
        == "sensor_001"
    )


def test_remove_block_added_by_case_drops_from_added_entities():
    app = _bootstrap_with_case()
    bid = app.add_block(block_type="constant", name="C", position=(0, 0))
    case = app.project.workspace.cases[0]
    assert len(case.added_entities["blocks"]) == 1
    app.remove_block(bid)
    assert case.added_entities.get("blocks", []) == []


def test_remove_block_from_baseline_records_removal_in_case():
    from quino.domain.blocks import BlockDiagram, BlockInstance
    app = _bootstrap_with_case()
    diagram = BlockDiagram()
    diagram.instances["pid"] = BlockInstance(instance_id="pid", block_type="pid", parameters={})
    app.project.model.control_graph = diagram
    app.remove_block("pid")
    case = app.project.workspace.cases[0]
    assert "pid" in case.removed_entity_ids
    # Baseline diagram still has it (composer will drop it on compose)
    assert "pid" in app.project.model.control_graph.instances


def test_remove_connection_with_case_records_removal():
    from quino.domain.blocks import BlockDiagram, BlockInstance, Connection
    app = _bootstrap_with_case()
    diagram = BlockDiagram()
    diagram.instances["a"] = BlockInstance(instance_id="a", block_type="src", parameters={})
    diagram.instances["b"] = BlockInstance(instance_id="b", block_type="sink", parameters={})
    diagram.connections.append(Connection(src_instance="a", src_port="out", dst_instance="b", dst_port="in"))
    app.project.model.control_graph = diagram
    app.remove_connection(src_instance="a", src_port="out", dst_instance="b", dst_port="in")
    case = app.project.workspace.cases[0]
    assert ("a", "out", "b", "in") in case.removed_connections
    # Baseline still has it
    assert len(diagram.connections) == 1


def test_remove_block_no_case_removes_baseline_connections():
    from quino.domain.blocks import BlockDiagram, BlockInstance, Connection
    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram()
    diagram.instances["a"] = BlockInstance(instance_id="a", block_type="src", parameters={})
    diagram.instances["b"] = BlockInstance(instance_id="b", block_type="sink", parameters={})
    diagram.connections.append(Connection(src_instance="a", src_port="out", dst_instance="b", dst_port="in"))
    app.project.model.control_graph = diagram

    app.remove_block("a")

    assert "a" not in diagram.instances
    assert diagram.connections == []


def test_remove_connection_no_case_updates_frozen_baseline_diagram():
    from quino.domain.blocks import BlockDiagram, BlockInstance, Connection
    app = ApplicationService()
    app.new_project("test")
    diagram = BlockDiagram()
    diagram.instances["a"] = BlockInstance(instance_id="a", block_type="src", parameters={})
    diagram.instances["b"] = BlockInstance(instance_id="b", block_type="sink", parameters={})
    diagram.connections.append(Connection(src_instance="a", src_port="out", dst_instance="b", dst_port="in"))
    app.project.model.control_graph = diagram

    app.remove_connection(src_instance="a", src_port="out", dst_instance="b", dst_port="in")

    assert diagram.connections == []


def test_remove_added_connection_drops_from_added_entities():
    app = _bootstrap_with_case()
    a = app.add_block(block_type="constant", name="A", position=(0, 0))
    b = app.add_block(block_type="constant", name="B", position=(1, 1))
    app.add_connection(src_instance=a, src_port="out", dst_instance=b, dst_port="in")
    case = app.project.workspace.cases[0]
    assert len(case.added_entities.get("connections", [])) == 1
    app.remove_connection(src_instance=a, src_port="out", dst_instance=b, dst_port="in")
    assert case.added_entities.get("connections", []) == []
    assert case.removed_connections == []  # was added by case, not pre-existing


def test_set_block_position_with_case_writes_reference_override():
    from quino.domain.blocks import BlockDiagram, BlockInstance
    app = _bootstrap_with_case()
    diagram = BlockDiagram()
    diagram.instances["pid"] = BlockInstance(instance_id="pid", block_type="pid", parameters={"_position": [0, 0]})
    app.project.model.control_graph = diagram
    app.set_block_position("pid", (100.0, 50.0))
    case = app.project.workspace.cases[0]
    assert case.reference_overrides["pid"]["_position"] == [100.0, 50.0]
    # Baseline position untouched
    assert diagram.instances["pid"].parameters["_position"] == [0, 0]


def test_child_case_removing_inherited_block_removes_inherited_connections():
    app = ApplicationService()
    app.new_project("blocks")
    baseline = app.project.workspace.baselines[0]
    parent = app.workspace.create_case("Parent", baseline_id=baseline.id)
    child = app.workspace.create_case("Child", parent_case_id=parent.id)

    app.set_working_context(case_id=parent.id)
    src_id = app.add_block(block_type="Constant", name="Source", position=(0.0, 0.0))
    dst_id = app.add_block(block_type="Gain", name="Gain", position=(100.0, 0.0))
    app.add_connection(src_instance=src_id, src_port="out", dst_instance=dst_id, dst_port="in")

    app.set_working_context(case_id=child.id)
    app.remove_block(src_id)

    cg = app.display_project.model.control_graph
    assert cg is not None
    assert src_id not in cg.instances
    assert dst_id in cg.instances
    assert all(conn.src_instance != src_id and conn.dst_instance != src_id for conn in cg.connections)
