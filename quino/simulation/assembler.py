from __future__ import annotations

from dataclasses import dataclass, field
import math

from quino.domain.model import Body, Driver, GravityLoad, Joint, Load, Marker, Project, Slider
from quino.domain.types import MarkerType
from quino.services.expressions import ExpressionService


@dataclass(slots=True)
class AssembledMarker:
    marker_id: str
    name: str
    marker_type: str
    local_x: float
    local_y: float
    global_x: float
    global_y: float
    visible: bool


@dataclass(slots=True)
class AssembledBody:
    body_id: str
    name: str
    body_type: str
    origin_x: float
    origin_y: float
    angle: float
    mass: float
    inertia: float
    com_local_x: float
    com_local_y: float
    markers: dict[str, AssembledMarker] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AssembledSlider:
    slider_id: str
    name: str
    origin_x: float
    origin_y: float
    angle: float
    axis_x: float
    axis_y: float
    normal_x: float
    normal_y: float
    travel_min: float | None
    travel_max: float | None


@dataclass(slots=True)
class AssembledDriver:
    driver_id: str
    name: str
    driver_type: str
    target_joint_id: str
    law_expression: str
    unit: str
    expected_dimension: str


@dataclass(slots=True)
class AssembledLoad:
    load_id: str
    name: str
    target_marker_id: str
    fx: float
    fy: float


@dataclass(slots=True)
class AssembledMechanism:
    bodies: dict[str, AssembledBody]
    sliders: dict[str, AssembledSlider]
    joints: list[Joint]
    drivers: list[AssembledDriver]
    loads: list[AssembledLoad]
    gravity: GravityLoad
    warnings: list[str] = field(default_factory=list)


class MechanismAssembler:
    def __init__(self, expression_service: ExpressionService) -> None:
        self.expression_service = expression_service

    def assemble(self, project: Project) -> AssembledMechanism:
        bodies = {body.id: self._assemble_body(project, body) for body in project.model.bodies}
        sliders = {slider.id: self._assemble_slider(project, slider) for slider in project.model.sliders}
        drivers = [self._assemble_driver(driver) for driver in project.model.drivers]
        loads = [self._assemble_load(project, load) for load in project.model.loads]
        return AssembledMechanism(
            bodies=bodies,
            sliders=sliders,
            joints=list(project.model.joints),
            drivers=drivers,
            loads=loads,
            gravity=project.model.gravity,
            warnings=[],
        )

    def _assemble_body(self, project: Project, body: Body) -> AssembledBody:
        structural_markers = body.structural_markers()
        global_markers = [self._eval_marker(project, marker) for marker in body.markers]
        marker_map = {marker.marker_id: marker for marker in global_markers}
        structural_global = [marker_map[marker.id] for marker in structural_markers]
        origin_x = structural_global[0].global_x
        origin_y = structural_global[0].global_y
        angle = 0.0
        if len(structural_global) >= 2:
            dx = structural_global[1].global_x - structural_global[0].global_x
            dy = structural_global[1].global_y - structural_global[0].global_y
            angle = math.atan2(dy, dx)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        transformed_markers: dict[str, AssembledMarker] = {}
        for marker in global_markers:
            local_x = cos_a * (marker.global_x - origin_x) + sin_a * (marker.global_y - origin_y)
            local_y = -sin_a * (marker.global_x - origin_x) + cos_a * (marker.global_y - origin_y)
            transformed_markers[marker.marker_id] = AssembledMarker(
                marker_id=marker.marker_id,
                name=marker.name,
                marker_type=marker.marker_type,
                local_x=local_x,
                local_y=local_y,
                global_x=marker.global_x,
                global_y=marker.global_y,
                visible=marker.visible,
            )
        com_marker = next(marker for marker in transformed_markers.values() if marker.marker_type == MarkerType.COM.value)
        mass = self._eval_optional(project, body.mass, default=0.0)
        if mass is None:
            mass = 0.0
        if mass == 0.0:
            inertia_default = 0.0
        elif len(structural_global) >= 2:
            dx = structural_global[1].global_x - structural_global[0].global_x
            dy = structural_global[1].global_y - structural_global[0].global_y
            L_sq_mm2 = dx * dx + dy * dy
            inertia_default = max(mass * L_sq_mm2 / 12.0, 1e-6)
        else:
            inertia_default = max(mass * 1.0, 1e-6)
        inertia = self._eval_optional(project, body.inertia, default=inertia_default)
        if inertia is None:
            inertia = inertia_default
        warnings: list[str] = []
        if body.mass is None:
            warnings.append(f"Body {body.name}: undefined mass, defaulting to 0.0 kg (massless / kinematic) for Exudyn assembly")
        if body.inertia is None:
            warnings.append(
                f"Body {body.name}: undefined inertia, defaulting to {inertia:.6g} for Exudyn assembly"
            )
        return AssembledBody(
            body_id=body.id,
            name=body.name,
            body_type=body.type.value,
            origin_x=origin_x,
            origin_y=origin_y,
            angle=angle,
            mass=mass,
            inertia=inertia,
            com_local_x=com_marker.local_x,
            com_local_y=com_marker.local_y,
            markers=transformed_markers,
            warnings=warnings,
        )

    def _assemble_slider(self, project: Project, slider: Slider) -> AssembledSlider:
        origin_x = self.expression_service.evaluate_property(slider.origin_x, project.parameters).value
        origin_y = self.expression_service.evaluate_property(slider.origin_y, project.parameters).value
        angle = self.expression_service.unit_service.convert(
            self.expression_service.evaluate_expression(slider.angle.expression, project.parameters),
            "rad",
        )
        return AssembledSlider(
            slider_id=slider.id,
            name=slider.name,
            origin_x=origin_x,
            origin_y=origin_y,
            angle=angle,
            axis_x=math.cos(angle),
            axis_y=math.sin(angle),
            normal_x=-math.sin(angle),
            normal_y=math.cos(angle),
            travel_min=self._eval_optional(project, slider.travel_min, default=None),
            travel_max=self._eval_optional(project, slider.travel_max, default=None),
        )

    def _eval_marker(self, project: Project, marker: Marker) -> AssembledMarker:
        x = self.expression_service.evaluate_property(marker.x, project.parameters).value
        y = self.expression_service.evaluate_property(marker.y, project.parameters).value
        return AssembledMarker(
            marker_id=marker.id,
            name=marker.name,
            marker_type=marker.type.value,
            local_x=0.0,
            local_y=0.0,
            global_x=x,
            global_y=y,
            visible=marker.visible,
        )

    def _eval_optional(self, project: Project, prop, default: float | None) -> float | None:
        if prop is None:
            return default
        return self.expression_service.evaluate_property(prop, project.parameters).value

    def _assemble_driver(self, driver: Driver) -> AssembledDriver:
        return AssembledDriver(
            driver_id=driver.id,
            name=driver.name,
            driver_type=driver.type.value,
            target_joint_id=driver.target_joint_id,
            law_expression=driver.law.expression,
            unit=driver.law.unit,
            expected_dimension=driver.law.expected_dimension.value,
        )

    def _assemble_load(self, project: Project, load: Load) -> AssembledLoad:
        fx = self.expression_service.evaluate_property(load.fx, project.parameters).value
        fy = self.expression_service.evaluate_property(load.fy, project.parameters).value
        return AssembledLoad(
            load_id=load.id,
            name=load.name,
            target_marker_id=load.target_marker_id,
            fx=fx,
            fy=fy,
        )
