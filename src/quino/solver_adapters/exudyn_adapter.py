from __future__ import annotations

import importlib
import math
from pathlib import Path
import tempfile

from quino.domain.model import Project, SimulationResult
from quino.domain.types import Dimension, DriverType, JointEndpointKind, JointType
from quino.services.expressions import ExpressionService
from quino.simulation.assembler import (
    AssembledBody,
    AssembledDriver,
    AssembledMechanism,
    AssembledSlider,
    MechanismAssembler,
)
from quino.solver_adapters.base import SolverAdapter


class ExudynAdapter(SolverAdapter):
    name = "exudyn"

    def __init__(self, expression_service: ExpressionService) -> None:
        self.expression_service = expression_service
        self.assembler = MechanismAssembler(expression_service)

    def is_available(self) -> bool:
        return importlib.util.find_spec("exudyn") is not None

    def run(self, project: Project, duration: float = 1.0, steps: int = 100) -> SimulationResult:
        assembled = self.assembler.assemble(project)
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
                    return fallback
                except Exception:
                    pass
            return SimulationResult(
                success=False,
                backend=self.name,
                warnings=list(assembled.warnings),
                messages=["Exudyn execution failed"],
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
    ) -> SimulationResult:
        item_interface = importlib.import_module("exudyn.itemInterface")
        sc = exu.SystemContainer()
        mbs = sc.AddSystem()
        ground_object = mbs.AddObject(item_interface.ObjectGround())
        body_objects, node_numbers, body_order = self._create_bodies(mbs, item_interface, assembled)
        for joint in assembled.joints:
            self._create_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint)
        for driver in assembled.drivers:
            self._create_driver(mbs, item_interface, project, assembled, body_objects, node_numbers, ground_object, driver)
        mbs.Assemble()
        time: list[float] = []
        frames: list[dict[str, float]] = []
        warnings = list(assembled.warnings)
        messages = ["Exudyn model assembled"]
        messages.extend(f"Assembly warning: {warning}" for warning in assembled.warnings)
        for body in assembled.bodies.values():
            warnings.extend(body.warnings)
            messages.extend(f"Body warning: {warning}" for warning in body.warnings)
        if assembled.drivers:
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
                    mbs.SolveDynamic(simulationSettings=simulation_settings)
                    time, frames = self._load_solution_frames(
                        exu,
                        mbs,
                        solution_path,
                        assembled,
                        body_order,
                        node_numbers,
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
            node = mbs.AddNode(
                item_interface.NodeRigidBody2D(
                    referenceCoordinates=[body.origin_x, body.origin_y, body.angle]
                )
            )
            body_object = mbs.AddObject(
                item_interface.ObjectRigidBody2D(
                    nodeNumber=node,
                    physicsMass=body.mass,
                    physicsInertia=body.inertia,
                    physicsCenterOfMass=[body.com_local_x, body.com_local_y],
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
            self._create_marker_to_marker_joint(mbs, item_interface, assembled, body_objects, node_numbers, joint)
            return
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.GROUND:
            self._create_marker_to_ground_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint)
            return
        if a.kind is JointEndpointKind.MARKER and b.kind is JointEndpointKind.SLIDER:
            self._create_marker_to_slider_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint)
            return
        if b.kind is JointEndpointKind.MARKER and a.kind is JointEndpointKind.GROUND:
            swapped = joint
            swapped.endpoint_a, swapped.endpoint_b = joint.endpoint_b, joint.endpoint_a
            self._create_marker_to_ground_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, swapped)
            swapped.endpoint_a, swapped.endpoint_b = joint.endpoint_a, joint.endpoint_b
            return
        if b.kind is JointEndpointKind.MARKER and a.kind is JointEndpointKind.SLIDER:
            swapped = joint
            swapped.endpoint_a, swapped.endpoint_b = joint.endpoint_b, joint.endpoint_a
            self._create_marker_to_slider_joint(mbs, item_interface, assembled, body_objects, node_numbers, ground_object, swapped)
            swapped.endpoint_a, swapped.endpoint_b = joint.endpoint_a, joint.endpoint_b
            return
        raise ValueError(f"Unsupported joint topology for Exudyn adapter: {joint.name}")

    def _create_marker_to_marker_joint(self, mbs, item_interface, assembled, body_objects, node_numbers, joint) -> None:
        body_a = assembled.bodies[joint.endpoint_a.body_id]
        body_b = assembled.bodies[joint.endpoint_b.body_id]
        marker_a = body_a.markers[joint.endpoint_a.marker_id]
        marker_b = body_b.markers[joint.endpoint_b.marker_id]
        marker_number_a = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=body_objects[body_a.body_id],
                localPosition=[marker_a.local_x, marker_a.local_y, 0.0],
            )
        )
        marker_number_b = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=body_objects[body_b.body_id],
                localPosition=[marker_b.local_x, marker_b.local_y, 0.0],
            )
        )
        mbs.AddObject(item_interface.ObjectJointRevolute2D(markerNumbers=[marker_number_a, marker_number_b]))
        if joint.type is JointType.RIGID:
            mbs.CreateCoordinateConstraint(
                bodyNumbers=[body_objects[body_a.body_id], body_objects[body_b.body_id]],
                coordinates=[2, 2],
                offset=0.0,
            )

    def _create_marker_to_ground_joint(
        self, mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint
    ) -> None:
        body = assembled.bodies[joint.endpoint_a.body_id]
        marker = body.markers[joint.endpoint_a.marker_id]
        ground_marker = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=ground_object,
                localPosition=[marker.global_x, marker.global_y, 0.0],
            )
        )
        body_marker = mbs.AddMarker(
            item_interface.MarkerBodyRigid(
                bodyNumber=body_objects[body.body_id],
                localPosition=[marker.local_x, marker.local_y, 0.0],
            )
        )
        mbs.AddObject(item_interface.ObjectJointRevolute2D(markerNumbers=[ground_marker, body_marker]))
        if joint.type is JointType.RIGID:
            mbs.CreateCoordinateConstraint(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                coordinates=[None, 2],
                offset=0.0,
            )

    def _create_marker_to_slider_joint(
        self, mbs, item_interface, assembled, body_objects, node_numbers, ground_object, joint
    ) -> None:
        body = assembled.bodies[joint.endpoint_a.body_id]
        marker = body.markers[joint.endpoint_a.marker_id]
        slider = assembled.sliders[joint.endpoint_b.slider_id]
        normal_translation_marker = mbs.AddMarker(
            item_interface.MarkerBodiesRelativeTranslationCoordinate(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                localPosition0=[slider.origin_x, slider.origin_y, 0.0],
                localPosition1=[marker.local_x, marker.local_y, 0.0],
                axis0=[slider.normal_x, slider.normal_y, 0.0],
                offset=0.0,
            )
        )
        ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
        zero_coordinate_marker = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=ground_node, coordinate=0))
        mbs.AddObject(
            item_interface.CoordinateConstraint(
                name=joint.name,
                markerNumbers=[normal_translation_marker, zero_coordinate_marker],
                offset=0.0,
            )
        )
        if joint.type is JointType.RIGID:
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

    def _add_slider_limit_stops(self, mbs, item_interface, slider: AssembledSlider, body: AssembledBody, marker, body_object: int, ground_object: int) -> None:
        if slider.travel_min is None and slider.travel_max is None:
            return
        relative_translation_marker = mbs.AddMarker(
            item_interface.MarkerBodiesRelativeTranslationCoordinate(
                bodyNumbers=[ground_object, body_object],
                localPosition0=[slider.origin_x, slider.origin_y, 0.0],
                localPosition1=[marker.local_x, marker.local_y, 0.0],
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
                limitStopsLower=slider.travel_min if slider.travel_min is not None else -1e30,
                limitStopsUpper=slider.travel_max if slider.travel_max is not None else 1e30,
                limitStopsStiffness=1e6,
                limitStopsDamping=1e3,
            )
        )

    def _create_driver(self, mbs, item_interface, project: Project, assembled: AssembledMechanism, body_objects: dict[str, int], node_numbers: dict[str, int], ground_object: int, driver: AssembledDriver) -> None:
        joint = next(joint for joint in assembled.joints if joint.id == driver.target_joint_id)
        if driver.driver_type == DriverType.ROTATION.value:
            self._create_rotation_driver(mbs, item_interface, project, node_numbers, ground_object, driver, joint)
            return
        if driver.driver_type == DriverType.TRANSLATION.value:
            self._create_translation_driver(mbs, item_interface, project, assembled, body_objects, ground_object, driver, joint)
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

    def _create_translation_driver(self, mbs, item_interface, project: Project, assembled: AssembledMechanism, body_objects: dict[str, int], ground_object: int, driver: AssembledDriver, joint) -> None:
        marker_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.MARKER else joint.endpoint_b
        slider_endpoint = joint.endpoint_a if joint.endpoint_a.kind is JointEndpointKind.SLIDER else joint.endpoint_b
        body = assembled.bodies[marker_endpoint.body_id]
        marker = body.markers[marker_endpoint.marker_id]
        slider = assembled.sliders[slider_endpoint.slider_id]
        relative_translation_marker = mbs.AddMarker(
            item_interface.MarkerBodiesRelativeTranslationCoordinate(
                bodyNumbers=[ground_object, body_objects[body.body_id]],
                localPosition0=[slider.origin_x, slider.origin_y, 0.0],
                localPosition1=[marker.local_x, marker.local_y, 0.0],
                axis0=[slider.axis_x, slider.axis_y, 0.0],
                offset=0.0,
            )
        )
        ground_node = mbs.AddNode(item_interface.NodePointGround(referenceCoordinates=[0.0, 0.0, 0.0]))
        zero_coordinate_marker = mbs.AddMarker(item_interface.MarkerNodeCoordinate(nodeNumber=ground_node, coordinate=0))
        mbs.AddObject(
            item_interface.ObjectConnectorCoordinateSpringDamper(
                name=driver.name,
                markerNumbers=[relative_translation_marker, zero_coordinate_marker],
                stiffness=1e5,
                damping=1e3,
                springForceUserFunction=self._make_servo_force_function(project, driver, Dimension.LENGTH),
            )
        )

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

    def _make_servo_force_function(self, project: Project, driver: AssembledDriver, expected_dimension: Dimension):
        def spring_force_fn(mbs, t, itemNumber, coordinate, velocity, stiffness, damping, offset):
            target = self._evaluate_driver_value(project, driver, expected_dimension, float(t))
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
        output_unit = "rad" if expected_dimension is Dimension.ANGLE else driver.unit
        return self.expression_service.unit_service.convert(quantity, output_unit)

    def _evaluate_driver_rate(self, project: Project, driver: AssembledDriver, expected_dimension: Dimension, time_value: float) -> float:
        dt = 1e-6
        return (
            self._evaluate_driver_value(project, driver, expected_dimension, time_value + dt)
            - self._evaluate_driver_value(project, driver, expected_dimension, time_value - dt)
        ) / (2 * dt)

    def _make_offset_function(self, project: Project, driver: AssembledDriver, expected_dimension: Dimension):
        def offset_fn(mbs, t, itemNumber, lOffset):
            return self._evaluate_driver_value(project, driver, expected_dimension, float(t))

        return offset_fn

    def _make_offset_function_t(self, project: Project, driver: AssembledDriver, expected_dimension: Dimension):
        offset_fn = self._make_offset_function(project, driver, expected_dimension)

        def offset_fn_t(mbs, t, itemNumber, lOffset):
            dt = 1e-6
            return (offset_fn(mbs, t + dt, itemNumber, lOffset) - offset_fn(mbs, t - dt, itemNumber, lOffset)) / (2 * dt)

        return offset_fn_t

    def _collect_final_state(self, mbs, exu, assembled: AssembledMechanism, node_numbers: dict[str, int]) -> dict[str, float]:
        state: dict[str, float] = {}
        for body_id, node_number in node_numbers.items():
            coordinates = mbs.GetNodeOutput(node_number, exu.OutputVariableType.Coordinates)
            body = assembled.bodies[body_id]
            state[f"{body_id}.x"] = body.origin_x + float(coordinates[0])
            state[f"{body_id}.y"] = body.origin_y + float(coordinates[1])
            if len(coordinates) > 2:
                state[f"{body_id}.angle"] = body.angle + float(coordinates[2])
        return state

    def _load_solution_frames(
        self,
        exu,
        mbs,
        solution_path: Path,
        assembled: AssembledMechanism,
        body_order: list[str],
        node_numbers: dict[str, int],
    ):
        if not solution_path.exists():
            return [0.0], [self._collect_final_state(mbs, exu, assembled, node_numbers)]
        try:
            utilities = importlib.import_module("exudyn.utilities")
        except ImportError:
            return [0.0], [self._collect_final_state(mbs, exu, assembled, node_numbers)]
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
                frame[f"{body_id}.x"] = body.origin_x + float(row[start])
                frame[f"{body_id}.y"] = body.origin_y + float(row[start + 1])
                frame[f"{body_id}.angle"] = body.angle + float(row[start + 2])
            if frame:
                frames.append(frame)
        if not frames:
            return [0.0], [self._collect_final_state(mbs, exu, assembled, node_numbers)]
        return time, frames
