from __future__ import annotations

import copy
import math
from pathlib import Path

from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput, SliderInput
from quino.domain.model import (
    Body,
    Driver,
    Joint,
    JointEndpoint,
    Marker,
    Metadata,
    Model,
    Parameter,
    Project,
    ScalarProperty,
    SimulationResult,
    Slider,
    Style,
    ValidationMessage,
    ValidationReport,
    ViewState,
)
from quino.domain.types import BodyType, Dimension, DriverType, JointEndpointKind, JointType, MarkerType
from quino.serialization.json_io import JsonMapper
from quino.services.expressions import ExpressionService
from quino.services.ids import IdService
from quino.services.units import UnitService
from quino.services.validation import ValidationService
from quino.simulation.runner import SimulationRunner
from quino.solver_adapters.exudyn_adapter import ExudynAdapter


class ApplicationService:
    schema_version = "0.1.0"

    def __init__(self) -> None:
        self.id_service = IdService()
        self.unit_service = UnitService()
        self.expression_service = ExpressionService(self.unit_service)
        self.validation_service = ValidationService()
        self.json_mapper = JsonMapper()
        self.project: Project | None = None
        self._undo_stack: list[Project] = []
        self._redo_stack: list[Project] = []
        self.simulation_runner = SimulationRunner(ExudynAdapter(self.expression_service))

    def new_project(self, name: str) -> Project:
        self.project = Project(
            id=self.id_service.new("proj"),
            name=name,
            schema_version=self.schema_version,
            model=Model(),
            parameters=[],
            view_state=ViewState(),
            metadata=Metadata(),
        )
        self._undo_stack.clear()
        self._redo_stack.clear()
        return self.project

    def load_project(self, path: str) -> Project:
        self.project = self.json_mapper.load_file(path)
        self._sync_id_service()
        self._undo_stack.clear()
        self._redo_stack.clear()
        return self.project

    def save_project(self, path: str) -> None:
        project = self._require_project()
        self.json_mapper.save_file(project, path)

    def create_parameter(self, name: str, expression: str, unit: str, description: str = "") -> str:
        project = self._require_project()
        self.validation_service.ensure_unique_name(project.parameters, name)
        self._validate_parameter_definition(expression, unit)
        self._snapshot()
        parameter = Parameter(
            id=self.id_service.new("param"),
            name=name,
            expression=expression,
            unit=unit,
            description=description,
        )
        project.parameters.append(parameter)
        return parameter.id

    def update_parameter(
        self,
        parameter_id: str,
        *,
        expression: str | None = None,
        unit: str | None = None,
        description: str | None = None,
    ) -> None:
        project = self._require_project()
        parameter = self._find_parameter(parameter_id)
        new_expression = expression if expression is not None else parameter.expression
        new_unit = unit if unit is not None else parameter.unit
        new_description = description if description is not None else parameter.description
        self._validate_parameter_definition(new_expression, new_unit, parameter_id=parameter_id)
        self._snapshot()
        parameter.expression = new_expression
        parameter.unit = new_unit
        parameter.description = new_description

    def delete_parameter(self, parameter_id: str) -> None:
        project = self._require_project()
        self._snapshot()
        project.parameters = [parameter for parameter in project.parameters if parameter.id != parameter_id]

    def create_body(self, name: str, markers: list[MarkerInput], body_type: str = "body") -> str:
        project = self._require_project()
        if not markers:
            raise ValueError("A body requires at least one structural marker")
        self.validation_service.ensure_unique_name(project.model.bodies, name)
        body_id = self.id_service.new("body")
        marker_names: set[str] = set()
        structural_markers = [
            self._make_marker(body_id, marker_input, is_first=index == 0)
            for index, marker_input in enumerate(markers)
        ]
        for marker in structural_markers:
            if marker.name in marker_names:
                raise ValueError(f"Duplicate marker name in body creation: {marker.name}")
            marker_names.add(marker.name)
            self.expression_service.evaluate_property(marker.x, project.parameters)
            self.expression_service.evaluate_property(marker.y, project.parameters)
        self._snapshot()
        actual_type = BodyType(body_type)
        if len(structural_markers) == 1:
            actual_type = BodyType.POINT_MASS
        body = Body(
            id=body_id,
            name=name,
            type=actual_type,
            markers=structural_markers,
            edge_order=[marker.id for marker in structural_markers],
            closed_shape=actual_type is not BodyType.BAR,
            mass=None,
            inertia=None,
            style=Style(),
        )
        body.markers.append(self._make_com_marker(body))
        project.model.bodies.append(body)
        return body.id

    def create_bar(self, name: str, start: MarkerInput, end: MarkerInput) -> str:
        return self.create_body(name=name, markers=[start, end], body_type=BodyType.BAR.value)

    def add_marker_to_body(self, body_id: str, marker: MarkerInput) -> str:
        body = self._find_body(body_id)
        marker_name = marker.name or f"M{len(body.structural_markers()) + 1}"
        self.validation_service.ensure_unique_marker_name(body, marker_name)
        created = Marker(
            id=self.id_service.new("marker"),
            name=marker_name,
            type=marker.marker_type,
            x=self._scalar(marker.x, "mm", Dimension.LENGTH),
            y=self._scalar(marker.y, "mm", Dimension.LENGTH),
            visible=marker.visible,
        )
        self.expression_service.evaluate_property(created.x, self._require_project().parameters)
        self.expression_service.evaluate_property(created.y, self._require_project().parameters)
        self._snapshot()
        body.markers.insert(len(body.structural_markers()), created)
        body.edge_order.append(created.id)
        if body.type is BodyType.BAR:
            body.type = BodyType.BODY
            body.closed_shape = True
        elif body.type is BodyType.POINT_MASS and len(body.structural_markers()) > 1:
            body.type = BodyType.BODY
            body.closed_shape = True
        return created.id

    def add_marker_to_body_at(
        self, body_id: str, x_expression: str, y_expression: str, name: str | None = None
    ) -> str:
        marker_name = name or f"M{len(self._find_body(body_id).structural_markers()) + 1}"
        return self.add_marker_to_body(body_id, MarkerInput(x_expression, y_expression, marker_name))

    def create_slider(self, name: str, slider: SliderInput) -> str:
        project = self._require_project()
        self.validation_service.ensure_unique_name(project.model.sliders, name)
        slider_obj = Slider(
            id=self.id_service.new("slider"),
            name=name,
            origin_x=self._scalar(slider.origin_x, "mm", Dimension.LENGTH),
            origin_y=self._scalar(slider.origin_y, "mm", Dimension.LENGTH),
            angle=self._scalar(slider.angle, "deg", Dimension.ANGLE),
            travel_min=self._scalar(slider.travel_min, "mm", Dimension.LENGTH) if slider.travel_min is not None else None,
            travel_max=self._scalar(slider.travel_max, "mm", Dimension.LENGTH) if slider.travel_max is not None else None,
        )
        self.expression_service.evaluate_property(slider_obj.origin_x, project.parameters)
        self.expression_service.evaluate_property(slider_obj.origin_y, project.parameters)
        self.expression_service.evaluate_property(slider_obj.angle, project.parameters)
        if slider_obj.travel_min is not None:
            self.expression_service.evaluate_property(slider_obj.travel_min, project.parameters)
        if slider_obj.travel_max is not None:
            self.expression_service.evaluate_property(slider_obj.travel_max, project.parameters)
        self._snapshot()
        project.model.sliders.append(slider_obj)
        return slider_obj.id

    def create_slider_from_points(
        self,
        name: str,
        start_x: str,
        start_y: str,
        end_x: str,
        end_y: str,
        travel_min: str | None = None,
        travel_max: str | None = None,
    ) -> str:
        project = self._require_project()
        start_x_value = self.expression_service.evaluate_expression(start_x, project.parameters)
        start_y_value = self.expression_service.evaluate_expression(start_y, project.parameters)
        end_x_value = self.expression_service.evaluate_expression(end_x, project.parameters)
        end_y_value = self.expression_service.evaluate_expression(end_y, project.parameters)
        sx = self.unit_service.convert(start_x_value, "mm")
        sy = self.unit_service.convert(start_y_value, "mm")
        ex = self.unit_service.convert(end_x_value, "mm")
        ey = self.unit_service.convert(end_y_value, "mm")
        origin_x = f"{0.5 * (sx + ex):.3f} mm"
        origin_y = f"{0.5 * (sy + ey):.3f} mm"
        angle_quantity = self.unit_service.quantity(math.atan2(ey - sy, ex - sx), "rad")
        angle = f"{self.unit_service.convert(angle_quantity, 'deg'):.6f} deg"
        half_length = 0.5 * ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
        return self.create_slider(
            name,
            SliderInput(
                origin_x,
                origin_y,
                angle,
                travel_min if travel_min is not None else f"{-half_length:.3f} mm",
                travel_max if travel_max is not None else f"{half_length:.3f} mm",
            ),
        )

    def create_joint(
        self,
        name: str,
        joint_type: str,
        endpoint_a: JointEndpointInput,
        endpoint_b: JointEndpointInput,
    ) -> str:
        project = self._require_project()
        self.validation_service.ensure_unique_name(project.model.joints, name)
        self._validate_endpoint_input(endpoint_a)
        self._validate_endpoint_input(endpoint_b)
        joint = Joint(
            id=self.id_service.new("joint"),
            name=name,
            type=JointType(joint_type),
            endpoint_a=self._make_endpoint(endpoint_a),
            endpoint_b=self._make_endpoint(endpoint_b),
        )
        self._ensure_joint_not_duplicate(joint)
        self._snapshot()
        project.model.joints.append(joint)
        return joint.id

    def create_rigid_joint(
        self,
        name: str,
        endpoint_a: JointEndpointInput,
        endpoint_b: JointEndpointInput,
    ) -> str:
        return self.create_joint(name, JointType.RIGID.value, endpoint_a, endpoint_b)

    def create_driver(self, name: str, driver_type: str, target_joint_id: str, expression: str, unit: str) -> str:
        project = self._require_project()
        self.validation_service.ensure_unique_name(project.model.drivers, name)
        joint = self._find_joint(target_joint_id)
        dtype = DriverType(driver_type)
        if any(driver.target_joint_id == target_joint_id for driver in project.model.drivers):
            raise ValueError("Only one driver per joint is supported in V1")
        if dtype is DriverType.ROTATION and joint.type is not JointType.REVOLUTE:
            raise ValueError("Rotation drivers require a revolute joint")
        if dtype is DriverType.TRANSLATION and not self._joint_has_slider(joint):
            raise ValueError("Translation drivers require a slider joint")
        law = ScalarProperty(
            expression=expression,
            unit=unit,
            expected_dimension=Dimension.ANGLE if dtype is DriverType.ROTATION else Dimension.LENGTH,
        )
        self.expression_service.evaluate_property(
            law,
            project.parameters,
            variables={"t": self.unit_service.quantity(0.0, "s")},
        )
        self._snapshot()
        driver = Driver(
            id=self.id_service.new("driver"),
            name=name,
            type=dtype,
            target_joint_id=target_joint_id,
            law=law,
        )
        project.model.drivers.append(driver)
        return driver.id

    def set_joint_type(self, joint_id: str, joint_type: str) -> None:
        joint = self._find_joint(joint_id)
        new_type = JointType(joint_type)
        if joint.type is new_type:
            return
        if any(driver.target_joint_id == joint_id for driver in self._require_project().model.drivers):
            raise ValueError("Cannot change joint type while it has a driver attached")
        self._snapshot()
        joint.type = new_type

    def connect_marker_to_ground(
        self, marker_id: str, joint_type: str = "revolute", name: str | None = None
    ) -> str:
        body = self._find_body_by_marker(marker_id)
        return self.create_joint(
            name=name or f"Ground_{marker_id}",
            joint_type=joint_type,
            endpoint_a=JointEndpointInput(JointEndpointKind.MARKER, body_id=body.id, marker_id=marker_id),
            endpoint_b=JointEndpointInput(JointEndpointKind.GROUND),
        )

    def connect_marker_to_slider(
        self, marker_id: str, slider_id: str, joint_type: str = "revolute", name: str | None = None
    ) -> str:
        body = self._find_body_by_marker(marker_id)
        return self.create_joint(
            name=name or f"{marker_id}_{slider_id}",
            joint_type=joint_type,
            endpoint_a=JointEndpointInput(JointEndpointKind.MARKER, body_id=body.id, marker_id=marker_id),
            endpoint_b=JointEndpointInput(JointEndpointKind.SLIDER, slider_id=slider_id),
        )

    def rename_entity(self, entity_id: str, new_name: str) -> None:
        entity = self._find_entity(entity_id)
        self._validate_entity_name(entity, new_name)
        self._snapshot()
        self._rename_entity_no_snapshot(entity, new_name)

    def move_marker(self, marker_id: str, x_expression: str, y_expression: str) -> None:
        marker = self._find_entity(marker_id)
        if not isinstance(marker, Marker):
            raise ValueError("move_marker requires a marker entity")
        project = self._require_project()
        new_x = ScalarProperty(expression=x_expression, unit=marker.x.unit, expected_dimension=Dimension.LENGTH)
        new_y = ScalarProperty(expression=y_expression, unit=marker.y.unit, expected_dimension=Dimension.LENGTH)
        self.expression_service.evaluate_property(new_x, project.parameters)
        self.expression_service.evaluate_property(new_y, project.parameters)
        self._snapshot()
        marker.x = new_x
        marker.y = new_y

    def update_property(self, entity_id: str, property_path: str, value: PropertyValueInput) -> None:
        entity = self._find_entity(entity_id)
        if property_path == "name":
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Name updates require an expression/string value")
            self._validate_entity_name(entity, value.value)
            self._snapshot()
            self._rename_entity_no_snapshot(entity, value.value)
            return
        if property_path == "edge_order":
            if not isinstance(entity, Body):
                raise ValueError("edge_order only applies to Body")
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("edge_order updates require a comma-separated expression/string value")
            edge_order = self._validated_edge_order(entity, value.value)
            self._snapshot()
            entity.edge_order = edge_order
            return
        if property_path in {"visible", "closed_shape"}:
            if value.kind != "boolean" or not isinstance(value.value, bool):
                raise ValueError("Boolean property requires a boolean input")
            self._snapshot()
            setattr(entity, property_path, value.value)
            return
        if property_path in {"mass", "inertia", "travel_min", "travel_max"} and value.kind == "null":
            self._snapshot()
            setattr(entity, property_path, None)
            return
        if property_path.startswith("style."):
            if value.kind == "boolean":
                self._snapshot()
                setattr(entity.style, property_path.split(".", 1)[1], value.value)
                return
            if value.kind == "expression":
                self._snapshot()
                setattr(entity.style, property_path.split(".", 1)[1], value.value)
                return
            raise ValueError("Unsupported style update")
        if property_path == "law":
            if not isinstance(entity, Driver):
                raise ValueError("law only applies to Driver")
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Driver law requires an expression value")
            law = ScalarProperty(
                expression=value.value,
                unit=entity.law.unit,
                expected_dimension=entity.law.expected_dimension,
            )
            self.expression_service.evaluate_property(
                law,
                self._require_project().parameters,
                variables={"t": self.unit_service.quantity(0.0, "s")},
            )
            self._snapshot()
            entity.law = law
            return
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError("Scalar properties require an expression value")
        scalar = self._build_validated_scalar_property(entity, property_path, value.value)
        self._snapshot()
        self._assign_scalar_property(entity, property_path, scalar)

    def delete_entity(self, entity_id: str) -> None:
        project = self._require_project()
        if any(body.id == entity_id for body in project.model.bodies):
            self._snapshot()
            body = self._find_body(entity_id)
            marker_ids = {marker.id for marker in body.markers}
            removed_joint_ids = {
                joint.id
                for joint in project.model.joints
                if joint.endpoint_a.marker_id in marker_ids or joint.endpoint_b.marker_id in marker_ids
            }
            project.model.joints = [
                joint
                for joint in project.model.joints
                if joint.endpoint_a.marker_id not in marker_ids and joint.endpoint_b.marker_id not in marker_ids
            ]
            project.model.drivers = [
                driver for driver in project.model.drivers if driver.target_joint_id not in removed_joint_ids
            ]
            project.model.bodies = [item for item in project.model.bodies if item.id != entity_id]
            return
        if any(slider.id == entity_id for slider in project.model.sliders):
            self._snapshot()
            slider_joint_ids = {
                joint.id
                for joint in project.model.joints
                if joint.endpoint_a.slider_id == entity_id or joint.endpoint_b.slider_id == entity_id
            }
            project.model.joints = [
                joint
                for joint in project.model.joints
                if joint.endpoint_a.slider_id != entity_id and joint.endpoint_b.slider_id != entity_id
            ]
            project.model.drivers = [
                driver for driver in project.model.drivers if driver.target_joint_id not in slider_joint_ids
            ]
            project.model.sliders = [item for item in project.model.sliders if item.id != entity_id]
            return
        if any(joint.id == entity_id for joint in project.model.joints):
            self._snapshot()
            project.model.joints = [item for item in project.model.joints if item.id != entity_id]
            project.model.drivers = [driver for driver in project.model.drivers if driver.target_joint_id != entity_id]
            return
        if any(driver.id == entity_id for driver in project.model.drivers):
            self._snapshot()
            project.model.drivers = [item for item in project.model.drivers if item.id != entity_id]
            return
        body = self._find_body_by_marker(entity_id)
        if any(marker.id == entity_id and marker.type is MarkerType.COM for marker in body.markers):
            raise ValueError("CoM marker cannot be deleted")
        if len(body.structural_markers()) <= 1:
            raise ValueError("The last structural marker of a body cannot be deleted")
        self._snapshot()
        removed_joint_ids = {
            joint.id
            for joint in project.model.joints
            if joint.endpoint_a.marker_id == entity_id or joint.endpoint_b.marker_id == entity_id
        }
        body.markers = [marker for marker in body.markers if marker.id != entity_id]
        body.edge_order = [marker_id for marker_id in body.edge_order if marker_id != entity_id]
        project.model.joints = [
            joint
            for joint in project.model.joints
            if joint.endpoint_a.marker_id != entity_id and joint.endpoint_b.marker_id != entity_id
        ]
        project.model.drivers = [
            driver for driver in project.model.drivers if driver.target_joint_id not in removed_joint_ids
        ]
        if len(body.structural_markers()) == 1:
            body.type = BodyType.POINT_MASS
            body.closed_shape = False
        elif body.type is BodyType.BODY and len(body.structural_markers()) == 2:
            body.closed_shape = True

    def validate_model(self) -> ValidationReport:
        project = self._require_project()
        report = self.validation_service.validate_project(project)
        self._evaluate_all(project, report)
        return report

    def run_kinematic_simulation(self, duration: float = 1.0, steps: int = 100) -> SimulationResult:
        project = self._require_project()
        report = self.validate_model()
        result = self.simulation_runner.run(project, duration=duration, steps=steps)
        validation_messages = [message.message for message in report.messages]
        result.warnings = [*validation_messages, *result.warnings]
        result.messages = [*validation_messages, *result.messages]
        return result

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        if self.project is not None:
            self._redo_stack.append(copy.deepcopy(self.project))
        self.project = self._undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        if self.project is not None:
            self._undo_stack.append(copy.deepcopy(self.project))
        self.project = self._redo_stack.pop()
        return True

    def _require_project(self) -> Project:
        if self.project is None:
            raise ValueError("No active project")
        return self.project

    def _snapshot(self) -> None:
        if self.project is not None:
            self._undo_stack.append(copy.deepcopy(self.project))
            self._redo_stack.clear()

    def _make_marker(self, body_id: str, marker_input: MarkerInput, is_first: bool) -> Marker:
        marker_name = marker_input.name or ("A" if is_first else self.id_service.new("mk"))
        return Marker(
            id=self.id_service.new("marker"),
            name=marker_name,
            type=marker_input.marker_type,
            x=self._scalar(marker_input.x, "mm", Dimension.LENGTH),
            y=self._scalar(marker_input.y, "mm", Dimension.LENGTH),
            visible=marker_input.visible,
        )

    def _make_com_marker(self, body: Body) -> Marker:
        structural = body.structural_markers()
        if body.type is BodyType.BAR and len(structural) == 2:
            x_expr = f"({structural[0].x.expression}+{structural[1].x.expression})/2"
            y_expr = f"({structural[0].y.expression}+{structural[1].y.expression})/2"
        else:
            x_expr = "(" + "+".join(marker.x.expression for marker in structural) + f")/{len(structural)}"
            y_expr = "(" + "+".join(marker.y.expression for marker in structural) + f")/{len(structural)}"
        return Marker(
            id=self.id_service.new("marker"),
            name="CoM",
            type=MarkerType.COM,
            x=self._scalar(x_expr, "mm", Dimension.LENGTH),
            y=self._scalar(y_expr, "mm", Dimension.LENGTH),
            visible=False,
        )

    def _scalar(self, expression: str, unit: str, dimension: Dimension) -> ScalarProperty:
        return ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension)

    def _make_endpoint(self, endpoint: JointEndpointInput) -> JointEndpoint:
        return JointEndpoint(
            kind=endpoint.kind,
            body_id=endpoint.body_id,
            marker_id=endpoint.marker_id,
            slider_id=endpoint.slider_id,
        )

    def _find_body(self, body_id: str) -> Body:
        project = self._require_project()
        for body in project.model.bodies:
            if body.id == body_id:
                return body
        raise ValueError(f"Unknown body: {body_id}")

    def _find_body_by_marker(self, marker_id: str) -> Body:
        project = self._require_project()
        for body in project.model.bodies:
            if any(marker.id == marker_id for marker in body.markers):
                return body
        raise ValueError(f"Unknown marker: {marker_id}")

    def _find_parameter(self, parameter_id: str) -> Parameter:
        project = self._require_project()
        for parameter in project.parameters:
            if parameter.id == parameter_id:
                return parameter
        raise ValueError(f"Unknown parameter: {parameter_id}")

    def _find_joint(self, joint_id: str) -> Joint:
        project = self._require_project()
        for joint in project.model.joints:
            if joint.id == joint_id:
                return joint
        raise ValueError(f"Unknown joint: {joint_id}")

    def _find_entity(self, entity_id: str) -> object:
        project = self._require_project()
        for collection in (
            project.model.bodies,
            project.model.joints,
            project.model.sliders,
            project.model.drivers,
            project.parameters,
        ):
            for entity in collection:
                if entity.id == entity_id:
                    return entity
        for body in project.model.bodies:
            for marker in body.markers:
                if marker.id == entity_id:
                    return marker
        raise ValueError(f"Unknown entity: {entity_id}")

    def _build_validated_scalar_property(self, entity: object, property_path: str, expression: str) -> ScalarProperty:
        dimension_map = {
            "x": Dimension.LENGTH,
            "y": Dimension.LENGTH,
            "origin_x": Dimension.LENGTH,
            "origin_y": Dimension.LENGTH,
            "travel_min": Dimension.LENGTH,
            "travel_max": Dimension.LENGTH,
            "angle": Dimension.ANGLE,
            "mass": Dimension.MASS,
            "inertia": Dimension.INERTIA,
            "law": getattr(entity, "law", None).expected_dimension if isinstance(entity, Driver) else None,
        }
        if property_path not in dimension_map:
            raise ValueError(f"Unsupported property path: {property_path}")
        current = getattr(entity, property_path)
        unit = "deg" if property_path == "angle" else "kg" if property_path == "mass" else "mm"
        if property_path == "inertia":
            unit = "unitless"
        if current is not None and isinstance(current, ScalarProperty):
            unit = current.unit
        scalar = ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension_map[property_path])
        variables = {"t": self.unit_service.quantity(0.0, "s")} if property_path == "law" else None
        self.expression_service.evaluate_property(scalar, self._require_project().parameters, variables=variables)
        return scalar

    def _assign_scalar_property(self, entity: object, property_path: str, scalar: ScalarProperty) -> None:
        setattr(entity, property_path, scalar)
        if isinstance(entity, Body) and property_path == "mass":
            value = self.expression_service.evaluate_property(scalar, self._require_project().parameters).value
            entity.com_marker().visible = value != 0

    def _rename_entity_no_snapshot(self, entity: object, new_name: str) -> None:
        entity.name = new_name

    def _validate_entity_name(self, entity: object, new_name: str) -> None:
        project = self._require_project()
        if isinstance(entity, Body):
            self.validation_service.ensure_unique_name(project.model.bodies, new_name, entity.id)
        elif isinstance(entity, Joint):
            self.validation_service.ensure_unique_name(project.model.joints, new_name, entity.id)
        elif isinstance(entity, Slider):
            self.validation_service.ensure_unique_name(project.model.sliders, new_name, entity.id)
        elif isinstance(entity, Driver):
            self.validation_service.ensure_unique_name(project.model.drivers, new_name, entity.id)
        elif isinstance(entity, Parameter):
            self.validation_service.ensure_unique_name(project.parameters, new_name, entity.id)
        elif isinstance(entity, Marker):
            body = self._find_body_by_marker(entity.id)
            self.validation_service.ensure_unique_marker_name(body, new_name, entity.id)

    def _validated_edge_order(self, body: Body, raw_value: str) -> list[str]:
        requested_names = [item.strip() for item in raw_value.split(",") if item.strip()]
        structural = body.structural_markers()
        structural_names = [marker.name for marker in structural]
        if sorted(requested_names) != sorted(structural_names):
            raise ValueError("edge_order must list every structural marker name exactly once")
        marker_by_name = {marker.name: marker.id for marker in structural}
        return [marker_by_name[name] for name in requested_names]

    def _validate_parameter_definition(self, expression: str, unit: str, parameter_id: str | None = None) -> None:
        project = self._require_project()
        parameter_map = [
            parameter
            for parameter in project.parameters
            if parameter.id != parameter_id
        ]
        quantity = self.expression_service.evaluate_expression(expression, parameter_map)
        self.unit_service.convert(quantity, unit)

    def _validate_endpoint_input(self, endpoint: JointEndpointInput) -> None:
        if endpoint.kind is JointEndpointKind.MARKER:
            if endpoint.body_id is None or endpoint.marker_id is None:
                raise ValueError("Marker endpoints require body_id and marker_id")
            return
        if endpoint.kind is JointEndpointKind.SLIDER:
            if endpoint.slider_id is None:
                raise ValueError("Slider endpoints require slider_id")
            return
        if endpoint.kind is JointEndpointKind.GROUND:
            return
        raise ValueError(f"Unsupported endpoint kind: {endpoint.kind}")

    def _sync_id_service(self) -> None:
        project = self._require_project()
        self.id_service.observe(project.id)
        for parameter in project.parameters:
            self.id_service.observe(parameter.id)
        for body in project.model.bodies:
            self.id_service.observe(body.id)
            for marker in body.markers:
                self.id_service.observe(marker.id)
        for slider in project.model.sliders:
            self.id_service.observe(slider.id)
        for joint in project.model.joints:
            self.id_service.observe(joint.id)
        for driver in project.model.drivers:
            self.id_service.observe(driver.id)

    def _ensure_joint_not_duplicate(self, candidate: Joint) -> None:
        project = self._require_project()
        new_key = self.validation_service._joint_key(candidate)
        for joint in project.model.joints:
            if self.validation_service._joint_key(joint) == new_key:
                raise ValueError("Duplicate joint between the same endpoints")

    def _joint_has_slider(self, joint: Joint) -> bool:
        return joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER

    def _evaluate_all(self, project: Project, report: ValidationReport) -> None:
        for parameter in project.parameters:
            try:
                self.expression_service.evaluate_expression(parameter.expression, project.parameters)
            except Exception as exc:
                report.messages.append(
                    ValidationMessage(
                        "warning", "parameter_evaluation", f"Parameter {parameter.name}: {exc}", parameter.id
                    )
                )
        for body in project.model.bodies:
            for marker in body.markers:
                for prop in (marker.x, marker.y):
                    try:
                        self.expression_service.evaluate_property(prop, project.parameters)
                    except Exception as exc:
                        report.messages.append(
                            ValidationMessage(
                                "warning", "property_evaluation", f"Marker {marker.name}: {exc}", marker.id
                            )
                        )
        for driver in project.model.drivers:
            try:
                self.expression_service.evaluate_property(
                    driver.law,
                    project.parameters,
                    variables={"t": self.unit_service.quantity(0.0, "s")},
                )
            except Exception as exc:
                report.messages.append(
                    ValidationMessage(
                        "warning",
                        "driver_evaluation",
                        f"Driver {driver.name}: {exc}",
                        driver.id,
                    )
                )
