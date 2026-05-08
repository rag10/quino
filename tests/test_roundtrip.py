from __future__ import annotations

from quino import ApplicationService, JointEndpointInput, JointEndpointKind, MarkerInput
from quino.serialization.json_io import JsonMapper


def test_roundtrip_project_json() -> None:
    app = ApplicationService()
    project = app.new_project("Demo")
    app.create_parameter("L1", "120 mm", "mm")
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    app.create_joint(
        "Ground_A",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body_id, marker_id=marker_id),
        JointEndpointInput(JointEndpointKind.GROUND),
    )

    mapper = JsonMapper()
    data = mapper.dump(project)
    restored = mapper.load(data)

    assert restored.name == "Demo"
    assert restored.model.bodies[0].name == "Crank"
    assert restored.model.bodies[0].com_marker().type.value == "com"
    assert restored.model.joints[0].name == "Ground_A"
