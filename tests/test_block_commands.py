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
    app.add_block(block_type="constant", name="Source", position=(0.0, 0.0))
    case = app.project.workspace.cases[0]
    assert "blocks" in case.added_entities
    assert len(case.added_entities["blocks"]) == 1
    assert case.added_entities["blocks"][0]["block_type"] == "constant"
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
    app.add_block(block_type="constant", name="Source", position=(0.0, 0.0))
    diagram = app.project.model.control_graph
    assert diagram is not None
    assert len(diagram.instances) == 1


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
