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
    assert restored.model.bodies[0].com.kind in {
        "bar_percent", "barycentric", "marker", "local_offset",
    }
    assert restored.model.joints[0].name == "Ground_A"


def test_roundtrip_project_json_with_sketch() -> None:
    app = ApplicationService()
    project = app.new_project("SketchDemo")
    p1 = app.create_sketch_point("0 mm", "0 mm", "Point1")
    p2 = app.create_sketch_point("100 mm", "0 mm", "Point2")
    p3 = app.create_sketch_point("100 mm", "40 mm", "Point3")
    app.create_sketch_line_segment(p1, p2, "Line1")
    app.create_sketch_circle(p1, "20 mm", "Circle1")
    app.create_sketch_arc(p1, p2, p3, "Arc1")
    app.create_sketch_infinite_line(p2, p3, "Axis1")
    app.create_sketch_constraint("horizontal", [p1, p2], name="H1")
    app.create_sketch_constraint("distance", [p2, p3], value="40 mm", name="D1")

    mapper = JsonMapper()
    data = mapper.dump(project)
    restored = mapper.load(data)

    assert restored.sketch is not None
    assert restored.sketch.name == "Main Sketch"
    assert len(restored.sketch.entities) == 7
    assert len(restored.sketch.constraints) == 2
    assert any(entity.name == "Arc1" for entity in restored.sketch.entities.values())
    assert any(constraint.name == "D1" for constraint in restored.sketch.constraints.values())


def test_roundtrip_load() -> None:
    app = ApplicationService()
    project = app.new_project("LoadDemo")
    body_id = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    load_id = app.create_load("Wind", marker_id, "10 N", "-5 N")

    mapper = JsonMapper()
    data = mapper.dump(project)
    restored = mapper.load(data)

    assert len(restored.model.loads) == 1
    load = restored.model.loads[0]
    assert load.name == "Wind"
    assert load.target_marker_id == marker_id
    assert load.fx.expression == "10 N"
    assert load.fy.expression == "-5 N"
    assert load.fx.unit == "N"
    assert load.fy.unit == "N"


def test_roundtrip_sensor_scope_and_view_state() -> None:
    app = ApplicationService()
    project = app.new_project("SensorDemo")
    body_id = app.create_body("Body", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    sensor_id = app.create_sensor("Probe", "point", [marker_id])
    app.update_sensor_scope_position(sensor_id, 180.0, 96.0)
    project.view_state.show_sensors = False

    mapper = JsonMapper()
    data = mapper.dump(project)
    restored = mapper.load(data)

    assert restored.view_state.show_sensors is False
    assert len(restored.model.sensors) == 1
    sensor = restored.model.sensors[0]
    assert sensor.metadata.values["scope_canvas_x"] == 180.0
    assert sensor.metadata.values["scope_canvas_y"] == 96.0
