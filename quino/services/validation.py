from __future__ import annotations

from quino.domain.model import (
    Body,
    Joint,
    Model,
    Project,
    SketchConstraint,
    SketchArc,
    SketchCircle,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    Spring,
    ValidationMessage,
    ValidationReport,
)
from quino.domain.sketch_constraints import CONSTRAINT_SPECS
from quino.domain.types import DriverType, MarkerType, SketchConstraintType, SpringEndpointKind, SpringType
from quino.simulation.sensor_expressions import sensor_channel_keys


class ValidationService:
    def validate_project(self, project: Project) -> ValidationReport:
        report = ValidationReport()
        self._validate_unique_names(project, report)
        self._validate_bodies(project.model, report)
        self._validate_joint_duplicates(project.model, report)
        self._validate_joint_references(project.model, report)
        self._validate_driver_references(project.model, report)
        self._validate_driver_duplicates(project.model, report)
        self._validate_springs(project.model, report)
        self._validate_control_graph(project, report)
        self._validate_sketch(project, report)
        return report

    def _validate_unique_names(self, project: Project, report: ValidationReport) -> None:
        for entity_name, entities in {
            "body": project.model.bodies,
            "joint": project.model.joints,
            "slider": project.model.sliders,
            "driver": project.model.drivers,
            "parameter": project.parameters,
        }.items():
            seen: set[str] = set()
            for entity in entities:
                if entity.name in seen:
                    report.messages.append(
                        ValidationMessage("warning", "duplicate_name", f"Duplicate {entity_name} name: {entity.name}", entity.id)
                    )
                seen.add(entity.name)
        for body in project.model.bodies:
            seen_markers: set[str] = set()
            for marker in body.markers:
                if marker.name in seen_markers:
                    report.messages.append(
                        ValidationMessage("warning", "duplicate_marker_name", f"Duplicate marker name: {marker.name}", marker.id)
                    )
                seen_markers.add(marker.name)

    def _validate_bodies(self, model: Model, report: ValidationReport) -> None:
        for body in model.bodies:
            structural_count = sum(1 for marker in body.markers if marker.type is MarkerType.STRUCTURAL)
            if structural_count < 1:
                report.messages.append(
                    ValidationMessage(
                        "error",
                        "invalid_structural_marker_count",
                        "Body must contain at least one structural marker",
                        body.id,
                    )
                )
            # The CoM is now a derived entity (Body.com anchor); it is
            # guaranteed by the dataclass and no longer requires per-body
            # validation of a dedicated marker.

    def _validate_joint_duplicates(self, model: Model, report: ValidationReport) -> None:
        seen: set[tuple[str, str]] = set()
        for joint in model.joints:
            key = self._joint_key(joint)
            if key in seen:
                report.messages.append(
                    ValidationMessage("warning", "duplicate_joint", f"Duplicate joint endpoints in {joint.name}", joint.id)
                )
            seen.add(key)

    def _validate_joint_references(self, model: Model, report: ValidationReport) -> None:
        body_ids = {body.id for body in model.bodies}
        slider_ids = {slider.id for slider in model.sliders}
        marker_ids = {marker.id for body in model.bodies for marker in body.markers}
        for joint in model.joints:
            for endpoint in (joint.endpoint_a, joint.endpoint_b):
                if endpoint.body_id is not None and endpoint.body_id not in body_ids:
                    report.messages.append(
                        ValidationMessage("error", "broken_reference", "Joint references an unknown body", joint.id)
                    )
                if endpoint.marker_id is not None and endpoint.marker_id not in marker_ids:
                    report.messages.append(
                        ValidationMessage("error", "broken_reference", "Joint references an unknown marker", joint.id)
                    )
                if endpoint.slider_id is not None and endpoint.slider_id not in slider_ids:
                    report.messages.append(
                        ValidationMessage("error", "broken_reference", "Joint references an unknown slider", joint.id)
                    )

    def _validate_driver_references(self, model: Model, report: ValidationReport) -> None:
        joint_ids = {joint.id for joint in model.joints}
        for driver in model.drivers:
            if driver.target_joint_id not in joint_ids:
                report.messages.append(
                    ValidationMessage(
                        "warning",
                        "broken_driver_reference",
                        "Driver references an unknown joint",
                        driver.id,
                    )
                )

    def _validate_driver_duplicates(self, model: Model, report: ValidationReport) -> None:
        seen_joint_ids: set[str] = set()
        for driver in model.drivers:
            if driver.target_joint_id in seen_joint_ids:
                report.messages.append(
                    ValidationMessage(
                        "warning",
                        "duplicate_driver_target",
                        "Multiple drivers target the same joint",
                        driver.id,
                    )
                )
            seen_joint_ids.add(driver.target_joint_id)

    def _joint_key(self, joint: Joint) -> tuple[str, str]:
        def serialize(endpoint: object) -> str:
            return repr(endpoint)

        serialized = sorted([serialize(joint.endpoint_a), serialize(joint.endpoint_b)])
        return serialized[0], serialized[1]

    def _validate_springs(self, model: Model, report: ValidationReport) -> None:
        marker_index: dict[str, str] = {}
        for body in model.bodies:
            for marker in body.markers:
                marker_index[marker.id] = body.id
        for spring in model.springs:
            for ep, label in [(spring.endpoint_a, "A"), (spring.endpoint_b, "B")]:
                if ep.kind is SpringEndpointKind.MARKER:
                    if ep.body_id is None or ep.marker_id is None:
                        report.messages.append(ValidationMessage("error", "spring_missing_endpoint", f"Spring '{spring.name}' endpoint {label} is incomplete", spring.id))
                    elif ep.marker_id not in marker_index:
                        report.messages.append(ValidationMessage("error", "spring_invalid_marker", f"Spring '{spring.name}' endpoint {label} references unknown marker", spring.id))
                elif ep.kind is SpringEndpointKind.GROUND:
                    if ep.ground_x is None or ep.ground_y is None:
                        report.messages.append(ValidationMessage("error", "spring_missing_ground_pos", f"Spring '{spring.name}' ground endpoint {label} has no position", spring.id))
            is_actuator = spring.spring_type in (SpringType.LINEAR_ACTUATOR, SpringType.ROTATIONAL_ACTUATOR)
            if is_actuator and spring.law is None:
                report.messages.append(ValidationMessage("error", "spring_missing_law", f"Actuator '{spring.name}' has no law expression", spring.id))
            if not is_actuator and spring.metadata.values.get("stiffness", 0.0) == 0.0 and spring.metadata.values.get("damping", 0.0) == 0.0:
                report.messages.append(ValidationMessage("warning", "spring_zero_properties", f"Spring '{spring.name}' has zero stiffness and damping", spring.id))

    def _validate_control_graph(self, project: Project, report: ValidationReport) -> None:
        diagram = project.model.control_graph
        if diagram is None:
            return

        sensors_by_id = {sensor.id: sensor for sensor in project.model.sensors}
        loads_by_id = {load.id: load for load in project.model.loads}
        springs_by_id = {spring.id: spring for spring in project.model.springs}
        drivers_by_id = {driver.id: driver for driver in project.model.drivers}
        body_ids = {body.id for body in project.model.bodies}

        for instance in diagram.instances.values():
            params = instance.parameters
            sensor_id = params.get("sensor_id")
            if instance.block_type in {"ModelSensor", "MBSSensor"} and "sensor_id" in params:
                if not isinstance(sensor_id, str) or not sensor_id:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "missing_block_reference",
                            f"Block '{instance.instance_id}' is missing a sensor reference",
                            instance.instance_id,
                        )
                    )
                elif sensor_id not in sensors_by_id:
                    report.messages.append(
                        ValidationMessage(
                            "error",
                            "broken_block_reference",
                            f"Block '{instance.instance_id}' references an unknown sensor",
                            instance.instance_id,
                        )
                    )
                else:
                    self._validate_sensor_block_channel(instance, sensors_by_id[sensor_id], report)

            load_id = params.get("load_id")
            if instance.block_type in {"LoadCommand", "MBSActuator"} and "load_id" in params:
                self._validate_load_command(instance, report)
                if not isinstance(load_id, str) or not load_id:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "missing_block_reference",
                            f"Block '{instance.instance_id}' is missing a load reference",
                            instance.instance_id,
                        )
                    )
                elif load_id not in loads_by_id:
                    report.messages.append(
                        ValidationMessage(
                            "error",
                            "broken_block_reference",
                            f"Block '{instance.instance_id}' references an unknown load",
                            instance.instance_id,
                        )
                    )

            spring_id = params.get("spring_id")
            if instance.block_type in {"SpringCommand", "MBSActuator"} and "spring_id" in params:
                if not isinstance(spring_id, str) or not spring_id:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "missing_block_reference",
                            f"Block '{instance.instance_id}' is missing a spring reference",
                            instance.instance_id,
                        )
                    )
                elif spring_id not in springs_by_id:
                    report.messages.append(
                        ValidationMessage(
                            "error",
                            "broken_block_reference",
                            f"Block '{instance.instance_id}' references an unknown spring",
                            instance.instance_id,
                        )
                    )

            driver_id = params.get("driver_id")
            if instance.block_type in {"DriverCommand", "MBSActuator"} and "driver_id" in params:
                if not isinstance(driver_id, str) or not driver_id:
                    report.messages.append(
                        ValidationMessage(
                            "warning",
                            "missing_block_reference",
                            f"Block '{instance.instance_id}' is missing a driver reference",
                            instance.instance_id,
                        )
                    )
                elif driver_id not in drivers_by_id:
                    report.messages.append(
                        ValidationMessage(
                            "error",
                            "broken_block_reference",
                            f"Block '{instance.instance_id}' references an unknown driver",
                            instance.instance_id,
                        )
                    )

            body_id = params.get("body_id")
            if instance.block_type in {"MBSSensor", "MBSActuator"} and isinstance(body_id, str) and body_id:
                if body_id not in body_ids:
                    report.messages.append(
                        ValidationMessage(
                            "error",
                            "broken_block_reference",
                            f"Legacy block '{instance.instance_id}' references an unknown body",
                            instance.instance_id,
                        )
                    )

        for connection in diagram.connections:
            src = diagram.instances.get(connection.src_instance)
            dst = diagram.instances.get(connection.dst_instance)
            if src is None or dst is None:
                continue
            self._validate_control_graph_connection(
                src,
                dst,
                sensors_by_id=sensors_by_id,
                springs_by_id=springs_by_id,
                drivers_by_id=drivers_by_id,
                report=report,
            )

    def _validate_sensor_block_channel(self, instance, sensor, report: ValidationReport) -> None:
        if "channel" not in instance.parameters:
            return
        channel = instance.parameters.get("channel")
        if not isinstance(channel, str) or not channel:
            report.messages.append(
                ValidationMessage(
                    "warning",
                    "missing_block_parameter",
                    f"Block '{instance.instance_id}' is missing a sensor channel",
                    instance.instance_id,
                )
            )
            return
        allowed = {name for name, _unit in sensor_channel_keys(sensor)}
        if channel not in allowed:
            report.messages.append(
                ValidationMessage(
                    "error",
                    "invalid_block_parameter",
                    f"Block '{instance.instance_id}' uses unsupported channel '{channel}'",
                    instance.instance_id,
                )
            )

    def _validate_load_command(self, instance, report: ValidationReport) -> None:
        component = instance.parameters.get("component")
        if component is None:
            return
        if component not in {"fx", "fy"}:
            report.messages.append(
                ValidationMessage(
                    "error",
                    "invalid_block_parameter",
                    f"Block '{instance.instance_id}' uses unsupported load component '{component}'",
                    instance.instance_id,
                )
            )

    def _validate_control_graph_connection(
        self,
        src,
        dst,
        *,
        sensors_by_id: dict[str, object],
        springs_by_id: dict[str, object],
        drivers_by_id: dict[str, object],
        report: ValidationReport,
    ) -> None:
        src_family = self._block_output_family(src, sensors_by_id)
        dst_family = self._block_input_family(dst, springs_by_id, drivers_by_id)
        if src_family is None or dst_family is None:
            return
        if src_family == dst_family:
            return
        allowed_pairs = {
            ("length", "length"),
            ("angle", "angle"),
            ("force", "force"),
            ("torque", "torque"),
        }
        if (src_family, dst_family) not in allowed_pairs:
            report.messages.append(
                ValidationMessage(
                    "warning",
                    "block_connection_mismatch",
                    f"Connection {src.instance_id} -> {dst.instance_id} mixes {src_family} with {dst_family}",
                    dst.instance_id,
                )
            )

    def _block_output_family(self, instance, sensors_by_id: dict[str, object]) -> str | None:
        if instance.block_type in {"ModelSensor", "MBSSensor"}:
            sensor_id = instance.parameters.get("sensor_id")
            channel = instance.parameters.get("channel")
            if isinstance(sensor_id, str) and sensor_id in sensors_by_id and isinstance(channel, str):
                return self._sensor_channel_family(sensors_by_id[sensor_id], channel)
        return None

    def _block_input_family(
        self,
        instance,
        springs_by_id: dict[str, object],
        drivers_by_id: dict[str, object],
    ) -> str | None:
        if instance.block_type in {"LoadCommand", "MBSActuator"} and instance.parameters.get("load_id"):
            return "force"
        if instance.block_type in {"SpringCommand", "MBSActuator"} and instance.parameters.get("spring_id"):
            spring_id = instance.parameters.get("spring_id")
            spring = springs_by_id.get(spring_id)
            if spring is None:
                return None
            if spring.spring_type in {SpringType.ROTATIONAL_SPRING, SpringType.ROTATIONAL_ACTUATOR}:
                return "torque"
            return "force"
        if instance.block_type in {"DriverCommand", "MBSActuator"} and instance.parameters.get("driver_id"):
            driver_id = instance.parameters.get("driver_id")
            driver = drivers_by_id.get(driver_id)
            if driver is None:
                return None
            if driver.type is DriverType.ROTATION:
                return "angle"
            if driver.type is DriverType.TRANSLATION:
                return "length"
        return None

    def _sensor_channel_family(self, sensor, channel: str) -> str | None:
        for name, unit in sensor_channel_keys(sensor):
            if name != channel:
                continue
            if unit in {"mm", "m"}:
                return "length"
            if unit in {"deg", "rad"}:
                return "angle"
            if unit in {"mm/s", "m/s"}:
                return "velocity"
        return None

    def _validate_sketch(self, project: Project, report: ValidationReport) -> None:
        sketch = project.sketch
        if sketch is None:
            return
        seen_names: set[str] = set()
        point_ids = {entity.id for entity in sketch.entities.values() if isinstance(entity, SketchPoint)}
        curve_ids = {entity.id for entity in sketch.entities.values() if isinstance(entity, (SketchCircle, SketchArc))}
        for entity in sketch.entities.values():
            if entity.name in seen_names:
                report.messages.append(
                    ValidationMessage("warning", "duplicate_sketch_name", f"Duplicate sketch name: {entity.name}", entity.id)
                )
            seen_names.add(entity.name)
            if isinstance(entity, SketchLineSegment):
                if entity.start_point_id == entity.end_point_id:
                    report.messages.append(
                        ValidationMessage("error", "invalid_sketch_reference", f"{entity.name} requires two distinct points", entity.id)
                    )
                self._validate_point_refs(entity.id, [entity.start_point_id, entity.end_point_id], point_ids, report)
            elif isinstance(entity, SketchCircle):
                self._validate_point_refs(entity.id, [entity.center_point_id], point_ids, report)
            elif isinstance(entity, SketchArc):
                refs = [entity.center_point_id, entity.start_point_id, entity.end_point_id]
                self._validate_point_refs(entity.id, refs, point_ids, report)
                if len(set(refs)) < 3:
                    report.messages.append(
                        ValidationMessage("error", "invalid_sketch_reference", f"{entity.name} requires three distinct points", entity.id)
                    )
            elif isinstance(entity, SketchInfiniteLine):
                if entity.point_a_id == entity.point_b_id:
                    report.messages.append(
                        ValidationMessage("error", "invalid_sketch_reference", f"{entity.name} requires two distinct points", entity.id)
                    )
                self._validate_point_refs(entity.id, [entity.point_a_id, entity.point_b_id], point_ids, report)
        constraint_names: set[str] = set()
        for constraint in sketch.constraints.values():
            if constraint.name in constraint_names:
                report.messages.append(
                    ValidationMessage("warning", "duplicate_sketch_constraint_name", f"Duplicate sketch constraint name: {constraint.name}", constraint.id)
                )
            constraint_names.add(constraint.name)
            self._validate_sketch_constraint(constraint, point_ids, curve_ids, report)

    def _validate_point_refs(
        self,
        entity_id: str,
        point_refs: list[str],
        point_ids: set[str],
        report: ValidationReport,
    ) -> None:
        for point_id in point_refs:
            if point_id not in point_ids:
                report.messages.append(
                    ValidationMessage("error", "broken_sketch_reference", "Sketch entity references an unknown point", entity_id)
                )

    def _validate_sketch_constraint(
        self,
        constraint: SketchConstraint,
        point_ids: set[str],
        curve_ids: set[str],
        report: ValidationReport,
    ) -> None:
        for point_id in constraint.references:
            if point_id not in point_ids:
                report.messages.append(
                    ValidationMessage("error", "broken_sketch_constraint_reference", "Sketch constraint references an unknown point", constraint.id)
                )
        point_entity_coincident = False
        if constraint.type is SketchConstraintType.FIX:
            if len(constraint.references) != 1:
                report.messages.append(
                    ValidationMessage("error", "invalid_sketch_constraint", f"{constraint.name} requires exactly one point", constraint.id)
                )
        else:
            spec = CONSTRAINT_SPECS.get(constraint.type)
            expected_points = spec.points if spec is not None else None
            point_entity_coincident = (
                constraint.type is SketchConstraintType.COINCIDENT
                and len(constraint.references) == 1
                and len(constraint.entity_references) == 1
            )
            tangent_curve_curve = (
                constraint.type is SketchConstraintType.TANGENT
                and len(constraint.references) == 0
                and len(constraint.entity_references) == 2
            )
            if expected_points is not None and not point_entity_coincident and (
                not tangent_curve_curve
                and (
                    len(constraint.references) != expected_points
                    or len(set(constraint.references)) != len(constraint.references)
                )
            ):
                report.messages.append(
                    ValidationMessage("error", "invalid_sketch_constraint", f"{constraint.name} requires {expected_points} distinct point references", constraint.id)
                )
        spec = CONSTRAINT_SPECS.get(constraint.type)
        if constraint.type in {
            SketchConstraintType.DISTANCE,
            SketchConstraintType.HORIZONTAL_DISTANCE,
            SketchConstraintType.VERTICAL_DISTANCE,
            SketchConstraintType.RADIUS,
        } and constraint.value is None:
            report.messages.append(
                ValidationMessage("error", "invalid_sketch_constraint", f"{constraint.name} requires a distance value", constraint.id)
            )
        if constraint.type is SketchConstraintType.ANGLE and constraint.value is None:
            report.messages.append(
                ValidationMessage("error", "invalid_sketch_constraint", f"{constraint.name} requires an angle value", constraint.id)
            )
        expected_entities = spec.entities if spec is not None else 0
        tangent_curve_curve = (
            constraint.type is SketchConstraintType.TANGENT
            and len(constraint.references) == 0
            and len(constraint.entity_references) == 2
        )
        if not point_entity_coincident and not tangent_curve_curve and len(constraint.entity_references) != expected_entities:
            report.messages.append(
                ValidationMessage("error", "invalid_sketch_constraint", f"{constraint.name} requires {expected_entities} entity references", constraint.id)
            )
        for entity_id in constraint.entity_references:
            if entity_id not in curve_ids:
                report.messages.append(
                    ValidationMessage("error", "broken_sketch_constraint_reference", "Sketch constraint references an unknown curve entity", constraint.id)
                )

    def ensure_unique_name(self, entities: list[object], name: str, entity_id: str | None = None) -> None:
        for entity in entities:
            if getattr(entity, "name") == name and getattr(entity, "id") != entity_id:
                raise ValueError(f"Name already exists: {name}")

    def ensure_unique_marker_name(self, body: Body, name: str, marker_id: str | None = None) -> None:
        for marker in body.markers:
            if marker.name == name and marker.id != marker_id:
                raise ValueError(f"Marker name already exists in body {body.name}: {name}")
