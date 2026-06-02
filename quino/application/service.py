from __future__ import annotations

import copy
import threading
from pathlib import Path

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
from quino.domain.workspace import Workspace, Case, create_default_pose
from quino.application._context import ServiceContext
from quino.application.commands.parameter_commands import ParameterCommands
from quino.application.commands.force_commands import ForceCommands
from quino.application.commands.pose_commands import PoseCommands
from quino.application.commands.sketch_commands import SketchCommands
from quino.application.commands.body_commands import BodyCommands
from quino.application.commands.joint_commands import JointCommands
from quino.application.commands.entity_commands import EntityCommands
from quino.application.commands.workspace_commands import WorkspaceCommands
from quino.application.commands.block_commands import BlockCommands
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
from quino.services.case_cascading import CascadingEngine


class ApplicationService:
    schema_version = "0.4.0"

    def __init__(self) -> None:
        self.id_service = IdService()
        self.unit_service = UnitService()
        self.expression_service = ExpressionService(self.unit_service)
        self.validation_service = ValidationService()
        self.json_mapper = JsonMapper()
        # New domain state: Workspace replaces Project
        self._workspace: Workspace | None = None
        # Back-compat alias so old code that reads self.project still works.
        # Reads from self._workspace via the property below.
        self.current_workspace_path: Path | None = None
        self.executor = None
        self.pending_run_handles: dict[str, object] = {}
        self.workspace_lock = threading.Lock()
        # Scratch directory used to persist run artefacts when the project
        # hasn't been saved yet, so the GUI can still play back a freshly
        # computed simulation. Lazily created on first use and cleaned up
        # when the process exits.
        self._scratch_dir: Path | None = None
        self._undo_stack: list[Workspace] = []
        self._redo_stack: list[Workspace] = []
        self._in_operation = False
        self._structural_case_warning_acknowledged: bool = False
        self.sketch_solver = SketchSolver(
            self.expression_service,
            self.unit_service,
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
            workspace_provider=lambda: self._workspace,
            current_case_provider=self.current_case,
            cascade_provider=lambda: CascadingEngine(self._workspace) if self._workspace else None,
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
        # WorkspaceCommands is stored under _workspace_cmds; the `workspace`
        # property below forwards to it for backward compatibility with GUI
        # and test code that calls app_service.workspace.create_case(...).
        self._workspace_cmds = WorkspaceCommands(self._service_context)
        self.blocks = BlockCommands(self._service_context)
        # Rewire context callables to their canonical implementations
        self._service_context.find_entity = self.entities._find_entity
        self._service_context.sync_all_special_com_markers = self.bodies.sync_all_special_com_markers
        self._service_context.connect_marker_to_ground = self.joints.connect_marker_to_ground
        self._service_context.set_current_pose_id = self.poses.set_current_pose_id
        self._service_context.joints_for_marker = self.joints._joints_for_marker
        self._service_context.translate_direct_joint_counterparts = self.joints._translate_direct_joint_counterparts
        self._service_context.build_validated_scalar_property = self.entities._build_validated_scalar_property
        self._service_context.assign_scalar_property = self.entities._assign_scalar_property
        self._service_context.apply_style_update = self.entities._apply_style_update

    # ------------------------------------------------------------------ workspace property (back-compat)

    @property
    def workspace(self):
        """Backward-compat property: returns WorkspaceCommands so GUI code like
        ``app_service.workspace.create_case(...)`` continues to work.
        New code should use ``app_service._workspace`` for the domain object
        or ``app_service.current_case()`` for the active case.
        """
        return self._workspace_cmds

    @workspace.setter
    def workspace(self, value):
        # Tolerate direct assignment from old init-style code (e.g. tests that do
        # ``svc.workspace = WorkspaceCommands(...)``).
        if isinstance(value, WorkspaceCommands):
            self._workspace_cmds = value
        else:
            # Treat as domain Workspace assignment (migration path)
            self._workspace = value

    # ------------------------------------------------------------------ project property (back-compat)

    @property
    def project(self):
        """Backward-compat: returns a _WorkspaceProjectProxy so old command-service
        code that reads ``self.project.model``, ``self.project.parameters``, etc.
        continues to work.  Mutations go through the underlying Case/Workspace.
        """
        from quino.application._context import _WorkspaceProjectProxy
        if self._workspace is None:
            return None
        return _WorkspaceProjectProxy(self._workspace, case=self.current_case())

    @project.setter
    def project(self, value):
        # Some old code does ``self.project = ...``. If it's a Project-like
        # object we silently ignore (migration), if it's None we clear workspace.
        if value is None:
            self._workspace = None

    # ------------------------------------------------------------------ current_project_path (back-compat)

    @property
    def current_project_path(self) -> Path | None:
        return self.current_workspace_path

    @current_project_path.setter
    def current_project_path(self, value) -> None:
        self.current_workspace_path = value

    # ------------------------------------------------------------------ new API

    def current_case(self) -> Case | None:
        """Return the currently selected Case, or None if no workspace is loaded."""
        if self._workspace is None or self._workspace.selected_case_id is None:
            return None
        return self._workspace.cases.get(self._workspace.selected_case_id)

    def new_workspace(self, name: str = "Untitled") -> Workspace:
        self.id_service = IdService()
        self._service_context.ids = self.id_service
        root_id = self.id_service.new("case")
        ws_id = self.id_service.new("ws")
        default_pose = create_default_pose(self.id_service.new("pose"))
        root = Case(id=root_id, name="Root", model=Model(), poses=[default_pose])
        self._workspace = Workspace(
            id=ws_id,
            name=name,
            schema_version=self.schema_version,
            root_case_ids=[root_id],
            cases={root_id: root},
            selected_case_id=root_id,
        )
        self.current_workspace_path = None
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.poses.clear_current()
        self._structural_case_warning_acknowledged = False
        return self._workspace

    def load_workspace(self, path) -> Workspace:
        from pathlib import Path as _Path
        self._workspace = self.json_mapper.load(path)
        if self._workspace is not None:
            version = getattr(self._workspace, "schema_version", "0.0.0")
            if version != self.schema_version:
                raise ValueError(
                    f"This workspace uses schema {version!r}; QUINO expects {self.schema_version!r}. "
                    f"Rebuild the file (no auto-migration is provided)."
                )
        self.current_workspace_path = _Path(path)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.poses.clear_current()
        self._structural_case_warning_acknowledged = False
        self.id_service = IdService()
        self._service_context.ids = self.id_service
        self._sync_id_service()
        self._dedupe_pose_and_analysis_ids()
        self._sync_all_special_com_markers()
        self._ensure_default_poses()
        case = self.current_case()
        if case is not None and self._workspace is not None and self._workspace.sketch is not None:
            self._workspace.sketch.solve_error = None
            self.sketch._apply_sketch_constraints(set())
        return self._workspace

    def save_workspace(self, path=None) -> None:
        if self._workspace is None:
            raise RuntimeError("No workspace loaded")
        target = path or self.current_workspace_path
        if target is None:
            raise RuntimeError("No save path specified")
        self.json_mapper.save(self._workspace, target)
        self.current_workspace_path = Path(target)

    # ------------------------------------------------------------------ back-compat aliases
    # These delegate to the new workspace-oriented methods. They will be removed in Task 25.

    def new_project(self, name: str = "Untitled"):
        return self.new_workspace(name)

    def load_project(self, path: str):
        return self.load_workspace(path)

    def _ensure_baseline(self) -> None:
        """No-op: baseline concept removed in case-as-model redesign."""
        pass

    @property
    def structural_case_warning_acknowledged(self) -> bool:
        return self._structural_case_warning_acknowledged

    def acknowledge_structural_case_warning(self) -> None:
        self._structural_case_warning_acknowledged = True

    def save_project(self, path: str) -> None:
        self.save_workspace(path)

    @property
    def current_project_dir(self) -> Path | None:
        if self.current_project_path is None:
            # Fall back to a per-session scratch directory so runners can
            # still persist artefacts (and the GUI can play them back) for
            # an Untitled project the user hasn't saved yet.
            return self._ensure_scratch_dir()
        return self.current_project_path.parent if self.current_project_path.suffix else self.current_project_path

    def _ensure_scratch_dir(self) -> Path:
        """Create (once) and return a process-lifetime scratch directory for
        artefacts of unsaved projects. The directory is registered with
        `atexit` so it disappears when QUINO closes."""
        if self._scratch_dir is not None and self._scratch_dir.exists():
            return self._scratch_dir
        import atexit
        import shutil
        import tempfile
        path = Path(tempfile.mkdtemp(prefix="quino_unsaved_"))
        self._scratch_dir = path
        atexit.register(lambda p=path: shutil.rmtree(p, ignore_errors=True))
        return path

    def ensure_executor(self):
        from quino.services.run_executor import RunExecutor

        if self.executor is None:
            self.executor = RunExecutor(self)
        return self.executor

    @property
    def display_project(self):
        """The effective project for UI display: returns a proxy over the active case."""
        return self.project  # project property already returns a _WorkspaceProjectProxy

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
        rollback_on_failure: bool = False,
    ) -> str:
        return self.sketch.create_sketch_constraint(
            constraint_type,
            references,
            value=value,
            name=name,
            entity_references=entity_references,
            rollback_on_failure=rollback_on_failure,
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

    def create_free_ground(self, name: str, x: str, y: str) -> tuple[str, str]:
        return self.bodies.create_free_ground(name, x, y)

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

    def run_analysis(self, analysis_id: str):
        """Dispatch an Analysis to the appropriate runner and return an AnalysisResult."""
        from quino.analysis.registry import get_runner_for_type
        from quino.analysis.runner import AnalysisResult

        ws = self._workspace
        if ws is None:
            return AnalysisResult(
                analysis_id=analysis_id,
                analysis_type="dynamic",
                status="failed",
                error_message="No workspace",
            )
        # Find the analysis across all cases in the workspace
        analysis = None
        target_case = None
        for case in ws.cases.values():
            found = next((a for a in case.analyses if a.id == analysis_id), None)
            if found is not None:
                analysis = found
                target_case = case
                break
        if analysis is None:
            return AnalysisResult(
                analysis_id=analysis_id,
                analysis_type="dynamic",
                status="failed",
                error_message=f"Analysis {analysis_id!r} not found",
            )
        # Use the case model directly — no compose_project needed in new domain
        try:
            runner = get_runner_for_type(analysis.analysis_type)
            from quino.application._context import _WorkspaceProjectProxy
            composed = _WorkspaceProjectProxy(ws, case=target_case)
            errors = runner.validate(composed, analysis)
            if errors:
                return AnalysisResult(
                    analysis_id=analysis_id,
                    analysis_type=analysis.analysis_type,
                    status="failed",
                    error_message="; ".join(errors),
                )
            initial_pose = None
            if getattr(analysis, "pose_id", None):
                candidate = next(
                    (pose for pose in target_case.poses if pose.id == analysis.pose_id),
                    None,
                )
                if candidate is not None:
                    from quino.pose.geometry import create_reference_pose
                    initial_pose = create_reference_pose(
                        composed,
                        pose_id=candidate.id,
                        name=candidate.name,
                    )
                    initial_pose.metadata = copy.deepcopy(candidate.metadata)
                    initial_pose.initial_velocities = dict(candidate.initial_velocities)
                    for body_id, body_pose in candidate.body_poses.items():
                        initial_pose.body_poses[body_id] = copy.deepcopy(body_pose)
            return runner.run(composed, analysis, initial_pose=initial_pose)
        except NotImplementedError as exc:
            return AnalysisResult(
                analysis_id=analysis_id,
                analysis_type=analysis.analysis_type,
                status="failed",
                error_message=str(exc),
            )
        except Exception as exc:
            return AnalysisResult(
                analysis_id=analysis_id,
                analysis_type=analysis.analysis_type,
                status="failed",
                error_message=str(exc),
            )

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        if self._workspace is not None:
            self._redo_stack.append(copy.deepcopy(self._workspace))
        self._workspace = self._undo_stack.pop()
        self.entities.invalidate_index()
        self.poses.clear_current()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        if self._workspace is not None:
            self._undo_stack.append(copy.deepcopy(self._workspace))
        self._workspace = self._redo_stack.pop()
        self.entities.invalidate_index()
        self.poses.clear_current()
        return True

    def _require_project(self):
        """Backward-compat: returns the project proxy (raises if no workspace)."""
        if self._workspace is None:
            raise ValueError("No active workspace")
        return self.project

    def _require_workspace(self) -> Workspace:
        if self._workspace is None:
            raise ValueError("No active workspace")
        return self._workspace

    def _snapshot(self) -> None:
        if self._workspace is not None and not self._in_operation:
            self._undo_stack.append(copy.deepcopy(self._workspace))
            self._redo_stack.clear()
            self.entities.invalidate_index()
            self.sketch.invalidate_cache()

    def _invalidate_pose_state(self) -> None:
        """Drop user pose data after a topology change that could leave stale refs.

        User poses reference body ids and driver ids; once the model topology
        changes we cannot guarantee they still describe a valid configuration,
        so we drop them and the user can re-solve from the reference pose.
        The reference (is_default=True) pose is always preserved.
        """
        self.poses.clear_current()
        case = self.current_case()
        if case is not None:
            case.poses = [p for p in case.poses if getattr(p, "is_default", False)]

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

    def _ensure_default_poses(self) -> None:
        """Guarantee every case has exactly one is_default=True pose (load-time migration).

        Also migrates legacy workspaces that overloaded `pose.is_default` to flag
        the simulation-initial pose: any user pose (body_poses non-empty) carrying
        is_default=True is moved to Case.metadata["simulation_initial_pose_id"] and
        its flag is cleared.
        """
        ws = self._workspace
        if ws is None:
            return
        for case in ws.cases.values():
            # Migrate legacy is_default=True user poses -> metadata field.
            for pose in case.poses:
                if pose.is_default and pose.body_poses:
                    case.metadata.setdefault("simulation_initial_pose_id", pose.id)
                    pose.is_default = False
            if not any(p.is_default for p in case.poses):
                pose_id = self.id_service.new("pose")
                case.poses.insert(0, create_default_pose(pose_id))

    def _dedupe_pose_and_analysis_ids(self) -> None:
        """Heal legacy workspaces that have colliding pose / analysis IDs across
        cases. Before id_service learned to observe pose/analysis IDs at load
        time, creating new poses on a loaded workspace minted IDs that already
        existed in another case. The result: any code that searches "the case
        owning pose X" by iterating cases hits the first match and acts on the
        wrong pose (e.g. refuses to delete a user pose because it found a
        Reference pose with the same ID first).

        For every duplicate occurrence (keeping the first), mint a fresh ID and
        re-target the analyses/runs/metadata that pointed at the old one
        *within the same case*.
        """
        ws = self._workspace
        if ws is None:
            return
        seen_poses: set[str] = set()
        for case in ws.cases.values():
            id_map: dict[str, str] = {}
            for pose in case.poses:
                if pose.id in seen_poses:
                    new_id = self.id_service.new("pose")
                    id_map[pose.id] = new_id
                    pose.id = new_id
                seen_poses.add(pose.id)
            if id_map:
                for analysis in case.analyses:
                    if analysis.pose_id in id_map:
                        analysis.pose_id = id_map[analysis.pose_id]
                sim_id = case.metadata.get("simulation_initial_pose_id")
                if sim_id in id_map:
                    case.metadata["simulation_initial_pose_id"] = id_map[sim_id]
        seen_analyses: set[str] = set()
        for case in ws.cases.values():
            for analysis in case.analyses:
                if analysis.id in seen_analyses:
                    analysis.id = self.id_service.new("analysis")
                seen_analyses.add(analysis.id)
        # Selected ids may now be ambiguous between cases; if the currently
        # selected pose / analysis no longer resolves to an entity in the
        # selected case, clear the selection rather than letting it cross-bind.
        if ws.selected_pose_id is not None:
            active = ws.cases.get(ws.selected_case_id) if ws.selected_case_id else None
            if active is None or not any(p.id == ws.selected_pose_id for p in active.poses):
                ws.selected_pose_id = None
        if ws.selected_analysis_id is not None:
            active = ws.cases.get(ws.selected_case_id) if ws.selected_case_id else None
            if active is None or not any(a.id == ws.selected_analysis_id for a in active.analyses):
                ws.selected_analysis_id = None

    def _find_body(self, body_id: str) -> Body:
        case = self.current_case()
        if case is None:
            raise ValueError(f"Unknown body: {body_id}")
        for body in case.model.bodies:
            if body.id == body_id:
                return body
        raise ValueError(f"Unknown body: {body_id}")

    def _find_body_by_marker(self, marker_id: str) -> Body:
        case = self.current_case()
        if case is None:
            raise ValueError(f"Unknown marker: {marker_id}")
        for body in case.model.bodies:
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

    def _bar_length(self, body: Body) -> float:
        return self.bodies._bar_length(body)

    def _bar_com_percent(self, body: Body) -> float:
        return self.bodies._bar_com_percent(body)

    def joint_friction_mode(self, joint: Joint) -> str | None:
        return self.joints.joint_friction_mode(joint)

    def joint_friction_values(self, joint: Joint) -> tuple[float, float]:
        return self.joints.joint_friction_values(joint)

    def joint_friction_pin_radius(self, joint: Joint) -> float:
        return self.joints.joint_friction_pin_radius(joint)

    def joint_supports_angular_limits(self, joint: Joint) -> bool:
        return self.joints.joint_supports_angular_limits(joint)

    def joint_angular_limit_values(self, joint: Joint) -> tuple[float | None, float | None]:
        return self.joints.joint_angular_limit_values(joint)

    def joint_angular_limit_expression(self, joint: Joint, path: str) -> str | None:
        return self.joints.joint_angular_limit_expression(joint, path)

    def joint_angular_limit_value(self, joint: Joint, path: str, unit: str = "deg") -> float | None:
        return self.joints.joint_angular_limit_value(joint, path, unit)

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
        ws = self._workspace
        if ws is None:
            return
        self.id_service.observe(ws.id)
        for parameter in ws.parameters:
            self.id_service.observe(parameter.id)
        if ws.sketch is not None:
            self.id_service.observe(ws.sketch.id)
            for entity in ws.sketch.entities.values():
                self.id_service.observe(entity.id)
            for constraint in ws.sketch.constraints.values():
                self.id_service.observe(constraint.id)
        for case in ws.cases.values():
            self.id_service.observe(case.id)
            model = case.model
            for body in model.bodies:
                self.id_service.observe(body.id)
                for marker in body.markers:
                    self.id_service.observe(marker.id)
            for slider in model.sliders:
                self.id_service.observe(slider.id)
            for joint in model.joints:
                self.id_service.observe(joint.id)
            for driver in model.drivers:
                self.id_service.observe(driver.id)
            for sensor in model.sensors:
                self.id_service.observe(sensor.id)
            for pose in case.poses:
                self.id_service.observe(pose.id)
            for analysis in case.analyses:
                self.id_service.observe(analysis.id)

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

    def _evaluate_all(self, project, report: ValidationReport) -> None:
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

    def _validate_sketch_solve(self, project, report: ValidationReport) -> None:
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

    def update_sensor_scope_position(self, sensor_id: str, canvas_x: float, canvas_y: float) -> None:
        self.forces.update_sensor_scope_position(sensor_id, canvas_x, canvas_y)

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

    # ------------------------------------------------------------------ workspace

    def set_working_context(self, *, case_id: str | None = None, baseline_id: str | None = None) -> None:
        self.workspace.set_working_context(case_id=case_id, baseline_id=baseline_id)

    def set_selected_pose(self, pose_id: str | None) -> None:
        self.workspace.set_selected_pose(pose_id)

    def set_selected_analysis(self, analysis_id: str | None) -> None:
        self.workspace.set_selected_analysis(analysis_id)

    def delete_run(self, run_id: str) -> None:
        self.workspace.delete_run(run_id)

    def duplicate_pose_in_case(self, pose_id: str, *, new_name: str | None = None):
        return self.workspace.duplicate_pose(pose_id, new_name=new_name)

    def duplicate_analysis(self, analysis_id: str, *, new_name: str | None = None):
        return self.workspace.duplicate_analysis(analysis_id, new_name=new_name)

    # ------------------------------------------------------------------ blocks

    def add_block(
        self,
        *,
        block_type: str,
        name: str,
        position: tuple[float, float],
        parameters: dict | None = None,
    ) -> str:
        return self.blocks.add_block(
            block_type=block_type, name=name, position=position, parameters=parameters
        )

    def add_connection(
        self,
        *,
        src_instance: str,
        src_port: str,
        dst_instance: str,
        dst_port: str,
    ) -> None:
        return self.blocks.add_connection(
            src_instance=src_instance,
            src_port=src_port,
            dst_instance=dst_instance,
            dst_port=dst_port,
        )

    def set_block_parameter(self, instance_id: str, key: str, value) -> None:
        self.blocks.set_block_parameter(instance_id, key, value)

    def set_block_name(self, instance_id: str, name: str) -> None:
        self.blocks.set_block_name(instance_id, name)

    def remove_block(self, instance_id: str) -> None:
        self.blocks.remove_block(instance_id)

    def remove_connection(
        self,
        *,
        src_instance: str,
        src_port: str,
        dst_instance: str,
        dst_port: str,
    ) -> None:
        self.blocks.remove_connection(
            src_instance=src_instance, src_port=src_port,
            dst_instance=dst_instance, dst_port=dst_port,
        )

    def set_block_position(self, instance_id: str, position: tuple[float, float]) -> None:
        self.blocks.set_block_position(instance_id, position)

    # ------------------------------------------------------------------ overrides

    def reset_override(self, *, path: str | None = None, entity_id: str | None = None, prop: str | None = None) -> bool:
        """Clear a local override on the active case so the inherited (or
        baseline) value becomes effective again.

        Pass either ``path`` (e.g. ``"bodies/<id>/mass"``) for invariant_values,
        or ``entity_id`` + ``prop`` for reference_overrides. Returns True when
        an override was actually removed.

        No-op (returns False) when no case is active, or when the active case
        does not contain that override locally. Overrides set on an ancestor
        case cannot be cleared from this call: ascend to that case first.
        """
        case = self.current_case()
        if case is None:
            return False
        with self._operation():
            if path is not None:
                inv = getattr(case, "invariant_values", {})
                if path in inv:
                    inv.pop(path)
                    self.entities.invalidate_index()
                    return True
                return False
            if entity_id is not None and prop is not None:
                ref_overrides = getattr(case, "reference_overrides", {})
                overrides = ref_overrides.get(entity_id)
                if overrides is None or prop not in overrides:
                    return False
                overrides.pop(prop)
                if not overrides:
                    ref_overrides.pop(entity_id, None)
                self.entities.invalidate_index()
                return True
        return False
