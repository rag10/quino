"""Build three extra example projects (with sketch + model + simulation setup)
and serialize them as .quino.json files into examples/.

Run from the repo root:

    python scripts/build_extra_examples.py
"""

from __future__ import annotations

import math
from pathlib import Path

from quino.application.service import ApplicationService
from quino.domain.inputs import (
    JointEndpointInput,
    MarkerInput,
    SliderInput,
)
from quino.domain.types import DriverType, JointEndpointKind


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def _marker_id(app: ApplicationService, body_id: str, marker_name: str) -> str:
    return next(
        m.id for m in app._find_body(body_id).markers if m.name == marker_name
    )


# ---------------------------------------------------------------------------
# 1. Slider-crank con sketch base
# ---------------------------------------------------------------------------

def build_slider_crank_with_sketch(app: ApplicationService) -> None:
    app.new_project("Slider Crank with Sketch")

    # ---- Sketch: define geometry skeleton at t=0 ----
    p_a = app.create_sketch_point("0 mm", "0 mm", name="A_sk")
    p_b = app.create_sketch_point("50 mm", "0 mm", name="B_sk")
    p_p = app.create_sketch_point("150 mm", "0 mm", name="P_sk")

    crank_seg = app.create_sketch_line_segment(p_a, p_b, name="CrankSeg")
    rod_seg = app.create_sketch_line_segment(p_b, p_p, name="RodSeg")
    guide_axis = app.create_sketch_infinite_line(p_a, p_p, name="GuideAxis")

    # Constraints: anchor A, keep guide horizontal, fix lengths
    app.create_sketch_constraint("fix", [p_a], name="FixA")
    app.create_sketch_constraint("horizontal", [p_a, p_p], name="HGuide")
    app.create_sketch_constraint("distance", [p_a, p_b], value="50 mm", name="CrankLen")
    app.create_sketch_constraint("distance", [p_b, p_p], value="100 mm", name="RodLen")

    # ---- Mechanism ----
    crank = app.create_bar(
        "Crank",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("50 mm", "0 mm", "B"),
    )
    rod = app.create_bar(
        "Rod",
        MarkerInput("50 mm", "0 mm", "B"),
        MarkerInput("150 mm", "0 mm", "P"),
    )
    guide = app.create_slider(
        "Guide",
        SliderInput("150 mm", "0 mm", "0 deg", "-60 mm", "60 mm"),
    )

    ground_a = app.connect_marker_to_ground(
        _marker_id(app, crank, "A"), name="Ground_A"
    )
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER, body_id=crank, marker_id=_marker_id(app, crank, "B")
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER, body_id=rod, marker_id=_marker_id(app, rod, "B")
        ),
    )
    app.connect_marker_to_slider(
        _marker_id(app, rod, "P"), guide, name="Slider_P"
    )

    app.create_driver(
        "CrankDrive",
        DriverType.ROTATION.value,
        ground_a,
        "360 deg * t / 1 s",
        "deg",
    )

    # Sensor on the piston so the user sees the trajectory
    app.create_sensor(
        "PistonSensor",
        "point",
        [_marker_id(app, rod, "P")],
    )

    app.save_project(str(EXAMPLES_DIR / "Slider_Crank_With_Sketch.quino.json"))


# ---------------------------------------------------------------------------
# 2. Umbrella mechanism (one rib + stretcher + slider on shaft)
# ---------------------------------------------------------------------------
#
# Geometry (mm), shaft is the vertical axis x=0:
#   Top hub T  : (0, 200)   fixed (top of shaft)
#   Runner   R : (0, hR)    slides along shaft, hR ∈ [60, 180]
#   Rib tip  K : end of rib, hinged at T
#   Stretcher S: connects R to a midpoint M of the rib
#
# At rest (closed):
#   Rib direction = (sin θ, -cos θ) with θ small (≈10°), length = 180 mm
#   Stretcher length kept constant by the slider position.
#

