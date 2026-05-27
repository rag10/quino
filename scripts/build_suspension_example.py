"""Build a realistic engineering example: 2D MacPherson-style suspension rig.

Run from the repo root:

    python scripts/build_suspension_example.py

What this exercises:

- Parametric sketch defining geometry (arm length, spring rest, mount points).
- Mechanism: chassis ground, lower control arm, wheel-hub (sprung mass),
  prismatic damper-spring acting on the hub.
- Driver: vertical road excitation (bump pulse) on the contact patch.
- Sensors: vertical hub displacement, vertical hub acceleration, spring
  length (for fatigue / packaging analysis).
- Loads: gravity, plus a payload load expressed in the inspector.
- Block diagram: an "active suspension" control loop reading the hub
  position sensor and driving an actuator force, structured as
  ModelSensor -> Gain -> PID -> LoadCommand.
- Workspace structure (one root case with multiple analyses):
    Analysis "Smooth road @ 2.5 Hz"
    Analysis "Smooth road under load"

Saved to examples/Active_Suspension_Validation.quino.json.
"""

from __future__ import annotations

from pathlib import Path

from quino.application.service import ApplicationService
from quino.domain.inputs import (
    JointEndpointInput,
    MarkerInput,
    PropertyValueInput,
    SliderInput,
)
from quino.domain.model import SpringEndpoint
from quino.domain.types import (
    JointEndpointKind,
    SpringEndpointKind,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def _marker_id(app: ApplicationService, body_id: str, marker_name: str) -> str:
    body = app.get_body(body_id)
    return next(m.id for m in body.markers if m.name == marker_name)


def build_active_suspension(app: ApplicationService) -> None:
    app.new_project("Active Suspension Validation Rig")

    # ------------------------------------------------------------------
    # 1. Parameters (so analyses reference named knobs)
    # ------------------------------------------------------------------
    arm_len_id = app.create_parameter(
        "ArmLength", "300 mm", "mm",
        description="Lower control arm length, hinge to ball-joint.",
    )
    chassis_mount_x = app.create_parameter("ChassisMountX", "0 mm", "mm")
    chassis_mount_y = app.create_parameter("ChassisMountY", "0 mm", "mm")
    spring_rest_id = app.create_parameter(
        "SpringRest", "320 mm", "mm",
        description="Free length of the strut spring.",
    )
    road_amp = app.create_parameter(
        "RoadAmp", "1500 N", "N",
        description="Peak vertical force the road profile applies to the wheel.",
    )
    road_freq = app.create_parameter(
        "RoadFreq", "2.5 unitless", "unitless",
        description="Excitation frequency of the rolling-road profile, in Hz.",
    )
    quarter_car_weight = app.create_parameter(
        "QuarterCarLoad", "4000 N", "N",
        description="Static load representing the quarter-car weight on this corner.",
    )

    # ------------------------------------------------------------------
    # 2. Sketch (paramétrico)
    # ------------------------------------------------------------------
    p_chassis = app.create_sketch_point("0 mm", "0 mm", name="ChassisHinge")
    p_strut_top = app.create_sketch_point("ArmLength", "320 mm", name="StrutTop")
    p_ball = app.create_sketch_point("ArmLength", "0 mm", name="BallJoint")
    p_hub = app.create_sketch_point("ArmLength", "0 mm", name="WheelHub")

    app.create_sketch_line_segment(p_chassis, p_ball, name="LowerArm")
    app.create_sketch_line_segment(p_strut_top, p_hub, name="Strut")

    app.create_sketch_constraint("fix", [p_chassis], name="FixChassis")
    app.create_sketch_constraint("fix", [p_strut_top], name="FixStrutTop")
    app.create_sketch_constraint(
        "horizontal", [p_chassis, p_ball], name="HArm",
    )
    app.create_sketch_constraint(
        "distance", [p_chassis, p_ball], value="ArmLength", name="LenArm",
    )
    app.create_sketch_constraint(
        "vertical", [p_strut_top, p_hub], name="VStrut",
    )

    # ------------------------------------------------------------------
    # 3. Mechanism bodies
    # ------------------------------------------------------------------
    chassis_mount_id, chassis_mount_marker = app.create_ground_anchor(
        "ChassisMount", "ChassisMountX", "ChassisMountY",
    )
    strut_top_anchor_id, strut_top_marker = app.create_ground_anchor(
        "StrutTopMount", "ArmLength", "320 mm",
    )

    lower_arm = app.create_bar(
        "LowerArm",
        MarkerInput("ChassisMountX", "ChassisMountY", "Hinge"),
        MarkerInput("ArmLength", "0 mm", "BallJoint"),
    )
    app.update_property(
        lower_arm, "mass",
        PropertyValueInput(kind="expression", value="3 kg"),
    )

    hub = app.create_body(
        "WheelHub",
        [
            MarkerInput("ArmLength", "0 mm", "Center"),
            MarkerInput("ArmLength", "320 mm", "StrutAttach"),
            MarkerInput("ArmLength", "-50 mm", "ContactPatch"),
        ],
        body_type="body",
    )
    app.update_property(
        hub, "mass",
        PropertyValueInput(kind="expression", value="40 kg"),
    )

    strut_slider = app.create_slider(
        "StrutGuide",
        SliderInput("ArmLength", "320 mm", "270 deg", "-60 mm", "60 mm"),
    )

    # ------------------------------------------------------------------
    # 4. Joints
    # ------------------------------------------------------------------
    app.create_joint(
        "Pivot_Chassis",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=chassis_mount_id,
            marker_id=chassis_mount_marker,
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=lower_arm,
            marker_id=_marker_id(app, lower_arm, "Hinge"),
        ),
    )
    app.create_joint(
        "BallJoint",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=lower_arm,
            marker_id=_marker_id(app, lower_arm, "BallJoint"),
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=hub,
            marker_id=_marker_id(app, hub, "Center"),
        ),
    )
    app.connect_marker_to_slider(
        _marker_id(app, hub, "StrutAttach"),
        strut_slider,
        name="StrutSlide",
    )

    # ------------------------------------------------------------------
    # 5. Spring + damper
    # ------------------------------------------------------------------
    spring_id = app.create_spring(
        "StrutSpring",
        "linear_spring",
        SpringEndpoint(
            kind=SpringEndpointKind.MARKER,
            body_id=strut_top_anchor_id,
            marker_id=strut_top_marker,
        ),
        SpringEndpoint(
            kind=SpringEndpointKind.MARKER,
            body_id=hub,
            marker_id=_marker_id(app, hub, "StrutAttach"),
        ),
    )
    app.update_spring_property(
        spring_id, "rest_value",
        PropertyValueInput(kind="expression", value="SpringRest"),
    )
    app.update_spring_property(
        spring_id, "stiffness",
        PropertyValueInput(kind="expression", value="35000"),
    )
    app.update_spring_property(
        spring_id, "damping",
        PropertyValueInput(kind="expression", value="1500"),
    )

    # ------------------------------------------------------------------
    # 6. Road excitation + static car load
    # ------------------------------------------------------------------
    road_load = app.create_load(
        "RoadProfile",
        _marker_id(app, hub, "ContactPatch"),
        "0 N",
        "RoadAmp * sin(360 deg * RoadFreq * t / 1 s)",
    )
    static_load = app.create_load(
        "QuarterCarLoad",
        _marker_id(app, hub, "StrutAttach"),
        "0 N",
        "-QuarterCarLoad",
    )

    # ------------------------------------------------------------------
    # 7. Sensors
    # ------------------------------------------------------------------
    hub_pos_sensor = app.create_sensor(
        "HubVerticalPos",
        "point",
        [_marker_id(app, hub, "Center")],
    )
    spring_length_sensor = app.create_sensor(
        "SpringLength",
        "distance",
        [strut_top_marker, _marker_id(app, hub, "StrutAttach")],
    )
    arm_angle_sensor = app.create_sensor(
        "ArmAngle",
        "angle_horizontal",
        [
            _marker_id(app, lower_arm, "Hinge"),
            _marker_id(app, lower_arm, "BallJoint"),
        ],
    )
    ride_comfort_sensor = app.create_sensor(
        "RideAccelerometer",
        "point",
        [_marker_id(app, hub, "Center")],
    )
    contact_sensor = app.create_sensor(
        "ContactPatchPos",
        "point",
        [_marker_id(app, hub, "ContactPatch")],
    )

    # ------------------------------------------------------------------
    # 8. Gravity
    # ------------------------------------------------------------------
    app.add_gravity()

    # ------------------------------------------------------------------
    # 9. Block diagram (control loop, gain=0 → passive baseline)
    # ------------------------------------------------------------------
    actuator_load = app.create_load(
        "ActuatorForce",
        _marker_id(app, hub, "StrutAttach"),
        "0 N",
        "0 N",
    )
    sensor_block = app.add_block(
        block_type="ModelSensor",
        name="HubPosBlock",
        position=(-380.0, -120.0),
        parameters={"sensor_id": hub_pos_sensor, "channel": "y"},
    )
    gain_block = app.add_block(
        block_type="Gain",
        name="ErrorGain",
        position=(-200.0, -120.0),
        parameters={"k": 0.0},
    )
    pid_block = app.add_block(
        block_type="PID",
        name="SuspensionPID",
        position=(-20.0, -120.0),
        parameters={
            "kp": 0.0, "ki": 0.0, "kd": 0.0,
            "lower": -2000.0, "upper": 2000.0,
            "anti_windup": True,
        },
    )
    actuator_block = app.add_block(
        block_type="LoadCommand",
        name="ActuatorCmd",
        position=(180.0, -120.0),
        parameters={"load_id": actuator_load, "component": "fy"},
    )
    app.add_connection(
        src_instance=sensor_block, src_port="out",
        dst_instance=gain_block, dst_port="in",
    )
    app.add_connection(
        src_instance=gain_block, src_port="out",
        dst_instance=pid_block, dst_port="error",
    )
    app.add_connection(
        src_instance=pid_block, src_port="out",
        dst_instance=actuator_block, dst_port="in",
    )

    # ------------------------------------------------------------------
    # 10. Workspace: root case + poses + analyses
    # ------------------------------------------------------------------
    ws = app._workspace
    case = ws.cases[ws.root_case_ids[0]]

    static_pose_base = app.workspace.create_pose(
        "Static load", case_id=case.id,
    )
    app.workspace.create_analysis(
        "Smooth road @ 2.5 Hz",
        analysis_type="dynamic",
        case_id=case.id,
        workspace_pose_id=static_pose_base.id,
    )
    app.workspace.create_analysis(
        "Smooth road under load",
        analysis_type="dynamic",
        case_id=case.id,
        workspace_pose_id=static_pose_base.id,
    )

    app.save_workspace(str(EXAMPLES_DIR / "Active_Suspension_Validation.quino.json"))


def main() -> None:
    app = ApplicationService()
    build_active_suspension(app)
    print("Wrote", EXAMPLES_DIR / "Active_Suspension_Validation.quino.json")


if __name__ == "__main__":
    main()
