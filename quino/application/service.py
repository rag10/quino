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
    Sensor,
    SensorOutput,
    SimulationResult,
    Slider,
    Style,
    ValidationMessage,
    ValidationReport,
    ViewState,
)
from quino.domain.types import BodyType, Dimension, DriverType, JointEndpointKind, JointType, MarkerType, SensorType
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
        project = self._require_project()
        body = self._find_body_by_marker(marker_id)
        marker = self._find_entity(marker_id)
        slider = self._find_entity(slider_id)
        if isinstance(marker, Marker) and isinstance(slider, Slider):
            # Snap the marker to the slider origin so there is no gap
            sx = self._evaluate_scalar_as(slider.origin_x, "mm")
            sy = self._evaluate_scalar_as(slider.origin_y, "mm")
            marker.x = ScalarProperty(expression=f"{sx:.3f} mm", unit="mm", expected_dimension=Dimension.LENGTH)
            marker.y = ScalarProperty(expression=f"{sy:.3f} mm", unit="mm", expected_dimension=Dimension.LENGTH)
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
        target_x_eval = self.expression_service.evaluate_property(new_x, project.parameters)
        target_y_eval = self.expression_service.evaluate_property(new_y, project.parameters)
        current_x_eval = self.expression_service.evaluate_property(marker.x, project.parameters)
        current_y_eval = self.expression_service.evaluate_property(marker.y, project.parameters)
        target_x = self.unit_service.convert(self.unit_service.quantity(target_x_eval.value, target_x_eval.unit), "mm")
        target_y = self.unit_service.convert(self.unit_service.quantity(target_y_eval.value, target_y_eval.unit), "mm")
        current_x = self.unit_service.convert(self.unit_service.quantity(current_x_eval.value, current_x_eval.unit), "mm")
        current_y = self.unit_service.convert(self.unit_service.quantity(current_y_eval.value, current_y_eval.unit), "mm")
        delta_x = target_x - current_x
        delta_y = target_y - current_y
        if abs(delta_x) < 1e-12 and abs(delta_y) < 1e-12:
            return
        linked_joints = self._joints_for_marker(marker_id)
        if linked_joints:
            self._snapshot()
            marker.x = new_x
            marker.y = new_y
            self._translate_direct_joint_counterparts(marker_id, linked_joints, delta_x, delta_y)
            return
        self._snapshot()
        marker.x = new_x
        marker.y = new_y

    def update_property(self, entity_id: str, property_path: str, value: PropertyValueInput) -> None:
        entity = self._find_entity(entity_id)
        if isinstance(entity, Marker) and property_path in {"x", "y"}:
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Marker coordinates require an expression value")
            target_x = value.value if property_path == "x" else entity.x.expression
            target_y = value.value if property_path == "y" else entity.y.expression
            self.move_marker(entity.id, target_x, target_y)
            return
        if isinstance(entity, Slider) and property_path in {"origin_x", "origin_y"}:
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Slider origin coordinates require an expression value")
            target_x = value.value if property_path == "origin_x" else entity.origin_x.expression
            target_y = value.value if property_path == "origin_y" else entity.origin_y.expression
            self._move_slider_origin(entity.id, target_x, target_y)
            return
        if isinstance(entity, Slider) and property_path == "angle":
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Slider angle requires an expression value")
            self._rotate_slider(entity.id, value.value)
            return
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
        if any(sensor.id == entity_id for sensor in project.model.sensors):
            self._snapshot()
            project.model.sensors = [item for item in project.model.sensors if item.id != entity_id]
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
        project.model.sensors = [
            sensor
            for sensor in project.model.sensors
            if entity_id not in sensor.marker_ids
        ]
        if len(body.structural_markers()) == 1:
            body.type = BodyType.POINT_MASS
            body.closed_shape = False
        elif body.type is BodyType.BODY and len(body.structural_markers()) == 2:
            body.closed_shape = True

    def validate_model(self, duration: float = 1.0, steps: int = 20) -> ValidationReport:
        project = self._require_project()
        report = self.validation_service.validate_project(project)
        self._validate_joint_geometry(project, report)
        self._validate_kinematic_reach(project, report, duration, steps)
        self._evaluate_all(project, report)
        return report

    def run_kinematic_simulation(self, duration: float = 1.0, steps: int = 100) -> SimulationResult:
        project = self._require_project()
        report = self.validate_model(duration=duration, steps=steps)
        validation_messages = [message.message for message in report.messages]
        blocking_messages = [
            message
            for message in report.messages
            if message.code in {"kinematic_reach", "kinematic_travel", "kinematic_loop_reach"}
        ]
        if blocking_messages:
            validation_messages.append(
                "Preflight detected unreachable kinematics; attempting solver for partial trajectory"
            )
        project.sensor_outputs.clear()
        result = self.simulation_runner.run(project, duration=duration, steps=steps)
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
            project.model.sensors,
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
        elif isinstance(entity, Sensor):
            self.validation_service.ensure_unique_name(project.model.sensors, new_name, entity.id)
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

    def _joints_for_marker(self, marker_id: str) -> list[Joint]:
        project = self._require_project()
        return [
            joint
            for joint in project.model.joints
            if joint.endpoint_a.marker_id == marker_id or joint.endpoint_b.marker_id == marker_id
        ]

    def _translate_direct_joint_counterparts(
        self,
        marker_id: str,
        joints: list[Joint],
        delta_x_mm: float,
        delta_y_mm: float,
    ) -> None:
        # BFS over joint graph: collect all markers/sliders co-located with marker_id
        project = self._require_project()
        all_joints = project.model.joints
        moved_marker_ids: set[str] = {marker_id}
        moved_slider_ids: set[str] = set()
        frontier: list[str] = [marker_id]
        while frontier:
            current_id = frontier.pop()
            for joint in all_joints:
                ep_a, ep_b = joint.endpoint_a, joint.endpoint_b
                # Find the counterpart of current_id in this joint
                counterpart_marker_id: str | None = None
                counterpart_slider_id: str | None = None
                if ep_a.kind is JointEndpointKind.MARKER and ep_a.marker_id == current_id:
                    if ep_b.kind is JointEndpointKind.MARKER:
                        counterpart_marker_id = ep_b.marker_id
                    elif ep_b.kind is JointEndpointKind.SLIDER:
                        counterpart_slider_id = ep_b.slider_id
                elif ep_b.kind is JointEndpointKind.MARKER and ep_b.marker_id == current_id:
                    if ep_a.kind is JointEndpointKind.MARKER:
                        counterpart_marker_id = ep_a.marker_id
                    elif ep_a.kind is JointEndpointKind.SLIDER:
                        counterpart_slider_id = ep_a.slider_id
                else:
                    continue
                if counterpart_marker_id and counterpart_marker_id not in moved_marker_ids:
                    linked_marker = self._find_entity(counterpart_marker_id)
                    if isinstance(linked_marker, Marker):
                        self._translate_marker_expression(linked_marker, delta_x_mm, delta_y_mm)
                        moved_marker_ids.add(counterpart_marker_id)
                        frontier.append(counterpart_marker_id)
                if counterpart_slider_id and counterpart_slider_id not in moved_slider_ids:
                    linked_slider = self._find_entity(counterpart_slider_id)
                    if isinstance(linked_slider, Slider):
                        self._translate_slider_expression(
                            linked_slider,
                            delta_x_mm,
                            delta_y_mm,
                            moved_marker_ids=moved_marker_ids,
                        )
                        moved_slider_ids.add(counterpart_slider_id)

    def _move_slider_origin(self, slider_id: str, x_expression: str, y_expression: str) -> None:
        slider = self._find_entity(slider_id)
        if not isinstance(slider, Slider):
            raise ValueError("move_slider_origin requires a slider entity")
        new_x = ScalarProperty(
            expression=x_expression,
            unit=slider.origin_x.unit,
            expected_dimension=Dimension.LENGTH,
        )
        new_y = ScalarProperty(
            expression=y_expression,
            unit=slider.origin_y.unit,
            expected_dimension=Dimension.LENGTH,
        )
        target_x = self._evaluate_scalar_as(new_x, "mm")
        target_y = self._evaluate_scalar_as(new_y, "mm")
        current_x = self._evaluate_scalar_as(slider.origin_x, "mm")
        current_y = self._evaluate_scalar_as(slider.origin_y, "mm")
        delta_x = target_x - current_x
        delta_y = target_y - current_y
        if abs(delta_x) < 1e-12 and abs(delta_y) < 1e-12:
            if (
                slider.origin_x.expression != x_expression
                or slider.origin_y.expression != y_expression
            ):
                self._snapshot()
                slider.origin_x = new_x
                slider.origin_y = new_y
            return
        self._snapshot()
        slider.origin_x = new_x
        slider.origin_y = new_y
        moved_marker_ids: set[str] = set()
        self._translate_markers_linked_to_slider(slider.id, delta_x, delta_y, moved_marker_ids)

    def _rotate_slider(self, slider_id: str, angle_expression: str) -> None:
        slider = self._find_entity(slider_id)
        if not isinstance(slider, Slider):
            raise ValueError("rotate_slider requires a slider entity")
        new_angle = ScalarProperty(
            expression=angle_expression,
            unit=slider.angle.unit,
            expected_dimension=Dimension.ANGLE,
        )
        old_angle = self._evaluate_scalar_as(slider.angle, "rad")
        target_angle = self._evaluate_scalar_as(new_angle, "rad")
        origin_x = self._evaluate_scalar_as(slider.origin_x, "mm")
        origin_y = self._evaluate_scalar_as(slider.origin_y, "mm")
        old_axis = (math.cos(old_angle), math.sin(old_angle))
        new_axis = (math.cos(target_angle), math.sin(target_angle))
        linked_markers = self._markers_linked_to_slider(slider.id)
        marker_targets: list[tuple[Marker, float, float]] = []
        for marker in linked_markers:
            marker_x = self._evaluate_scalar_as(marker.x, "mm")
            marker_y = self._evaluate_scalar_as(marker.y, "mm")
            slider_coordinate = (
                (marker_x - origin_x) * old_axis[0]
                + (marker_y - origin_y) * old_axis[1]
            )
            marker_targets.append(
                (
                    marker,
                    origin_x + slider_coordinate * new_axis[0],
                    origin_y + slider_coordinate * new_axis[1],
                )
            )
        if abs(target_angle - old_angle) < 1e-12:
            if slider.angle.expression == angle_expression:
                return
            self._snapshot()
            slider.angle = new_angle
            return
        self._snapshot()
        slider.angle = new_angle
        for marker, marker_x, marker_y in marker_targets:
            self._set_marker_absolute_mm(marker, marker_x, marker_y)

    def _translate_slider_expression(
        self,
        slider: Slider,
        delta_x_mm: float,
        delta_y_mm: float,
        moved_marker_ids: set[str] | None = None,
    ) -> None:
        slider.origin_x.expression = self._offset_expression(
            slider.origin_x.expression,
            delta_x_mm,
            "mm",
        )
        slider.origin_y.expression = self._offset_expression(
            slider.origin_y.expression,
            delta_y_mm,
            "mm",
        )
        self._translate_markers_linked_to_slider(
            slider.id,
            delta_x_mm,
            delta_y_mm,
            moved_marker_ids or set(),
        )

    def _translate_markers_linked_to_slider(
        self,
        slider_id: str,
        delta_x_mm: float,
        delta_y_mm: float,
        moved_marker_ids: set[str],
    ) -> None:
        for linked_marker in self._markers_linked_to_slider(slider_id):
            if linked_marker.id in moved_marker_ids:
                continue
            self._translate_marker_expression(linked_marker, delta_x_mm, delta_y_mm)
            moved_marker_ids.add(linked_marker.id)

    def _markers_linked_to_slider(self, slider_id: str) -> list[Marker]:
        project = self._require_project()
        marker_ids: list[str] = []
        for joint in project.model.joints:
            endpoints = (joint.endpoint_a, joint.endpoint_b)
            has_slider = any(
                endpoint.kind is JointEndpointKind.SLIDER and endpoint.slider_id == slider_id
                for endpoint in endpoints
            )
            if not has_slider:
                continue
            for endpoint in endpoints:
                if endpoint.kind is JointEndpointKind.MARKER and endpoint.marker_id is not None:
                    marker_ids.append(endpoint.marker_id)
        markers: list[Marker] = []
        seen: set[str] = set()
        for marker_id in marker_ids:
            if marker_id in seen:
                continue
            entity = self._find_entity(marker_id)
            if isinstance(entity, Marker):
                markers.append(entity)
                seen.add(marker_id)
        return markers

    def _translate_marker_expression(
        self,
        marker: Marker,
        delta_x_mm: float,
        delta_y_mm: float,
    ) -> None:
        marker.x.expression = self._offset_expression(marker.x.expression, delta_x_mm, "mm")
        marker.y.expression = self._offset_expression(marker.y.expression, delta_y_mm, "mm")

    def _set_marker_absolute_mm(self, marker: Marker, x_mm: float, y_mm: float) -> None:
        marker.x.expression = f"{x_mm:.6f} mm"
        marker.y.expression = f"{y_mm:.6f} mm"

    def _evaluate_scalar_as(self, scalar: ScalarProperty, unit: str) -> float:
        result = self.expression_service.evaluate_property(
            scalar,
            self._require_project().parameters,
        )
        return self.unit_service.convert(
            self.unit_service.quantity(result.value, result.unit),
            unit,
        )

    def _offset_expression(self, expression: str, delta: float, unit: str) -> str:
        if abs(delta) < 1e-12:
            return expression
        sign = "+" if delta >= 0 else "-"
        return f"({expression}) {sign} {abs(delta):.6f} {unit}"

    def _validate_joint_geometry(self, project: Project, report: ValidationReport) -> None:
        try:
            assembled = self.simulation_runner.adapter.assembler.assemble(project)
        except Exception as exc:
            report.messages.append(
                ValidationMessage(
                    "warning",
                    "geometry_assembly_failed",
                    f"Could not evaluate joint geometry: {exc}",
                )
            )
            return
        tolerance = 1e-6
        for joint in project.model.joints:
            endpoints = (joint.endpoint_a, joint.endpoint_b)
            marker_endpoints = [
                endpoint for endpoint in endpoints if endpoint.kind is JointEndpointKind.MARKER
            ]
            slider_endpoints = [
                endpoint for endpoint in endpoints if endpoint.kind is JointEndpointKind.SLIDER
            ]
            if len(marker_endpoints) == 2:
                first = self._assembled_marker(assembled, marker_endpoints[0])
                second = self._assembled_marker(assembled, marker_endpoints[1])
                if first is None or second is None:
                    continue
                gap = (
                    (first.global_x - second.global_x) ** 2
                    + (first.global_y - second.global_y) ** 2
                ) ** 0.5
                if gap > tolerance:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "joint_gap",
                            f"Joint {joint.name} marker-marker gap is {gap:.6g} mm",
                            joint.id,
                        )
                    )
            elif len(marker_endpoints) == 1 and slider_endpoints:
                marker = self._assembled_marker(assembled, marker_endpoints[0])
                slider = assembled.sliders.get(slider_endpoints[0].slider_id)
                if marker is None or slider is None:
                    continue
                dx = marker.global_x - slider.origin_x
                dy = marker.global_y - slider.origin_y
                normal_gap = abs(dx * slider.normal_x + dy * slider.normal_y)
                slider_coordinate = dx * slider.axis_x + dy * slider.axis_y
                if normal_gap > tolerance:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "slider_joint_gap",
                            f"Joint {joint.name} marker-slider normal gap is {normal_gap:.6g} mm",
                            joint.id,
                        )
                    )
                if (
                    slider.travel_min is not None
                    and slider_coordinate < slider.travel_min - tolerance
                ):
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "slider_joint_travel",
                            (
                                f"Joint {joint.name} slider coordinate {slider_coordinate:.6g} mm "
                                f"is below travel_min {slider.travel_min:.6g} mm"
                            ),
                            joint.id,
                        )
                    )
                if (
                    slider.travel_max is not None
                    and slider_coordinate > slider.travel_max + tolerance
                ):
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "slider_joint_travel",
                            (
                                f"Joint {joint.name} slider coordinate {slider_coordinate:.6g} mm "
                                f"is above travel_max {slider.travel_max:.6g} mm"
                            ),
                            joint.id,
                        )
                    )

    def _assembled_marker(self, assembled, endpoint):
        if endpoint.body_id not in assembled.bodies:
            return None
        return assembled.bodies[endpoint.body_id].markers.get(endpoint.marker_id)

    def _validate_kinematic_reach(
        self,
        project: Project,
        report: ValidationReport,
        duration: float,
        steps: int,
    ) -> None:
        try:
            assembled = self.simulation_runner.adapter.assembler.assemble(project)
        except Exception:
            return
        sample_times = self._simulation_sample_times(duration, steps)
        reported: set[tuple[str, str, str]] = set()
        for driver in project.model.drivers:
            if driver.type is not DriverType.ROTATION:
                continue
            try:
                driven_joint = self._find_joint(driver.target_joint_id)
            except ValueError:
                continue
            grounded_endpoint = self._marker_ground_endpoint(driven_joint)
            if grounded_endpoint is None or grounded_endpoint.body_id is None:
                continue
            driven_body = assembled.bodies.get(grounded_endpoint.body_id)
            if driven_body is None or grounded_endpoint.marker_id is None:
                continue
            ground_marker = driven_body.markers.get(grounded_endpoint.marker_id)
            if ground_marker is None:
                continue
            for joint in project.model.joints:
                if joint.id == driven_joint.id:
                    continue
                marker_endpoints = [
                    endpoint
                    for endpoint in (joint.endpoint_a, joint.endpoint_b)
                    if endpoint.kind is JointEndpointKind.MARKER
                ]
                if len(marker_endpoints) != 2:
                    continue
                driven_endpoints = [
                    endpoint
                    for endpoint in marker_endpoints
                    if endpoint.body_id == driven_body.body_id
                ]
                follower_endpoints = [
                    endpoint for endpoint in marker_endpoints if endpoint.body_id != driven_body.body_id
                ]
                for driven_endpoint in driven_endpoints:
                    if driven_endpoint.marker_id is None:
                        continue
                    driven_marker = driven_body.markers.get(driven_endpoint.marker_id)
                    if driven_marker is None:
                        continue
                    for follower_endpoint in follower_endpoints:
                        if follower_endpoint.body_id is None or follower_endpoint.marker_id is None:
                            continue
                        follower_body = assembled.bodies.get(follower_endpoint.body_id)
                        if follower_body is None:
                            continue
                        follower_marker = follower_body.markers.get(follower_endpoint.marker_id)
                        if follower_marker is None:
                            continue
                        slider_links = self._slider_links_for_body(
                            project,
                            follower_endpoint.body_id,
                            exclude_marker_id=follower_endpoint.marker_id,
                        )
                        for slider_joint, slider_marker_endpoint, slider_endpoint in slider_links:
                            key = (driver.id, joint.id, slider_joint.id)
                            if key in reported:
                                continue
                            slider = assembled.sliders.get(slider_endpoint.slider_id)
                            slider_marker = follower_body.markers.get(slider_marker_endpoint.marker_id)
                            if slider is None or slider_marker is None:
                                continue
                            reach = (
                                (slider_marker.local_x - follower_marker.local_x) ** 2
                                + (slider_marker.local_y - follower_marker.local_y) ** 2
                            ) ** 0.5
                            failure = self._first_slider_reach_failure(
                                project,
                                driver,
                                driven_body,
                                ground_marker,
                                driven_marker,
                                slider,
                                reach,
                                sample_times,
                            )
                            if failure is None:
                                continue
                            reported.add(key)
                            report.messages.append(
                                ValidationMessage(
                                    "warning",
                                    failure[0],
                                    failure[1],
                                    slider_joint.id,
                                )
                            )

        self._validate_rotational_loop_reach(project, report, assembled, sample_times)

    def _validate_rotational_loop_reach(
        self,
        project: Project,
        report: ValidationReport,
        assembled,
        sample_times: list[float],
    ) -> None:
        reported: set[tuple[str, str, str, str]] = set()
        for driver in project.model.drivers:
            if driver.type is not DriverType.ROTATION:
                continue
            try:
                driven_joint = self._find_joint(driver.target_joint_id)
            except ValueError:
                continue
            grounded_endpoint = self._marker_ground_endpoint(driven_joint)
            if grounded_endpoint is None or grounded_endpoint.body_id is None:
                continue
            driven_body = assembled.bodies.get(grounded_endpoint.body_id)
            if driven_body is None or grounded_endpoint.marker_id is None:
                continue
            ground_marker = driven_body.markers.get(grounded_endpoint.marker_id)
            if ground_marker is None:
                continue
            for input_joint in project.model.joints:
                if input_joint.id == driven_joint.id:
                    continue
                input_endpoints = self._marker_marker_endpoints(input_joint)
                if input_endpoints is None:
                    continue
                driven_endpoint = next(
                    (
                        endpoint
                        for endpoint in input_endpoints
                        if endpoint.body_id == driven_body.body_id
                    ),
                    None,
                )
                follower_endpoint = next(
                    (
                        endpoint
                        for endpoint in input_endpoints
                        if endpoint.body_id != driven_body.body_id
                    ),
                    None,
                )
                if (
                    driven_endpoint is None
                    or follower_endpoint is None
                    or driven_endpoint.marker_id is None
                    or follower_endpoint.body_id is None
                    or follower_endpoint.marker_id is None
                ):
                    continue
                driven_marker = driven_body.markers.get(driven_endpoint.marker_id)
                follower_body = assembled.bodies.get(follower_endpoint.body_id)
                if driven_marker is None or follower_body is None:
                    continue
                follower_input_marker = follower_body.markers.get(follower_endpoint.marker_id)
                if follower_input_marker is None:
                    continue
                for output_joint in project.model.joints:
                    if output_joint.id in {driven_joint.id, input_joint.id}:
                        continue
                    output_endpoints = self._marker_marker_endpoints(output_joint)
                    if output_endpoints is None:
                        continue
                    follower_output_endpoint = next(
                        (
                            endpoint
                            for endpoint in output_endpoints
                            if (
                                endpoint.body_id == follower_body.body_id
                                and endpoint.marker_id != follower_endpoint.marker_id
                            )
                        ),
                        None,
                    )
                    terminal_endpoint = next(
                        (
                            endpoint
                            for endpoint in output_endpoints
                            if endpoint.body_id != follower_body.body_id
                        ),
                        None,
                    )
                    if (
                        follower_output_endpoint is None
                        or terminal_endpoint is None
                        or follower_output_endpoint.marker_id is None
                        or terminal_endpoint.body_id is None
                        or terminal_endpoint.marker_id is None
                    ):
                        continue
                    terminal_body = assembled.bodies.get(terminal_endpoint.body_id)
                    if terminal_body is None:
                        continue
                    follower_output_marker = follower_body.markers.get(
                        follower_output_endpoint.marker_id
                    )
                    terminal_output_marker = terminal_body.markers.get(terminal_endpoint.marker_id)
                    if follower_output_marker is None or terminal_output_marker is None:
                        continue
                    terminal_ground = self._ground_endpoint_for_body(
                        project,
                        terminal_body.body_id,
                        exclude_marker_id=terminal_endpoint.marker_id,
                    )
                    if terminal_ground is None or terminal_ground.marker_id is None:
                        continue
                    terminal_ground_marker = terminal_body.markers.get(terminal_ground.marker_id)
                    if terminal_ground_marker is None:
                        continue
                    key = (driver.id, input_joint.id, output_joint.id, terminal_ground.marker_id)
                    if key in reported:
                        continue
                    follower_length = self._local_distance(
                        follower_input_marker,
                        follower_output_marker,
                    )
                    terminal_length = self._local_distance(
                        terminal_ground_marker,
                        terminal_output_marker,
                    )
                    failure = self._first_four_bar_reach_failure(
                        project,
                        driver,
                        driven_body,
                        ground_marker,
                        driven_marker,
                        terminal_ground_marker,
                        follower_length,
                        terminal_length,
                        sample_times,
                    )
                    if failure is None:
                        continue
                    reported.add(key)
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "kinematic_loop_reach",
                            failure,
                            output_joint.id,
                        )
                    )

    def _first_four_bar_reach_failure(
        self,
        project: Project,
        driver: Driver,
        driven_body,
        ground_marker,
        driven_marker,
        terminal_ground_marker,
        follower_length: float,
        terminal_length: float,
        sample_times: list[float],
    ) -> str | None:
        tolerance = 1e-6
        minimum = abs(follower_length - terminal_length)
        maximum = follower_length + terminal_length
        for time_value in sample_times:
            try:
                driver_angle = self._driver_value_at(driver, project, time_value, "rad")
            except Exception:
                return None
            marker_x, marker_y = self._driven_marker_position(
                driven_body,
                ground_marker,
                driven_marker,
                driver_angle,
            )
            distance = (
                (marker_x - terminal_ground_marker.global_x) ** 2
                + (marker_y - terminal_ground_marker.global_y) ** 2
            ) ** 0.5
            if distance > maximum + tolerance or distance < minimum - tolerance:
                return (
                    f"Driver {driver.name} may make the closed loop unreachable at "
                    f"t={time_value:.3g}s: distance between driven joint and fixed rocker "
                    f"ground is {distance:.6g} mm, but the connected links require "
                    f"{minimum:.6g} mm <= distance <= {maximum:.6g} mm"
                )
        return None

    def _first_slider_reach_failure(
        self,
        project: Project,
        driver: Driver,
        driven_body,
        ground_marker,
        driven_marker,
        slider,
        reach: float,
        sample_times: list[float],
    ) -> tuple[str, str] | None:
        tolerance = 1e-6
        for time_value in sample_times:
            try:
                driver_angle = self._driver_value_at(driver, project, time_value, "rad")
            except Exception:
                return None
            marker_x, marker_y = self._driven_marker_position(
                driven_body,
                ground_marker,
                driven_marker,
                driver_angle,
            )
            dx = marker_x - slider.origin_x
            dy = marker_y - slider.origin_y
            normal_distance = abs(dx * slider.normal_x + dy * slider.normal_y)
            if normal_distance > reach + tolerance:
                return (
                    "kinematic_reach",
                    (
                        f"Driver {driver.name} may make the mechanism unreachable at "
                        f"t={time_value:.3g}s: driven joint is {normal_distance:.6g} mm "
                        f"from slider {slider.name}, but connected body reach is {reach:.6g} mm"
                    ),
                )
            slider_coordinate = dx * slider.axis_x + dy * slider.axis_y
            half_chord = max(reach**2 - normal_distance**2, 0.0) ** 0.5
            min_possible = slider_coordinate - half_chord
            max_possible = slider_coordinate + half_chord
            if slider.travel_min is not None and max_possible < slider.travel_min - tolerance:
                return (
                    "kinematic_travel",
                    (
                        f"Driver {driver.name} may move beyond slider {slider.name} travel at "
                        f"t={time_value:.3g}s: reachable slider coordinate is at most "
                        f"{max_possible:.6g} mm, below travel_min {slider.travel_min:.6g} mm"
                    ),
                )
            if slider.travel_max is not None and min_possible > slider.travel_max + tolerance:
                return (
                    "kinematic_travel",
                    (
                        f"Driver {driver.name} may move beyond slider {slider.name} travel at "
                        f"t={time_value:.3g}s: reachable slider coordinate is at least "
                        f"{min_possible:.6g} mm, above travel_max {slider.travel_max:.6g} mm"
                    ),
                )
        return None

    def _simulation_sample_times(self, duration: float, steps: int) -> list[float]:
        count = max(2, min(max(steps, 1) + 1, 80))
        return [duration * index / (count - 1) for index in range(count)]

    def _marker_ground_endpoint(self, joint: Joint) -> JointEndpoint | None:
        endpoints = (joint.endpoint_a, joint.endpoint_b)
        if not any(endpoint.kind is JointEndpointKind.GROUND for endpoint in endpoints):
            return None
        for endpoint in endpoints:
            if endpoint.kind is JointEndpointKind.MARKER:
                return endpoint
        return None

    def _marker_marker_endpoints(self, joint: Joint) -> tuple[JointEndpoint, JointEndpoint] | None:
        if (
            joint.endpoint_a.kind is JointEndpointKind.MARKER
            and joint.endpoint_b.kind is JointEndpointKind.MARKER
        ):
            return joint.endpoint_a, joint.endpoint_b
        return None

    def _ground_endpoint_for_body(
        self,
        project: Project,
        body_id: str,
        exclude_marker_id: str,
    ) -> JointEndpoint | None:
        for joint in project.model.joints:
            marker_endpoint = self._marker_ground_endpoint(joint)
            if (
                marker_endpoint is not None
                and marker_endpoint.body_id == body_id
                and marker_endpoint.marker_id != exclude_marker_id
            ):
                return marker_endpoint
        return None

    def _local_distance(self, first, second) -> float:
        return ((first.local_x - second.local_x) ** 2 + (first.local_y - second.local_y) ** 2) ** 0.5

    def _slider_links_for_body(
        self,
        project: Project,
        body_id: str,
        exclude_marker_id: str,
    ) -> list[tuple[Joint, JointEndpoint, JointEndpoint]]:
        links: list[tuple[Joint, JointEndpoint, JointEndpoint]] = []
        for joint in project.model.joints:
            marker_endpoint = None
            slider_endpoint = None
            for endpoint in (joint.endpoint_a, joint.endpoint_b):
                if (
                    endpoint.kind is JointEndpointKind.MARKER
                    and endpoint.body_id == body_id
                    and endpoint.marker_id != exclude_marker_id
                ):
                    marker_endpoint = endpoint
                elif endpoint.kind is JointEndpointKind.SLIDER:
                    slider_endpoint = endpoint
            if marker_endpoint is not None and slider_endpoint is not None:
                links.append((joint, marker_endpoint, slider_endpoint))
        return links

    def _driver_value_at(
        self,
        driver: Driver,
        project: Project,
        time_value: float,
        unit: str,
    ) -> float:
        quantity = self.expression_service.evaluate_expression(
            driver.law.expression,
            project.parameters,
            variables={"t": self.unit_service.quantity(time_value, "s")},
        )
        return self.unit_service.convert(quantity, unit)

    def _driven_marker_position(self, body, ground_marker, driven_marker, driver_angle: float) -> tuple[float, float]:
        absolute_angle = body.angle + driver_angle
        cos_a = math.cos(absolute_angle)
        sin_a = math.sin(absolute_angle)
        origin_x = ground_marker.global_x - (
            cos_a * ground_marker.local_x - sin_a * ground_marker.local_y
        )
        origin_y = ground_marker.global_y - (
            sin_a * ground_marker.local_x + cos_a * ground_marker.local_y
        )
        return (
            origin_x + cos_a * driven_marker.local_x - sin_a * driven_marker.local_y,
            origin_y + sin_a * driven_marker.local_x + cos_a * driven_marker.local_y,
        )

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

    def create_sensor(self, name: str, sensor_type: str, marker_ids: list[str]) -> str:
        if self.project is None:
            raise ValueError("No project loaded")
        sensor_id = self.id_service.new("sensor")
        sensor = Sensor(
            id=sensor_id,
            name=name,
            type=SensorType(sensor_type),
            marker_ids=marker_ids,
            metadata=Metadata(),
        )
        self._snapshot()
        self.project.model.sensors.append(sensor)
        return sensor_id

    def delete_sensor(self, sensor_id: str) -> None:
        if self.project is None:
            raise ValueError("No project loaded")
        self._snapshot()
        self.project.model.sensors = [s for s in self.project.model.sensors if s.id != sensor_id]

    def rename_sensor(self, sensor_id: str, name: str) -> None:
        if self.project is None:
            raise ValueError("No project loaded")
        sensor = next((s for s in self.project.model.sensors if s.id == sensor_id), None)
        if sensor is not None:
            self._snapshot()
            sensor.name = name
