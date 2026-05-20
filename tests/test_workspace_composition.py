from __future__ import annotations

import pytest

from quino import ApplicationService, MarkerInput
from quino.domain.workspace import Case, ScalarValue, Study, StudyOverlay
from quino.services.workspace_composition import compose_project, _apply_parameter_override


def test_compose_project_preserves_topology() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    param_id = app.create_parameter("L1", "120 mm", "mm")
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))

    study = Study(id="s1", name="Study")
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={f"parameters/{param_id}": ScalarValue(200.0, "mm")},
    )

    composed = compose_project(base, study, case)

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

    study = Study(id="s1", name="Study")
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={f"bodies/{body_id}/mass": ScalarValue(2.5, "kg")},
    )

    composed = compose_project(base, study, case)
    assert composed.model.bodies[0].mass.expression == "2.5 kg"


def test_compose_project_override_load_force() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "A")])
    marker = [m for m in app._find_body(body_id).markers if m.name == "A"][0]
    load_id = app.create_load("Wind", marker.id, "10 N", "-5 N")

    study = Study(id="s1", name="Study")
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={f"loads/{load_id}/fx": ScalarValue(20.0, "N")},
    )

    composed = compose_project(base, study, case)
    load = composed.model.loads[0]
    assert load.fx.expression == "20 N"
    assert load.fy.expression == "-5 N"


def test_compose_project_study_variable_override() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    param_id = app.create_parameter("L1", "120 mm", "mm")

    study = Study(
        id="s1",
        name="Study",
        variable_values={f"parameters/{param_id}": ScalarValue(300.0, "mm")},
    )

    composed = compose_project(base, study, None)
    assert composed.parameters[0].expression == "300 mm"


def test_compose_project_study_overlay_override() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    param_id = app.create_parameter("L1", "120 mm", "mm")

    study = Study(
        id="s1",
        name="Study",
        overlay=StudyOverlay(
            parameter_overrides={f"parameters/{param_id}": ScalarValue(400.0, "mm")},
        ),
    )

    composed = compose_project(base, study, None)
    assert composed.parameters[0].expression == "400 mm"


def test_compose_project_priority_case_then_study() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    param_id = app.create_parameter("L1", "120 mm", "mm")

    study = Study(
        id="s1",
        name="Study",
        variable_values={f"parameters/{param_id}": ScalarValue(300.0, "mm")},
    )
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={f"parameters/{param_id}": ScalarValue(200.0, "mm")},
    )

    composed = compose_project(base, study, case)
    # Study variable_values has higher priority than case
    assert composed.parameters[0].expression == "300 mm"


def test_compose_project_invalid_path_raises() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    study = Study(id="s1", name="Study")
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={"bodies/nonexistent/mass": ScalarValue(2.5, "kg")},
    )

    with pytest.raises(ValueError, match="not found"):
        compose_project(base, study, case)


def test_compose_project_invalid_domain_raises() -> None:
    app = ApplicationService()
    base = app.new_project("Base")
    study = Study(id="s1", name="Study")
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={"unknown/foo/bar": ScalarValue(1.0, "")},
    )

    with pytest.raises(ValueError, match="Unknown parameter domain"):
        compose_project(base, study, case)


def test_apply_parameter_override_block_diagram() -> None:
    from quino.domain.blocks import BlockDiagram, BlockInstance

    app = ApplicationService()
    base = app.new_project("Base")
    base.block_diagram = BlockDiagram(
        instances={"pid_001": BlockInstance(instance_id="pid_001", block_type="PID", parameters={"kp": 1.0, "ki": 0.1})},
        connections=[],
    )

    study = Study(id="s1", name="Study")
    case = Case(
        id="c1",
        name="Case1",
        invariant_values={"block_diagram/instances/pid_001/parameters/kp": ScalarValue(5.0, "")},
    )

    composed = compose_project(base, study, case)
    assert composed.block_diagram.instances["pid_001"].parameters["kp"] == 5.0
    assert composed.block_diagram.instances["pid_001"].parameters["ki"] == 0.1
