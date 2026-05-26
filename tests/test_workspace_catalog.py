from __future__ import annotations

import pytest

from quino import ApplicationService, MarkerInput
from quino.domain.blocks import BlockDiagram, BlockInstance
from quino.domain.model import Parameter, SpringEndpoint
from quino.domain.types import SpringEndpointKind
from quino.domain.workspace import Case, ScalarValue, Workspace
from quino.services.workspace_catalog import build_parameter_catalog


def test_build_parameter_catalog_derives_paths_and_tags() -> None:
    app = ApplicationService()
    app.new_workspace("Catalog")
    param_id = app.create_parameter("L1", "120 mm", "mm")
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body = app.get_body(body_id)
    assert body is not None
    marker_a = next(m.id for m in body.markers if m.name == "A")
    driver_joint_id = app.connect_marker_to_ground(marker_a)
    driver_id = app.create_driver("Drv", "rotation", driver_joint_id, "10 deg", "deg")

    # Add a control graph to the root case model directly (avoids create_load path that has unrelated bug)
    root_case = app.current_case()
    assert root_case is not None
    root_case.model.control_graph = BlockDiagram(
        instances={
            "pid_001": BlockInstance(
                instance_id="pid_001",
                block_type="PID",
                parameters={"kp": 1.0, "ki": 2.0},
            )
        },
        connections=[],
    )

    catalog = build_parameter_catalog(app._workspace)

    assert catalog[f"parameters/{param_id}"].tag == "invariant"
    assert catalog[f"drivers/{driver_id}/law"].tag == "variable"
    assert catalog["model/control_graph/instances/pid_001/parameters/kp"].tag == "variable"
    assert "block_diagram/instances/pid_001/parameters/kp" in catalog


def test_build_parameter_catalog_empty_workspace() -> None:
    """Workspace with no root cases returns only parameter entries."""
    ws = Workspace(id="ws1", name="Empty", schema_version="0.3.0")
    catalog = build_parameter_catalog(ws)
    assert isinstance(catalog, dict)
    assert len(catalog) == 0


def test_build_parameter_catalog_parameters_only() -> None:
    """Workspace-level parameters appear without needing a root case model."""
    ws = Workspace(id="ws1", name="Test", schema_version="0.3.0")
    p = Parameter(id="p1", name="Length", expression="100 mm", unit="mm")
    ws.parameters = [p]
    ws.root_case_ids = []

    catalog = build_parameter_catalog(ws)

    assert "parameters/p1" in catalog
    assert catalog["parameters/p1"].tag == "invariant"
    assert catalog["parameters/p1"].display_name == "Length"
