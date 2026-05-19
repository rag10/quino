from __future__ import annotations

import copy
import importlib

from quino.domain.model import Pose, Project
from quino.pose.geometry import marker_world_position, state_overlay_to_pose
from quino.pose.model import PoseConstraint, PoseSolveResult, PoseSolveSettings
from quino.services.expressions import ExpressionService
from quino.solver_adapters.exudyn_adapter import ExudynAdapter, _MM_TO_M


class ExudynPoseAdapter(ExudynAdapter):
    name = "exudyn_pose"

    def __init__(self, expression_service: ExpressionService) -> None:
        super().__init__(expression_service)

    def solve_pose(
        self,
        project: Project,
        initial_pose: Pose | None,
        temporary_constraints: list[PoseConstraint],
        settings: PoseSolveSettings,
    ) -> PoseSolveResult:
        try:
            assembled = self.assembler.assemble(project)
        except Exception as exc:
            return PoseSolveResult(
                success=False,
                backend=self.name,
                messages=["Solver phase: assemble internal mechanism", self._format_exception(exc)],
                error=f"Assembly failed: {exc}",
            )
        if not self.is_available():
            return PoseSolveResult(
                success=False,
                backend=self.name,
                warnings=list(assembled.warnings),
                messages=["Exudyn is not installed in the current environment"],
                error="Missing dependency: exudyn",
            )
        attempts = [initial_pose]
        if initial_pose is not None:
            attempts.append(self._perturb_pose(initial_pose, +0.1))
            attempts.append(self._perturb_pose(initial_pose, -0.1))
        last_result: PoseSolveResult | None = None
        for index, pose_attempt in enumerate(attempts):
            result = self._solve_pose_once(
                project,
                assembled,
                pose_attempt,
                temporary_constraints,
                settings,
            )
            if result.success:
                if index > 0:
                    result.warnings.append("Pose solve required a perturbed initial guess near a singular configuration")
                return result
            last_result = result
        return last_result or PoseSolveResult(
            success=False,
            backend=self.name,
            warnings=list(assembled.warnings),
            messages=["Solver phase: Exudyn pose solve"],
            error="Pose solve failed",
        )

    def _solve_pose_once(
        self,
        project: Project,
        assembled,
        initial_pose: Pose | None,
        temporary_constraints: list[PoseConstraint],
        settings: PoseSolveSettings,
    ) -> PoseSolveResult:
        try:
            exu = importlib.import_module("exudyn")
            item_interface = importlib.import_module("exudyn.itemInterface")
            sc = exu.SystemContainer()
            mbs = sc.AddSystem()
            ground_object = mbs.AddObject(item_interface.ObjectGround())
            body_objects, node_numbers, _body_order = self._create_bodies(
                mbs,
                item_interface,
                assembled,
                initial_pose=initial_pose,
            )
            for joint in assembled.joints:
                self._create_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint)
            for joint in assembled.joints:
                self._add_revolute_limit_stops(
                    mbs,
                    item_interface,
                    project,
                    assembled,
                    node_numbers,
                    ground_object,
                    joint,
                )
            # Drivers are deliberately NOT applied in pose mode. They are
            # time-dependent constraints for simulation; evaluating them at t=0
            # would lock the driven body at the reference angle and remove the
            # mechanism's DOF, making the pose unsolvable for any drag target.
            # If the user wants to fix a body's angle, they can add an explicit
            # body_angle pose constraint.

            warnings = list(assembled.warnings)
            messages = ["Exudyn pose model assembled"]
            for constraint in temporary_constraints:
                self._apply_pose_constraint(
                    mbs,
                    item_interface,
                    project,
                    assembled,
                    body_objects,
                    node_numbers,
                    ground_object,
                    constraint,
                    warnings,
                )

            mbs.Assemble()
            simulation_settings = exu.SimulationSettings()
            simulation_settings.staticSolver.numberOfLoadSteps = 1
            simulation_settings.staticSolver.verboseMode = 1 if settings.verbose else 0
            if hasattr(simulation_settings.staticSolver, "newton"):
                simulation_settings.staticSolver.newton.maxIterations = settings.max_iterations
                simulation_settings.staticSolver.newton.absoluteTolerance = settings.tolerance
                simulation_settings.staticSolver.newton.relativeTolerance = settings.tolerance
            mbs.SolveStatic(simulationSettings=simulation_settings)
            final_state = self._collect_final_state(mbs, exu, assembled, node_numbers)
            pose = state_overlay_to_pose(
                project,
                final_state,
                pose_id=initial_pose.id if initial_pose is not None else "pose_result",
                name=initial_pose.name if initial_pose is not None else "Pose",
            )
            for constraint in temporary_constraints:
                validation_error = self._constraint_validation_error(project, pose, constraint)
                if validation_error is not None:
                    messages.append(validation_error)
                    return PoseSolveResult(
                        success=False,
                        backend=self.name,
                        pose=pose,
                        warnings=warnings,
                        messages=messages,
                        error=validation_error,
                    )
            messages.append("Exudyn pose solve completed")
            return PoseSolveResult(
                success=True,
                pose=pose,
                warnings=warnings,
                messages=messages,
                backend=self.name,
            )
        except Exception as exc:  # pragma: no cover - depends on external package/runtime
            return PoseSolveResult(
                success=False,
                backend=self.name,
                warnings=list(assembled.warnings),
                messages=["Solver phase: Exudyn pose solve", self._format_exception(exc)],
                error=str(exc),
            )

    def _perturb_pose(self, pose: Pose, delta_angle: float) -> Pose:
        perturbed = copy.deepcopy(pose)
        for body_pose in perturbed.body_poses.values():
            body_pose.angle += delta_angle
        return perturbed

    def _apply_pose_constraint(
        self,
        mbs,
        item_interface,
        project: Project,
        assembled,
        body_objects: dict[str, int],
        node_numbers: dict[str, int],
        ground_object: int,
        constraint: PoseConstraint,
        warnings: list[str],
    ) -> None:
        if constraint.kind == "marker_position":
            self._apply_marker_position_constraint(
                mbs,
                item_interface,
                assembled,
                body_objects,
                ground_object,
                constraint.target_id,
                x_mm=float(constraint.metadata["x"]),
                y_mm=float(constraint.metadata["y"]),
            )
            return
        if constraint.kind == "marker_projected_coordinate":
            self._apply_marker_projected_coordinate_constraint(
                mbs,
                item_interface,
                assembled,
                body_objects,
                ground_object,
                constraint.target_id,
                axis_x=float(constraint.metadata.get("axis_x", 1.0)),
                axis_y=float(constraint.metadata.get("axis_y", 0.0)),
                value_mm=float(constraint.metadata["value"]),
                reference_x=float(constraint.metadata.get("reference_x", 0.0)),
                reference_y=float(constraint.metadata.get("reference_y", 0.0)),
            )
            return
        if constraint.kind == "body_angle":
            self._apply_body_angle_constraint(
                mbs,
                item_interface,
                assembled,
                node_numbers,
                constraint.target_id,
                float(constraint.metadata["angle"]),
            )
            return
        if constraint.kind == "relative_body_angle":
            self._apply_relative_body_angle_constraint(
                mbs,
                item_interface,
                assembled,
                node_numbers,
                str(constraint.metadata["body_a_id"]),
                str(constraint.metadata["body_b_id"]),
                float(constraint.metadata["local_phi_a"]),
                float(constraint.metadata["local_phi_b"]),
                float(constraint.metadata["angle"]),
            )
            return
        warnings.append(f"Constraint unsupported in pose mode: {constraint.kind}")

    def _apply_marker_projected_coordinate_constraint(
        self,
        mbs,
        item_interface,
        assembled,
        body_objects: dict[str, int],
        ground_object: int,
        marker_id: str,
        *,
        axis_x: float,
        axis_y: float,
        value_mm: float,
        reference_x: float,
        reference_y: float,
    ) -> None:
        body = self._find_body_for_marker(assembled, marker_id)
        marker = body.markers[marker_id]
        axis_norm = (axis_x ** 2 + axis_y ** 2) ** 0.5
        if axis_norm <= 1e-12:
            raise ValueError("Pose constraint axis must be non-zero")
        marker_coordinate = mbs.AddMarker(
            item_interface.MarkerBodiesRelativeTranslationCoordinate(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                localPosition0=[reference_x * _MM_TO_M, reference_y * _MM_TO_M, 0.0],
                localPosition1=[
                    (marker.local_x - body.com_local_x) * _MM_TO_M,
                    (marker.local_y - body.com_local_y) * _MM_TO_M,
                    0.0,
                ],
                axis0=[axis_x / axis_norm, axis_y / axis_norm, 0.0],
                offset=0.0,
            )
        )
        ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
        zero_coordinate_marker = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=ground_node, coordinate=0))
        mbs.AddObject(
            item_interface.CoordinateConstraint(
                markerNumbers=[marker_coordinate, zero_coordinate_marker],
                offset=-value_mm * _MM_TO_M,
            )
        )

    def _apply_marker_position_constraint(
        self,
        mbs,
        item_interface,
        assembled,
        body_objects: dict[str, int],
        ground_object: int,
        marker_id: str,
        *,
        x_mm: float,
        y_mm: float,
    ) -> None:
        body = self._find_body_for_marker(assembled, marker_id)
        marker = body.markers[marker_id]
        body_marker = mbs.AddMarker(
            item_interface.MarkerBodyPosition(
                bodyNumber=body_objects[body.body_id],
                localPosition=[
                    (marker.local_x - body.com_local_x) * _MM_TO_M,
                    (marker.local_y - body.com_local_y) * _MM_TO_M,
                    0.0,
                ],
            )
        )
        target_marker = mbs.AddMarker(
            item_interface.MarkerBodyPosition(
                bodyNumber=ground_object,
                localPosition=[x_mm * _MM_TO_M, y_mm * _MM_TO_M, 0.0],
            )
        )
        mbs.AddObject(
            item_interface.CartesianSpringDamper(
                markerNumbers=[target_marker, body_marker],
                stiffness=[1.0e8, 1.0e8, 0.0],
                damping=[1.0e3, 1.0e3, 0.0],
                offset=[0.0, 0.0, 0.0],
            )
        )

    def _apply_body_angle_constraint(
        self,
        mbs,
        item_interface,
        assembled,
        node_numbers: dict[str, int],
        body_id: str,
        target_angle: float,
    ) -> None:
        # CoordinateConstraint: q_m0 - q_m1 + offset = 0
        # q_m0 = 0 (ground), q_m1 = actual_angle - ref_angle (displacement from reference)
        # → actual_angle = ref_angle + offset  →  offset = target_angle - ref_angle
        ref_angle = assembled.bodies[body_id].angle if body_id in assembled.bodies else 0.0
        ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
        ground_marker = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=ground_node, coordinate=0))
        body_marker = mbs.AddMarker(
            item_interface.MarkerNodeCoordinate(
                nodeNumber=node_numbers[body_id],
                coordinate=2,
            )
        )
        mbs.AddObject(
            item_interface.CoordinateConstraint(
                markerNumbers=[ground_marker, body_marker],
                offset=target_angle - ref_angle,
            )
        )

    def _apply_relative_body_angle_constraint(
        self,
        mbs,
        item_interface,
        assembled,
        node_numbers: dict[str, int],
        body_a_id: str,
        body_b_id: str,
        local_phi_a: float,
        local_phi_b: float,
        target_relative_angle: float,
    ) -> None:
        # Constraint: world_angle_A - world_angle_B = target_relative_angle
        # where world_angle_X = body_X.actual_angle + local_phi_X
        # In Exudyn coords: q_X = body_X.actual_angle - ref_X
        # (q_A + ref_A + phi_A) - (q_B + ref_B + phi_B) = target
        # q_A - q_B + offset = 0  →  offset = phi_A - phi_B + ref_A - ref_B - target
        ref_a = assembled.bodies[body_a_id].angle if body_a_id in assembled.bodies else 0.0
        ref_b = assembled.bodies[body_b_id].angle if body_b_id in assembled.bodies else 0.0
        offset = local_phi_a - local_phi_b + ref_a - ref_b - target_relative_angle
        body_a_angle_marker = mbs.AddMarker(
            item_interface.MarkerNodeCoordinate(nodeNumber=node_numbers[body_a_id], coordinate=2)
        )
        body_b_angle_marker = mbs.AddMarker(
            item_interface.MarkerNodeCoordinate(nodeNumber=node_numbers[body_b_id], coordinate=2)
        )
        mbs.AddObject(
            item_interface.CoordinateConstraint(
                markerNumbers=[body_a_angle_marker, body_b_angle_marker],
                offset=offset,
            )
        )

    def _constraint_validation_error(
        self,
        project: Project,
        pose: Pose,
        constraint: PoseConstraint,
    ) -> str | None:
        return None
