from __future__ import annotations

import importlib
import math
from pathlib import Path
import tempfile
import traceback

from quino.domain.model import Project, ReactionOutput, SensorOutput, SimulationResult
from quino.domain.types import Dimension, DriverType, JointEndpointKind, JointType
from quino.services.expressions import ExpressionService
from quino.simulation.assembler import (
    AssembledBody,
    AssembledDriver,
    AssembledLoad,
    AssembledMechanism,
    AssembledSlider,
    AssembledSpring,
    MechanismAssembler,
)
from quino.simulation.sensor_expressions import safe_sensor_var, sensor_channel_keys, sensor_expression_variables
from quino.solver_adapters.base import SolverAdapter
from quino.solver_adapters.exudyn_script_generator import generate_exudyn_script

_MM_TO_M = 1e-3       # assembled positions are in mm; Exudyn expects SI metres
_KGMM2_TO_KGM2 = 1e-6  # assembled inertia is in kgmm²; Exudyn expects kg·m²
_M_TO_MM = 1e3          # convert Exudyn ODE2 displacements (m) back to mm for output


def _body_com_global_mm(body: "AssembledBody") -> tuple[float, float]:
    """Global CoM position in mm (reference configuration)."""
    cos_a = math.cos(body.angle)
    sin_a = math.sin(body.angle)
    return (
        body.origin_x + cos_a * body.com_local_x - sin_a * body.com_local_y,
        body.origin_y + sin_a * body.com_local_x + cos_a * body.com_local_y,
    )


def _marker_local_rel_com(body: "AssembledBody", marker: "AssembledMarker") -> tuple[float, float]:
    """Marker local position relative to body CoM (not body origin/pivot)."""
    return (marker.local_x - body.com_local_x, marker.local_y - body.com_local_y)


def _make_constant_friction_fn(coulomb: float, viscous: float):
    """Constant-torque/force Coulomb model (no reaction force scaling)."""
    def fn(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):
        sign = 1.0 if velocity > 1e-12 else -1.0 if velocity < -1e-12 else 0.0
        return -(viscous * float(velocity) + coulomb * sign)
    return fn


def _make_revolute_physics_friction_fn(joint_obj_num: int, exu, mu: float, r_m: float, viscous: float):
    """Physics-based revolute friction: T = μ × ||F_joint|| × r_pin × sign(ω) + c × ω."""
    def fn(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):
        try:
            forces = mbs.GetObjectOutput(joint_obj_num, exu.OutputVariableType.Force)
            N = math.sqrt(float(forces[0]) ** 2 + float(forces[1]) ** 2)
        except Exception:
            N = 0.0
        sign = 1.0 if velocity > 1e-12 else -1.0 if velocity < -1e-12 else 0.0
        return -(mu * N * r_m * sign + viscous * float(velocity))
    return fn


def _make_slider_physics_friction_fn(joint_obj_num: int, exu, mu: float, viscous: float):
    """Physics-based slider friction: F = μ × |F_normal| × sign(v) + c × v."""
    def fn(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):
        try:
            forces = mbs.GetObjectOutput(joint_obj_num, exu.OutputVariableType.Force)
            raw = forces[0] if hasattr(forces, "__len__") else forces
            N = abs(float(raw))
        except Exception:
            N = 0.0
        sign = 1.0 if velocity > 1e-12 else -1.0 if velocity < -1e-12 else 0.0
        return -(mu * N * sign + viscous * float(velocity))
    return fn