def build_umbrella_mechanism(app: ApplicationService) -> None:
    app.new_project("Umbrella Mechanism")

    rib_length = 180.0
    stretcher_length = 90.0
    rib_mid_ratio = 0.5
    theta_rest = math.radians(35.0)  # opened ~35° from shaft

    top_x, top_y = 0.0, 200.0
    rib_dir = (math.sin(theta_rest), -math.cos(theta_rest))
    rib_tip = (top_x + rib_length * rib_dir[0], top_y + rib_length * rib_dir[1])
    rib_mid = (
        top_x + rib_length * rib_mid_ratio * rib_dir[0],
        top_y + rib_length * rib_mid_ratio * rib_dir[1],
    )
    runner_y = rib_mid[1] - math.sqrt(
        max(stretcher_length**2 - rib_mid[0] ** 2, 0.0)
    )

    # ---- Sketch ----
    p_top = app.create_sketch_point(f"{top_x:.3f} mm", f"{top_y:.3f} mm", name="Top")
    p_runner = app.create_sketch_point("0 mm", f"{runner_y:.3f} mm", name="Runner")
    p_tip = app.create_sketch_point(
        f"{rib_tip[0]:.3f} mm", f"{rib_tip[1]:.3f} mm", name="RibTip"
    )
    p_mid = app.create_sketch_point(
        f"{rib_mid[0]:.3f} mm", f"{rib_mid[1]:.3f} mm", name="RibMid"
    )
    p_base = app.create_sketch_point("0 mm", "0 mm", name="ShaftBase")

    app.create_sketch_line_segment(p_top, p_tip, name="RibLine")
    app.create_sketch_line_segment(p_runner, p_mid, name="StretcherLine")
    app.create_sketch_infinite_line(p_base, p_top, name="ShaftAxis")

    # Constraints: shaft is vertical, hub anchored, runner stays on shaft,
    # rib has fixed length, stretcher has fixed length, mid is midpoint of rib.
    app.create_sketch_constraint("fix", [p_top], name="FixHub")
    app.create_sketch_constraint("fix", [p_base], name="FixBase")
    app.create_sketch_constraint("vertical", [p_base, p_top], name="ShaftV")
    app.create_sketch_constraint("vertical", [p_base, p_runner], name="RunnerOnShaft")
    app.create_sketch_constraint(
        "midpoint", [p_mid, p_top, p_tip], name="RibMidIsHalf"
    )
    app.create_sketch_constraint(
        "distance", [p_top, p_tip], value=f"{rib_length:.1f} mm", name="RibLen"
    )
    app.create_sketch_constraint(
        "distance",
        [p_runner, p_mid],
        value=f"{stretcher_length:.1f} mm",
        name="StretcherLen",
    )

    # ---- Mechanism ----
    rib = app.create_bar(
        "Rib",
        MarkerInput(f"{top_x:.3f} mm", f"{top_y:.3f} mm", "T"),
        MarkerInput(f"{rib_tip[0]:.3f} mm", f"{rib_tip[1]:.3f} mm", "K"),
    )
    # Add a midpoint marker on the rib so the stretcher attaches halfway
    app.add_marker_to_body_at(
        rib,
        f"{rib_mid[0]:.3f} mm",
        f"{rib_mid[1]:.3f} mm",
        name="M",
    )
    stretcher = app.create_bar(
        "Stretcher",
        MarkerInput("0 mm", f"{runner_y:.3f} mm", "R"),
        MarkerInput(f"{rib_mid[0]:.3f} mm", f"{rib_mid[1]:.3f} mm", "M"),
    )
    shaft = app.create_slider(
        "Shaft",
        SliderInput("0 mm", "100 mm", "90 deg", "-100 mm", "80 mm"),
    )

    ground_top = app.connect_marker_to_ground(
        _marker_id(app, rib, "T"), name="Ground_Top"
    )
    runner_joint = app.connect_marker_to_slider(
        _marker_id(app, stretcher, "R"), shaft, name="Runner_Slide"
    )
    app.create_joint(
        "Stretcher_Mid",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=stretcher,
            marker_id=_marker_id(app, stretcher, "M"),
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=rib,
            marker_id=_marker_id(app, rib, "M"),
        ),
    )

    # Drive the runner up and down so the umbrella opens and closes
    app.create_driver(
        "RunnerDrive",
        DriverType.TRANSLATION.value,
        runner_joint,
        "60 mm * sin(360 deg * t / 4 s)",
        "mm",
    )

    app.create_sensor(
        "RibTipSensor", "point", [_marker_id(app, rib, "K")]
    )
    app.create_sensor(
        "RibAngle",
        "angle_vertical",
        [_marker_id(app, rib, "T"), _marker_id(app, rib, "K")],
    )

    app.save_project(str(EXAMPLES_DIR / "Umbrella_Mechanism.quino.json"))


# ---------------------------------------------------------------------------
# 3. Pantograph (parallelogram amplifier)
# ---------------------------------------------------------------------------
#
# Classic pantograph: input pen at P traces a path; output Q on a parallel
# linkage traces the same path scaled by a factor k.  We use the simple
# 4-bar pantograph with one ground pivot at O.
#
#   O ---- A
#   |      |
#   B ---- P
#   |
#   Q
#
# Lengths chosen so OA = AP = BP = OB = 60 mm (rhombus), and Q lies on the
# extension of OB at distance OB * 2 → magnification factor 2.

