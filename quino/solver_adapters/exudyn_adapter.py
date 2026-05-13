from __future__ import annotations

import importlib
import math
from pathlib import Path
import tempfile
import traceback

from quino.domain.model import Project, SensorOutput, SimulationResult
from quino.domain.types import Dimension, DriverType, JointEndpointKind, JointType
from quino.services.expressions import ExpressionService
from quino.simulation.assembler import (
    AssembledBody,
    AssembledDriver,
    AssembledLoad,
    AssembledMechanism,
    AssembledSlider,
    MechanismAssembler,
)
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
        for joint in assembled.joints:
            self._create_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint)
        for joint in assembled.joints:
            self._add_joint_friction(mbs, item_interface, assembled, node_numbers, body_objects, ground_object, joint)
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
            self._create_load(mbs, item_interface, assembled, body_objects, load)
        mbs.Assemble()
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
                with tempfile.TemporaryDirectory(prefix="quino_exudyn_") as temp_dir:
                    solution_path = Path(temp_dir) / "solution.txt"
                    simulation_settings.solutionSettings.writeSolutionToFile = True
                    simulation_settings.solutionSettings.coordinatesSolutionFileName = str(solution_path)
                    simulation_settings.solutionSettings.solutionWritePeriod = duration / max(steps, 1)
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
                messages.append("Exudyn dynamic solve completed")
            elif solve_mode == "static":
                simulation_settings = exu.SimulationSettings()
                simulation_settings.staticSolver.numberOfLoadSteps = 100
                simulation_settings.solutionSettings.writeSolutionToFile = False
                mbs.SolveStatic(simulationSettings=simulation_settings)
                final_state = self._collect_final_state(mbs, exu, assembled, node_numbers)
                time = [duration]
                frames = [final_state]
                warnings.append("Dynamic solve fallback used; returning a single static frame")
                messages.append("Exudyn static fallback completed")
            else:
                raise ValueError(f"Unsupported Exudyn solve mode: {solve_mode}")
        else:
            time = [0.0]
            frames = [self._collect_final_state(mbs, exu, assembled, node_numbers)]
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
            if body.mass > 0 and assembled.gravity.enabled:
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

    def _create_joint(self, mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint) -> None:
        a = joint.endpoint_a
        b = joint.endpoint_b
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.MARKER:
            self._create_marker_to_marker_joint(mbs, item_interface, assembled, body_objects, node_numbers, a, b, joint.type)
            return
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.GROUND:
            self._create_marker_to_ground_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, a, joint.type)
            return
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.SLIDER:
            self._create_marker_to_slider_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, a, b, joint.type, joint.name)
            return
        if b.kind is JointEndpointKind.MARKER and a.kind is JointEndpointKind.GROUND:
            self._create_marker_to_ground_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, b, joint.type)
            return
        if b.kind is JointEndpointKind.MARKER and a.kind is JointEndpointKind.SLIDER:
            self._create_marker_to_slider_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, b, a, joint.type, joint.name)
            return
        raise ValueError(f"Unsupported joint topology for Exudyn adapter: {joint.name}")

    def _find_body_for_marker(self, assembled: AssembledMechanism, marker_id: str) -> AssembledBody:
        for body in assembled.bodies.values():
            if marker_id in body.markers:
                return body
        raise ValueError(f"Marker {marker_id} not found in any body")

    def _create_load(self, mbs, item_interface, assembled, body_objects, load: AssembledLoad) -> None:
        body = self._find_body_for_marker(assembled, load.target_marker_id)
        marker = body.markers[load.target_marker_id]
        lx, ly = _marker_local_rel_com(body, marker)
        load_marker = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=body_objects[body.body_id],
                localPosition=[lx * _MM_TO_M, ly * _MM_TO_M, 0.0],
            )
        )
        mbs.AddLoad(
            item_interface.LoadForceVector(
                markerNumber=load_marker,
                loadVector=[load.fx, load.fy, 0.0],
            )
        )

    def _create_marker_to_marker_joint(self, mbs, item_interface, assembled, body_objects, node_numbers, endpoint_a, endpoint_b, joint_type) -> None:
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
        mbs.AddObject(item_interface.ObjectJointRevolute2D(markerNumbers=[marker_number_a, marker_number_b]))
        if joint_type is JointType.RIGID:
            mbs.CreateCoordinateConstraint(
                bodyNumbers=[body_objects[body_a.body_id], body_objects[body_b.body_id]],
                coordinates=[2, 2],
                offset=0.0,
            )

    def _create_marker_to_ground_joint(
        self, mbs, item_interface, assembled, body_objects, node_numbers, ground_object, endpoint, joint_type
    ) -> None:
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
        mbs.AddObject(item_interface.ObjectJointRevolute2D(markerNumbers=[ground_marker, body_marker]))
        if joint_type is JointType.RIGID:
            mbs.CreateCoordinateConstraint(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                coordinates=[None, 2],
                offset=0.0,
            )

    def _create_marker_to_slider_joint(
        self, mbs, item_interface, assembled, body_objects, node_numbers, ground_object, endpoint_a, endpoint_b, joint_type, joint_name
    ) -> None:
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
        mbs.AddObject(
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

    def _add_joint_friction(
        self,
        mbs,
        item_interface,
        assembled: AssembledMechanism,
        node_numbers: dict[str, int],
        body_objects: dict[str, int],
        ground_object: int,
        joint: Joint,
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
        if mode == "rotation":
            marker_numbers = self._rotation_coordinate_markers(mbs, item_interface, node_numbers, ground_object, joint)
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
        mbs.AddObject(
            item_interface.ObjectConnectorCoordinateSpringDamper(
                name=f"{joint.name}_friction",
                markerNumbers=marker_numbers,
                stiffness=0.0,
                damping=0.0,
                springForceUserFunction=self._make_friction_force_function(coulomb, viscous),
            )
        )

    def _make_friction_force_function(self, coulomb: float, viscous: float):
        def friction_force_fn(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):
            sign = 1.0 if velocity > 1e-12 else -1.0 if velocity < -1e-12 else 0.0
            return -(viscous * float(velocity) + coulomb * sign)

        return friction_force_fn

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
