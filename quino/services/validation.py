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
from quino.domain.types import MarkerType, SketchConstraintType, SpringEndpointKind, SpringType


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
            com_count = sum(1 for marker in body.markers if marker.type is MarkerType.COM)
            if com_count != 1:
                report.messages.append(
                    ValidationMessage("error", "invalid_com_count", "Body must contain exactly one CoM marker", body.id)
                )

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
