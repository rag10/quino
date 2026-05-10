from __future__ import annotations

import json
from pathlib import Path

from quino.domain.model import (
    Body,
    Driver,
    Joint,
    JointEndpoint,
    Marker,
    Metadata,
    Model,
    Parameter,
    Project,
    ScalarProperty,
    Sensor,
    Sketch,
    SketchConstraint,
    SketchArc,
    SketchCircle,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    Slider,
    Style,
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
    SketchEntityType,
    SketchConstraintType,
)


class JsonMapper:
    def dump(self, project: Project) -> dict:
        return {
            "schema_version": project.schema_version,
            "project": {
                "id": project.id,
                "name": project.name,
                "metadata": project.metadata.values,
            },
            "parameters": [self._parameter_to_dict(parameter) for parameter in project.parameters],
            "sketch": self._sketch_to_dict(project.sketch),
            "model": {
                "bodies": [self._body_to_dict(body) for body in project.model.bodies],
                "sliders": [self._slider_to_dict(slider) for slider in project.model.sliders],
                "joints": [self._joint_to_dict(joint) for joint in project.model.joints],
                "drivers": [self._driver_to_dict(driver) for driver in project.model.drivers],
                "sensors": [self._sensor_to_dict(sensor) for sensor in project.model.sensors],
            },
            "view_state": {
                "zoom": project.view_state.zoom,
                "pan_x": project.view_state.pan_x,
                "pan_y": project.view_state.pan_y,
                "show_grid": project.view_state.show_grid,
                "show_markers": project.view_state.show_markers,
                "show_com": project.view_state.show_com,
                "show_sliders": project.view_state.show_sliders,
            },
        }

    def load(self, data: dict) -> Project:
        project_block = data["project"]
        model_block = data["model"]
        return Project(
            id=project_block["id"],
            name=project_block["name"],
            schema_version=data["schema_version"],
            parameters=[self._parameter_from_dict(item) for item in data.get("parameters", [])],
            sketch=self._sketch_from_dict(data.get("sketch")),
            model=Model(
                bodies=[self._body_from_dict(item) for item in model_block.get("bodies", [])],
                sliders=[self._slider_from_dict(item) for item in model_block.get("sliders", [])],
                joints=[self._joint_from_dict(item) for item in model_block.get("joints", [])],
                drivers=[self._driver_from_dict(item) for item in model_block.get("drivers", [])],
                sensors=[self._sensor_from_dict(item) for item in model_block.get("sensors", [])],
            ),
            view_state=ViewState(**data.get("view_state", {})),
            metadata=Metadata(project_block.get("metadata", {})),
        )

    def save_file(self, project: Project, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.dump(project), indent=2), encoding="utf-8")

    def load_file(self, path: str | Path) -> Project:
        return self.load(json.loads(Path(path).read_text(encoding="utf-8")))

    def _parameter_to_dict(self, parameter: Parameter) -> dict:
        return {
            "id": parameter.id,
            "name": parameter.name,
            "expression": parameter.expression,
            "unit": parameter.unit,
            "description": parameter.description,
            "metadata": parameter.metadata.values,
        }

    def _parameter_from_dict(self, data: dict) -> Parameter:
        return Parameter(
            id=data["id"],
            name=data["name"],
            expression=data["expression"],
            unit=data["unit"],
            description=data.get("description", ""),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _scalar_to_dict(self, value: ScalarProperty | None) -> dict | None:
        if value is None:
            return None
        return {
            "expression": value.expression,
            "unit": value.unit,
            "expected_dimension": value.expected_dimension.value,
        }

    def _scalar_from_dict(self, data: dict | None) -> ScalarProperty | None:
        if data is None:
            return None
        return ScalarProperty(
            expression=data["expression"],
            unit=data["unit"],
            expected_dimension=Dimension(data["expected_dimension"]),
        )

    def _style_to_dict(self, style: Style) -> dict:
        return {
            "color": style.color,
            "visible": style.visible,
            "line_width": style.line_width,
            "marker_size": style.marker_size,
        }

    def _style_from_dict(self, data: dict | None) -> Style:
        if data is None:
            return Style()
        return Style(**data)

    def _marker_to_dict(self, marker: Marker) -> dict:
        return {
            "id": marker.id,
            "name": marker.name,
            "type": marker.type.value,
            "x": self._scalar_to_dict(marker.x),
            "y": self._scalar_to_dict(marker.y),
            "visible": marker.visible,
            "style": self._style_to_dict(marker.style),
            "metadata": marker.metadata.values,
        }

    def _marker_from_dict(self, data: dict) -> Marker:
        return Marker(
            id=data["id"],
            name=data["name"],
            type=MarkerType(data["type"]),
            x=self._scalar_from_dict(data["x"]),
            y=self._scalar_from_dict(data["y"]),
            visible=data.get("visible", True),
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _body_to_dict(self, body: Body) -> dict:
        return {
            "id": body.id,
            "name": body.name,
            "type": body.type.value,
            "markers": [self._marker_to_dict(marker) for marker in body.markers],
            "edge_order": body.edge_order,
            "closed_shape": body.closed_shape,
            "mass": self._scalar_to_dict(body.mass),
            "inertia": self._scalar_to_dict(body.inertia),
            "style": self._style_to_dict(body.style),
            "metadata": body.metadata.values,
        }

    def _body_from_dict(self, data: dict) -> Body:
        return Body(
            id=data["id"],
            name=data["name"],
            type=BodyType(data["type"]),
            markers=[self._marker_from_dict(item) for item in data.get("markers", [])],
            edge_order=data.get("edge_order", []),
            closed_shape=data.get("closed_shape", True),
            mass=self._scalar_from_dict(data.get("mass")),
            inertia=self._scalar_from_dict(data.get("inertia")),
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _slider_to_dict(self, slider: Slider) -> dict:
        return {
            "id": slider.id,
            "name": slider.name,
            "origin_x": self._scalar_to_dict(slider.origin_x),
            "origin_y": self._scalar_to_dict(slider.origin_y),
            "angle": self._scalar_to_dict(slider.angle),
            "travel_min": self._scalar_to_dict(slider.travel_min),
            "travel_max": self._scalar_to_dict(slider.travel_max),
            "style": self._style_to_dict(slider.style),
            "metadata": slider.metadata.values,
        }

    def _slider_from_dict(self, data: dict) -> Slider:
        return Slider(
            id=data["id"],
            name=data["name"],
            origin_x=self._scalar_from_dict(data["origin_x"]),
            origin_y=self._scalar_from_dict(data["origin_y"]),
            angle=self._scalar_from_dict(data["angle"]),
            travel_min=self._scalar_from_dict(data.get("travel_min")),
            travel_max=self._scalar_from_dict(data.get("travel_max")),
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _endpoint_to_dict(self, endpoint: JointEndpoint) -> dict:
        result = {"kind": endpoint.kind.value}
        if endpoint.body_id is not None:
            result["body_id"] = endpoint.body_id
        if endpoint.marker_id is not None:
            result["marker_id"] = endpoint.marker_id
        if endpoint.slider_id is not None:
            result["slider_id"] = endpoint.slider_id
        return result

    def _endpoint_from_dict(self, data: dict) -> JointEndpoint:
        return JointEndpoint(
            kind=JointEndpointKind(data["kind"]),
            body_id=data.get("body_id"),
            marker_id=data.get("marker_id"),
            slider_id=data.get("slider_id"),
        )

    def _joint_to_dict(self, joint: Joint) -> dict:
        return {
            "id": joint.id,
            "name": joint.name,
            "type": joint.type.value,
            "endpoint_a": self._endpoint_to_dict(joint.endpoint_a),
            "endpoint_b": self._endpoint_to_dict(joint.endpoint_b),
            "style": self._style_to_dict(joint.style),
            "metadata": joint.metadata.values,
        }

    def _joint_from_dict(self, data: dict) -> Joint:
        return Joint(
            id=data["id"],
            name=data["name"],
            type=JointType(data["type"]),
            endpoint_a=self._endpoint_from_dict(data["endpoint_a"]),
            endpoint_b=self._endpoint_from_dict(data["endpoint_b"]),
            style=self._style_from_dict(data.get("style")),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _driver_to_dict(self, driver: Driver) -> dict:
        return {
            "id": driver.id,
            "name": driver.name,
            "type": driver.type.value,
            "target_joint_id": driver.target_joint_id,
            "law": self._scalar_to_dict(driver.law),
            "metadata": driver.metadata.values,
        }

    def _driver_from_dict(self, data: dict) -> Driver:
        return Driver(
            id=data["id"],
            name=data["name"],
            type=DriverType(data["type"]),
            target_joint_id=data["target_joint_id"],
            law=self._scalar_from_dict(data["law"]),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _sensor_to_dict(self, sensor: Sensor) -> dict:
        return {
            "id": sensor.id,
            "name": sensor.name,
            "type": sensor.type.value,
            "marker_ids": sensor.marker_ids,
            "metadata": sensor.metadata.values,
        }

    def _sensor_from_dict(self, data: dict) -> Sensor:
        return Sensor(
            id=data["id"],
            name=data["name"],
            type=SensorType(data["type"]),
            marker_ids=data.get("marker_ids", []),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _sketch_to_dict(self, sketch: Sketch | None) -> dict | None:
        if sketch is None:
            return None
        return {
            "id": sketch.id,
            "name": sketch.name,
            "visible": sketch.visible,
            "style": self._style_to_dict(sketch.style),
            "entities": [self._sketch_entity_to_dict(entity) for entity in sketch.entities],
            "constraints": [self._sketch_constraint_to_dict(constraint) for constraint in sketch.constraints],
            "metadata": sketch.metadata.values,
        }

    def _sketch_from_dict(self, data: dict | None) -> Sketch | None:
        if data is None:
            return None
        return Sketch(
            id=data["id"],
            name=data["name"],
            visible=data.get("visible", True),
            style=self._style_from_dict(data.get("style")),
            entities=[self._sketch_entity_from_dict(item) for item in data.get("entities", [])],
            constraints=[self._sketch_constraint_from_dict(item) for item in data.get("constraints", [])],
            metadata=Metadata(data.get("metadata", {})),
        )

    def _sketch_constraint_to_dict(self, constraint: SketchConstraint) -> dict:
        return {
            "id": constraint.id,
            "name": constraint.name,
            "type": constraint.type.value,
            "references": list(constraint.references),
            "value": self._scalar_to_dict(constraint.value) if constraint.value is not None else None,
            "entity_references": list(constraint.entity_references),
            "metadata": constraint.metadata.values,
        }

    def _sketch_constraint_from_dict(self, data: dict) -> SketchConstraint:
        return SketchConstraint(
            id=data["id"],
            name=data["name"],
            type=SketchConstraintType(data["type"]),
            references=list(data.get("references", [])),
            value=self._scalar_from_dict(data["value"]) if data.get("value") is not None else None,
            entity_references=list(data.get("entity_references", [])),
            metadata=Metadata(data.get("metadata", {})),
        )

    def _sketch_entity_to_dict(
        self,
        entity: SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine,
    ) -> dict:
        base = {
            "id": entity.id,
            "name": entity.name,
            "type": entity.type.value,
            "visible": entity.visible,
            "construction": entity.construction,
            "style": self._style_to_dict(entity.style),
            "metadata": entity.metadata.values,
        }
        if isinstance(entity, SketchPoint):
            base["x"] = self._scalar_to_dict(entity.x)
            base["y"] = self._scalar_to_dict(entity.y)
        elif isinstance(entity, SketchLineSegment):
            base["start_point_id"] = entity.start_point_id
            base["end_point_id"] = entity.end_point_id
        elif isinstance(entity, SketchCircle):
            base["center_point_id"] = entity.center_point_id
            base["radius"] = self._scalar_to_dict(entity.radius)
        elif isinstance(entity, SketchArc):
            base["point_a_id"] = entity.point_a_id
            base["point_b_id"] = entity.point_b_id
            base["point_c_id"] = entity.point_c_id
        elif isinstance(entity, SketchInfiniteLine):
            base["point_a_id"] = entity.point_a_id
            base["point_b_id"] = entity.point_b_id
        return base

    def _sketch_entity_from_dict(
        self,
        data: dict,
    ) -> SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine:
        entity_type = SketchEntityType(data["type"])
        common = {
            "id": data["id"],
            "name": data["name"],
            "type": entity_type,
            "visible": data.get("visible", True),
            "construction": data.get("construction", False),
            "style": self._style_from_dict(data.get("style")),
            "metadata": Metadata(data.get("metadata", {})),
        }
        if entity_type is SketchEntityType.POINT:
            return SketchPoint(
                x=self._scalar_from_dict(data["x"]),
                y=self._scalar_from_dict(data["y"]),
                **common,
            )
        if entity_type is SketchEntityType.LINE_SEGMENT:
            return SketchLineSegment(
                start_point_id=data["start_point_id"],
                end_point_id=data["end_point_id"],
                **common,
            )
        if entity_type is SketchEntityType.CIRCLE:
            return SketchCircle(
                center_point_id=data["center_point_id"],
                radius=self._scalar_from_dict(data["radius"]),
                **common,
            )
        if entity_type is SketchEntityType.ARC:
            return SketchArc(
                point_a_id=data["point_a_id"],
                point_b_id=data["point_b_id"],
                point_c_id=data["point_c_id"],
                **common,
            )
        return SketchInfiniteLine(
            point_a_id=data["point_a_id"],
            point_b_id=data["point_b_id"],
            **common,
        )
