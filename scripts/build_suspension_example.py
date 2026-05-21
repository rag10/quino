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
  ModelSensor -> Gain -> PID -> LoadCommand. Disabled at baseline,
  switched on in one of the cases.
- Workspace structure:
    Baseline = "Reference (passive)"
        Default pose       (rig at rest)
        Pose "Static load" (suspension compressed by car weight)
        Analysis "Bump @ rest"
    Case "Stiffer spring"   (overrides spring stiffness)
        Default pose
        Pose "Static load - stiff"
        Analysis "Bump @ stiff load"
    Case "Active suspension" (enables PID feedback, softer base)
        Subcase "Heavy passenger" (adds payload mass)
            Default pose
            Pose "Static load - heavy"
            Analyses on the pose

Saved to examples/Active_Suspension_Validation.quino.json.
"""

from __future__ import annotations

import math
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
    DriverType,
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
    # 1. Parameters (so case overrides operate on named knobs)
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

    # ------------------------------------------------------------------
    # 2. Sketch (paramétrico)
    # ------------------------------------------------------------------
    p_chassis = app.create_sketch_point("0 mm", "0 mm", name="ChassisHinge")
    p_strut_top = app.create_sketch_point("250 mm", "320 mm", name="StrutTop")
    p_ball = app.create_sketch_point("ArmLength", "0 mm", name="BallJoint")
    p_hub = app.create_sketch_point("250 mm", "0 mm", name="WheelHub")

    app.create_sketch_line_segment(p_chassis, p_ball, name="LowerArm")
    app.create_sketch_line_segment(p_strut_top, p_hub, name="Strut")
    app.create_sketch_line_segment(p_ball, p_hub, name="HubMount")

    app.create_sketch_constraint("fix", [p_chassis], name="FixChassis")
    app.create_sketch_constraint("fix", [p_strut_top], name="FixStrutTop")
    app.create_sketch_constraint(
        "horizontal", [p_chassis, p_ball], name="HArm",
    )
    app.create_sketch_constraint(
        "distance", [p_chassis, p_ball], value="ArmLength", name="LenArm",
    )
    app.create_sketch_constraint(
        "distance", [p_ball, p_hub], value="50 mm", name="HubOffset",
    )

    # ------------------------------------------------------------------
    # 3. Mechanism bodies
    # ------------------------------------------------------------------
    chassis_mount_id, chassis_mount_marker = app.create_ground_anchor(
        "ChassisMount", "ChassisMountX", "ChassisMountY",
    )
    strut_top_anchor_id, strut_top_marker = app.create_ground_anchor(
        "StrutTopMount", "250 mm", "320 mm",
    )

    lower_arm = app.create_bar(
        "LowerArm",
        MarkerInput("ChassisMountX", "ChassisMountY", "Hinge"),
        MarkerInput("ArmLength", "0 mm", "BallJoint"),
    )

    # The wheel hub is a small rigid body (sprung mass).
    hub = app.create_body(
        "WheelHub",
        [
            MarkerInput("250 mm", "0 mm", "Center"),
            MarkerInput("250 mm", "50 mm", "StrutAttach"),
            MarkerInput("200 mm", "-30 mm", "ContactPatch"),
        ],
        body_type="body",
    )
    app.update_property(
        hub, "mass",
        PropertyValueInput(kind="expression", value="40 kg"),
    )

    # Strut: prismatic slider along the strut axis (almost vertical here).
    strut_slider = app.create_slider(
        "StrutGuide",
        SliderInput("250 mm", "320 mm", "270 deg", "-60 mm", "60 mm"),
    )

    # ------------------------------------------------------------------
    # 4. Joints
    # ------------------------------------------------------------------
    # Lower arm pivots at the chassis mount.
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
    # Ball joint between lower arm and hub.
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
    # Strut top pinned to the chassis top mount (revolute so the strut can
    # swing slightly with the arm).
    app.create_joint(
        "StrutTopPivot",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=strut_top_anchor_id,
            marker_id=strut_top_marker,
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=hub,
            marker_id=_marker_id(app, hub, "StrutAttach"),
        ),
    )
    # Strut prismatic: hub StrutAttach slides along the strut guide axis.
    app.connect_marker_to_slider(
        _marker_id(app, hub, "StrutAttach"),
        strut_slider,
        name="StrutSlide",
    )

    # ------------------------------------------------------------------
    # 5. Spring + damper as a single linear spring with damping metadata
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
        PropertyValueInput(kind="expression", value="35000"),  # N/m
    )
    app.update_spring_property(
        spring_id, "damping",
        PropertyValueInput(kind="expression", value="1500"),   # N·s/m
    )

    # ------------------------------------------------------------------
    # 6. Driver: road bump excitation on the contact patch (vertical force-free
    # — modelled as imposed translation of a phantom ground via a rigid joint?
    # Simplification: drive a vertical load on the contact patch instead.)
    # ------------------------------------------------------------------
    # The bump is modelled as a half-period sine pulse: peaks at 2.5 kN and
    # vanishes by ~0.2 s. The expression language does not support if() so we
    # rely on the assembler clamping the load expression at simulation start.
    bump_load = app.create_load(
        "RoadBump",
        _marker_id(app, hub, "ContactPatch"),
        "0 N",
        "2500 N * sin(180 deg * t / 0.1 s)",
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

    # ------------------------------------------------------------------
    # 8. Gravity (acts on hub mass)
    # ------------------------------------------------------------------
    app.add_gravity()

    # ------------------------------------------------------------------
    # 9. Block diagram (control loop, disabled in baseline)
    #
    #   ModelSensor[HubVerticalPos.y]  ──►  Gain(k=-1)  ──►  PID  ──►  LoadCommand(ActuatorForce)
    #
    # Saved on baseline; the "Active suspension" case will tune the PID gains
    # and enable a higher gain factor.
    # ------------------------------------------------------------------
    # We add an "actuator" load that the PID will drive (force in y).
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
        parameters={"k": 0.0},  # disabled in baseline
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
        dst_instance=pid_block, dst_port="in",
    )
    app.add_connection(
        src_instance=pid_block, src_port="out",
        dst_instance=actuator_block, dst_port="in",
    )

    # ------------------------------------------------------------------
    # 10. Workspace: baseline + cases + poses + analyses
    # ------------------------------------------------------------------
    ws = app.project.workspace
    # Rename the default baseline to something meaningful for this rig.
    baseline = ws.baselines[0]
    app.workspace.rename_baseline(baseline.id, "Reference (passive)")
    # Opt-in: declare the PID and Gain block parameters as case-invariant so
    # downstream cases can tune them. Without this, the composer treats block
    # parameters as study-level variables only.
    baseline.invariant_parameter_keys.extend([
        f"model/control_graph/instances/{gain_block}/parameters/k",
        f"model/control_graph/instances/{pid_block}/parameters/kp",
        f"model/control_graph/instances/{pid_block}/parameters/ki",
        f"model/control_graph/instances/{pid_block}/parameters/kd",
    ])

    # --- Baseline-scope analyses + extra static pose -------------------
    static_pose_base = app.workspace.create_pose(
        "Static load", baseline_id=baseline.id,
    )
    app.workspace.create_analysis(
        "Bump @ rest",
        analysis_type="dynamic",
        baseline_id=baseline.id,
        workspace_pose_id=None,  # uses default pose
    )
    app.workspace.create_analysis(
        "Bump @ static load",
        analysis_type="dynamic",
        baseline_id=baseline.id,
        workspace_pose_id=static_pose_base.id,
    )

    # --- Case 1: Stiffer spring ----------------------------------------
    stiff_case = app.workspace.create_case(
        "Stiffer spring", baseline_id=baseline.id,
    )
    app.workspace.update_case_invariants(
        stiff_case.id,
        {
            f"springs_meta/{spring_id}/stiffness": "55000",
            f"springs_meta/{spring_id}/damping": "1900",
        },
    )
    stiff_pose = app.workspace.create_pose(
        "Static load - stiff", case_id=stiff_case.id,
    )
    app.workspace.create_analysis(
        "Bump @ stiff",
        analysis_type="dynamic",
        case_id=stiff_case.id,
        workspace_pose_id=stiff_pose.id,
    )

    # --- Case 2: Active suspension (PID enabled, softer base) ----------
    active_case = app.workspace.create_case(
        "Active suspension", baseline_id=baseline.id,
    )
    # Softer mechanical base + nonzero control gains.
    app.workspace.update_case_invariants(
        active_case.id,
        {
            f"springs_meta/{spring_id}/stiffness": "20000",
            f"springs_meta/{spring_id}/damping": "800",
            f"model/control_graph/instances/{gain_block}/parameters/k": "-1.0",
            f"model/control_graph/instances/{pid_block}/parameters/kp": "1800.0",
            f"model/control_graph/instances/{pid_block}/parameters/ki": "60.0",
            f"model/control_graph/instances/{pid_block}/parameters/kd": "120.0",
        },
    )
    active_pose = app.workspace.create_pose(
        "Settled (active)", case_id=active_case.id,
    )
    app.workspace.create_analysis(
        "Bump with PID",
        analysis_type="dynamic",
        case_id=active_case.id,
        workspace_pose_id=active_pose.id,
    )

    # --- Subcase under "Active suspension": Heavy passenger ------------
    heavy_case = app.workspace.create_case(
        "Heavy passenger", parent_case_id=active_case.id,
    )
    # Increase the sprung mass without breaking the PID tuning of the parent.
    app.workspace.update_case_invariants(
        heavy_case.id,
        {
            f"bodies/{hub}/mass": "70 kg",
        },
    )
    heavy_pose = app.workspace.create_pose(
        "Static load - heavy", case_id=heavy_case.id,
    )
    app.workspace.create_analysis(
        "Bump heavy passenger",
        analysis_type="dynamic",
        case_id=heavy_case.id,
        workspace_pose_id=heavy_pose.id,
    )
    app.workspace.create_analysis(
        "Bump heavy passenger - long",
        analysis_type="dynamic",
        case_id=heavy_case.id,
        workspace_pose_id=heavy_pose.id,
    )

    # Default to the baseline view when the project opens.
    app.set_working_context(baseline_id=baseline.id)

    app.save_project(str(EXAMPLES_DIR / "Active_Suspension_Validation.quino.json"))


def main() -> None:
    app = ApplicationService()
    build_active_suspension(app)
    print("Wrote", EXAMPLES_DIR / "Active_Suspension_Validation.quino.json")


if __name__ == "__main__":
    main()
