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
    # Knobs the user can tweak from the inspector (or override per-case).
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

    # The wheel hub is a small rigid body (sprung mass). Its markers must
    # coincide at rest with their joint counterparts:
    #   Center      → coincident with LowerArm.BallJoint  (ball joint)
    #   StrutAttach → coincident with StrutTopMount       (strut top pivot)
    #   ContactPatch is below the hub (where the road bump applies).
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

    # Strut: prismatic slider along the vertical strut axis, anchored at
    # the strut top mount, pointing down.
    strut_slider = app.create_slider(
        "StrutGuide",
        SliderInput("ArmLength", "320 mm", "270 deg", "-60 mm", "60 mm"),
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
    # Strut prismatic: hub StrutAttach slides along the strut guide axis.
    # The strut top mount only acts as a geometric reference for the spring
    # (no separate revolute joint — the slider already constrains the hub
    # to the strut axis, so adding a pivot would over-constrain the model).
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
    # 6. Road excitation + static car load
    # ------------------------------------------------------------------
    # The "RoadProfile" load models a continuously undulating road: a sine
    # with adjustable amplitude (RoadAmp, in N) and frequency (RoadFreq, in
    # Hz). Per-case overrides will turn it into a pothole pulse, a resonant
    # excitation, or a high-frequency washboard.
    road_load = app.create_load(
        "RoadProfile",
        _marker_id(app, hub, "ContactPatch"),
        "0 N",
        "RoadAmp * sin(360 deg * RoadFreq * t / 1 s)",
    )
    # Static quarter-car weight transmitted from the chassis to the hub. We
    # represent it as a constant downward force on StrutAttach so the spring
    # sits at a realistic ride height before the road wakes up.
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
    # Aceleración vertical del hub para evaluar el confort del pasajero
    # (a/ay del sensor 'point' es la aceleración vertical en m/s²).
    ride_comfort_sensor = app.create_sensor(
        "RideAccelerometer",
        "point",
        [_marker_id(app, hub, "Center")],
    )
    # Posición del contact patch — útil para ver el "desplazamiento de la
    # rueda contra la carretera" en los análisis de pothole / washboard.
    contact_sensor = app.create_sensor(
        "ContactPatchPos",
        "point",
        [_marker_id(app, hub, "ContactPatch")],
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
    # PID block's input port is named "error" (it expects an error signal,
    # i.e. the negated hub displacement here).
    app.add_connection(
        src_instance=gain_block, src_port="out",
        dst_instance=pid_block, dst_port="error",
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

    # --- Baseline-scope analyses + a couple of static poses ------------
    static_pose_base = app.workspace.create_pose(
        "Static load", baseline_id=baseline.id,
    )
    app.workspace.create_analysis(
        "Smooth road @ 2.5 Hz",
        analysis_type="dynamic",
        baseline_id=baseline.id,
        workspace_pose_id=static_pose_base.id,
    )
    app.workspace.create_analysis(
        "Smooth road under load",
        analysis_type="dynamic",
        baseline_id=baseline.id,
        workspace_pose_id=static_pose_base.id,
    )

    # --- Case 1: Stiffer spring ("rally setup") ------------------------
    stiff_case = app.workspace.create_case(
        "Rally setup (stiffer spring)", baseline_id=baseline.id,
    )
    app.workspace.update_case_invariants(
        stiff_case.id,
        {
            f"springs_meta/{spring_id}/stiffness": "55000",
            f"springs_meta/{spring_id}/damping": "1900",
            # Rally tracks have higher-frequency, lower-amplitude content.
            f"parameters/{road_amp}": "1200 N",
            f"parameters/{road_freq}": "4.0",
        },
    )
    stiff_pose = app.workspace.create_pose(
        "Static load - stiff", case_id=stiff_case.id,
    )
    app.workspace.create_analysis(
        "Rally washboard run",
        analysis_type="dynamic",
        case_id=stiff_case.id,
        workspace_pose_id=stiff_pose.id,
    )

    # --- Case 2: Pothole strike ---------------------------------------
    pothole_case = app.workspace.create_case(
        "Pothole strike", baseline_id=baseline.id,
    )
    # A pothole = wheel briefly loses ground (downward impulse) then slams
    # the far edge (upward impulse). We approximate it with a 6 Hz wavelet
    # at much higher amplitude. The 1.2 m/s road profile peak gives ≈ 4 kN.
    app.workspace.update_case_invariants(
        pothole_case.id,
        {
            f"parameters/{road_amp}": "4000 N",
            f"parameters/{road_freq}": "6.0",
        },
    )
    pothole_pose = app.workspace.create_pose(
        "Static load - pothole", case_id=pothole_case.id,
    )
    app.workspace.create_analysis(
        "Single pothole impact",
        analysis_type="dynamic",
        case_id=pothole_case.id,
        workspace_pose_id=pothole_pose.id,
    )

    # --- Case 3: Resonance test ---------------------------------------
    # Sprung-mass natural frequency f0 ≈ (1/2π)·sqrt(k/m).
    # For k=35 kN/m and m=40 kg → f0 ≈ 4.7 Hz. Driving slightly below to
    # show resonance build-up.
    resonance_case = app.workspace.create_case(
        "Resonance sweep", baseline_id=baseline.id,
    )
    app.workspace.update_case_invariants(
        resonance_case.id,
        {
            f"parameters/{road_amp}": "800 N",
            f"parameters/{road_freq}": "4.7",
            # Low damping so the resonance peak builds up dramatically.
            f"springs_meta/{spring_id}/damping": "300",
        },
    )
    resonance_pose = app.workspace.create_pose(
        "Static load - resonance", case_id=resonance_case.id,
    )
    app.workspace.create_analysis(
        "Drive at natural frequency",
        analysis_type="dynamic",
        case_id=resonance_case.id,
        workspace_pose_id=resonance_pose.id,
    )

    # --- Case 4: Active suspension (PID enabled, softer base) ----------
    active_case = app.workspace.create_case(
        "Active suspension", baseline_id=baseline.id,
    )
    # Softer mechanical base + nonzero control gains. The PID is asked to
    # keep the hub centred against an aggressive road input.
    app.workspace.update_case_invariants(
        active_case.id,
        {
            f"springs_meta/{spring_id}/stiffness": "20000",
            f"springs_meta/{spring_id}/damping": "800",
            f"model/control_graph/instances/{gain_block}/parameters/k": "-1.0",
            f"model/control_graph/instances/{pid_block}/parameters/kp": "1800.0",
            f"model/control_graph/instances/{pid_block}/parameters/ki": "60.0",
            f"model/control_graph/instances/{pid_block}/parameters/kd": "120.0",
            # Mix of bump + sustained excitation so the PID has work to do.
            f"parameters/{road_amp}": "2200 N",
            f"parameters/{road_freq}": "3.0",
        },
    )
    active_pose = app.workspace.create_pose(
        "Settled (active)", case_id=active_case.id,
    )
    app.workspace.create_analysis(
        "Comfort cruise (PID on)",
        analysis_type="dynamic",
        case_id=active_case.id,
        workspace_pose_id=active_pose.id,
    )

    # --- Subcase under "Active suspension": Heavy passenger ------------
    heavy_case = app.workspace.create_case(
        "Heavy passenger", parent_case_id=active_case.id,
    )
    # Two adults in the back seat: bump the quarter-car load and the
    # sprung mass. PID tuning is inherited from the parent case.
    app.workspace.update_case_invariants(
        heavy_case.id,
        {
            f"bodies/{hub}/mass": "70 kg",
            f"parameters/{quarter_car_weight}": "6500 N",
        },
    )
    heavy_pose = app.workspace.create_pose(
        "Static load - heavy", case_id=heavy_case.id,
    )
    app.workspace.create_analysis(
        "Heavy comfort cruise",
        analysis_type="dynamic",
        case_id=heavy_case.id,
        workspace_pose_id=heavy_pose.id,
    )
    app.workspace.create_analysis(
        "Heavy + pothole",
        analysis_type="dynamic",
        case_id=heavy_case.id,
        workspace_pose_id=heavy_pose.id,
    )

    # --- Subcase under "Active suspension": Failure mode --------------
    # What happens if the actuator fails (gain drops to zero) while the
    # car is on rough road? Useful for fault-tolerance studies.
    fail_case = app.workspace.create_case(
        "Actuator failure", parent_case_id=active_case.id,
    )
    app.workspace.update_case_invariants(
        fail_case.id,
        {
            # Override only the PID/gain: actuator does nothing but the
            # softer-spring base from the parent is inherited.
            f"model/control_graph/instances/{gain_block}/parameters/k": "0.0",
            f"model/control_graph/instances/{pid_block}/parameters/kp": "0.0",
            f"model/control_graph/instances/{pid_block}/parameters/ki": "0.0",
            f"model/control_graph/instances/{pid_block}/parameters/kd": "0.0",
        },
    )
    fail_pose = app.workspace.create_pose(
        "Static load - failure", case_id=fail_case.id,
    )
    app.workspace.create_analysis(
        "Failure on rough road",
        analysis_type="dynamic",
        case_id=fail_case.id,
        workspace_pose_id=fail_pose.id,
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
