from __future__ import annotations

import pytest

from quino import ApplicationService, MarkerInput
from quino.domain.workspace import Case, ScalarValue, Workspace
from quino.services.workspace_composition import compose_project, _apply_parameter_override


def test_compose_project_preserves_topology() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    param_id = app.create_parameter("L1", "120 mm", "mm")
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))

    case = Case(
        id="c1",
        name="Case1",
        invariant_values={f"parameters/{param_id}": ScalarValue(200.0, "mm")},
    )

    composed = compose_project(base, case=case)

    assert composed.name == base.name
    assert len(composed.model.bodies) == 1
    assert composed.model.bodies[0].id == body_id
    # Parameter overridden
    param = composed.parameters[0]
    assert param.expression == "200 mm"


def test_compose_project_override_body_mass() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "A")])
    # Body starts with no mass; set a mass expression first via the domain
    from quino.domain.model import ScalarProperty
    from quino.domain.types import Dimension

    body = app._find_body(body_id)
    body.mass = ScalarProperty(expression="1 kg", unit="kg", expected_dimension=Dimension.MASS)

    case = Case(
        id="c1",
        name="Case1",
        invariant_values={f"bodies/{body_id}/mass": ScalarValue(2.5, "kg")},
    )

    composed = compose_project(base, case=case)
    assert composed.model.bodies[0].mass.expression == "2.5 kg"


def test_compose_project_override_load_force() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "A")])
    marker = [m for m in app._find_body(body_id).markers if m.name == "A"][0]
    load_id = app.create_load("Wind", marker.id, "10 N", "-5 N")

    case = Case(
        id="c1",
        name="Case1",
        invariant_values={f"loads/{load_id}/fx": ScalarValue(20.0, "N")},
    )

    composed = compose_project(base, case=case)
    load = composed.model.loads[0]
    assert load.fx.expression == "20 N"
    assert load.fy.expression == "-5 N"


def _pvi(expr: str):
    from quino.domain.inputs import PropertyValueInput
    return PropertyValueInput(kind="expression", value=expr)


def test_compose_project_invalid_path_raises() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={"bodies/nonexistent/mass": ScalarValue(2.5, "kg")},
    )

    with pytest.raises(ValueError, match="not found"):
        compose_project(base, case=case)


def test_compose_project_invalid_domain_raises() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={"unknown/foo/bar": ScalarValue(1.0, "")},
    )

    with pytest.raises(ValueError, match="Unknown parameter domain"):
        compose_project(base, case=case)


def test_apply_parameter_override_block_diagram() -> None:
    """Direct override of block_diagram path."""
    from quino.domain.blocks import BlockDiagram, BlockInstance

    app = ApplicationService()
    base = app.new_project("Base")
    base.model.control_graph = BlockDiagram(
        instances={"pid_001": BlockInstance(instance_id="pid_001", block_type="PID", parameters={"kp": 1.0, "ki": 0.1})},
        connections=[],
    )

    _apply_parameter_override(base, "block_diagram/instances/pid_001/parameters/kp", ScalarValue(5.0, ""))
    assert base.model.control_graph.instances["pid_001"].parameters["kp"] == 5.0
    assert base.model.control_graph.instances["pid_001"].parameters["ki"] == 0.1


def test_apply_parameter_override_model_control_graph() -> None:
    """Same as above using the model/control_graph/... legacy path form."""
    from quino.domain.blocks import BlockDiagram, BlockInstance

    app = ApplicationService()
    base = app.new_project("Base")
    base.model.control_graph = BlockDiagram(
        instances={"pid_001": BlockInstance(instance_id="pid_001", block_type="PID", parameters={"kp": 1.0, "ki": 0.1})},
        connections=[],
    )

    _apply_parameter_override(base, "model/control_graph/instances/pid_001/parameters/kp", ScalarValue(7.0, ""))
    assert base.model.control_graph is not None
    assert base.model.control_graph.instances["pid_001"].parameters["kp"] == 7.0


def test_compose_project_applies_parent_case_chain_accumulatively() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    p1 = app.create_parameter("L1", "120 mm", "mm")
    p2 = app.create_parameter("L2", "80 mm", "mm")
    base.workspace = Workspace()
    parent = Case(
        id="case_parent",
        name="Parent",
        baseline_id="baseline_001",
        invariant_values={f"parameters/{p1}": ScalarValue(200.0, "mm")},
    )
    child = Case(
        id="case_child",
        name="Child",
        baseline_id="baseline_001",
        parent_case_id=parent.id,
        invariant_values={f"parameters/{p2}": ScalarValue(150.0, "mm")},
    )
    base.workspace.cases.extend([parent, child])

    composed = compose_project(base, case=child)

    assert composed.parameters[0].expression == "200 mm"
    assert composed.parameters[1].expression == "150 mm"
