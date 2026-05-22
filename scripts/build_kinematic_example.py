"""Build a kinematic-sweep example: a planar double pendulum.

Run from the repo root:

    python scripts/build_kinematic_example.py

What this exercises (Phase 3 plan):

- A two-bar double pendulum hinged from a ground anchor.
- A kinematic analysis with two `SweepDef` entries:
    * `angle_horizontal` on bar A (shoulder angle, w.r.t. ground).
    * `angle_between_segments` for bar B vs bar A (relative elbow angle).
- The kinematic runner is invoked programmatically to assert the sweep
  converges. The result artefact ends up under `<project_dir>/artifacts/`
  the same way as in the GUI.

Saved to examples/Double_Pendulum_Kinematic_Sweep.quino.json.
"""

from __future__ import annotations

from pathlib import Path

from quino.analysis.kinematic_runner import KinematicAnalysisRunner
from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput
from quino.domain.types import JointEndpointKind
from quino.domain.workspace import SweepDef

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
EXAMPLE_PATH = EXAMPLES_DIR / "Double_Pendulum_Kinematic_Sweep.quino.json"


def _marker_id(app: ApplicationService, body_id: str, name: str) -> str:
    body = app.get_body(body_id)
    return next(m.id for m in body.markers if m.name == name)


def build_double_pendulum_kinematic(app: ApplicationService) -> None:
    app.new_project("Double Pendulum Kinematic Sweep")

    # Ground anchor at the origin (pendulum suspension point).
    ground_id, ground_marker = app.create_ground_anchor("Anchor", "0 mm", "0 mm")

    # Bar A: from the anchor down to (200 mm, -200 mm).
    bar_a = app.create_bar(
        "BarA",
        MarkerInput("0 mm", "0 mm", "Hinge"),
        MarkerInput("200 mm", "-200 mm", "Tip"),
    )
    # Bar B: from the tip of bar A out to (400 mm, -400 mm).
    bar_b = app.create_bar(
        "BarB",
        MarkerInput("200 mm", "-200 mm", "Hinge"),
        MarkerInput("400 mm", "-400 mm", "Tip"),
    )

    app.create_joint(
        "ShoulderPivot",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=ground_id,
            marker_id=ground_marker,
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=bar_a,
            marker_id=_marker_id(app, bar_a, "Hinge"),
        ),
    )
    app.create_joint(
        "ElbowPivot",
        "revolute",
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=bar_a,
            marker_id=_marker_id(app, bar_a, "Tip"),
        ),
        JointEndpointInput(
            JointEndpointKind.MARKER,
            body_id=bar_b,
            marker_id=_marker_id(app, bar_b, "Hinge"),
        ),
    )

    app.add_gravity()

    # Workspace: baseline + pose + kinematic analysis with two sweeps.
    ws = app.project.workspace
    baseline = ws.baselines[0]
    app.workspace.rename_baseline(baseline.id, "Reference")
    pose = app.workspace.create_pose(
        "Pendulum reference pose", baseline_id=baseline.id,
    )
    analysis = app.workspace.create_analysis(
        "Sweep shoulder + elbow",
        analysis_type="kinematic",
        baseline_id=baseline.id,
        workspace_pose_id=pose.id,
    )

    bar_a_hinge = _marker_id(app, bar_a, "Hinge")
    bar_a_tip = _marker_id(app, bar_a, "Tip")
    bar_b_hinge = _marker_id(app, bar_b, "Hinge")
    bar_b_tip = _marker_id(app, bar_b, "Tip")

    # Shoulder angle: bar A vs horizontal ground.
    analysis.config.sweeps.append(
        SweepDef(
            id="sw_shoulder",
            variable_kind="angle_horizontal",
            target_ids=[bar_a_hinge, bar_a_tip],
            mode="linear",
            start=-1.2,  # rad, ≈ -69 deg
            end=-0.2,    # rad, ≈ -11 deg
            steps=5,
            label="shoulder",
        )
    )
    # Elbow angle: bar B relative to bar A.
    analysis.config.sweeps.append(
        SweepDef(
            id="sw_elbow",
            variable_kind="angle_between_segments",
            target_ids=[bar_a_hinge, bar_a_tip, bar_b_hinge, bar_b_tip],
            mode="linear",
            start=-0.6,
            end=0.6,
            steps=5,
            label="elbow",
        )
    )

    app.set_working_context(baseline_id=baseline.id)

    # Save first, then run the kinematic analysis (the runner writes its
    # artefact under <project_dir>/artifacts/).
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    app.save_project(str(EXAMPLE_PATH))

    runner = KinematicAnalysisRunner()
    errors = runner.validate(app.project, analysis)
    if errors:
        raise RuntimeError(f"Kinematic validation failed: {errors}")
    result = runner.run(app.project, analysis)
    if result is None:
        raise RuntimeError("Kinematic runner returned no result")


def main() -> None:
    app = ApplicationService()
    build_double_pendulum_kinematic(app)
    print("Wrote", EXAMPLE_PATH)


if __name__ == "__main__":
    main()
