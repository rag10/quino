from __future__ import annotations

import copy
import math
import re

from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput, SliderInput
from quino.domain.sketch_constraints import CONSTRAINT_SPECS
from quino.domain.model import (
    Body,
    Driver,
    Expression,
    GravityLoad,
    Joint,
    JointEndpoint,
    Load,
    Marker,
    Metadata,
    Model,
    Parameter,
    Project,
    Pose,
    ScalarProperty,
    Sensor,
    SimulationResult,
    Sketch,
    SketchConstraint,
    SketchArc,
    SketchCircle,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    SketchSpline,
    Slider,
    Spring,
    SpringEndpoint,
    Style,
    ValidationMessage,
    ValidationReport,
    ViewState,
)
from quino.domain.types import (
    BodyType,
    Dimension,
    DriverType,
    JointEndpointKind,
    JointType,
    MarkerType,
    SensorType,
    SketchConstraintType,
    SketchEntityType,
    SpringType,
)
from quino.application._context import ServiceContext
from quino.application.commands.parameter_commands import ParameterCommands
from quino.application.commands.force_commands import ForceCommands
from quino.application.commands.pose_commands import PoseCommands
from quino.application.commands.sketch_commands import SketchCommands
from quino.serialization.json_io import JsonMapper
from quino.pose.model import PoseConstraint, PoseSolveResult, PoseSolveSettings
from quino.pose.runner import PoseRunner
from quino.services.expressions import ExpressionService
from quino.services.ids import IdService
from quino.services.kinematic_validation import KinematicValidator
from quino.services.units import UnitService
from quino.services.validation import ValidationService
from quino.services.sketch_solver import SketchSolver
from quino.simulation.runner import SimulationRunner
from quino.simulation.sensor_expressions import sensor_expression_variables
from quino.solver_adapters.exudyn_adapter import ExudynAdapter
from quino.solver_adapters.exudyn_pose_adapter import ExudynPoseAdapter


