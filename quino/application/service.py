from __future__ import annotations

import copy

from quino.domain.inputs import JointEndpointInput, MarkerInput, PropertyValueInput, SliderInput
from quino.domain.model import (
    Body,
    Driver,
    Expression,
    Joint,
    Load,
    Marker,
    Metadata,
    Model,
    Parameter,
    Project,
    Pose,
    ScalarProperty,
    SimulationResult,
    Sketch,
    SketchConstraint,
    SketchCircle,
    SketchPoint,
    Spring,
    SpringEndpoint,
    ValidationMessage,
    ValidationReport,
    ViewState,
)
from quino.application._context import ServiceContext
from quino.application.commands.parameter_commands import ParameterCommands
from quino.application.commands.force_commands import ForceCommands
from quino.application.commands.pose_commands import PoseCommands
from quino.application.commands.sketch_commands import SketchCommands
from quino.application.commands.body_commands import BodyCommands
from quino.application.commands.joint_commands import JointCommands
from quino.application.commands.entity_commands import EntityCommands
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
from quino.solver_adapters.exudyn_adapter import ExudynAdapter
from quino.solver_adapters.exudyn_pose_adapter import ExudynPoseAdapter


class ApplicationService:
    schema_version = "0.1.0"

    def __init__(self, *, sketch_solver_backend: str = "legacy") -> None:
        self.id_service = IdService()
        self.unit_service = UnitService()
        self.expression_service = ExpressionService(self.unit_service)
        self.validation_service = ValidationService()
        self.json_mapper = JsonMapper()
        self.project: Project | None = None
        self._undo_stack: list[Project] = []
        self._redo_stack: list[Project] = []
        self._in_operation = False
        self._sketch_solver_backend = sketch_solver_backend
        self.sketch_solver = SketchSolver(
            self.expression_service,
            self.unit_service,
            backend=sketch_solver_backend,
        )
        self.simulation_runner = SimulationRunner(ExudynAdapter(self.expression_service))
        self.pose_runner = PoseRunner(ExudynPoseAdapter(self.expression_service))
        self._kinematic_validator = KinematicValidator(
            self.simulation_runner.adapter.assembler,
            self.expression_service,
            self.unit_service,
        )
        # Build command-services. The ServiceContext callables that depend on command-services
        # are wired after construction (see "Rewire" block below).
        _unset: object = None  # type: ignore[assignment]
        self._service_context = ServiceContext(
            project_provider=lambda: self.project,
            operation=self._operation,
            snapshot=self._snapshot,
            invalidate_pose_state=self._invalidate_pose_state,
            ids=self.id_service,
            expressions=self.expression_service,
            units=self.unit_service,
            validation=self.validation_service,
            find_entity=_unset,
            sync_all_special_com_markers=_unset,
            load_expression_variables=self._kinematic_validator.load_expression_variables,
            build_validated_scalar_property=_unset,
            assign_scalar_property=_unset,
            apply_style_update=_unset,
            connect_marker_to_ground=self.connect_marker_to_ground,
            joints_for_marker=_unset,
            translate_direct_joint_counterparts=_unset,
        )
        self.parameters = ParameterCommands(self._service_context)
        self.forces = ForceCommands(self._service_context)
        self.poses = PoseCommands(self._service_context, self.pose_runner)
        self.sketch = SketchCommands(self._service_context, self.sketch_solver)
        self.bodies = BodyCommands(self._service_context)
        self.joints = JointCommands(self._service_context)
        self.entities = EntityCommands(
            self._service_context,
            bodies=self.bodies,
            joints=self.joints,
            sketch=self.sketch,
            forces=self.forces,
            parameters=self.parameters,
            poses=self.poses,
        )
        # Rewire context callables to their canonical implementations
        self._service_context.find_entity = self.entities._find_entity
        self._service_context.sync_all_special_com_markers = self.bodies.sync_all_special_com_markers
        self._service_context.connect_marker_to_ground = self.joints.connect_marker_to_ground
        self._service_context.joints_for_marker = self.joints._joints_for_marker
        self._service_context.translate_direct_joint_counterparts = self.joints._translate_direct_joint_counterparts
        self._service_context.build_validated_scalar_property = self.entities._build_validated_scalar_property
        self._service_context.assign_scalar_property = self.entities._assign_scalar_property
        self._service_context.apply_style_update = self.entities._apply_style_update

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
        return self.bodies.create_body(name, markers, body_type)

    def create_bar(self, name: str, start: MarkerInput, end: MarkerInput) -> str:
        return self.bodies.create_bar(name, start, end)

    def create_punctual_mass(self, name: str, x: str, y: str) -> str:
        return self.bodies.create_punctual_mass(name, x, y)

    def create_ground_anchor(self, name: str, x: str, y: str) -> tuple[str, str]:
        return self.bodies.create_ground_anchor(name, x, y)

    def get_marker_deletion_consequence(self, marker_id: str) -> str:
        return self.bodies.get_marker_deletion_consequence(marker_id)

    def delete_structural_marker_convert_to_bar(self, marker_id: str) -> None:
        return self.bodies.delete_structural_marker_convert_to_bar(marker_id)

    def add_marker_to_body(self, body_id: str, marker: MarkerInput) -> str:
        return self.bodies.add_marker_to_body(body_id, marker)

    def add_marker_to_body_at(
        self, body_id: str, x_expression: str, y_expression: str, name: str | None = None
    ) -> str:
        return self.bodies.add_marker_to_body_at(body_id, x_expression, y_expression, name)

    def create_slider(self, name: str, slider: SliderInput) -> str:
        return self.joints.create_slider(name, slider)

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
        return self.joints.create_slider_from_points(name, start_x, start_y, end_x, end_y, travel_min, travel_max)

    def create_joint(
        self,
        name: str,
        joint_type: str,
        endpoint_a: JointEndpointInput,
        endpoint_b: JointEndpointInput,
    ) -> str:
        return self.joints.create_joint(name, joint_type, endpoint_a, endpoint_b)

    def create_rigid_joint(
        self,
        name: str,
        endpoint_a: JointEndpointInput,
        endpoint_b: JointEndpointInput,
    ) -> str:
        return self.joints.create_rigid_joint(name, endpoint_a, endpoint_b)

    def create_driver(self, name: str, driver_type: str, target_joint_id: str, expression: str, unit: str) -> str:
        return self.joints.create_driver(name, driver_type, target_joint_id, expression, unit)

    def set_joint_type(self, joint_id: str, joint_type: str) -> None:
        return self.joints.set_joint_type(joint_id, joint_type)

    def connect_marker_to_ground(
        self, marker_id: str, joint_type: str = "revolute", name: str | None = None
    ) -> str:
        return self.joints.connect_marker_to_ground(marker_id, joint_type, name)

    def connect_marker_to_slider(
        self,
        marker_id: str,
        slider_id: str,
        joint_type: str = "revolute",
        name: str | None = None,
        align: str = "marker_to_slider",
    ) -> str:
        return self.joints.connect_marker_to_slider(marker_id, slider_id, joint_type, name, align)

    def rename_entity(self, entity_id: str, new_name: str) -> None:
        return self.entities.rename_entity(entity_id, new_name)

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
        return self.bodies.move_marker(marker_id, x_expression, y_expression)

    def update_property(self, entity_id: str, property_path: str, value: PropertyValueInput) -> None:
        return self.entities.update_property(entity_id, property_path, value)

    def add_gravity(self) -> None:
        return self.entities.add_gravity()

    def delete_gravity(self) -> None:
        return self.entities.delete_gravity()

    def delete_entity(self, entity_id: str) -> None:
        return self.entities.delete_entity(entity_id)

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
        self.entities.invalidate_index()
        self.poses.clear_current()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        if self.project is not None:
            self._undo_stack.append(copy.deepcopy(self.project))
        self.project = self._redo_stack.pop()
        self.entities.invalidate_index()
        self.poses.clear_current()
        return True

    def set_sketch_solver_backend(self, name: str) -> None:
        """Switch the sketch solver backend at runtime (e.g. from Preferences dialog)."""
        if name not in ("solvespace", "legacy"):
            raise ValueError(f"Unknown sketch solver backend: {name!r}")
        self._sketch_solver_backend = name
        self.sketch_solver = SketchSolver(
            self.expression_service,
            self.unit_service,
            backend=name,
        )

    def _require_project(self) -> Project:
        if self.project is None:
            raise ValueError("No active project")
        return self.project

    def _snapshot(self) -> None:
        if self.project is not None and not self._in_operation:
            self._undo_stack.append(copy.deepcopy(self.project))
            self._redo_stack.clear()
            self.entities.invalidate_index()
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

    def _sync_all_special_com_markers(self) -> None:
        return self.bodies.sync_all_special_com_markers()

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

    def _find_joint(self, joint_id: str) -> Joint:
        return self.joints._find_joint(joint_id)

    def _find_entity(self, entity_id: str) -> object:
        return self.entities._find_entity(entity_id)

    # Public read-only query API -------------------------------------------------
    def get_entity(self, entity_id: str) -> object | None:
        """Return any entity by id, or None if not found."""
        return self.entities.get_entity(entity_id)

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

    def joint_friction_mode(self, joint: Joint) -> str | None:
        return self.joints.joint_friction_mode(joint)

    def joint_friction_values(self, joint: Joint) -> tuple[float, float]:
        return self.joints.joint_friction_values(joint)

    def joint_friction_pin_radius(self, joint: Joint) -> float:
        return self.joints.joint_friction_pin_radius(joint)

    # --- Sketch helper back-compat shims --------------------------------------
    # The following methods used to live on ApplicationService and are referenced
    # by canvas, main_window, and tests. They delegate to SketchCommands so the
    # external API remains stable while the implementation lives in one place.

    def _evaluate_sketch_expression(self, expression: Expression, parameters: list[Parameter]) -> float:
        return self.sketch._evaluate_sketch_expression(expression, parameters)

    def _find_sketch_entity(self, entity_id: str):
        return self.sketch._find_sketch_entity(entity_id)

    def _find_sketch_point(self, point_id: str) -> SketchPoint:
        return self.sketch._find_sketch_point(point_id)

    def _find_sketch_constraint(self, constraint_id: str) -> SketchConstraint:
        return self.sketch._find_sketch_constraint(constraint_id)

    def _current_sketch_angle_degrees(self, vertex_id: str, arm1_id: str, arm2_id: str) -> float:
        return self.sketch._current_sketch_angle_degrees(vertex_id, arm1_id, arm2_id)

    def _current_sketch_constraint_label_position(self, constraint: SketchConstraint) -> tuple[float, float]:
        return self.sketch._current_sketch_constraint_label_position(constraint)

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

    def update_slider_geometry(
        self,
        slider_id: str,
        origin_x: str | None = None,
        origin_y: str | None = None,
        angle: str | None = None,
        travel_min: str | None = None,
        travel_max: str | None = None,
    ) -> None:
        return self.joints.update_slider_geometry(slider_id, origin_x, origin_y, angle, travel_min, travel_max)

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