class ExudynAdapter(SolverAdapter):
    name = "exudyn"

    def __init__(self, expression_service: ExpressionService) -> None:
        self.expression_service = expression_service
        self.assembler = MechanismAssembler(expression_service)

    def is_available(self) -> bool:
        return importlib.util.find_spec("exudyn") is not None

    def export_script(self, project: Project, duration: float = 1.0, steps: int = 100) -> str:
        assembled = self.assembler.assemble(project)
        return generate_exudyn_script(project, assembled, duration, steps, self.expression_service)

    def run(self, project: Project, duration: float = 1.0, steps: int = 100) -> SimulationResult:
        try:
            assembled = self.assembler.assemble(project)
        except Exception as exc:
            return SimulationResult(
                success=False,
                backend=self.name,
                messages=[
                    "Solver phase: assemble internal mechanism",
                    *self._project_diagnostics(project),
                    self._format_exception(exc),
                ],
                error=f"Assembly failed: {exc}",
            )
        if not self.is_available():
            return SimulationResult(
                success=False,
                backend=self.name,
                warnings=list(assembled.warnings),
                messages=["Exudyn is not installed in the current environment"],
                error="Missing dependency: exudyn",
            )
        try:
            exu = importlib.import_module("exudyn")
            return self._run_with_exudyn(project, assembled, exu, solve_mode="dynamic", duration=duration, steps=steps)
        except Exception as exc:  # pragma: no cover - depends on external package/runtime
            dynamic_error = exc
            dynamic_traceback = self._format_exception(exc)
            if self._has_translation_drivers(assembled):
                try:
                    exu = importlib.import_module("exudyn")
                    fallback = self._run_with_exudyn(
                        project,
                        assembled,
                        exu,
                        solve_mode="dynamic",
                        duration=duration,
                        steps=steps,
                        translation_driver_mode="servo",
                    )
                    fallback.warnings.append(
                        f"Translation driver constraint fallback used: {dynamic_error}"
                    )
                    fallback.messages.append(
                        "Translation driver constraint solve failed; compliant servo fallback used"
                    )
                    fallback.messages.append(dynamic_traceback)
                    return fallback
                except Exception as servo_exc:
                    dynamic_error = (
                        f"{dynamic_error}; translation servo fallback failed: {servo_exc}"
                    )
                    dynamic_traceback = "\n".join(
                        [dynamic_traceback, "Solver phase: translation servo fallback", self._format_exception(servo_exc)]
                    )
            if assembled.drivers:
                try:
                    exu = importlib.import_module("exudyn")
                    fallback = self._run_with_exudyn(
                        project,
                        assembled,
                        exu,
                        solve_mode="static",
                        duration=duration,
                        steps=steps,
                    )
                    fallback.warnings.append(f"Dynamic solve fallback used: {exc}")
                    fallback.messages.append("Static fallback used after dynamic solve failure")
                    fallback.messages.append(dynamic_traceback)
                    return fallback
                except Exception as fallback_exc:
                    return SimulationResult(
                        success=False,
                        backend=self.name,
                        warnings=list(assembled.warnings),
                        messages=[
                            "Solver phase: Exudyn dynamic solve",
                            *self._project_diagnostics(project),
                            dynamic_traceback,
                            "Solver phase: Exudyn static fallback",
                            self._format_exception(fallback_exc),
                        ],
                        error=f"Dynamic solve failed: {dynamic_error}; static fallback failed: {fallback_exc}",
                    )
            return SimulationResult(
                success=False,
                backend=self.name,
                warnings=list(assembled.warnings),
                messages=[
                    "Solver phase: Exudyn execution",
                    *self._project_diagnostics(project),
                    dynamic_traceback,
                ],
                error=str(exc),
            )

    def _run_with_exudyn(
        self,
        project: Project,
        assembled: AssembledMechanism,
        exu,
        solve_mode: str,
        duration: float,
        steps: int,
        translation_driver_mode: str = "constraint",
    ) -> SimulationResult:
        item_interface = importlib.import_module("exudyn.itemInterface")
        sc = exu.SystemContainer()
        mbs = sc.AddSystem()
        ground_object = mbs.AddObject(item_interface.ObjectGround())
        body_objects, node_numbers, body_order = self._create_bodies(mbs, item_interface, assembled)
        joint_objects: dict[str, int] = {}
        for joint in assembled.joints:
            joint_objects[joint.id] = self._create_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint)
        for joint in assembled.joints:
            self._add_joint_friction(mbs, item_interface, assembled, node_numbers, body_objects, ground_object, joint, exu, joint_objects)
        for driver in assembled.drivers:
            self._create_driver(
                mbs,
                item_interface,
                project,
                assembled,
                body_objects,
                node_numbers,
                ground_object,
                driver,
                translation_driver_mode=translation_driver_mode,
            )
        for load in assembled.loads:
            self._create_load(mbs, item_interface, project, assembled, body_objects, node_numbers, load, exu)
        for spring in assembled.springs:
            self._create_spring(mbs, item_interface, project, body_objects, node_numbers, ground_object, spring, exu)
        reaction_info = self._reaction_joint_info(assembled, joint_objects)
        time: list[float] = []
        frames: list[dict[str, float]] = []
        warnings = list(assembled.warnings)
        messages = ["Exudyn model assembled"]
        messages.extend(f"Assembly warning: {warning}" for warning in assembled.warnings)
        for body in assembled.bodies.values():
            warnings.extend(body.warnings)
            messages.extend(f"Body warning: {warning}" for warning in body.warnings)
        has_dynamic_bodies = any(body.mass > 0 for body in assembled.bodies.values())
        if assembled.drivers or has_dynamic_bodies:
            if solve_mode == "dynamic":
                simulation_settings = exu.SimulationSettings()
                simulation_settings.timeIntegration.numberOfSteps = steps
                simulation_settings.timeIntegration.endTime = duration
                reaction_logs: dict[str, list[list[float]]] = {}
                for jid, _jname, etype, _sid, nx, ny in reaction_info:
                    joint_obj_num = joint_objects.get(jid)
                    if joint_obj_num is None:
                        continue
                    log: list[list[float]] = []
                    reaction_logs[jid] = log
                    if etype == "slider":
                        sensor_fn = self._make_slider_reaction_sensor_fn(joint_obj_num, nx, ny, log, exu)
                    else:
                        sensor_fn = self._make_ground_reaction_sensor_fn(joint_obj_num, log)
                    mbs.AddSensor(item_interface.SensorUserFunction(
                        sensorNumbers=[],
                        sensorUserFunction=sensor_fn,
                    ))
                mbs.Assemble()
                with tempfile.TemporaryDirectory(prefix="quino_exudyn_") as temp_dir:
                    temp_dir_path = Path(temp_dir)
                    solution_path = temp_dir_path / "solution.txt"
                    simulation_settings.solutionSettings.writeSolutionToFile = True
                    simulation_settings.solutionSettings.coordinatesSolutionFileName = str(solution_path)
                    simulation_settings.solutionSettings.solutionWritePeriod = duration / max(steps, 1)
                    simulation_settings.solutionSettings.sensorsWritePeriod = duration / max(steps, 1)
                    if hasattr(simulation_settings.solutionSettings, "binarySolutionFile"):
                        simulation_settings.solutionSettings.binarySolutionFile = False
                    try:
                        mbs.SolveDynamic(simulationSettings=simulation_settings)
                    except Exception as exc:
                        time, frames = self._load_solution_frames(
                            exu,
                            mbs,
                            solution_path,
                            assembled,
                            body_order,
                            node_numbers,
                            allow_final_fallback=False,
                            project=project,
                        )
                        if frames:
                            warnings.append(
                                "Dynamic solve failed; returning partial trajectory up to last converged frame"
                            )
                            messages.append(
                                "Exudyn dynamic solve terminated before end; partial frames are available"
                            )
                            messages.append(self._format_exception(exc))
                            if project:
                                self._record_reaction_data_dynamic(
                                    project, assembled, time, frames, reaction_info, reaction_logs
                                )
                            return SimulationResult(
                                success=False,
                                backend=self.name,
                                messages=messages,
                                warnings=warnings,
                                time=time,
                                frames=frames,
                                error=f"Dynamic solve failed after partial trajectory: {exc}",
                            )
                        raise
                    time, frames = self._load_solution_frames(
                        exu,
                        mbs,
                        solution_path,
                        assembled,
                        body_order,
                        node_numbers,
                        project=project,
                    )
                    if project:
                        self._record_reaction_data_dynamic(
                            project, assembled, time, frames, reaction_info, reaction_logs
                        )
                messages.append("Exudyn dynamic solve completed")
            elif solve_mode == "static":
                mbs.Assemble()
                simulation_settings = exu.SimulationSettings()
                simulation_settings.staticSolver.numberOfLoadSteps = 100
                simulation_settings.solutionSettings.writeSolutionToFile = False
                mbs.SolveStatic(simulationSettings=simulation_settings)
                final_state = self._collect_final_state(mbs, exu, assembled, node_numbers)
                time = [duration]
                frames = [final_state]
                if project:
                    self._record_reaction_data_static(
                        project, assembled, mbs, exu, time, frames, reaction_info, joint_objects
                    )
                warnings.append("Dynamic solve fallback used; returning a single static frame")
                messages.append("Exudyn static fallback completed")
            else:
                raise ValueError(f"Unsupported Exudyn solve mode: {solve_mode}")
        else:
            mbs.Assemble()
            time = [0.0]
            frames = [self._collect_final_state(mbs, exu, assembled, node_numbers)]
            if project:
                self._record_reaction_data_static(
                    project, assembled, mbs, exu, time, frames, reaction_info, joint_objects
                )
            messages.append("No drivers defined; returning assembled reference configuration")
        return SimulationResult(
            success=True,
            backend=self.name,
            messages=messages,
            warnings=warnings,
            time=time,
            frames=frames,
        )

    def _create_bodies(
        self, mbs, item_interface, assembled: AssembledMechanism
    ) -> tuple[dict[str, int], dict[str, int], list[str]]:
        body_objects: dict[str, int] = {}
        node_numbers: dict[str, int] = {}
        body_order: list[str] = []
        for body in assembled.bodies.values():
            com_x_mm, com_y_mm = _body_com_global_mm(body)
            node = mbs.AddNode(
                item_interface.NodeRigidBody2D(
                    referenceCoordinates=[com_x_mm * _MM_TO_M, com_y_mm * _MM_TO_M, body.angle]
                )
            )
            body_object = mbs.AddObject(
                item_interface.ObjectRigidBody2D(
                    nodeNumber=node,
                    physicsMass=body.mass,
                    physicsInertia=body.inertia * _KGMM2_TO_KGM2,
                    physicsCenterOfMass=[0.0, 0.0],
                )
            )
            if body.mass > 0 and assembled.gravity is not None:
                g = assembled.gravity
                gravity_marker = mbs.AddMarker(
                    item_interface.MarkerBodyMass(
                        bodyNumber=body_object,
                    )
                )
                mbs.AddLoad(
                    item_interface.LoadMassProportional(
                        markerNumber=gravity_marker,
                        loadVector=[g.magnitude * g.direction_x, g.magnitude * g.direction_y, 0.0],
                    )
                )
            node_numbers[body.body_id] = node
            body_objects[body.body_id] = body_object
            body_order.append(body.body_id)
        return body_objects, node_numbers, body_order

    def _create_joint(self, mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint) -> int:
        a = joint.endpoint_a
        b = joint.endpoint_b
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.MARKER:
            return self._create_marker_to_marker_joint(mbs, item_interface, assembled, body_objects, node_numbers, a, b, joint.type)
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.GROUND:
            return self._create_marker_to_ground_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, a, joint.type)
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.SLIDER:
            return self._create_marker_to_slider_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, a, b, joint.type, joint.name)
        if b.kind is JointEndpointKind.MARKER and a.kind is JointEndpointKind.GROUND:
            return self._create_marker_to_ground_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, b, joint.type)
        if b.kind is JointEndpointKind.MARKER and a.kind is JointEndpointKind.SLIDER:
            return self._create_marker_to_slider_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, b, a, joint.type, joint.name)
        raise ValueError(f"Unsupported joint topology for Exudyn adapter: {joint.name}")

    def _find_body_for_marker(self, assembled: AssembledMechanism, marker_id: str) -> AssembledBody:
        for body in assembled.bodies.values():
            if marker_id in body.markers:
                return body
        raise ValueError(f"Marker {marker_id} not found in any body")

    def _create_load(self, mbs, item_interface, project, assembled, body_objects, node_numbers, load: AssembledLoad, exu) -> None:
        body = self._find_body_for_marker(assembled, load.target_marker_id)
        marker = body.markers[load.target_marker_id]
        lx, ly = _marker_local_rel_com(body, marker)
        load_marker = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=body_objects[body.body_id],
                localPosition=[lx * _MM_TO_M, ly * _MM_TO_M, 0.0],
            )
        )
        if self._load_is_dynamic(project, load):
            mbs.AddLoad(
                item_interface.LoadForceVector(
                    markerNumber=load_marker,
                    loadVector=[0.0, 0.0, 0.0],
                    loadVectorUserFunction=self._make_load_vector_function(
                        project, assembled, node_numbers, load, exu
                    ),
                )
            )
            return
        mbs.AddLoad(item_interface.LoadForceVector(markerNumber=load_marker, loadVector=[load.fx, load.fy, 0.0]))

    def _load_is_dynamic(self, project: Project, load: AssembledLoad) -> bool:
        tokens = ["t"]
        for sensor in project.model.sensors:
            safe = safe_sensor_var(sensor.name)
            for channel, _ in sensor_channel_keys(sensor):
                tokens.append(f"{safe}.{channel}")
        expressions = (load.fx_expression, load.fy_expression)
        for expression in expressions:
            for token in tokens:
                if token and token in expression:
                    return True
        return False

    def _make_load_vector_function(self, project: Project, assembled: AssembledMechanism, node_numbers: dict[str, int], load: AssembledLoad, exu):
        def force_fn(mbs, t, loadVector):
            frame = self._current_frame(mbs, exu, assembled, node_numbers)
            variables = {"t": self.expression_service.unit_service.quantity(float(t), "s")}
            variables.update(
                sensor_expression_variables(
                    project,
                    assembled,
                    frame,
                    self.expression_service.unit_service,
                )
            )
            fx_q = self.expression_service.evaluate_expression(load.fx_expression, project.parameters, variables=variables)
            fy_q = self.expression_service.evaluate_expression(load.fy_expression, project.parameters, variables=variables)
            return [
                self.expression_service.unit_service.convert(fx_q, "N"),
                self.expression_service.unit_service.convert(fy_q, "N"),
                0.0,
            ]

        return force_fn

    def _current_frame(self, mbs, exu, assembled: AssembledMechanism, node_numbers: dict[str, int]) -> dict[str, float]:
        frame: dict[str, float] = {}
        for body_id, node_number in node_numbers.items():
            coordinates = mbs.GetNodeOutput(node_number, exu.OutputVariableType.Coordinates)
            body = assembled.bodies[body_id]
            com_ref_x, com_ref_y = _body_com_global_mm(body)
            cur_angle = body.angle + (float(coordinates[2]) if len(coordinates) > 2 else 0.0)
            cos_a = math.cos(cur_angle)
            sin_a = math.sin(cur_angle)
            cur_com_x = com_ref_x + float(coordinates[0]) * _M_TO_MM
            cur_com_y = com_ref_y + float(coordinates[1]) * _M_TO_MM
            frame[f"{body_id}.x"] = cur_com_x - cos_a * body.com_local_x + sin_a * body.com_local_y
            frame[f"{body_id}.y"] = cur_com_y - sin_a * body.com_local_x - cos_a * body.com_local_y
            frame[f"{body_id}.angle"] = cur_angle
            try:
                vel = mbs.GetNodeOutput(node_number, exu.OutputVariableType.Velocity)
                frame[f"{body_id}.vx"] = float(vel[0]) * _M_TO_MM
                frame[f"{body_id}.vy"] = float(vel[1]) * _M_TO_MM
                frame[f"{body_id}.omega"] = float(vel[2]) if len(vel) > 2 else 0.0
            except Exception:
                pass
        return frame

    def _create_spring(
        self,
        mbs,
        item_interface,
        project: Project,
        body_objects: dict[str, int],
        node_numbers: dict[str, int],
        ground_object: int,
        spring: AssembledSpring,
        exu,
    ) -> None:
        is_rotational = spring.spring_type in ("rotational_spring", "rotational_actuator")
        if is_rotational:
            self._create_rotational_spring(mbs, item_interface, project, node_numbers, ground_object, spring)
        else:
            self._create_linear_spring(mbs, item_interface, project, body_objects, ground_object, spring, exu)

    def _linear_spring_marker(self, mbs, item_interface, body_objects: dict[str, int], ground_object: int, ep) -> int:
        if ep.kind == "ground":
            return mbs.AddMarker(
                item_interface.MarkerBodyPosition(
                    bodyNumber=ground_object,
                    localPosition=[ep.global_x * _MM_TO_M, ep.global_y * _MM_TO_M, 0.0],
                )
            )
        return mbs.AddMarker(
            item_interface.MarkerBodyPosition(
                bodyNumber=body_objects[ep.body_id],
                localPosition=[ep.global_x * _MM_TO_M, ep.global_y * _MM_TO_M, 0.0],
            )
        )

    def _create_linear_spring(self, mbs, item_interface, project, body_objects, ground_object, spring: AssembledSpring, exu) -> None:
        m_a = mbs.AddMarker(
            item_interface.MarkerBodyPosition(
                bodyNumber=ground_object if spring.endpoint_a.kind == "ground" else body_objects[spring.endpoint_a.body_id],
                localPosition=[spring.endpoint_a.anchor_x * _MM_TO_M, spring.endpoint_a.anchor_y * _MM_TO_M, 0.0],
            )
        )
        m_b = mbs.AddMarker(
            item_interface.MarkerBodyPosition(
                bodyNumber=ground_object if spring.endpoint_b.kind == "ground" else body_objects[spring.endpoint_b.body_id],
                localPosition=[spring.endpoint_b.anchor_x * _MM_TO_M, spring.endpoint_b.anchor_y * _MM_TO_M, 0.0],
            )
        )
        k = spring.stiffness * 1e3   # N/mm → N/m
        c = spring.damping * 1e3     # N·s/mm → N·s/m
        L0 = spring.rest_value * _MM_TO_M  # mm → m
        if spring.spring_type == "linear_actuator":
            law_fn = self._make_spring_law_fn(project, spring, "N")  # already SI
            mbs.AddObject(item_interface.ObjectConnectorSpringDamper(
                name=spring.name, markerNumbers=[m_a, m_b],
                stiffness=0.0, damping=0.0, referenceLength=0.0,
                springForceUserFunction=law_fn,
            ))
        else:
            mbs.AddObject(item_interface.ObjectConnectorSpringDamper(
                name=spring.name, markerNumbers=[m_a, m_b],
                stiffness=k, damping=c, referenceLength=L0,
            ))

    def _create_rotational_spring(self, mbs, item_interface, project, node_numbers: dict[str, int], ground_object: int, spring: AssembledSpring) -> None:
        def _angle_marker(ep) -> int:
            if ep.kind == "ground":
                gn = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
                return mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=gn, coordinate=0))
            return mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=node_numbers[ep.body_id], coordinate=2))

        m_a = _angle_marker(spring.endpoint_a)
        m_b = _angle_marker(spring.endpoint_b)
        k = spring.stiffness * 1e-3   # N·mm/rad → N·m/rad
        c = spring.damping * 1e-3     # N·mm·s/rad → N·m·s/rad
        theta0 = spring.rest_value    # already in rad
        if spring.spring_type == "rotational_actuator":
            law_fn = self._make_spring_law_fn(project, spring, "N*m")
            mbs.AddObject(item_interface.ObjectConnectorCoordinateSpringDamper(
                name=spring.name, markerNumbers=[m_a, m_b],
                stiffness=0.0, damping=0.0, offset=0.0,
                springForceUserFunction=law_fn,
            ))
        else:
            mbs.AddObject(item_interface.ObjectConnectorCoordinateSpringDamper(
                name=spring.name, markerNumbers=[m_a, m_b],
                stiffness=k, damping=c, offset=theta0,
            ))

    def _make_spring_law_fn(self, project: Project, spring: AssembledSpring, si_unit: str):
        """Returns a springForceUserFunction. si_unit: 'N' (linear) or 'N*m' (rotational, SI)."""
        def fn(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):
            variables = {"t": self.expression_service.unit_service.quantity(float(t), "s")}
            quantity = self.expression_service.evaluate_expression(spring.law_expression, project.parameters, variables=variables)
            return self.expression_service.unit_service.convert(quantity, si_unit)
        return fn

    def _create_marker_to_marker_joint(self, mbs, item_interface, assembled, body_objects, node_numbers, endpoint_a, endpoint_b, joint_type) -> int:
        body_a = assembled.bodies[endpoint_a.body_id]
        body_b = assembled.bodies[endpoint_b.body_id]
        marker_a = body_a.markers[endpoint_a.marker_id]
        marker_b = body_b.markers[endpoint_b.marker_id]
        lx_a, ly_a = _marker_local_rel_com(body_a, marker_a)
        lx_b, ly_b = _marker_local_rel_com(body_b, marker_b)
        marker_number_a = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=body_objects[body_a.body_id],
                localPosition=[lx_a * _MM_TO_M, ly_a * _MM_TO_M, 0.0],
            )
        )
        marker_number_b = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=body_objects[body_b.body_id],
                localPosition=[lx_b * _MM_TO_M, ly_b * _MM_TO_M, 0.0],
            )
        )
        joint_obj = mbs.AddObject(item_interface.ObjectJointRevolute2D(markerNumbers=[marker_number_a, marker_number_b]))
        if joint_type is JointType.RIGID:
            mbs.CreateCoordinateConstraint(
                bodyNumbers=[body_objects[body_a.body_id], body_objects[body_b.body_id]],
                coordinates=[2, 2],
                offset=0.0,
            )
        return joint_obj

    def _create_marker_to_ground_joint(
        self, mbs, item_interface, assembled, body_objects, node_numbers, ground_object, endpoint, joint_type
    ) -> int:
        body = assembled.bodies[endpoint.body_id]
        marker = body.markers[endpoint.marker_id]
        ground_marker = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=ground_object,
                localPosition=[marker.global_x * _MM_TO_M, marker.global_y * _MM_TO_M, 0.0],
            )
        )
        lx, ly = _marker_local_rel_com(body, marker)
        body_marker = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=body_objects[body.body_id],
                localPosition=[lx * _MM_TO_M, ly * _MM_TO_M, 0.0],
            )
        )
        joint_obj = mbs.AddObject(item_interface.ObjectJointRevolute2D(markerNumbers=[ground_marker, body_marker]))
        if joint_type is JointType.RIGID:
            mbs.CreateCoordinateConstraint(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                coordinates=[None, 2],
                offset=0.0,
            )
        return joint_obj

    def _create_marker_to_slider_joint(
        self, mbs, item_interface, assembled, body_objects, node_numbers, ground_object, endpoint_a, endpoint_b, joint_type, joint_name
    ) -> int:
        body = assembled.bodies[endpoint_a.body_id]
        marker = body.markers[endpoint_a.marker_id]
        slider = assembled.sliders[endpoint_b.slider_id]
        lx, ly = _marker_local_rel_com(body, marker)
        normal_translation_marker = mbs.AddMarker(
            item_interface.MarkerBodiesRelativeTranslationCoordinate(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                localPosition0=[slider.origin_x * _MM_TO_M, slider.origin_y * _MM_TO_M, 0.0],
                localPosition1=[lx * _MM_TO_M, ly * _MM_TO_M, 0.0],
                axis0=[slider.normal_x, slider.normal_y, 0.0],
                offset=0.0,
            )
        )
        ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
        zero_coordinate_marker = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=ground_node, coordinate=0))
        joint_obj = mbs.AddObject(
            item_interface.CoordinateConstraint(
                name=joint_name,
                markerNumbers=[normal_translation_marker, zero_coordinate_marker],
                offset=0.0,
            )
        )
        if joint_type is JointType.RIGID:
            mbs.CreateCoordinateConstraint(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                coordinates=[None, 2],
                offset=0.0,
            )
        self._add_slider_limit_stops(
            mbs=mbs,
            item_interface=item_interface,
            slider=slider,
            body=body,
            marker=marker,
            body_object=body_objects[body.body_id],
            ground_object=ground_object,
        )
        return joint_obj

    def _add_joint_friction(
        self,
        mbs,
        item_interface,
        assembled: AssembledMechanism,
        node_numbers: dict[str, int],
        body_objects: dict[str, int],
        ground_object: int,
        joint: Joint,
        exu,
        joint_objects: dict[str, int],
    ) -> None:
        mode = None
        if joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER:
            mode = "translation"
        elif joint.type is JointType.REVOLUTE:
            mode = "rotation"
        if mode is None:
            return
        try:
            coulomb = float(joint.metadata.values.get("friction_coulomb", 0.0))
            viscous = float(joint.metadata.values.get("friction_viscous", 0.0))
        except (TypeError, ValueError):
            return
        if abs(coulomb) <= 1e-12 and abs(viscous) <= 1e-12:
            return
        joint_obj_num = joint_objects.get(joint.id, -1)
        if mode == "rotation":
            marker_numbers = self._rotation_coordinate_markers(mbs, item_interface, node_numbers, ground_object, joint)
            try:
                pin_radius_mm = float(joint.metadata.values.get("friction_pin_radius", 0.0))
            except (TypeError, ValueError):
                pin_radius_mm = 0.0
            if pin_radius_mm > 1e-12:
                force_fn = _make_revolute_physics_friction_fn(joint_obj_num, exu, coulomb, pin_radius_mm * _MM_TO_M, viscous)
            else:
                force_fn = _make_constant_friction_fn(coulomb, viscous)
        else:
            marker_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.MARKER else joint.endpoint_b
            slider_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.SLIDER else joint.endpoint_b
            body = assembled.bodies[marker_endpoint.body_id]
            marker = body.markers[marker_endpoint.marker_id]
            slider = assembled.sliders[slider_endpoint.slider_id]
            lx, ly = _marker_local_rel_com(body, marker)
            relative_translation_marker = mbs.AddMarker(
                item_interface.MarkerBodiesRelativeTranslationCoordinate(
                    bodyNumbers=[ground_object, body_objects[body.body_id]],
                    localPosition0=[slider.origin_x * _MM_TO_M, slider.origin_y * _MM_TO_M, 0.0],
                    localPosition1=[lx * _MM_TO_M, ly * _MM_TO_M, 0.0],
                    axis0=[slider.axis_x, slider.axis_y, 0.0],
                    offset=0.0,
                )
            )
            friction_ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
            zero_coordinate_marker = mbs.AddMarker(
                item_interface.MarkerNodeCoordinate(nodeNumber=friction_ground_node, coordinate=0)
            )
            marker_numbers = [relative_translation_marker, zero_coordinate_marker]
            force_fn = _make_slider_physics_friction_fn(joint_obj_num, exu, coulomb, viscous)
        mbs.AddObject(
            item_interface.ObjectConnectorCoordinateSpringDamper(
                name=f"{joint.name}_friction",
                markerNumbers=marker_numbers,
                stiffness=0.0,
                damping=0.0,
                springForceUserFunction=force_fn,
            )
        )

    def _add_slider_limit_stops(self, mbs, item_interface, slider: AssembledSlider, body: AssembledBody, marker, body_object: int, ground_object: int) -> None:
        if slider.travel_min is None and slider.travel_max is None:
            return
        lx_lim, ly_lim = _marker_local_rel_com(body, marker)
        relative_translation_marker = mbs.AddMarker(
            item_interface.MarkerBodiesRelativeTranslationCoordinate(
                bodyNumbers=[ground_object, body_object],
                localPosition0=[slider.origin_x * _MM_TO_M, slider.origin_y * _MM_TO_M, 0.0],
                localPosition1=[lx_lim * _MM_TO_M, ly_lim * _MM_TO_M, 0.0],
                axis0=[slider.axis_x, slider.axis_y, 0.0],
                offset=0.0,
            )
        )
        limit_ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
        zero_coordinate_marker = mbs.AddMarker(
            item_interface.MarkerNodeCoordinate(nodeNumber=limit_ground_node, coordinate=0)
        )
        limit_data_node = mbs.AddNode(
            item_interface.NodeGenericData(
                initialCoordinates=[0.0, 0.0, 0.0],
                numberOfDataCoordinates=3,
            )
        )
        mbs.AddObject(
            item_interface.ObjectConnectorCoordinateSpringDamperExt(
                markerNumbers=[relative_translation_marker, zero_coordinate_marker],
                nodeNumber=limit_data_node,
                factor0=-1.0,
                factor1=1.0,
                stiffness=0.0,
                damping=0.0,
                useLimitStops=True,
                limitStopsLower=slider.travel_min * _MM_TO_M if slider.travel_min is not None else -1e30,
                limitStopsUpper=slider.travel_max * _MM_TO_M if slider.travel_max is not None else 1e30,
                limitStopsStiffness=1e6,
                limitStopsDamping=1e3,
            )
        )

    def _create_driver(
        self,
        mbs,
        item_interface,
        project: Project,
        assembled: AssembledMechanism,
        body_objects: dict[str, int],
        node_numbers: dict[str, int],
        ground_object: int,
        driver: AssembledDriver,
        *,
        translation_driver_mode: str = "constraint",
    ) -> None:
        joint = next(joint for joint in assembled.joints if joint.id == driver.target_joint_id)
        if driver.driver_type == DriverType.ROTATION.value:
            self._create_rotation_driver(mbs, item_interface, project, node_numbers, ground_object, driver, joint)
            return
        if driver.driver_type == DriverType.TRANSLATION.value:
            self._create_translation_driver(
                mbs,
                item_interface,
                project,
                assembled,
                body_objects,
                ground_object,
                driver,
                joint,
                mode=translation_driver_mode,
            )
            return
        raise ValueError(f"Unsupported driver type: {driver.driver_type}")

    def _create_rotation_driver(self, mbs, item_interface, project: Project, node_numbers: dict[str, int], ground_object: int, driver: AssembledDriver, joint) -> None:
        marker_numbers = self._rotation_coordinate_markers(mbs, item_interface, node_numbers, ground_object, joint)
        mbs.AddObject(
            item_interface.CoordinateConstraint(
                name=driver.name,
                markerNumbers=marker_numbers,
                offset=0.0,
                offsetUserFunction=self._make_offset_function(project, driver, Dimension.ANGLE),
                offsetUserFunction_t=self._make_offset_function_t(project, driver, Dimension.ANGLE),
            )
        )

    def _create_translation_driver(
        self,
        mbs,
        item_interface,
        project: Project,
        assembled: AssembledMechanism,
        body_objects: dict[str, int],
        ground_object: int,
        driver: AssembledDriver,
        joint,
        *,
        mode: str = "constraint",
    ) -> None:
        marker_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.MARKER else joint.endpoint_b
        slider_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.SLIDER else joint.endpoint_b
        body = assembled.bodies[marker_endpoint.body_id]
        marker = body.markers[marker_endpoint.marker_id]
        slider = assembled.sliders[slider_endpoint.slider_id]
        initial_coordinate = (
            (marker.global_x - slider.origin_x) * slider.axis_x
            + (marker.global_y - slider.origin_y) * slider.axis_y
        ) * _MM_TO_M
        lx_td, ly_td = _marker_local_rel_com(body, marker)
        relative_translation_marker = mbs.AddMarker(
            item_interface.MarkerBodiesRelativeTranslationCoordinate(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                localPosition0=[slider.origin_x * _MM_TO_M, slider.origin_y * _MM_TO_M, 0.0],
                localPosition1=[lx_td * _MM_TO_M, ly_td * _MM_TO_M, 0.0],
                axis0=[slider.axis_x, slider.axis_y, 0.0],
                offset=0.0,
            )
        )
        ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
        zero_coordinate_marker = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=ground_node, coordinate=0))
        if mode == "servo":
            mbs.AddObject(
                item_interface.ObjectConnectorCoordinateSpringDamper(
                    name=driver.name,
                    markerNumbers=[relative_translation_marker, zero_coordinate_marker],
                    stiffness=1e5,
                    damping=1e3,
                    springForceUserFunction=self._make_servo_force_function(
                        project,
                        driver,
                        Dimension.LENGTH,
                        base_value=initial_coordinate,
                    ),
                )
            )
            return
        mbs.AddObject(
            item_interface.CoordinateConstraint(
                name=driver.name,
                markerNumbers=[relative_translation_marker, zero_coordinate_marker],
                offset=0.0,
                offsetUserFunction=self._make_offset_function(
                    project,
                    driver,
                    Dimension.LENGTH,
                    base_value=initial_coordinate,
                    scale=-1.0,
                ),
                offsetUserFunction_t=self._make_offset_function_t(
                    project,
                    driver,
                    Dimension.LENGTH,
                    base_value=initial_coordinate,
                    scale=-1.0,
                ),
            )
        )

    def _has_translation_drivers(self, assembled: AssembledMechanism) -> bool:
        return any(driver.driver_type == DriverType.TRANSLATION.value for driver in assembled.drivers)

    def _rotation_coordinate_markers(self, mbs, item_interface, node_numbers: dict[str, int], ground_object: int, joint) -> list[int]:
        if joint.endpoint_a.kind is JointEndpointKind.MARKER and joint.endpoint_b.kind is JointEndpointKind.GROUND:
            ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
            marker_ground = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=ground_node, coordinate=0))
            marker_body = mbs.AddMarker(
                item_interface.MarkerNodeCoordinate(
                    nodeNumber=node_numbers[joint.endpoint_a.body_id],
                    coordinate=2,
                )
            )
            return [marker_ground, marker_body]
        if joint.endpoint_b.kind is JointEndpointKind.MARKER and joint.endpoint_a.kind is JointEndpointKind.GROUND:
            ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
            marker_ground = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=ground_node, coordinate=0))
            marker_body = mbs.AddMarker(
                item_interface.MarkerNodeCoordinate(
                    nodeNumber=node_numbers[joint.endpoint_b.body_id],
                    coordinate=2,
                )
            )
            return [marker_ground, marker_body]
        if joint.endpoint_a.kind is JointEndpointKind.MARKER and joint.endpoint_b.kind is JointEndpointKind.MARKER:
            marker_a = mbs.AddMarker(
                item_interface.MarkerNodeCoordinate(
                    nodeNumber=node_numbers[joint.endpoint_a.body_id],
                    coordinate=2,
                )
            )
            marker_b = mbs.AddMarker(
                item_interface.MarkerNodeCoordinate(
                    nodeNumber=node_numbers[joint.endpoint_b.body_id],
                    coordinate=2,
                )
            )
            return [marker_a, marker_b]
        raise ValueError(f"Rotation driver requires a revolute joint between marker-ground or marker-marker: {joint.name}")

    def _make_servo_force_function(
        self,
        project: Project,
        driver: AssembledDriver,
        expected_dimension: Dimension,
        *,
        base_value: float = 0.0,
    ):
        def spring_force_fn(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):
            target = base_value + self._evaluate_driver_value(project, driver, expected_dimension, float(t))
            target_velocity = self._evaluate_driver_rate(project, driver, expected_dimension, float(t))
            return stiffness * (target - coordinate) + damping * (target_velocity - velocity)

        return spring_force_fn

    def _evaluate_driver_value(self, project: Project, driver: AssembledDriver, expected_dimension: Dimension, time_value: float) -> float:
        quantity = self.expression_service.evaluate_expression(
            driver.law_expression,
            project.parameters,
            variables={"t": self.expression_service.unit_service.quantity(time_value, "s")},
        )
        if not quantity.is_pure(expected_dimension):
            raise ValueError(
                f"Driver {driver.name} expected {expected_dimension.value} but got {quantity.dimension_text}"
            )
        if expected_dimension is Dimension.ANGLE:
            output_unit = "rad"
        elif expected_dimension is Dimension.LENGTH:
            output_unit = "m"
        else:
            output_unit = driver.unit
        return self.expression_service.unit_service.convert(quantity, output_unit)

    def _evaluate_driver_rate(self, project: Project, driver: AssembledDriver, expected_dimension: Dimension, time_value: float) -> float:
        dt = 1e-6
        return (
            self._evaluate_driver_value(project, driver, expected_dimension, time_value + dt)
            - self._evaluate_driver_value(project, driver, expected_dimension, time_value - dt)
        ) / (2 * dt)

    def _make_offset_function(
        self,
        project: Project,
        driver: AssembledDriver,
        expected_dimension: Dimension,
        *,
        base_value: float = 0.0,
        scale: float = 1.0,
    ):
        def offset_fn(mbs, t, itemNumber, lOffset):
            return scale * (
                base_value + self._evaluate_driver_value(project, driver, expected_dimension, float(t))
            )

        return offset_fn

    def _make_offset_function_t(
        self,
        project: Project,
        driver: AssembledDriver,
        expected_dimension: Dimension,
        *,
        base_value: float = 0.0,
        scale: float = 1.0,
    ):
        offset_fn = self._make_offset_function(
            project,
            driver,
            expected_dimension,
            base_value=base_value,
            scale=scale,
        )

        def offset_fn_t(mbs, t, itemNumber, lOffset):
            dt = 1e-6
            return (offset_fn(mbs, t + dt, itemNumber, lOffset) - offset_fn(mbs, t - dt, itemNumber, lOffset)) / (2 * dt)

        return offset_fn_t

    def _collect_final_state(self, mbs, exu, assembled: AssembledMechanism, node_numbers: dict[str, int]) -> dict[str, float]:
        state: dict[str, float] = {}
        for body_id, node_number in node_numbers.items():
            coordinates = mbs.GetNodeOutput(node_number, exu.OutputVariableType.Coordinates)
            body = assembled.bodies[body_id]
            com_ref_x, com_ref_y = _body_com_global_mm(body)
            cur_angle = body.angle + (float(coordinates[2]) if len(coordinates) > 2 else 0.0)
            cos_a = math.cos(cur_angle)
            sin_a = math.sin(cur_angle)
            cur_com_x = com_ref_x + float(coordinates[0]) * _M_TO_MM
            cur_com_y = com_ref_y + float(coordinates[1]) * _M_TO_MM
            state[f"{body_id}.x"] = cur_com_x - cos_a * body.com_local_x + sin_a * body.com_local_y
            state[f"{body_id}.y"] = cur_com_y - sin_a * body.com_local_x - cos_a * body.com_local_y
            if len(coordinates) > 2:
                state[f"{body_id}.angle"] = self._equivalent_angle_near(cur_angle, body.angle)
        return state

    def _load_solution_frames(
        self,
        exu,
        mbs,
        solution_path: Path,
        assembled: AssembledMechanism,
        body_order: list[str],
        node_numbers: dict[str, int],
        allow_final_fallback: bool = True,
        project: Project | None = None,
    ):
        if not solution_path.exists():
            if allow_final_fallback:
                return [0.0], [self._collect_final_state(mbs, exu, assembled, node_numbers)]
            return [], []
        try:
            utilities = importlib.import_module("exudyn.utilities")
        except ImportError:
            if allow_final_fallback:
                return [0.0], [self._collect_final_state(mbs, exu, assembled, node_numbers)]
            return [], []
        solution = utilities.LoadSolutionFile(str(solution_path), verbose=False)
        data = solution["data"]
        if getattr(data, "ndim", 1) == 1:
            data = data.reshape(1, -1)
        frames: list[dict[str, float]] = []
        time: list[float] = []
        n_ode2 = int(solution["columnsExported"][0]) if solution.get("columnsExported") else len(body_order) * 3
        for row in data:
            time.append(float(row[0]))
            frame: dict[str, float] = {}
            for index, body_id in enumerate(body_order):
                start = 1 + index * 3
                if start + 2 > n_ode2:
                    break
                body = assembled.bodies[body_id]
                com_ref_x, com_ref_y = _body_com_global_mm(body)
                raw_angle = body.angle + float(row[start + 2])
                cos_a = math.cos(raw_angle)
                sin_a = math.sin(raw_angle)
                cur_com_x = com_ref_x + float(row[start]) * _M_TO_MM
                cur_com_y = com_ref_y + float(row[start + 1]) * _M_TO_MM
                frame[f"{body_id}.x"] = cur_com_x - cos_a * body.com_local_x + sin_a * body.com_local_y
                frame[f"{body_id}.y"] = cur_com_y - sin_a * body.com_local_x - cos_a * body.com_local_y
                previous_angle = frames[-1].get(f"{body_id}.angle", body.angle) if frames else body.angle
                frame[f"{body_id}.angle"] = self._equivalent_angle_near(raw_angle, previous_angle)
            if frame:
                frames.append(frame)
        if not frames:
            if allow_final_fallback:
                return [0.0], [self._collect_final_state(mbs, exu, assembled, node_numbers)]
            return [], []
        if project:
            self._record_sensor_data(project, assembled, body_order, time, frames)
        return time, frames

    def _equivalent_angle_near(self, angle: float, reference: float) -> float:
        two_pi = 2.0 * math.pi
        return reference + math.atan2(math.sin(angle - reference), math.cos(angle - reference))

    def _record_sensor_data(
        self,
        project: Project,
        assembled: AssembledMechanism,
        body_order: list[str],
        time: list[float],
        frames: list[dict[str, float]],
    ) -> None:
        for sensor in project.model.sensors:
            output = SensorOutput(sensor_id=sensor.id, time=list(time))
            if sensor.type.value == "point":
                self._record_point_sensor(output, sensor, assembled, frames)
            elif sensor.type.value == "distance":
                self._record_distance_sensor(output, sensor, assembled, frames)
            elif sensor.type.value in {"angle_horizontal", "angle_vertical"}:
                self._record_angle_sensor(output, sensor, assembled, frames)
            elif sensor.type.value == "angle_vector":
                self._record_angle_vector_sensor(output, sensor, assembled, frames)
            if output.columns and output.data:
                project.sensor_outputs[sensor.id] = output

    def _marker_global_pos(
        self, assembled: AssembledMechanism, body_id: str, marker_id: str, frame: dict[str, float]
    ) -> tuple[float, float]:
        body = assembled.bodies[body_id]
        assembled_marker = body.markers[marker_id]
        bx = frame.get(f"{body_id}.x", 0.0)
        by = frame.get(f"{body_id}.y", 0.0)
        ba = frame.get(f"{body_id}.angle", body.angle)
        cos_a = math.cos(ba)
        sin_a = math.sin(ba)
        lx = assembled_marker.local_x
        ly = assembled_marker.local_y
        return bx + cos_a * lx - sin_a * ly, by + sin_a * lx + cos_a * ly

    def _record_point_sensor(
        self, output: SensorOutput, sensor, assembled: AssembledMechanism, frames: list[dict[str, float]]
    ) -> None:
        if len(sensor.marker_ids) != 1:
            return
        marker_id = sensor.marker_ids[0]
        body_id = self._find_body_id_for_marker(assembled, marker_id)
        if not body_id:
            return
        output.columns = ["x [mm]", "y [mm]", "vx [mm/s]", "vy [mm/s]", "v [mm/s]", "ax [mm/s²]", "ay [mm/s²]", "a [mm/s²]"]
        positions: list[tuple[float, float]] = []
        for frame in frames:
            positions.append(self._marker_global_pos(assembled, body_id, marker_id, frame))
        for i, (x, y) in enumerate(positions):
            vx = vy = 0.0
            if i > 0:
                dt = output.time[i] - output.time[i - 1]
                if dt > 0:
                    vx = (x - positions[i - 1][0]) / dt
                    vy = (y - positions[i - 1][1]) / dt
            v = math.sqrt(vx**2 + vy**2)
            ax = ay = 0.0
            if i > 1:
                dt = output.time[i] - output.time[i - 1]
                dt_prev = output.time[i - 1] - output.time[i - 2]
                if dt > 0 and dt_prev > 0:
                    prev_vx = (positions[i - 1][0] - positions[i - 2][0]) / dt_prev
                    prev_vy = (positions[i - 1][1] - positions[i - 2][1]) / dt_prev
                    ax = (vx - prev_vx) / dt
                    ay = (vy - prev_vy) / dt
            a = math.sqrt(ax**2 + ay**2)
            output.data.append([x, y, vx, vy, v, ax, ay, a])

    def _record_distance_sensor(
        self, output: SensorOutput, sensor, assembled: AssembledMechanism, frames: list[dict[str, float]]
    ) -> None:
        if len(sensor.marker_ids) != 2:
            return
        marker_id_a, marker_id_b = sensor.marker_ids
        body_id_a = self._find_body_id_for_marker(assembled, marker_id_a)
        body_id_b = self._find_body_id_for_marker(assembled, marker_id_b)
        if not body_id_a or not body_id_b:
            return
        output.columns = ["distance [mm]", "velocity [mm/s]", "acceleration [mm/s²]"]
        distances: list[float] = []
        for frame in frames:
            xa, ya = self._marker_global_pos(assembled, body_id_a, marker_id_a, frame)
            xb, yb = self._marker_global_pos(assembled, body_id_b, marker_id_b, frame)
            distances.append(math.sqrt((xb - xa) ** 2 + (yb - ya) ** 2))
        for i, distance in enumerate(distances):
            velocity = 0.0
            if i > 0:
                dt = output.time[i] - output.time[i - 1]
                velocity = (distance - distances[i - 1]) / dt if dt > 0 else 0.0
            acceleration = 0.0
            if i > 1:
                dt = output.time[i] - output.time[i - 1]
                dt_prev = output.time[i - 1] - output.time[i - 2]
                if dt > 0 and dt_prev > 0:
                    prev_vel = (distances[i - 1] - distances[i - 2]) / dt_prev
                    acceleration = (velocity - prev_vel) / dt
            output.data.append([distance, velocity, acceleration])

    def _record_angle_sensor(
        self, output: SensorOutput, sensor, assembled: AssembledMechanism, frames: list[dict[str, float]]
    ) -> None:
        if len(sensor.marker_ids) != 2:
            return
        reference_axis = "horizontal" if "horizontal" in sensor.type.value else "vertical"
        marker_id_a, marker_id_b = sensor.marker_ids
        body_id_a = self._find_body_id_for_marker(assembled, marker_id_a)
        body_id_b = self._find_body_id_for_marker(assembled, marker_id_b)
        if not body_id_a or not body_id_b:
            return
        output.columns = ["angle [deg]", "angular_velocity [deg/s]", "angular_acceleration [deg/s²]"]
        angles: list[float] = []
        for frame in frames:
            xa, ya = self._marker_global_pos(assembled, body_id_a, marker_id_a, frame)
            xb, yb = self._marker_global_pos(assembled, body_id_b, marker_id_b, frame)
            dx, dy = xb - xa, yb - ya
            angle_rad = math.atan2(dy, dx) if reference_axis == "horizontal" else math.atan2(dx, dy)
            angles.append(math.degrees(angle_rad))
        for i, angle_deg in enumerate(angles):
            angular_velocity = 0.0
            if i > 0:
                dt = output.time[i] - output.time[i - 1]
                if dt > 0:
                    angle_diff = angle_deg - angles[i - 1]
                    if angle_diff > 180:
                        angle_diff -= 360
                    elif angle_diff < -180:
                        angle_diff += 360
                    angular_velocity = angle_diff / dt
            angular_acceleration = 0.0
            if i > 1:
                dt = output.time[i] - output.time[i - 1]
                dt_prev = output.time[i - 1] - output.time[i - 2]
                if dt > 0 and dt_prev > 0:
                    diff_prev = angles[i - 1] - angles[i - 2]
                    if diff_prev > 180:
                        diff_prev -= 360
                    elif diff_prev < -180:
                        diff_prev += 360
                    prev_vel = diff_prev / dt_prev
                    angular_acceleration = (angular_velocity - prev_vel) / dt
            output.data.append([angle_deg, angular_velocity, angular_acceleration])

    def _record_angle_vector_sensor(
        self, output: SensorOutput, sensor, assembled: AssembledMechanism, frames: list[dict[str, float]]
    ) -> None:
        if len(sensor.marker_ids) != 4:
            return
        m_a_id, m_b_id, m_c_id, m_d_id = sensor.marker_ids
        body_a = self._find_body_id_for_marker(assembled, m_a_id)
        body_b = self._find_body_id_for_marker(assembled, m_b_id)
        body_c = self._find_body_id_for_marker(assembled, m_c_id)
        body_d = self._find_body_id_for_marker(assembled, m_d_id)
        if not all([body_a, body_b, body_c, body_d]):
            return
        output.columns = ["angle [deg]", "angular_velocity [deg/s]", "angular_acceleration [deg/s²]"]
        angles: list[float] = []
        for frame in frames:
            xa, ya = self._marker_global_pos(assembled, body_a, m_a_id, frame)
            xb, yb = self._marker_global_pos(assembled, body_b, m_b_id, frame)
            xc, yc = self._marker_global_pos(assembled, body_c, m_c_id, frame)
            xd, yd = self._marker_global_pos(assembled, body_d, m_d_id, frame)
            angle1 = math.atan2(yb - ya, xb - xa)
            angle2 = math.atan2(yd - yc, xd - xc)
            angle_diff_rad = angle2 - angle1
            if angle_diff_rad > math.pi:
                angle_diff_rad -= 2 * math.pi
            elif angle_diff_rad < -math.pi:
                angle_diff_rad += 2 * math.pi
            angles.append(math.degrees(angle_diff_rad))
        for i, angle_deg in enumerate(angles):
            angular_velocity = 0.0
            if i > 0:
                dt = output.time[i] - output.time[i - 1]
                if dt > 0:
                    angle_diff = angle_deg - angles[i - 1]
                    if angle_diff > 180:
                        angle_diff -= 360
                    elif angle_diff < -180:
                        angle_diff += 360
                    angular_velocity = angle_diff / dt
            angular_acceleration = 0.0
            if i > 1:
                dt = output.time[i] - output.time[i - 1]
                dt_prev = output.time[i - 1] - output.time[i - 2]
                if dt > 0 and dt_prev > 0:
                    diff_prev = angles[i - 1] - angles[i - 2]
                    if diff_prev > 180:
                        diff_prev -= 360
                    elif diff_prev < -180:
                        diff_prev += 360
                    prev_vel = diff_prev / dt_prev
                    angular_acceleration = (angular_velocity - prev_vel) / dt
            output.data.append([angle_deg, angular_velocity, angular_acceleration])

    def _find_body_id_for_marker(self, assembled: AssembledMechanism, marker_id: str) -> str | None:
        for body_id, body in assembled.bodies.items():
            if marker_id in body.markers:
                return body_id
        return None

    # ------------------------------------------------------------------
    # Reaction force helpers
    # ------------------------------------------------------------------

    def _reaction_joint_info(
        self,
        assembled: AssembledMechanism,
        joint_objects: dict[str, int],
    ) -> list[tuple[str, str, str, str | None, float, float]]:
        """Return metadata for joints whose reactions we should capture.

        Each entry: (joint_id, joint_name, endpoint_type, slider_id_or_None, normal_x, normal_y)
        """
        result = []
        for joint in assembled.joints:
            ep_a = joint.endpoint_a
            ep_b = joint.endpoint_b
            is_ground = ep_a.kind is JointEndpointKind.GROUND or ep_b.kind is JointEndpointKind.GROUND
            is_slider = ep_a.kind is JointEndpointKind.SLIDER or ep_b.kind is JointEndpointKind.SLIDER
            if not (is_ground or is_slider):
                continue
            if joint.id not in joint_objects:
                continue
            if is_slider:
                slider_ep = ep_a if ep_a.kind is JointEndpointKind.SLIDER else ep_b
                slider = assembled.sliders.get(slider_ep.slider_id)
                nx = slider.normal_x if slider else 0.0
                ny = slider.normal_y if slider else 0.0
                result.append((joint.id, joint.name, "slider", slider_ep.slider_id, nx, ny))
            else:
                result.append((joint.id, joint.name, "ground", None, 0.0, 0.0))
        return result

    def _reaction_joint_marker_ep(
        self, assembled: AssembledMechanism, joint_id: str
    ) -> tuple[str | None, str | None]:
        """Return (body_id, marker_id) for the MARKER endpoint of a ground/slider joint."""
        for joint in assembled.joints:
            if joint.id != joint_id:
                continue
            ep_a, ep_b = joint.endpoint_a, joint.endpoint_b
            if ep_a.kind is JointEndpointKind.MARKER:
                return ep_a.body_id, ep_a.marker_id
            if ep_b.kind is JointEndpointKind.MARKER:
                return ep_b.body_id, ep_b.marker_id
        return None, None

    def _build_reaction_positions(
        self,
        assembled: AssembledMechanism,
        frames: list[dict[str, float]],
        body_id: str,
        marker_id: str,
    ) -> list[tuple[float, float]]:
        """Return world-space mm positions of a marker for each simulation frame."""
        positions = []
        for frame in frames:
            x, y = self._marker_global_pos(assembled, body_id, marker_id, frame)
            positions.append((x, y))
        return positions

    def _load_sensor_file(self, path) -> list[list[float]]:
        """Parse an Exudyn sensor output file into a list of numeric rows."""
        path = Path(path)
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rows.append([float(v) for v in line.split()])
            except ValueError:
                continue
        return rows

    def _resample_sensor_to_time_axis(
        self,
        sensor_rows: list[list[float]],
        target_times: list[float],
    ) -> list[list[float]]:
        """For each target time, find the nearest sensor row and return its value columns."""
        if not sensor_rows or not target_times:
            return []
        result = []
        for t_target in target_times:
            best = min(sensor_rows, key=lambda row: abs(row[0] - t_target))
            result.append(best[1:])
        return result

    def _make_slider_reaction_sensor_fn(self, joint_obj_num: int, nx: float, ny: float, log: list, exu):
        """SensorUserFunction that records Lagrange multiplier × normal after each converged step."""
        def fn(mbs, t, sensorNumbers, factors, configuration):
            try:
                raw = mbs.GetObjectOutput(joint_obj_num, exu.OutputVariableType.Force)
                lam = float(raw[0]) if hasattr(raw, "__len__") else float(raw)
                fx = lam * nx
                fy = lam * ny
            except Exception:
                fx, fy = 0.0, 0.0
            log.append([float(t), fx, fy])
            return [fx, fy]
        return fn

    def _make_ground_reaction_sensor_fn(self, joint_obj_num: int, log: list):
        """SensorUserFunction that records revolute joint reaction force from AE Lagrange multipliers."""
        def fn(mbs, t, sensorNumbers, factors, configuration):
            try:
                ae = mbs.systemData.GetAECoordinates()
                ltg = mbs.systemData.GetObjectLTGAE(joint_obj_num)
                fx = -float(ae[ltg[0]])
                fy = -float(ae[ltg[1]])
            except Exception:
                fx, fy = 0.0, 0.0
            log.append([float(t), fx, fy])
            return [fx, fy]
        return fn



    def _record_reaction_data_dynamic(
        self,
        project: Project,
        assembled: AssembledMechanism,
        time: list[float],
        frames: list[dict[str, float]],
        reaction_info: list[tuple],
        reaction_logs: dict[str, list[list[float]]],
    ) -> None:
        """Populate project.reaction_outputs from dynamic solve frames."""
        for joint_id, joint_name, endpoint_type, _slider_id, nx, ny in reaction_info:
            body_id, marker_id = self._reaction_joint_marker_ep(assembled, joint_id)
            if body_id is None:
                continue
            positions = self._build_reaction_positions(assembled, frames, body_id, marker_id)
            if endpoint_type == "ground":
                rows = reaction_logs.get(joint_id, [])
                values = self._resample_sensor_to_time_axis(rows, time)
                force_rows = [[v[0] if len(v) > 0 else 0.0, v[1] if len(v) > 1 else 0.0] for v in values]
            else:
                rows = reaction_logs.get(joint_id, [])
                values = self._resample_sensor_to_time_axis(rows, time)
                force_rows = [[v[0] if len(v) > 0 else 0.0, v[1] if len(v) > 1 else 0.0] for v in values]
            if not force_rows:
                continue
            data: list[list[float]] = []
            for frow in force_rows:
                fx = frow[0]
                fy = frow[1]
                data.append([fx, fy, math.sqrt(fx * fx + fy * fy)])
            project.reaction_outputs[joint_id] = ReactionOutput(
                joint_id=joint_id,
                joint_name=joint_name,
                endpoint_type=endpoint_type,
                time=list(time),
                columns=["Fx [N]", "Fy [N]", "F [N]"],
                data=data,
                positions=positions,
            )

    def _record_reaction_data_static(
        self,
        project: Project,
        assembled: AssembledMechanism,
        mbs,
        exu,
        time: list[float],
        frames: list[dict[str, float]],
        reaction_info: list[tuple],
        joint_objects: dict[str, int],
    ) -> None:
        """Populate project.reaction_outputs via GetObjectOutput after static/no-driver solve."""
        for joint_id, joint_name, endpoint_type, slider_id, normal_x, normal_y in reaction_info:
            if endpoint_type == "ground":
                joint_obj_num = joint_objects.get(joint_id)
                if joint_obj_num is None:
                    continue
                try:
                    ae = mbs.systemData.GetAECoordinates()
                    ltg = mbs.systemData.GetObjectLTGAE(joint_obj_num)
                    fx = -float(ae[ltg[0]])
                    fy = -float(ae[ltg[1]])
                except Exception:
                    continue
            else:
                joint_obj_num = joint_objects.get(joint_id)
                if joint_obj_num is None:
                    continue
                try:
                    raw = mbs.GetObjectOutput(joint_obj_num, exu.OutputVariableType.Force)
                    lam = float(raw[0]) if hasattr(raw, "__len__") else float(raw)
                    fx = lam * normal_x
                    fy = lam * normal_y
                except Exception:
                    continue
            f_mag = math.sqrt(fx * fx + fy * fy)
            body_id, marker_id = self._reaction_joint_marker_ep(assembled, joint_id)
            if body_id is None:
                continue
            positions = self._build_reaction_positions(assembled, frames, body_id, marker_id)
            project.reaction_outputs[joint_id] = ReactionOutput(
                joint_id=joint_id,
                joint_name=joint_name,
                endpoint_type=endpoint_type,
                time=list(time),
                columns=["Fx [N]", "Fy [N]", "F [N]"],
                data=[[fx, fy, f_mag]] * len(frames),
                positions=positions,
            )

    def _project_diagnostics(self, project: Project) -> list[str]:
        lines = [
            (
                "Model summary: "
                f"bodies={len(project.model.bodies)}, "
                f"markers={sum(len(body.markers) for body in project.model.bodies)}, "
                f"sliders={len(project.model.sliders)}, "
                f"joints={len(project.model.joints)}, "
                f"drivers={len(project.model.drivers)}"
            )
        ]
        for body in project.model.bodies:
            lines.append(
                f"Body {body.name}: type={body.type.value}, structural_markers={len(body.structural_markers())}"
            )
        for joint in project.model.joints:
            lines.append(
                f"Joint {joint.name}: type={joint.type.value}, "
                f"a={joint.endpoint_a.kind.value}:{joint.endpoint_a.marker_id or joint.endpoint_a.slider_id or 'ground'}, "
                f"b={joint.endpoint_b.kind.value}:{joint.endpoint_b.marker_id or joint.endpoint_b.slider_id or 'ground'}"
            )
        for driver in project.model.drivers:
            lines.append(
                f"Driver {driver.name}: type={driver.type.value}, target_joint={driver.target_joint_id}, law={driver.law.expression}"
            )
        return lines

    def _format_exception(self, exc: Exception) -> str:
        traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=12)).strip()
        return f"{type(exc).__name__}: {exc}\n{traceback_text}"