def build_pantograph(app: ApplicationService) -> None:
    app.new_project("Pantograph")

    L = 60.0  # arm length

    o = (0.0, 0.0)
    a = (L, 0.0)
    b = (0.0, -L)
    p = (L, -L)
    q = (-L, -2 * L)  # extension of OB beyond B by another L → magnifies by 2

    # ---- Sketch (only Points + segments, no constraints to keep solver light) ----
    p_o = app.create_sketch_point(f"{o[0]:.3f} mm", f"{o[1]:.3f} mm", name="O")
    p_a = app.create_sketch_point(f"{a[0]:.3f} mm", f"{a[1]:.3f} mm", name="A")
    p_b = app.create_sketch_point(f"{b[0]:.3f} mm", f"{b[1]:.3f} mm", name="B")
    p_p = app.create_sketch_point(f"{p[0]:.3f} mm", f"{p[1]:.3f} mm", name="P")
    p_q = app.create_sketch_point(f"{q[0]:.3f} mm", f"{q[1]:.3f} mm", name="Q")

    seg_oa = app.create_sketch_line_segment(p_o, p_a, name="OA")
    seg_ap = app.create_sketch_line_segment(p_a, p_p, name="AP")
    seg_ob = app.create_sketch_line_segment(p_o, p_b, name="OB")
    seg_bp = app.create_sketch_line_segment(p_b, p_p, name="BP")
    seg_bq = app.create_sketch_line_segment(p_b, p_q, name="BQ")

    app.create_sketch_constraint("fix", [p_o], name="FixO")
    app.create_sketch_constraint("distance", [p_o, p_a], value=f"{L:.1f} mm", name="LenOA")
    app.create_sketch_constraint("distance", [p_a, p_p], value=f"{L:.1f} mm", name="LenAP")
    app.create_sketch_constraint("distance", [p_o, p_b], value=f"{L:.1f} mm", name="LenOB")
    app.create_sketch_constraint("distance", [p_b, p_p], value=f"{L:.1f} mm", name="LenBP")
    # Q collinear with O and B, on the far side of B → use collinear + distance
    app.create_sketch_constraint("collinear", [p_o, p_b, p_q], name="QonOB")
    app.create_sketch_constraint("distance", [p_b, p_q], value=f"{L:.1f} mm", name="LenBQ")
    app.create_sketch_constraint("parallel", [p_o, p_a, p_b, p_p], name="OAparBP")
    app.create_sketch_constraint("parallel", [p_o, p_b, p_a, p_p], name="OBparAP")

    # ---- Mechanism ----
    arm_oa = app.create_bar(
        "OA",
        MarkerInput(f"{o[0]:.3f} mm", f"{o[1]:.3f} mm", "O"),
        MarkerInput(f"{a[0]:.3f} mm", f"{a[1]:.3f} mm", "A"),
    )
    arm_ap = app.create_bar(
        "AP",
        MarkerInput(f"{a[0]:.3f} mm", f"{a[1]:.3f} mm", "A"),
        MarkerInput(f"{p[0]:.3f} mm", f"{p[1]:.3f} mm", "P"),
    )
    arm_ob = app.create_bar(
        "OBQ",
        MarkerInput(f"{o[0]:.3f} mm", f"{o[1]:.3f} mm", "O"),
        MarkerInput(f"{b[0]:.3f} mm", f"{b[1]:.3f} mm", "B"),
    )
    # Add Q on the same body as OB so Q is rigidly tied to it (extension)
    app.add_marker_to_body_at(arm_ob, f"{q[0]:.3f} mm", f"{q[1]:.3f} mm", name="Q")
    arm_bp = app.create_bar(
        "BP",
        MarkerInput(f"{b[0]:.3f} mm", f"{b[1]:.3f} mm", "B"),
        MarkerInput(f"{p[0]:.3f} mm", f"{p[1]:.3f} mm", "P"),
    )

    ground_o_oa = app.connect_marker_to_ground(
        _marker_id(app, arm_oa, "O"), name="Ground_O"
    )
    # Pivot O of arm_ob is also grounded but we already have one ground at O
    # for arm_oa; instead pin OB to OA at O via a revolute joint
    app.create_joint(
        "Joint_O_OAOB",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=arm_oa,
            marker_id=_marker_id(app, arm_oa, "O"),
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=arm_ob,
            marker_id=_marker_id(app, arm_ob, "O"),
        ),
    )
    app.create_joint(
        "Joint_A",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=arm_oa,
            marker_id=_marker_id(app, arm_oa, "A"),
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=arm_ap,
            marker_id=_marker_id(app, arm_ap, "A"),
        ),
    )
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=arm_ob,
            marker_id=_marker_id(app, arm_ob, "B"),
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=arm_bp,
            marker_id=_marker_id(app, arm_bp, "B"),
        ),
    )
    app.create_joint(
        "Joint_P",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=arm_ap,
            marker_id=_marker_id(app, arm_ap, "P"),
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=arm_bp,
            marker_id=_marker_id(app, arm_bp, "P"),
        ),
    )

    # Drive arm OA so the input pen (P) traces a circle and Q traces a scaled one
    app.create_driver(
        "InputDrive",
        DriverType.ROTATION.value,
        ground_o_oa,
        "45 deg * sin(360 deg * t / 2 s)",
        "deg",
    )

    app.create_sensor(
        "PenSensor", "point", [_marker_id(app, arm_ap, "P")]
    )
    app.create_sensor(
        "OutputSensor", "point", [_marker_id(app, arm_ob, "Q")]
    )

    app.save_project(str(EXAMPLES_DIR / "Pantograph.quino.json"))


def main() -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    builders = (
        build_slider_crank_with_sketch,
        build_umbrella_mechanism,
        build_pantograph,
    )
    for builder in builders:
        app = ApplicationService()
        builder(app)
        print(f"Built: {app.project.name}")


if __name__ == "__main__":
    main()
