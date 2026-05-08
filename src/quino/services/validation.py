from __future__ import annotations

from quino.domain.model import Body, Joint, Model, Project, ValidationMessage, ValidationReport
from quino.domain.types import MarkerType


class ValidationService:
    def validate_project(self, project: Project) -> ValidationReport:
        report = ValidationReport()
        self._validate_unique_names(project, report)
        self._validate_bodies(project.model, report)
        self._validate_joint_duplicates(project.model, report)
        self._validate_joint_references(project.model, report)
        self._validate_driver_references(project.model, report)
        self._validate_driver_duplicates(project.model, report)
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
                        "warning",
                        "invalid_structural_marker_count",
                        "Body must contain at least one structural marker",
                        body.id,
                    )
                )
            com_count = sum(1 for marker in body.markers if marker.type is MarkerType.COM)
            if com_count != 1:
                report.messages.append(
                    ValidationMessage("warning", "invalid_com_count", "Body must contain exactly one CoM marker", body.id)
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
                        ValidationMessage("warning", "broken_reference", "Joint references an unknown body", joint.id)
                    )
                if endpoint.marker_id is not None and endpoint.marker_id not in marker_ids:
                    report.messages.append(
                        ValidationMessage("warning", "broken_reference", "Joint references an unknown marker", joint.id)
                    )
                if endpoint.slider_id is not None and endpoint.slider_id not in slider_ids:
                    report.messages.append(
                        ValidationMessage("warning", "broken_reference", "Joint references an unknown slider", joint.id)
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

    def ensure_unique_name(self, entities: list[object], name: str, entity_id: str | None = None) -> None:
        for entity in entities:
            if getattr(entity, "name") == name and getattr(entity, "id") != entity_id:
                raise ValueError(f"Name already exists: {name}")

    def ensure_unique_marker_name(self, body: Body, name: str, marker_id: str | None = None) -> None:
        for marker in body.markers:
            if marker.name == name and marker.id != marker_id:
                raise ValueError(f"Marker name already exists in body {body.name}: {name}")
