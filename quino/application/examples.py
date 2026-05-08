from __future__ import annotations

from dataclasses import dataclass

from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput, SliderInput
from quino.domain.types import DriverType, JointEndpointKind


@dataclass(slots=True)
class ExampleBuildResult:
    project_name: str
    body_ids: list[str]
    joint_ids: list[str]
    slider_ids: list[str]
    driver_ids: list[str]


def build_four_bar_example(app: ApplicationService) -> ExampleBuildResult:
    app.new_project("Four Bar")
    crank = app.create_bar(
        "Crank",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("30 mm", "10 mm", "B"),
    )
    coupler = app.create_bar(
        "Coupler",
        MarkerInput("30 mm", "10 mm", "B"),
        MarkerInput("90 mm", "70 mm", "C"),
    )
    rocker = app.create_bar(
        "Rocker",
        MarkerInput("120 mm", "0 mm", "D"),
        MarkerInput("90 mm", "70 mm", "C"),
    )

    def mid(body_id: str, marker_name: str) -> str:
        return next(marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name)

    ground_a = app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    joint_b = app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=coupler, marker_id=mid(coupler, "B")),
    )
    joint_c = app.create_joint(
        "Joint_C",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=coupler, marker_id=mid(coupler, "C")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rocker, marker_id=mid(rocker, "C")),
    )
    ground_d = app.connect_marker_to_ground(mid(rocker, "D"), name="Ground_D")
    driver = app.create_driver(
        "CrankDrive",
        DriverType.ROTATION.value,
        ground_a,
        "20 deg * t / 1 s",
        "deg",
    )

    return ExampleBuildResult(
        project_name=app.project.name,
        body_ids=[crank, coupler, rocker],
        joint_ids=[ground_a, joint_b, joint_c, ground_d],
        slider_ids=[],
        driver_ids=[driver],
    )


def build_slider_crank_example(app: ApplicationService) -> ExampleBuildResult:
    app.new_project("Slider Crank")
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
    slider = app.create_slider(
        "Guide",
        SliderInput("150 mm", "0 mm", "0 deg", "-20 mm", "20 mm"),
    )

    def mid(body_id: str, marker_name: str) -> str:
        return next(marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name)

    ground_a = app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    joint_b = app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rod, marker_id=mid(rod, "B")),
    )
    slider_p = app.connect_marker_to_slider(mid(rod, "P"), slider, name="Slider_P")
    driver = app.create_driver(
        "CrankDrive",
        DriverType.ROTATION.value,
        ground_a,
        "20 deg * t / 1 s",
        "deg",
    )

    return ExampleBuildResult(
        project_name=app.project.name,
        body_ids=[crank, rod],
        joint_ids=[ground_a, joint_b, slider_p],
        slider_ids=[slider],
        driver_ids=[driver],
    )