class ApplicationService:
    schema_version = "0.1.0"
    _PLAIN_NUMBER_RE = re.compile(r"^\s*[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)\s*$")

    _STYLE_FIELD_TYPES: dict[str, type] = {
        "color": str,
        "visible": bool,
        "line_width": float,
        "marker_size": float,
    }

    def __init__(self) -> None:
        self.id_service = IdService()
        self.unit_service = UnitService()
        self.expression_service = ExpressionService(self.unit_service)
        self.validation_service = ValidationService()
        self.json_mapper = JsonMapper()
        self.project: Project | None = None
        self._undo_stack: list[Project] = []
        self._redo_stack: list[Project] = []
        self._in_operation = False
        self._entity_index: dict[str, object] | None = None
        self.sketch_solver = SketchSolver(self.expression_service, self.unit_service)
        self.simulation_runner = SimulationRunner(ExudynAdapter(self.expression_service))
        self.pose_runner = PoseRunner(ExudynPoseAdapter(self.expression_service))
        self._kinematic_validator = KinematicValidator(
            self.simulation_runner.adapter.assembler,
            self.expression_service,
            self.unit_service,
        )
        self._service_context = ServiceContext(
            project_provider=lambda: self.project,
            operation=self._operation,
            snapshot=self._snapshot,
            invalidate_pose_state=self._invalidate_pose_state,
            ids=self.id_service,
            expressions=self.expression_service,
            units=self.unit_service,
            validation=self.validation_service,
            find_entity=self._find_entity,
            sync_all_special_com_markers=self._sync_all_special_com_markers,
            load_expression_variables=self._kinematic_validator.load_expression_variables,
            build_validated_scalar_property=self._build_validated_scalar_property,
            assign_scalar_property=self._assign_scalar_property,
            apply_style_update=self._apply_style_update,
        )
        self.parameters = ParameterCommands(self._service_context)
        self.forces = ForceCommands(self._service_context)
        self.poses = PoseCommands(self._service_context, self.pose_runner)
        self.sketch = SketchCommands(self._service_context, self.sketch_solver)

    def new_project(self, name: str) -> Project:
        self.id_service = IdService()
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
        self.poses.clear_current()
        return self.project

    def load_project(self, path: str) -> Project:
        self.project = self.json_mapper.load_file(path)
        self._sync_id_service()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.poses.clear_current()
        self._sync_all_special_com_markers()
        if self.project is not None and self.project.sketch is not None:
            self.project.sketch.solve_error = None
            self.sketch._apply_sketch_constraints(set())
        return self.project

    def save_project(self, path: str) -> None:
        project = self._require_project()
        self.json_mapper.save_file(project, path)

    def create_reference_pose(self, name: str = "Reference") -> Pose:
        return self.poses.create_reference_pose(name)

    def list_poses(self) -> list[Pose]:
        return self.poses.list_poses()

    def get_pose(self, pose_id: str) -> Pose | None:
        return self.poses.get_pose(pose_id)

    def get_current_pose_id(self) -> str | None:
        return self.poses.get_current_pose_id()

    def set_current_pose_id(self, pose_id: str | None) -> None:
        return self.poses.set_current_pose_id(pose_id)

    def get_current_pose(self) -> Pose | None:
        return self.poses.get_current_pose()

    def set_current_pose(self, pose: Pose | None) -> None:
        return self.poses.set_current_pose(pose)

    def create_pose(self, name: str | None = None, *, set_current: bool = True) -> Pose:
        return self.poses.create_pose(name, set_current=set_current)

    def duplicate_pose(self, pose_id: str, *, set_current: bool = True) -> Pose:
        return self.poses.duplicate_pose(pose_id, set_current=set_current)

    def rename_pose(self, pose_id: str, name: str) -> None:
        return self.poses.rename_pose(pose_id, name)

    def delete_pose(self, pose_id: str) -> None:
        return self.poses.delete_pose(pose_id)

    def reset_current_pose_to_reference(self) -> Pose:
        return self.poses.reset_current_pose_to_reference()

    def get_simulation_initial_pose_id(self) -> str | None:
        return self.poses.get_simulation_initial_pose_id()

    def set_simulation_initial_pose(self, pose_id: str | None) -> None:
        return self.poses.set_simulation_initial_pose(pose_id)

    def get_simulation_initial_pose(self) -> Pose | None:
        return self.poses.get_simulation_initial_pose()

    def set_driver_initial_velocity(self, driver_id: str, value: float | None) -> None:
        return self.poses.set_driver_initial_velocity(driver_id, value)

    def get_driver_initial_velocity(self, driver_id: str) -> float | None:
        return self.poses.get_driver_initial_velocity(driver_id)

    # --- Legacy single-pose helpers (kept for GUI toolbar compat) -----------

    def set_initial_pose_from_current(self) -> None:
        return self.poses.set_initial_pose_from_current()

    def clear_initial_pose(self) -> None:
        return self.poses.clear_initial_pose()

    def solve_current_pose(
        self,
        temporary_constraints: list[PoseConstraint] | None = None,
        settings: PoseSolveSettings | None = None,
    ) -> PoseSolveResult:
        return self.poses.solve_current_pose(
            temporary_constraints=temporary_constraints,
            settings=settings,
        )

    def _complete_pose(self, pose: Pose) -> Pose:
        # Retained for back-compat (used by tests/test_gui.py).
        return self.poses.complete_pose(pose)

    def create_parameter(self, name: str, expression: str, unit: str, description: str = "") -> str:
        return self.parameters.create(name, expression, unit, description)

    def update_parameter(
        self,
        parameter_id: str,
        *,
        expression: str | None = None,
        unit: str | None = None,
        description: str | None = None,
    ) -> None:
        return self.parameters.update(
            parameter_id,
            expression=expression,
            unit=unit,
            description=description,
        )

    def delete_parameter(self, parameter_id: str) -> None:
        return self.parameters.delete(parameter_id)

    def create_sketch(self, name: str = "Main Sketch") -> str:
        return self.sketch.create_sketch(name)

    def delete_sketch(self) -> None:
        return self.sketch.delete_sketch()

    def create_sketch_point(self, x: str, y: str, name: str | None = None, visible: bool = True) -> str:
        return self.sketch.create_sketch_point(x, y, name=name, visible=visible)

    def move_sketch_point(self, point_id: str, x: str, y: str) -> None:
        return self.sketch.move_sketch_point(point_id, x, y)

    def create_sketch_line_segment(
        self,
        start_point_id: str,
        end_point_id: str,
        name: str | None = None,
    ) -> str:
        return self.sketch.create_sketch_line_segment(start_point_id, end_point_id, name=name)

    def create_sketch_circle(
        self,
        center_point_id: str,
        radius: str,
        name: str | None = None,
        edge_point_id: str | None = None,
    ) -> str:
        return self.sketch.create_sketch_circle(center_point_id, radius, name=name, edge_point_id=edge_point_id)

    def create_sketch_arc(
        self,
        point_a_id: str,
        point_b_id: str,
        point_c_id: str,
        name: str | None = None,
    ) -> str:
        return self.sketch.create_sketch_arc(point_a_id, point_b_id, point_c_id, name=name)

    def create_sketch_arc_by_center(
        self,
        cx: float, cy: float,
        sx: float, sy: float,
        ex: float, ey: float,
        name: str | None = None,
    ) -> str:
        return self.sketch.create_sketch_arc_by_center(cx, cy, sx, sy, ex, ey, name=name)

    def create_sketch_infinite_line(
        self,
        point_a_id: str,
        point_b_id: str,
        name: str | None = None,
    ) -> str:
        return self.sketch.create_sketch_infinite_line(point_a_id, point_b_id, name=name)

    def create_sketch_rectangle(
        self,
        corner_a: tuple[float, float],
        corner_b: tuple[float, float],
        name: str | None = None,
    ) -> list[str]:
        return self.sketch.create_sketch_rectangle(corner_a, corner_b, name=name)

    def move_sketch_point_with_solver(self, point_id: str, x: str, y: str) -> None:
        return self.sketch.move_sketch_point_with_solver(point_id, x, y)

    def toggle_sketch_construction(self, entity_ids: list[str] | set[str]) -> bool:
        return self.sketch.toggle_sketch_construction(entity_ids)

    def edit_distance_constraint_value(
        self,
        constraint_id: str,
        value: str,
        *,
        label_position: tuple[float, float] | None = None,
    ) -> None:
        return self.sketch.edit_distance_constraint_value(constraint_id, value, label_position=label_position)

    def apply_sketch_constraint_from_entities(
        self,
        constraint_type: str,
        entity_ids: list[str],
        value: str | None = None,
    ) -> str:
        return self.sketch.apply_sketch_constraint_from_entities(constraint_type, entity_ids, value=value)

    def create_sketch_constraint(
        self,
        constraint_type: str,
        references: list[str],
        value: str | None = None,
        name: str | None = None,
        entity_references: list[str] | None = None,
    ) -> str:
        return self.sketch.create_sketch_constraint(
            constraint_type, references, value=value, name=name, entity_references=entity_references,
        )

    def update_sketch_constraint(self, constraint_id: str, property_path: str, value: PropertyValueInput) -> None:
        return self.sketch.update_sketch_constraint(constraint_id, property_path, value)

    def delete_sketch_constraint(self, constraint_id: str) -> None:
        return self.sketch.delete_sketch_constraint(constraint_id)

    def solve_sketch(self) -> ValidationReport:
        return self.sketch.solve_sketch()

    def update_sketch_entity(self, entity_id: str, property_path: str, value: PropertyValueInput) -> None:
        return self.sketch.update_sketch_entity(entity_id, property_path, value)

    def delete_sketch_entity(self, entity_id: str) -> None:
        return self.sketch.delete_sketch_entity(entity_id)

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
            style=Style(),
        )
        body.markers.append(self._make_com_marker(body))
        project.model.bodies.append(body)
        self._invalidate_pose_state()
        return body.id

    def create_bar(self, name: str, start: MarkerInput, end: MarkerInput) -> str:
        return self.create_body(name=name, markers=[start, end], body_type=BodyType.BAR.value)

    def create_punctual_mass(self, name: str, x: str, y: str) -> str:
        return self.create_body(name=name, markers=[MarkerInput(x, y, "P")], body_type=BodyType.POINT_MASS.value)

    def create_ground_anchor(self, name: str, x: str, y: str) -> tuple[str, str]:
        """Create a PointMass body + rigid ground joint as one undo step.

        Returns (body_id, structural_marker_id).
        """
        project = self._require_project()
        self.validation_service.ensure_unique_name(project.model.bodies, name)
        with self._operation():
            body_id = self.create_body(name=name, markers=[MarkerInput(x, y, "P")], body_type=BodyType.POINT_MASS.value)
            body = next(b for b in project.model.bodies if b.id == body_id)
            structural = next(m for m in body.markers if m.type is MarkerType.STRUCTURAL)
            self.connect_marker_to_ground(structural.id, joint_type="rigid", name=f"Ground_{name}")
        return body_id, structural.id

    def get_marker_deletion_consequence(self, marker_id: str) -> str:
        """Returns 'to_bar', 'to_point_mass', or 'normal' for deleting a structural marker."""
        try:
            body = self._find_body_by_marker(marker_id)
        except ValueError:
            return "normal"
        marker = next((m for m in body.markers if m.id == marker_id), None)
        if marker is None or marker.type is not MarkerType.STRUCTURAL:
            return "normal"
        remaining = len(body.structural_markers()) - 1
        if remaining == 1:
            return "to_point_mass"
        if remaining == 2:
            return "to_bar"
        return "normal"

    def delete_structural_marker_convert_to_bar(self, marker_id: str) -> None:
        """Remove one structural marker from a 3-marker body and convert the result to a Bar."""
        project = self._require_project()
        body = self._find_body_by_marker(marker_id)
        if len(body.structural_markers()) != 3:
            raise ValueError("delete_structural_marker_convert_to_bar requires exactly 3 structural markers")
        self._snapshot()
        removed_joint_ids = {
            joint.id
            for joint in project.model.joints
            if joint.endpoint_a.marker_id == marker_id or joint.endpoint_b.marker_id == marker_id
        }
        body.markers = [m for m in body.markers if m.id != marker_id]
        body.edge_order = [mid for mid in body.edge_order if mid != marker_id]
        project.model.joints = [
            j for j in project.model.joints
            if j.endpoint_a.marker_id != marker_id and j.endpoint_b.marker_id != marker_id
        ]
        project.model.drivers = [
            d for d in project.model.drivers if d.target_joint_id not in removed_joint_ids
        ]
        project.model.sensors = [
            s for s in project.model.sensors if marker_id not in s.marker_ids
        ]
        project.model.loads = [
            load for load in project.model.loads if load.target_marker_id != marker_id
        ]
        body.type = BodyType.BAR
        body.closed_shape = False
        body.com_marker().metadata.values["position_percent"] = 50.0
        self._set_bar_com_from_percent(body, 50.0)
        self._invalidate_pose_state()

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
        self._sync_special_com_marker(body)
        self._invalidate_pose_state()
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
        self._invalidate_pose_state()
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
        self._validate_endpoint_input(endpoint_a, project)
        self._validate_endpoint_input(endpoint_b, project)
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
        self._entity_index = None
        self._invalidate_pose_state()
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
        self._invalidate_pose_state()

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
        self,
        marker_id: str,
        slider_id: str,
        joint_type: str = "revolute",
        name: str | None = None,
        align: str = "marker_to_slider",
    ) -> str:
        body = self._find_body_by_marker(marker_id)
        marker = self._find_entity(marker_id)
        slider = self._find_entity(slider_id)
        if not isinstance(marker, Marker):
            raise ValueError("connect_marker_to_slider requires a marker")
        if not isinstance(slider, Slider):
            raise ValueError("connect_marker_to_slider requires a slider")
        if align not in {"marker_to_slider", "slider_to_marker", "none"}:
            raise ValueError("align must be marker_to_slider, slider_to_marker, or none")
        joint_name = name or f"{marker_id}_{slider_id}"
        joint_enum = JointType(joint_type)
        endpoint_a = JointEndpointInput(JointEndpointKind.MARKER, body_id=body.id, marker_id=marker_id)
        endpoint_b = JointEndpointInput(JointEndpointKind.SLIDER, slider_id=slider_id)
        candidate = Joint(
            id="__candidate__",
            name=joint_name,
            type=joint_enum,
            endpoint_a=self._make_endpoint(endpoint_a),
            endpoint_b=self._make_endpoint(endpoint_b),
        )
        project = self._require_project()
        self.validation_service.ensure_unique_name(project.model.joints, joint_name)
        self._validate_endpoint_input(endpoint_a, project)
        self._validate_endpoint_input(endpoint_b, project)
        self._ensure_joint_not_duplicate(candidate)

        with self._operation():
            if align != "none":
                target_x, target_y = self._slider_center_mm(slider)
                self.move_marker(marker_id, self._mm_expression(target_x), self._mm_expression(target_y))
            return self.create_joint(
                name=joint_name,
                joint_type=joint_enum.value,
                endpoint_a=endpoint_a,
                endpoint_b=endpoint_b,
            )

    def rename_entity(self, entity_id: str, new_name: str) -> None:
        entity = self._find_entity(entity_id)
        self._validate_entity_name(entity, new_name)
        self._snapshot()
        self._rename_entity_no_snapshot(entity, new_name)

    def set_sketch_visible(self, visible: bool) -> None:
        return self.sketch.set_sketch_visible(visible)

    def update_parameter_definition(
        self,
        parameter_id: str,
        name: str,
        expression: str,
        unit: str,
        description: str = "",
    ) -> None:
        return self.parameters.update_definition(parameter_id, name, expression, unit, description)

    def move_marker(self, marker_id: str, x_expression: str, y_expression: str) -> None:
        marker = self._find_entity(marker_id)
        if not isinstance(marker, Marker):
            raise ValueError("move_marker requires a marker entity")
        body = self._find_body_by_marker(marker_id)
        if marker.type is MarkerType.COM:
            if body.type is BodyType.POINT_MASS:
                raise ValueError("CoM of a point mass cannot be moved independently")
            if body.type is BodyType.BAR:
                project = self._require_project()
                new_x = ScalarProperty(expression=x_expression, unit=marker.x.unit, expected_dimension=Dimension.LENGTH)
                new_y = ScalarProperty(expression=y_expression, unit=marker.y.unit, expected_dimension=Dimension.LENGTH)
                target_x_eval = self.expression_service.evaluate_property(new_x, project.parameters)
                target_y_eval = self.expression_service.evaluate_property(new_y, project.parameters)
                target_x = self.unit_service.convert(self.unit_service.quantity(target_x_eval.value, target_x_eval.unit), "mm")
                target_y = self.unit_service.convert(self.unit_service.quantity(target_y_eval.value, target_y_eval.unit), "mm")
                self._snapshot()
                self._set_bar_com_from_point(body, target_x, target_y)
                self._invalidate_pose_state()
                return
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
            moved_marker_ids = self._translate_direct_joint_counterparts(marker_id, linked_joints, delta_x, delta_y)
            for moved_marker_id in moved_marker_ids:
                try:
                    moved_body = self._find_body_by_marker(moved_marker_id)
                    self._sync_special_com_marker(moved_body)
                except ValueError:
                    pass
            self._invalidate_pose_state()
            return
        self._snapshot()
        marker.x = new_x
        marker.y = new_y
        self._sync_special_com_marker(body)
        self._invalidate_pose_state()

    def update_property(self, entity_id: str, property_path: str, value: PropertyValueInput) -> None:
        if entity_id == "__gravity__":
            self._update_gravity_property(property_path, value)
            return
        entity = self._find_entity(entity_id)
        if isinstance(entity, Marker) and entity.type is MarkerType.COM:
            body = self._find_body_by_marker(entity.id)
            if property_path in {"x", "y"}:
                if body.type is BodyType.POINT_MASS:
                    raise ValueError("CoM of a point mass cannot be moved independently")
                if body.type is BodyType.BAR:
                    raise ValueError("Bar CoM must be edited with position_percent or position_distance")
            if body.type is BodyType.BAR and property_path in {"position_percent", "position_distance"}:
                self._update_bar_com_property(body, property_path, value)
                return
        if isinstance(entity, Joint) and property_path in {"friction_coulomb", "friction_viscous", "friction_pin_radius"}:
            self._update_joint_friction_property(entity, property_path, value)
            return
        if isinstance(entity, Spring) and property_path in {"stiffness", "damping", "rest_value", "law"}:
            self.update_spring_property(entity.id, property_path, value)
            return
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
        if property_path in {"mass", "travel_min", "travel_max"} and value.kind == "null":
            self._snapshot()
            setattr(entity, property_path, None)
            return
        if property_path.startswith("style."):
            self._apply_style_update(entity, property_path, value)
            return
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

    def add_gravity(self) -> None:
        project = self._require_project()
        if project.model.gravity is not None:
            return
        self._snapshot()
        project.model.gravity = GravityLoad()

    def delete_gravity(self) -> None:
        project = self._require_project()
        if project.model.gravity is None:
            return
        self._snapshot()
        project.model.gravity = None

    def delete_entity(self, entity_id: str) -> None:
        if entity_id == "__gravity__":
            self.delete_gravity()
            return
        project = self._require_project()
        if project.sketch is not None and entity_id in project.sketch.entities:
            self.delete_sketch_entity(entity_id)
            return
        if project.sketch is not None and entity_id in project.sketch.constraints:
            self.delete_sketch_constraint(entity_id)
            return
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
            project.model.loads = [
                load for load in project.model.loads if load.target_marker_id not in marker_ids
            ]
            project.model.bodies = [item for item in project.model.bodies if item.id != entity_id]
            self._invalidate_pose_state()
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
            self._invalidate_pose_state()
            return
        if any(joint.id == entity_id for joint in project.model.joints):
            self._snapshot()
            project.model.joints = [item for item in project.model.joints if item.id != entity_id]
            project.model.drivers = [driver for driver in project.model.drivers if driver.target_joint_id != entity_id]
            self._invalidate_pose_state()
            return
        if any(driver.id == entity_id for driver in project.model.drivers):
            self._snapshot()
            project.model.drivers = [item for item in project.model.drivers if item.id != entity_id]
            self._cleanup_driver_velocities({entity_id})
            return
        if any(load.id == entity_id for load in project.model.loads):
            self._snapshot()
            project.model.loads = [item for item in project.model.loads if item.id != entity_id]
            return
        if any(sensor.id == entity_id for sensor in project.model.sensors):
            self._snapshot()
            project.model.sensors = [item for item in project.model.sensors if item.id != entity_id]
            return
        if any(spring.id == entity_id for spring in project.model.springs):
            self._snapshot()
            project.model.springs = [item for item in project.model.springs if item.id != entity_id]
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
        project.model.loads = [
            load for load in project.model.loads if load.target_marker_id != entity_id
        ]
        if len(body.structural_markers()) == 1:
            body.type = BodyType.POINT_MASS
            body.closed_shape = False
        elif body.type is BodyType.BODY and len(body.structural_markers()) == 2:
            body.closed_shape = True
        self._sync_special_com_marker(body)
        self._invalidate_pose_state()

    def validate_model(self, duration: float = 1.0, steps: int = 20) -> ValidationReport:
        project = self._require_project()
        report = self.validation_service.validate_project(project)
        self._kinematic_validator.validate_joint_geometry(project, report)
        self._kinematic_validator.validate_kinematic_reach(project, report, duration, steps)
        self._evaluate_all(project, report)
        self._validate_sketch_solve(project, report)
        return report

    def export_exudyn_script(self, duration: float = 1.0, steps: int = 100) -> str:
        project = self._require_project()
        if self.simulation_runner.backend_name() != "exudyn":
            raise RuntimeError("Export is only supported for the Exudyn backend")
        return self.simulation_runner.adapter.export_script(project, duration=duration, steps=steps)

    def run_kinematic_simulation(
        self,
        duration: float = 1.0,
        steps: int = 100,
        cancel_event=None,
        log_path=None,
    ) -> SimulationResult:
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
        project.reaction_outputs.clear()
        result = self.simulation_runner.run(
            project, duration=duration, steps=steps,
            cancel_event=cancel_event, log_path=log_path,
        )
        result.warnings = [*validation_messages, *result.warnings]
        result.messages = [*validation_messages, *result.messages]
        return result

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        if self.project is not None:
            self._redo_stack.append(copy.deepcopy(self.project))
        self.project = self._undo_stack.pop()
        self._entity_index = None
        self.poses.clear_current()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        if self.project is not None:
            self._undo_stack.append(copy.deepcopy(self.project))
        self.project = self._redo_stack.pop()
        self._entity_index = None
        self.poses.clear_current()
        return True

    def _require_project(self) -> Project:
        if self.project is None:
            raise ValueError("No active project")
        return self.project

    def _snapshot(self) -> None:
        if self.project is not None and not self._in_operation:
            self._undo_stack.append(copy.deepcopy(self.project))
            self._redo_stack.clear()
            self._entity_index = None
            self.sketch.invalidate_cache()

    def _invalidate_pose_state(self) -> None:
        """Drop pose data after a topology change that could leave stale refs.

        Poses reference body ids and driver ids; once the model topology
        changes we cannot guarantee they still describe a valid configuration,
        so we drop them and the user can re-solve from the reference pose.
        """
        self.poses.clear_current()
        if self.project is not None:
            self.project.poses = []
            self.project.simulation_initial_pose_id = None

    def _cleanup_driver_velocities(self, removed_driver_ids: set[str]) -> None:
        if not removed_driver_ids or self.project is None:
            return
        for pose in self.project.poses:
            for driver_id in list(pose.initial_velocities.keys()):
                if driver_id in removed_driver_ids:
                    pose.initial_velocities.pop(driver_id, None)

    def _operation(self):
        """Context manager that takes a single snapshot for the whole operation."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            self._snapshot()
            self._in_operation = True
            try:
                yield
            finally:
                self._in_operation = False

        return _ctx()

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
        project = self._require_project()
        x_vals = [self.expression_service.evaluate_property(m.x, project.parameters).value for m in structural]
        y_vals = [self.expression_service.evaluate_property(m.y, project.parameters).value for m in structural]
        x_avg = sum(x_vals) / len(x_vals) if x_vals else 0.0
        y_avg = sum(y_vals) / len(y_vals) if y_vals else 0.0
        com_marker = Marker(
            id=self.id_service.new("marker"),
            name="CoM",
            type=MarkerType.COM,
            x=self._scalar(self._mm_expression(x_avg), "mm", Dimension.LENGTH),
            y=self._scalar(self._mm_expression(y_avg), "mm", Dimension.LENGTH),
            visible=False,
        )
        if body.type is BodyType.BAR and len(structural) == 2:
            com_marker.metadata.values["position_percent"] = 50.0
        return com_marker

    def _scalar(self, expression: str, unit: str, dimension: Dimension) -> ScalarProperty:
        return ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension)

    def _mm_expression(self, value: float) -> str:
        return f"{value:.6g} mm"

    def _sync_all_special_com_markers(self) -> None:
        project = self.project
        if project is None:
            return
        for body in project.model.bodies:
            self._sync_special_com_marker(body)

    def _sync_special_com_marker(self, body: Body) -> None:
        com_marker = body.com_marker()
        structural = body.structural_markers()
        if body.type is BodyType.POINT_MASS and len(structural) == 1:
            base = structural[0]
            com_marker.x = self._scalar(base.x.expression, base.x.unit, Dimension.LENGTH)
            com_marker.y = self._scalar(base.y.expression, base.y.unit, Dimension.LENGTH)
            com_marker.metadata.values.pop("position_percent", None)
            return
        if body.type is BodyType.BAR and len(structural) == 2:
            self._set_bar_com_from_percent(body, self._bar_com_percent(body))

    def _bar_structural_data(self, body: Body) -> tuple[Marker, Marker, float, float, float, float]:
        if body.type is not BodyType.BAR or len(body.structural_markers()) != 2:
            raise ValueError("Bar CoM helpers require a bar with exactly two structural markers")
        first, second = body.structural_markers()
        project = self._require_project()
        x1 = self.expression_service.evaluate_property(first.x, project.parameters).value
        y1 = self.expression_service.evaluate_property(first.y, project.parameters).value
        x2 = self.expression_service.evaluate_property(second.x, project.parameters).value
        y2 = self.expression_service.evaluate_property(second.y, project.parameters).value
        return first, second, x1, y1, x2, y2

    def _bar_length(self, body: Body) -> float:
        _, _, x1, y1, x2, y2 = self._bar_structural_data(body)
        return math.hypot(x2 - x1, y2 - y1)

    def _bar_com_percent(self, body: Body) -> float:
        com_marker = body.com_marker()
        stored = com_marker.metadata.values.get("position_percent")
        if stored is not None:
            try:
                return max(0.0, min(100.0, float(stored)))
            except (TypeError, ValueError):
                pass
        _, _, x1, y1, x2, y2 = self._bar_structural_data(body)
        length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if length_sq <= 1e-12:
            return 0.0
        project = self._require_project()
        cx = self.expression_service.evaluate_property(com_marker.x, project.parameters).value
        cy = self.expression_service.evaluate_property(com_marker.y, project.parameters).value
        t = ((cx - x1) * (x2 - x1) + (cy - y1) * (y2 - y1)) / length_sq
        return max(0.0, min(100.0, t * 100.0))

    def _set_bar_com_from_percent(self, body: Body, percent: float) -> None:
        com_marker = body.com_marker()
        _, _, x1, y1, x2, y2 = self._bar_structural_data(body)
        clamped = max(0.0, min(100.0, percent))
        t = clamped / 100.0
        cx = x1 + t * (x2 - x1)
        cy = y1 + t * (y2 - y1)
        com_marker.x = self._scalar(self._mm_expression(cx), "mm", Dimension.LENGTH)
        com_marker.y = self._scalar(self._mm_expression(cy), "mm", Dimension.LENGTH)
        com_marker.metadata.values["position_percent"] = clamped

    def _set_bar_com_from_distance(self, body: Body, distance_mm: float) -> None:
        length = self._bar_length(body)
        if length <= 1e-12:
            self._set_bar_com_from_percent(body, 0.0)
            return
        clamped_distance = max(0.0, min(distance_mm, length))
        self._set_bar_com_from_percent(body, clamped_distance / length * 100.0)

    def _set_bar_com_from_point(self, body: Body, x: float, y: float) -> None:
        _, _, x1, y1, x2, y2 = self._bar_structural_data(body)
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            self._set_bar_com_from_percent(body, 0.0)
            return
        t = ((x - x1) * dx + (y - y1) * dy) / length_sq
        self._set_bar_com_from_percent(body, t * 100.0)

    def _update_bar_com_property(self, body: Body, property_path: str, value: PropertyValueInput) -> None:
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError("Bar CoM properties require an expression value")
        if property_path == "position_percent":
            try:
                percent = float(value.value.strip().replace(",", "."))
            except ValueError as exc:
                raise ValueError("position_percent must be a number between 0 and 100") from exc
            self._snapshot()
            self._set_bar_com_from_percent(body, percent)
            return
        scalar = self._scalar(value.value, "mm", Dimension.LENGTH)
        evaluated = self.expression_service.evaluate_property(scalar, self._require_project().parameters)
        self._snapshot()
        self._set_bar_com_from_distance(body, evaluated.value)

    def _normalize_angle_expression(self, expression: str) -> str:
        stripped = expression.strip()
        if self._PLAIN_NUMBER_RE.fullmatch(stripped):
            return f"{stripped} deg"
        return expression

    def _is_literal_expression(self, expression: str) -> bool:
        """Return True if expression is a plain number with optional unit (no parameters)."""
        cleaned = expression.strip()
        # Strip known unit suffixes
        for unit in ("mm", "m", "deg", "rad", "s"):
            if cleaned.endswith(unit):
                cleaned = cleaned[: -len(unit)].strip()
                break
        try:
            float(cleaned)
            return True
        except ValueError:
            return False

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

    def _build_entity_index(self) -> dict[str, object]:
        project = self._require_project()
        index: dict[str, object] = {}
        if project.sketch is not None:
            index[project.sketch.id] = project.sketch
            for entity in project.sketch.entities.values():
                index[entity.id] = entity
            for constraint in project.sketch.constraints.values():
                index[constraint.id] = constraint
        for collection in (
            project.model.bodies,
            project.model.joints,
            project.model.sliders,
            project.model.drivers,
            project.model.loads,
            project.model.sensors,
            project.model.springs,
            project.parameters,
        ):
            for entity in collection:
                index[entity.id] = entity
        for body in project.model.bodies:
            for marker in body.markers:
                index[marker.id] = marker
        return index

    def _find_entity(self, entity_id: str) -> object:
        if entity_id == "__gravity__":
            gravity = self._require_project().model.gravity
            if gravity is None:
                raise ValueError("No gravity in this project")
            return gravity
        if self._entity_index is None:
            self._entity_index = self._build_entity_index()
        entity = self._entity_index.get(entity_id)
        if entity is not None:
            return entity
        raise ValueError(f"Unknown entity: {entity_id}")

    # Public read-only query API -------------------------------------------------
    def get_entity(self, entity_id: str) -> object | None:
        """Return any entity by id, or None if not found."""
        if entity_id == "__gravity__":
            project = self.project
            return project.model.gravity if project else None
        if entity_id.startswith("__reaction__"):
            joint_id = entity_id[len("__reaction__"):]
            project = self.project
            return project.reaction_outputs.get(joint_id) if project else None
        try:
            return self._find_entity(entity_id)
        except ValueError:
            return None

    def get_body_by_marker(self, marker_id: str) -> Body | None:
        """Return the Body that owns the given marker, or None."""
        try:
            return self._find_body_by_marker(marker_id)
        except ValueError:
            return None

    def get_sketch_point(self, point_id: str) -> SketchPoint | None:
        """Return a sketch point by id, or None."""
        try:
            return self.sketch._find_sketch_point(point_id)
        except ValueError:
            return None

    def get_joint(self, joint_id: str) -> Joint | None:
        """Return a joint by id, or None."""
        try:
            return self._find_joint(joint_id)
        except ValueError:
            return None

    def get_body(self, body_id: str) -> Body | None:
        """Return a body by id, or None."""
        try:
            return self._find_body(body_id)
        except ValueError:
            return None

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
            "fx": Dimension.FORCE,
            "fy": Dimension.FORCE,
            "law": getattr(entity, "law", None).expected_dimension if isinstance(entity, Driver) else None,
        }
        if property_path not in dimension_map:
            raise ValueError(f"Unsupported property path: {property_path}")
        current = getattr(entity, property_path, None)
        unit = "deg" if property_path == "angle" else "kg" if property_path == "mass" else "N" if property_path in ("fx", "fy") else "mm"
        if current is not None and isinstance(current, ScalarProperty):
            unit = current.unit
        scalar = ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension_map[property_path])
        if property_path == "law":
            variables = {"t": self.unit_service.quantity(0.0, "s")}
        elif property_path in {"fx", "fy"}:
            variables = self._kinematic_validator.load_expression_variables(self._require_project(), time_value=0.0)
        else:
            variables = None
        self.expression_service.evaluate_property(scalar, self._require_project().parameters, variables=variables)
        return scalar

    def _assign_scalar_property(self, entity: object, property_path: str, scalar: ScalarProperty) -> None:
        setattr(entity, property_path, scalar)
        if isinstance(entity, Body) and property_path == "mass":
            value = self.expression_service.evaluate_property(scalar, self._require_project().parameters).value
            entity.com_marker().visible = value != 0

    def _rename_entity_no_snapshot(self, entity: object, new_name: str) -> None:
        entity.name = new_name

    def _update_gravity_property(self, path: str, value: PropertyValueInput) -> None:
        gravity = self._require_project().model.gravity
        if gravity is None:
            raise ValueError("No gravity in this project")
        if path not in {"magnitude", "direction_x", "direction_y"}:
            raise ValueError(f"Unknown gravity property: {path}")
        if value.kind != "expression":
            raise ValueError(f"Gravity {path} requires a numeric expression")
        try:
            float_val = float(value.value)
        except (ValueError, TypeError):
            raise ValueError(f"Gravity {path} must be a number, got: {value.value!r}")
        self._snapshot()
        setattr(gravity, path, float_val)

    def joint_friction_mode(self, joint: Joint) -> str | None:
        if joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER:
            return "translation"
        if joint.type is JointType.REVOLUTE:
            return "rotation"
        return None

    def joint_friction_values(self, joint: Joint) -> tuple[float, float]:
        coulomb = joint.metadata.values.get("friction_coulomb", 0.0)
        viscous = joint.metadata.values.get("friction_viscous", 0.0)
        try:
            return float(coulomb), float(viscous)
        except (TypeError, ValueError):
            return 0.0, 0.0

    def joint_friction_pin_radius(self, joint: Joint) -> float:
        r = joint.metadata.values.get("friction_pin_radius", 0.0)
        try:
            return float(r)
        except (TypeError, ValueError):
            return 0.0

    def _update_joint_friction_property(self, joint: Joint, path: str, value: PropertyValueInput) -> None:
        if self.joint_friction_mode(joint) is None:
            raise ValueError("This joint topology does not support friction")
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError(f"{path} requires a numeric value")
        if path == "friction_pin_radius":
            scalar = self._scalar(value.value, "mm", Dimension.LENGTH)
            result = self.expression_service.evaluate_property(scalar, self._require_project().parameters)
            numeric = result.value
        else:
            try:
                numeric = float(value.value.strip().replace(",", "."))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path} must be a number") from exc
        self._snapshot()
        joint.metadata.values[path] = numeric

    def _apply_style_update(self, entity: object, property_path: str, value: PropertyValueInput) -> None:
        field = property_path.split(".", 1)[1]
        expected_type = self._STYLE_FIELD_TYPES.get(field)
        if expected_type is None:
            raise ValueError(f"Unknown style field: {field}")
        if expected_type is bool and value.kind != "boolean":
            raise ValueError(f"Style field '{field}' requires a boolean value")
        if expected_type is str and value.kind != "expression":
            raise ValueError(f"Style field '{field}' requires a string/expression value")
        if expected_type is float and value.kind != "expression":
            raise ValueError(f"Style field '{field}' requires a numeric expression")
        if expected_type is float:
            try:
                float_value = float(value.value)
            except Exception:
                raise ValueError(f"Style field '{field}' requires a numeric value")
            self._snapshot()
            setattr(entity.style, field, float_value)
            return
        self._snapshot()
        setattr(entity.style, field, value.value)

    def _validate_entity_name(self, entity: object, new_name: str) -> None:
        project = self._require_project()
        if isinstance(entity, Sketch):
            return
        if isinstance(entity, (SketchPoint, SketchLineSegment, SketchCircle, SketchArc, SketchInfiniteLine)):
            self.sketch._validate_sketch_entity_name(new_name, entity.id)
        elif isinstance(entity, SketchConstraint):
            self.sketch._validate_sketch_constraint_name(new_name, entity.id)
        elif isinstance(entity, Body):
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

    # --- Sketch helper back-compat shims --------------------------------------
    # The following methods used to live on ApplicationService and are referenced
    # by canvas, main_window, and tests. They delegate to SketchCommands so the
    # external API remains stable while the implementation lives in one place.

    def _require_sketch(self, create_if_missing: bool = False) -> Sketch:
        return self.sketch._require_sketch(create_if_missing=create_if_missing)

    def _evaluate_sketch_expression(self, expression: Expression, parameters: list[Parameter]) -> float:
        return self.sketch._evaluate_sketch_expression(expression, parameters)

    def _find_sketch_entity(self, entity_id: str):
        return self.sketch._find_sketch_entity(entity_id)

    def _find_sketch_point(self, point_id: str) -> SketchPoint:
        return self.sketch._find_sketch_point(point_id)

    def _find_sketch_constraint(self, constraint_id: str) -> SketchConstraint:
        return self.sketch._find_sketch_constraint(constraint_id)

    def _apply_sketch_constraints(self, locked_point_ids: set[str], *, strict: bool = False):
        return self.sketch._apply_sketch_constraints(locked_point_ids, strict=strict)

    def _current_sketch_angle_degrees(self, vertex_id: str, arm1_id: str, arm2_id: str) -> float:
        return self.sketch._current_sketch_angle_degrees(vertex_id, arm1_id, arm2_id)

    def _current_sketch_constraint_label_position(self, constraint: SketchConstraint) -> tuple[float, float]:
        return self.sketch._current_sketch_constraint_label_position(constraint)

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

    def _validate_endpoint_input(self, endpoint: JointEndpointInput, project: Project) -> None:
        if endpoint.kind is JointEndpointKind.MARKER:
            if endpoint.body_id is None or endpoint.marker_id is None:
                raise ValueError("Marker endpoints require body_id and marker_id")
            body = None
            for b in project.model.bodies:
                if b.id == endpoint.body_id:
                    body = b
                    break
            if body is None:
                raise ValueError(f"Body not found: {endpoint.body_id}")
            marker = None
            for m in body.markers:
                if m.id == endpoint.marker_id:
                    marker = m
                    break
            if marker is None:
                raise ValueError(f"Marker not found: {endpoint.marker_id} in body {endpoint.body_id}")
            return
        if endpoint.kind is JointEndpointKind.SLIDER:
            if endpoint.slider_id is None:
                raise ValueError("Slider endpoints require slider_id")
            slider = None
            for s in project.model.sliders:
                if s.id == endpoint.slider_id:
                    slider = s
                    break
            if slider is None:
                raise ValueError(f"Slider not found: {endpoint.slider_id}")
            return
        if endpoint.kind is JointEndpointKind.GROUND:
            return
        raise ValueError(f"Unsupported endpoint kind: {endpoint.kind}")

    def _sync_id_service(self) -> None:
        project = self._require_project()
        self.id_service.observe(project.id)
        for parameter in project.parameters:
            self.id_service.observe(parameter.id)
        if project.sketch is not None:
            self.id_service.observe(project.sketch.id)
            for entity in project.sketch.entities.values():
                self.id_service.observe(entity.id)
            for constraint in project.sketch.constraints.values():
                self.id_service.observe(constraint.id)
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
        for sensor in project.model.sensors:
            self.id_service.observe(sensor.id)

    def _ensure_joint_not_duplicate(self, candidate: Joint) -> None:
        project = self._require_project()
        new_key = self.validation_service._joint_key(candidate)
        for joint in project.model.joints:
            if self.validation_service._joint_key(joint) == new_key:
                raise ValueError("Duplicate joint between the same endpoints")

    def _joint_has_slider(self, joint: Joint) -> bool:
        return joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER

    def _marker_slider_endpoints(self, joint: Joint) -> tuple[JointEndpoint | None, JointEndpoint | None]:
        marker_endpoint = None
        slider_endpoint = None
        for endpoint in (joint.endpoint_a, joint.endpoint_b):
            if endpoint.kind is JointEndpointKind.MARKER:
                marker_endpoint = endpoint
            elif endpoint.kind is JointEndpointKind.SLIDER:
                slider_endpoint = endpoint
        return marker_endpoint, slider_endpoint

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
    ) -> set[str]:
        # Direct-only: move immediate counterparts of marker_id, no BFS transitives
        moved_marker_ids: set[str] = {marker_id}
        moved_slider_ids: set[str] = set()
        for joint in joints:
            ep_a, ep_b = joint.endpoint_a, joint.endpoint_b
            counterpart_marker_id: str | None = None
            counterpart_slider_id: str | None = None
            if ep_a.kind is JointEndpointKind.MARKER and ep_a.marker_id == marker_id:
                if ep_b.kind is JointEndpointKind.MARKER:
                    counterpart_marker_id = ep_b.marker_id
                elif ep_b.kind is JointEndpointKind.SLIDER:
                    counterpart_slider_id = ep_b.slider_id
            elif ep_b.kind is JointEndpointKind.MARKER and ep_b.marker_id == marker_id:
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
        return moved_marker_ids

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
                self._invalidate_pose_state()
            return
        self._snapshot()
        slider.origin_x = new_x
        slider.origin_y = new_y
        moved_marker_ids: set[str] = set()
        self._translate_markers_linked_to_slider(slider.id, delta_x, delta_y, moved_marker_ids)
        self._invalidate_pose_state()

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
            self._invalidate_pose_state()
            return
        self._snapshot()
        slider.angle = new_angle
        for marker, marker_x, marker_y in marker_targets:
            self._set_marker_absolute_mm(marker, marker_x, marker_y)
        self._invalidate_pose_state()

    def update_slider_geometry(
        self,
        slider_id: str,
        origin_x: str | None = None,
        origin_y: str | None = None,
        angle: str | None = None,
        travel_min: str | None = None,
        travel_max: str | None = None,
    ) -> None:
        """Atomically update all slider geometry properties in a single snapshot."""
        slider = self._find_entity(slider_id)
        if not isinstance(slider, Slider):
            raise ValueError("update_slider_geometry requires a slider entity")

        old_ox = self._evaluate_scalar_as(slider.origin_x, "mm")
        old_oy = self._evaluate_scalar_as(slider.origin_y, "mm")
        old_angle = self._evaluate_scalar_as(slider.angle, "rad")
        old_axis = (math.cos(old_angle), math.sin(old_angle))

        new_ox = self._evaluate_scalar_as(
            ScalarProperty(expression=origin_x, unit=slider.origin_x.unit, expected_dimension=Dimension.LENGTH), "mm"
        ) if origin_x is not None else old_ox
        new_oy = self._evaluate_scalar_as(
            ScalarProperty(expression=origin_y, unit=slider.origin_y.unit, expected_dimension=Dimension.LENGTH), "mm"
        ) if origin_y is not None else old_oy
        new_angle = self._evaluate_scalar_as(
            ScalarProperty(expression=angle, unit=slider.angle.unit, expected_dimension=Dimension.ANGLE), "rad"
        ) if angle is not None else old_angle
        new_axis = (math.cos(new_angle), math.sin(new_angle))

        changed = (
            (origin_x is not None and slider.origin_x.expression != origin_x)
            or (origin_y is not None and slider.origin_y.expression != origin_y)
            or (angle is not None and slider.angle.expression != angle)
            or (travel_min is not None and (
                (slider.travel_min is None and travel_min != "")
                or (slider.travel_min is not None and slider.travel_min.expression != travel_min)
            ))
            or (travel_max is not None and (
                (slider.travel_max is None and travel_max != "")
                or (slider.travel_max is not None and slider.travel_max.expression != travel_max)
            ))
        )

        linked_markers = self._markers_linked_to_slider(slider.id)
        marker_targets: list[tuple[Marker, float, float]] = []
        for marker in linked_markers:
            mx = self._evaluate_scalar_as(marker.x, "mm")
            my = self._evaluate_scalar_as(marker.y, "mm")
            slider_coordinate = (mx - old_ox) * old_axis[0] + (my - old_oy) * old_axis[1]
            marker_targets.append((
                marker,
                new_ox + slider_coordinate * new_axis[0],
                new_oy + slider_coordinate * new_axis[1],
            ))

        if not changed and not marker_targets:
            return

        self._snapshot()
        if origin_x is not None:
            slider.origin_x = ScalarProperty(
                expression=origin_x, unit=slider.origin_x.unit, expected_dimension=Dimension.LENGTH
            )
        if origin_y is not None:
            slider.origin_y = ScalarProperty(
                expression=origin_y, unit=slider.origin_y.unit, expected_dimension=Dimension.LENGTH
            )
        if angle is not None:
            slider.angle = ScalarProperty(
                expression=angle, unit=slider.angle.unit, expected_dimension=Dimension.ANGLE
            )
        if travel_min is not None:
            if travel_min == "" or travel_min.lower() == "none":
                slider.travel_min = None
            else:
                slider.travel_min = ScalarProperty(
                    expression=travel_min, unit="mm", expected_dimension=Dimension.LENGTH
                )
        if travel_max is not None:
            if travel_max == "" or travel_max.lower() == "none":
                slider.travel_max = None
            else:
                slider.travel_max = ScalarProperty(
                    expression=travel_max, unit="mm", expected_dimension=Dimension.LENGTH
                )
        for marker, marker_x, marker_y in marker_targets:
            self._set_marker_absolute_mm(marker, marker_x, marker_y)
        self._invalidate_pose_state()

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

    def _slider_center_mm(self, slider: Slider) -> tuple[float, float]:
        return self._evaluate_scalar_as(slider.origin_x, "mm"), self._evaluate_scalar_as(slider.origin_y, "mm")

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

    _OFFSET_RE = re.compile(r'^\((.*)\)\s+([+-])\s+([\d.]+)\s+(mm|m|deg|rad)$')

    def _strip_offset(self, expression: str) -> str:
        """Undo the outermost offset wrapper added by _offset_expression."""
        match = self._OFFSET_RE.match(expression.strip())
        if not match:
            return expression.strip()
        return match.group(1).strip()

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
        for load in project.model.loads:
            for component_name, component in (("Fx", load.fx), ("Fy", load.fy)):
                try:
                    self.expression_service.evaluate_property(
                        component,
                        project.parameters,
                        variables=self._kinematic_validator.load_expression_variables(project, time_value=0.0),
                    )
                except Exception as exc:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "load_evaluation",
                            f"Load {load.name} {component_name}: {exc}",
                            load.id,
                        )
                    )
        if project.sketch is not None:
            for entity in project.sketch.entities.values():
                if isinstance(entity, SketchPoint):
                    for prop in (entity.x, entity.y):
                        try:
                            self.sketch._evaluate_sketch_expression(prop, project.parameters)
                        except Exception as exc:
                            report.messages.append(
                                ValidationMessage(
                                    "warning",
                                    "sketch_property_evaluation",
                                    f"Sketch point {entity.name}: {exc}",
                                    entity.id,
                                )
                            )
                elif isinstance(entity, SketchCircle):
                    try:
                        radius = self.sketch._evaluate_sketch_expression(entity.radius, project.parameters)
                        if radius <= 0:
                            report.messages.append(
                                ValidationMessage(
                                    "warning",
                                    "invalid_sketch_radius",
                                    f"Sketch circle {entity.name}: radius must be positive",
                                    entity.id,
                                )
                            )
                    except Exception as exc:
                        report.messages.append(
                            ValidationMessage(
                                "warning",
                                "sketch_property_evaluation",
                                f"Sketch circle {entity.name}: {exc}",
                                entity.id,
                            )
                        )
            for constraint in project.sketch.constraints.values():
                if constraint.value is None:
                    continue
                try:
                    self.expression_service.evaluate_property(constraint.value, project.parameters)
                except Exception as exc:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "sketch_constraint_evaluation",
                            f"Sketch constraint {constraint.name}: {exc}",
                            constraint.id,
                        )
                    )

    def _validate_sketch_solve(self, project: Project, report: ValidationReport) -> None:
        if project.sketch is None or not project.sketch.constraints:
            return
        result = self.sketch_solver.solve(copy.deepcopy(project), locked_point_ids=set())
        if not result.success:
            report.messages.append(
                ValidationMessage(
                    "warning",
                    "sketch_not_solved",
                    result.message or "Sketch solver did not converge",
                    project.sketch.id,
                )
            )

    def create_sensor(self, name: str, sensor_type: str, marker_ids: list[str]) -> str:
        return self.forces.create_sensor(name, sensor_type, marker_ids)

    def delete_sensor(self, sensor_id: str) -> None:
        self.forces.delete_sensor(sensor_id)

    def rename_sensor(self, sensor_id: str, name: str) -> None:
        self.forces.rename_sensor(sensor_id, name)

    def create_load(self, name: str, marker_id: str, fx_expression: str, fy_expression: str) -> str:
        return self.forces.create_load(name, marker_id, fx_expression, fy_expression)

    def delete_load(self, load_id: str) -> None:
        self.forces.delete_load(load_id)

    def rename_load(self, load_id: str, name: str) -> None:
        self.forces.rename_load(load_id, name)

    def update_load_property(self, load_id: str, property_path: str, expression: str) -> None:
        self.forces.update_load_property(load_id, property_path, expression)

    # ------------------------------------------------------------------ springs

    def create_spring(
        self,
        name: str,
        spring_type: str,
        endpoint_a: SpringEndpoint,
        endpoint_b: SpringEndpoint,
    ) -> str:
        return self.forces.create_spring(name, spring_type, endpoint_a, endpoint_b)

    def delete_spring(self, spring_id: str) -> None:
        self.forces.delete_spring(spring_id)

    def rename_spring(self, spring_id: str, name: str) -> None:
        self.forces.rename_spring(spring_id, name)

    def get_spring(self, spring_id: str) -> Spring:
        return self.forces.get_spring(spring_id)

    def spring_stiffness(self, spring: Spring) -> float:
        return self.forces.spring_stiffness(spring)

    def spring_damping(self, spring: Spring) -> float:
        return self.forces.spring_damping(spring)

    def update_spring_property(self, spring_id: str, property_path: str, value: "PropertyValueInput") -> None:
        self.forces.update_spring_property(spring_id, property_path, value)

    def _require_spring(self, spring_id: str) -> Spring:
        return self.forces._require_spring(spring_id)
