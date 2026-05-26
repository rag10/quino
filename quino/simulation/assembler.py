from __future__ import annotations

from dataclasses import dataclass, field
import math

from quino.domain.model import Body, Driver, GravityLoad, Joint, Load, Marker, Project, Slider, Spring
from quino.domain.types import Dimension, MarkerType, SpringEndpointKind, SpringType
from quino.services.expressions import ExpressionService
from quino.simulation.sensor_expressions import sensor_expression_variables


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
    fx_expression: str
    fy_expression: str


@dataclass(slots=True)
class AssembledSpringEndpoint:
    kind: str
    body_id: str | None
    marker_id: str | None
    # For body: local position of marker relative to CoM (mm, body frame)
    # For ground: world-space anchor position (mm)
    anchor_x: float
    anchor_y: float
    global_x: float  # reference global position (mm) — for canvas rendering
    global_y: float


@dataclass(slots=True)
class AssembledSpring:
    spring_id: str
    name: str
    spring_type: str
    endpoint_a: AssembledSpringEndpoint
    endpoint_b: AssembledSpringEndpoint
    stiffness: float  # N/mm (linear) or N·mm/rad (rotational)
    damping: float    # N·s/mm (linear) or N·mm·s/rad (rotational)
    rest_value: float  # mm (linear) or rad (rotational)
    law_expression: str | None  # for actuators
    law_unit: str | None
    law_dimension: str | None


@dataclass(slots=True)
class AssembledMechanism:
    bodies: dict[str, AssembledBody]
    sliders: dict[str, AssembledSlider]
    joints: list[Joint]
    drivers: list[AssembledDriver]
    loads: list[AssembledLoad]
    springs: list[AssembledSpring]
    gravity: GravityLoad | None
    warnings: list[str] = field(default_factory=list)


class MechanismAssembler:
    def __init__(self, expression_service: ExpressionService) -> None:
        self.expression_service = expression_service

    def assemble(self, project: Project) -> AssembledMechanism:
        bodies = {body.id: self._assemble_body(project, body) for body in project.model.bodies}
        sliders = {slider.id: self._assemble_slider(project, slider) for slider in project.model.sliders}
        drivers = [self._assemble_driver(driver) for driver in project.model.drivers]
        loads = [self._assemble_load(project, load, bodies, sliders) for load in project.model.loads]
        springs = [self._assemble_spring(project, spring, bodies) for spring in project.model.springs]
        return AssembledMechanism(
            bodies=bodies,
            sliders=sliders,
            joints=list(project.model.joints),
            drivers=drivers,
            loads=loads,
            springs=springs,
            gravity=project.model.gravity,
            warnings=[],
        )

    def _assemble_spring(self, project: Project, spring: Spring, bodies: dict) -> AssembledSpring:
        def _ep(ep) -> AssembledSpringEndpoint:
            if ep.kind is SpringEndpointKind.GROUND:
                gx = self.expression_service.evaluate_property(ep.ground_x, project.parameters).value if ep.ground_x else 0.0
                gy = self.expression_service.evaluate_property(ep.ground_y, project.parameters).value if ep.ground_y else 0.0
                return AssembledSpringEndpoint(kind="ground", body_id=None, marker_id=None, anchor_x=gx, anchor_y=gy, global_x=gx, global_y=gy)
            body = bodies[ep.body_id]
            m = body.markers[ep.marker_id]
            return AssembledSpringEndpoint(kind="marker", body_id=ep.body_id, marker_id=ep.marker_id, anchor_x=m.local_x - body.com_local_x, anchor_y=m.local_y - body.com_local_y, global_x=m.global_x, global_y=m.global_y)

        is_rotational = spring.spring_type in (SpringType.ROTATIONAL_SPRING, SpringType.ROTATIONAL_ACTUATOR)
        stiffness = float(spring.metadata.values.get("stiffness", 0.0))
        damping = float(spring.metadata.values.get("damping", 0.0))
        if spring.rest_value is not None:
            rest_unit = "rad" if is_rotational else "mm"
            rest_val = self.expression_service.unit_service.convert(
                self.expression_service.evaluate_expression(spring.rest_value.expression, project.parameters),
                rest_unit,
            )
        else:
            rest_val = 0.0
        law_expression = spring.law.expression if spring.law else None
        law_unit = spring.law.unit if spring.law else None
        law_dimension = spring.law.expected_dimension.value if spring.law else None
        return AssembledSpring(
            spring_id=spring.id,
            name=spring.name,
            spring_type=spring.spring_type.value,
            endpoint_a=_ep(spring.endpoint_a),
            endpoint_b=_ep(spring.endpoint_b),
            stiffness=stiffness,
            damping=damping,
            rest_value=rest_val,
            law_expression=law_expression,
            law_unit=law_unit,
            law_dimension=law_dimension,
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
        # Derive CoM from the body's anchor and project it into the body's
        # assembled local frame (the COM marker is no longer the source of truth).
        from quino.services.com_geometry import com_local_position
        com_world_x, com_world_y = com_local_position(project, body)
        com_lx = cos_a * (com_world_x - origin_x) + sin_a * (com_world_y - origin_y)
        com_ly = -sin_a * (com_world_x - origin_x) + cos_a * (com_world_y - origin_y)
        mass = self._eval_optional(project, body.mass, default=0.0)
        if mass is None:
            mass = 0.0
        warnings: list[str] = []
        if body.mass is None:
            warnings.append(f"Body {body.name}: undefined mass, defaulting to 0.0 kg (massless / kinematic) for Exudyn assembly")
        return AssembledBody(
            body_id=body.id,
            name=body.name,
            body_type=body.type.value,
            origin_x=origin_x,
            origin_y=origin_y,
            angle=angle,
            mass=mass,
            com_local_x=com_lx,
            com_local_y=com_ly,
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

    def _assemble_load(
        self,
        project: Project,
        load: Load,
        bodies: dict[str, AssembledBody],
        sliders: dict[str, AssembledSlider],
    ) -> AssembledLoad:
        assembled = AssembledMechanism(
            bodies=bodies,
            sliders=sliders,
            joints=list(project.model.joints),
            drivers=[],
            loads=[],
            springs=[],
            gravity=project.model.gravity,
        )
        frame: dict[str, float] = {}
        for body_id, body in bodies.items():
            frame[f"{body_id}.x"] = body.origin_x
            frame[f"{body_id}.y"] = body.origin_y
            frame[f"{body_id}.angle"] = body.angle
        variables = {"t": self.expression_service.unit_service.quantity(0.0, "s")}
        variables.update(
            sensor_expression_variables(
                project,
                assembled,
                frame,
                self.expression_service.unit_service,
            )
        )
        fx = self.expression_service.evaluate_property(load.fx, project.parameters, variables=variables).value
        fy = self.expression_service.evaluate_property(load.fy, project.parameters, variables=variables).value
        return AssembledLoad(
            load_id=load.id,
            name=load.name,
            target_marker_id=load.target_marker_id,
            fx=fx,
            fy=fy,
            fx_expression=load.fx.expression,
            fy_expression=load.fy.expression,
        )
