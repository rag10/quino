from __future__ import annotations

from pathlib import Path

from quino.application.examples import (
    build_double_pendulum_example,
    build_four_bar_example,
    build_slider_crank_example,
)
from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput
from quino.domain.model import ScalarProperty, SpringEndpoint
from quino.domain.types import Dimension, DriverType, JointEndpointKind, SpringEndpointKind, SpringType


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def _marker(app: ApplicationService, body_id: str, marker_name: str) -> str:
    body = app.get_body(body_id)
    if body is None:
        raise ValueError(f"Unknown body {body_id!r}")
    return next(marker.id for marker in body.markers if marker.name == marker_name)


def _enrich(app: ApplicationService, *, child_name: str = "Lightweight variant") -> None:
    ws = app._workspace
    if ws is None:
        return
    root_id = ws.root_case_ids[0]
    root = ws.cases[root_id]
    app.workspace.create_pose("Setup pose", case_id=root_id)
    app.workspace.create_analysis("Root static check", analysis_type="static", case_id=root_id)

    child = app.workspace.create_case(child_name, parent_case_id=root_id)
    ws.selected_case_id = child.id
    app.workspace.create_pose("Variant pose", case_id=child.id)
    app.workspace.create_analysis("Variant static check", analysis_type="static", case_id=child.id)
    if child.model.bodies:
        app.update_property(
            child.model.bodies[0].id,
            "mass",
            PropertyValueInput("expression", "0.75 kg"),
        )
    ws.selected_case_id = root_id


def _save(app: ApplicationService, filename: str) -> None:
    app.save_workspace(str(EXAMPLES_DIR / filename))


def build_four_bar() -> None:
    app = ApplicationService()
    build_four_bar_example(app)
    _enrich(app)
    _save(app, "Four_Bar_Linkage.quino.json")


def build_double_pendulum() -> None:
    app = ApplicationService()
    build_double_pendulum_example(app)
    _enrich(app)
    _save(app, "Double_Pendulum.quino.json")


def build_scotch_yoke() -> None:
    app = ApplicationService()
    result = build_slider_crank_example(app)
    app._workspace.name = "Scotch Yoke"
    root = app._workspace.cases[app._workspace.root_case_ids[0]]
    root.name = "Root case"
    app.workspace.create_analysis("Kinematic sweep", analysis_type="kinematic", case_id=root.id)
    _enrich(app, child_name="Offset slot variant")
    _save(app, "Scotch_Yoke.quino.json")


def build_spring_oscillator() -> None:
    app = ApplicationService()
    app.new_workspace("Spring Oscillator")
    mass = app.create_bar(
        "Mass",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("50 mm", "0 mm", "B"),
    )
    marker_a = _marker(app, mass, "A")
    app.create_spring(
        "Linear spring",
        SpringType.LINEAR_SPRING.value,
        SpringEndpoint(
            SpringEndpointKind.GROUND,
            ground_x=ScalarProperty("-80 mm", "mm", Dimension.LENGTH),
            ground_y=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
        ),
        SpringEndpoint(SpringEndpointKind.MARKER, body_id=mass, marker_id=marker_a),
    )
    _enrich(app, child_name="Soft spring variant")
    _save(app, "Spring_Oscillator.quino.json")


def build_torsional_pendulum() -> None:
    app = ApplicationService()
    app.new_workspace("Torsional Spring Pendulum")
    arm = app.create_bar(
        "Arm",
        MarkerInput("0 mm", "0 mm", "Pivot"),
        MarkerInput("120 mm", "0 mm", "Tip"),
    )
    pivot = app.connect_marker_to_ground(_marker(app, arm, "Pivot"), name="Pivot")
    app.create_driver("Release angle", DriverType.ROTATION.value, pivot, "10 deg", "deg")
    app.workspace.create_analysis("Equilibrium", analysis_type="equilibrium")
    _enrich(app, child_name="Long arm variant")
    _save(app, "Torsional_Spring_Pendulum.quino.json")


def build_controlled_mass_pid() -> None:
    app = ApplicationService()
    app.new_workspace("Controlled Mass PID")
    source = app.blocks.add_block(block_type="Step", name="Reference", position=(20.0, 40.0))
    pid = app.blocks.add_block(
        block_type="PID",
        name="PID",
        position=(180.0, 40.0),
        parameters={"kp": 12.0, "ki": 2.0, "kd": 0.5},
    )
    actuator = app.blocks.add_block(block_type="LoadCommand", name="Actuator", position=(340.0, 40.0))
    app.blocks.add_connection(src_instance=source, src_port="out", dst_instance=pid, dst_port="error")
    app.blocks.add_connection(src_instance=pid, src_port="out", dst_instance=actuator, dst_port="in")
    _enrich(app, child_name="Retuned PID")
    _save(app, "Controlled_Mass_PID.quino.json")


def main() -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    build_four_bar()
    build_double_pendulum()
    build_scotch_yoke()
    build_spring_oscillator()
    build_torsional_pendulum()
    build_controlled_mass_pid()


if __name__ == "__main__":
    main()
