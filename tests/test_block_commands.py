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
