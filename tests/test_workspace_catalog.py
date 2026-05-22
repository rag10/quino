from __future__ import annotations

import pytest

from quino import ApplicationService, MarkerInput
from quino.domain.blocks import BlockDiagram, BlockInstance
from quino.domain.model import SpringEndpoint
from quino.domain.types import SpringEndpointKind
from quino.domain.workspace import Case, ScalarValue, Workspace
from quino.services.workspace_catalog import build_parameter_catalog
from quino.services.workspace_composition import compose_project


def test_build_parameter_catalog_derives_paths_and_tags() -> None:
    app = ApplicationService()
    project = app.new_project("Catalog")
    param_id = app.create_parameter("L1", "120 mm", "mm")
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app.get_body(body_id)
    assert body is not None
    marker_a = next(m.id for m in body.markers if m.name == "A")
    marker_b = next(m.id for m in body.markers if m.name == "B")
    load_id = app.create_load("Wind", marker_b, "10 N", "0 N")
    spring_id = app.create_spring(
        "Act",
        "linear_actuator",
        SpringEndpoint(kind=SpringEndpointKind.MARKER, marker_id=marker_a),
        SpringEndpoint(kind=SpringEndpointKind.MARKER, marker_id=marker_b),
    )
    driver_joint_id = app.connect_marker_to_ground(marker_a)
    driver_id = app.create_driver("Drv", "rotation", driver_joint_id, "10 deg", "deg")
    project.model.control_graph = BlockDiagram(
        instances={
            "pid_001": BlockInstance(
                instance_id="pid_001",
                block_type="PID",
                parameters={"kp": 1.0, "ki": 2.0},
            )
        },
        connections=[],
    )

    catalog = build_parameter_catalog(project)

    assert catalog[f"parameters/{param_id}"].tag == "invariant"
    assert catalog[f"loads/{load_id}/fx"].tag == "invariant"
    assert catalog[f"springs/{spring_id}/law"].tag == "variable"
    assert catalog[f"drivers/{driver_id}/law"].tag == "variable"
    assert catalog["model/control_graph/instances/pid_001/parameters/kp"].tag == "variable"
    assert "block_diagram/instances/pid_001/parameters/kp" in catalog


