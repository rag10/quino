from __future__ import annotations

import json
from pathlib import Path

from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec
from quino.domain.workspace import (
    Analysis,
    ArtifactRef,
    Baseline,
    Case,
    CaseGroup,
    MetricDefinition,
    ParameterDescriptor,
    ResultRef,
    Run,
    RunEntry,
    ScalarValue,
    Study,
    StudyConfig,
    StudyMask,
    StudyOverlay,
    SweepParameter,
    Tolerance,
    Workspace,
    WorkspacePose,
)
from quino.domain.model import (
    Body,
    BodyPose,
    Driver,
    Expression,
    GravityLoad,
    Joint,
    JointEndpoint,
    Load,
    Marker,
    Metadata,
    Model,
    Parameter,
    Pose,
    Project,
    ScalarProperty,
    Sensor,
    Sketch,
    SketchAnalysis,
    SketchArc,
    SketchCircle,
    SketchConstraint,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    SketchSpline,
    Slider,
    Spring,
    SpringEndpoint,
    Style,
    Variable,
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
    SpringEndpointKind,
    SpringType,
)


class JsonMapper:
    def dump(self, project: Project) -> dict:
        result = {
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
                "loads": [self._load_to_dict(load) for load in project.model.loads],
                "sensors": [self._sensor_to_dict(sensor) for sensor in project.model.sensors],
                "springs": [self._spring_to_dict(spring) for spring in project.model.springs],
                "gravity": {
                    "magnitude": project.model.gravity.magnitude,
                    "direction_x": project.model.gravity.direction_x,
                    "direction_y": project.model.gravity.direction_y,
                } if project.model.gravity is not None else None,
                "control_graph": self._block_diagram_to_dict(project.model.control_graph)
                if project.model.control_graph is not None and project.model.control_graph.instances
                else None,
            },
            "view_state": {
                "zoom": project.view_state.zoom,
                "pan_x": project.view_state.pan_x,
                "pan_y": project.view_state.pan_y,
                "show_grid": project.view_state.show_grid,
                "show_sensors": project.view_state.show_sensors,
                "show_markers": project.view_state.show_markers,
                "show_com": project.view_state.show_com,
                "show_sliders": project.view_state.show_sliders,
                "show_sensors": project.view_state.show_sensors,
            },
        }
        if project.poses:
            result["poses"] = [self._pose_to_dict(pose) for pose in project.poses]
        if project.simulation_initial_pose_id is not None:
            result["simulation_initial_pose_id"] = project.simulation_initial_pose_id
        if project.model.control_graph is None and project.block_diagram is not None and project.block_diagram.instances:
            result["block_diagram"] = self._block_diagram_to_dict(project.block_diagram)
        if project.workspace is not None and not project.workspace.is_empty():
            result["workspace"] = self._workspace_to_dict(project.workspace)
        return result

    def load(self, data: dict) -> Project:
        project_block = data["project"]
        model_block = data["model"]
        poses_data = data.get("poses")
        sim_initial_pose_id = data.get("simulation_initial_pose_id")
        if poses_data is None:
            # Backwards-compat: old projects had a single `initial_pose` field.
            legacy = self._pose_from_dict(data.get("initial_pose"))
            poses = [legacy] if legacy is not None else []
            if legacy is not None and sim_initial_pose_id is None:
                sim_initial_pose_id = legacy.id
        else:
            poses = [self._pose_from_dict(item) for item in poses_data if item is not None]
        return Project(
            id=project_block["id"],
            name=project_block["name"],
            schema_version=data["schema_version"],
            parameters=[self._parameter_from_dict(item) for item in data.get("parameters", [])],
            sketch=self._sketch_from_dict(data.get("sketch")),
            poses=poses,
            simulation_initial_pose_id=sim_initial_pose_id,
            model=Model(
                bodies=[self._body_from_dict(item) for item in model_block.get("bodies", [])],
                sliders=[self._slider_from_dict(item) for item in model_block.get("sliders", [])],
                joints=[self._joint_from_dict(item) for item in model_block.get("joints", [])],
                drivers=[self._driver_from_dict(item) for item in model_block.get("drivers", [])],
                loads=[self._load_from_dict(item) for item in model_block.get("loads", [])],
                sensors=[self._sensor_from_dict(item) for item in model_block.get("sensors", [])],
                springs=[self._spring_from_dict(item) for item in model_block.get("springs", [])],
                gravity=self._gravity_from_dict(model_block.get("gravity")),
                control_graph=self._block_diagram_from_dict(model_block.get("control_graph"))
                or self._block_diagram_from_dict(data.get("block_diagram")),
            ),
            view_state=ViewState(**data.get("view_state", {})),
            metadata=Metadata(project_block.get("metadata", {})),
            workspace=self._workspace_from_dict(data.get("workspace")),
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

    def _body_pose_to_dict(self, body_pose: BodyPose) -> dict:
        return {
            "body_id": body_pose.body_id,
            "x": body_pose.x,
            "y": body_pose.y,
            "angle": body_pose.angle,
        }

    def _body_pose_from_dict(self, data: dict) -> BodyPose:
        return BodyPose(
            body_id=data["body_id"],
            x=float(data["x"]),
            y=float(data["y"]),
            angle=float(data["angle"]),
        )

    def _pose_to_dict(self, pose: Pose | None) -> dict | None:
        if pose is None:
            return None
        result: dict = {
            "id": pose.id,
            "name": pose.name,
            "body_poses": {
                body_id: self._body_pose_to_dict(body_pose)
                for body_id, body_pose in pose.body_poses.items()
            },
            "metadata": pose.metadata.values,
        }
        if pose.initial_velocities:
            result["initial_velocities"] = dict(pose.initial_velocities)
        return result

    def _pose_from_dict(self, data: dict | None) -> Pose | None:
        if data is None:
            return None
        return Pose(
            id=data["id"],
            name=data["name"],
            body_poses={
                body_id: self._body_pose_from_dict(body_pose)
                for body_id, body_pose in data.get("body_poses", {}).items()
            },
            initial_velocities={
                str(driver_id): float(value)
                for driver_id, value in data.get("initial_velocities", {}).items()
            },
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

    def _expression_to_dict(self, value: Expression | None) -> dict | None:
        if value is None:
            return None
        return {"text": value.text, "unit": value.unit}

    def _expression_from_dict(self, data: dict | None) -> Expression | None:
        if data is None:
            return None
        # Fallback: support legacy ScalarProperty serialization format
        if "text" in data:
            return Expression(text=data["text"], unit=data.get("unit", "mm"))
        return Expression(text=data.get("expression", ""), unit=data.get("unit", "mm"))

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

    def _load_to_dict(self, load: Load) -> dict:
        return {
            "id": load.id,
            "name": load.name,
            "target_marker_id": load.target_marker_id,
            "fx": self._scalar_to_dict(load.fx),
            "fy": self._scalar_to_dict(load.fy),
            "metadata": load.metadata.values,
        }

    def _load_from_dict(self, data: dict) -> Load:
        return Load(
            id=data["id"],
            name=data["name"],
            target_marker_id=data["target_marker_id"],
            fx=self._scalar_from_dict(data["fx"]),
            fy=self._scalar_from_dict(data["fy"]),
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

    def _gravity_from_dict(self, data: dict | None) -> GravityLoad | None:
        if data is None:
            return None
        # backward compat: old format had an 'enabled' boolean field
        if not data.get("enabled", True):
            return None
        return GravityLoad(
            magnitude=data.get("magnitude", 9.81),
            direction_x=data.get("direction_x", 0.0),
            direction_y=data.get("direction_y", -1.0),
        )

    def _spring_endpoint_to_dict(self, ep: SpringEndpoint) -> dict:
        result: dict = {"kind": ep.kind.value}
        if ep.body_id is not None:
            result["body_id"] = ep.body_id
        if ep.marker_id is not None:
            result["marker_id"] = ep.marker_id
        if ep.ground_x is not None:
            result["ground_x"] = self._scalar_to_dict(ep.ground_x)
        if ep.ground_y is not None:
            result["ground_y"] = self._scalar_to_dict(ep.ground_y)
        return result

    def _spring_endpoint_from_dict(self, data: dict) -> SpringEndpoint:
        return SpringEndpoint(
            kind=SpringEndpointKind(data["kind"]),
            body_id=data.get("body_id"),
            marker_id=data.get("marker_id"),
            ground_x=self._scalar_from_dict(data.get("ground_x")),
            ground_y=self._scalar_from_dict(data.get("ground_y")),
        )

    def _spring_to_dict(self, spring: Spring) -> dict:
        return {
            "id": spring.id,
            "name": spring.name,
            "spring_type": spring.spring_type.value,
            "endpoint_a": self._spring_endpoint_to_dict(spring.endpoint_a),
            "endpoint_b": self._spring_endpoint_to_dict(spring.endpoint_b),
            "rest_value": self._scalar_to_dict(spring.rest_value),
            "law": self._scalar_to_dict(spring.law),
            "style": self._style_to_dict(spring.style),
            "metadata": spring.metadata.values,
        }

    def _spring_from_dict(self, data: dict) -> Spring:
        return Spring(
            id=data["id"],
            name=data["name"],
            spring_type=SpringType(data["spring_type"]),
            endpoint_a=self._spring_endpoint_from_dict(data["endpoint_a"]),
            endpoint_b=self._spring_endpoint_from_dict(data["endpoint_b"]),
            rest_value=self._scalar_from_dict(data.get("rest_value")),
            law=self._scalar_from_dict(data.get("law")),
            style=self._style_from_dict(data.get("style")),
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
            "entities": {
                eid: self._sketch_entity_to_dict(entity)
                for eid, entity in sketch.entities.items()
            },
            "constraints": {
                cid: self._sketch_constraint_to_dict(constraint)
                for cid, constraint in sketch.constraints.items()
            },
            "variables": {
                vid: self._variable_to_dict(variable)
                for vid, variable in sketch.variables.items()
            },
            "metadata": sketch.metadata.values,
        }

    def _sketch_from_dict(self, data: dict | None) -> Sketch | None:
        if data is None:
            return None
        entities_data = data.get("entities", {})
        constraints_data = data.get("constraints", {})
        variables_data = data.get("variables", {})
        # Fallback: support legacy list format for entities / constraints
        if isinstance(entities_data, list):
            entities_data = {item["id"]: item for item in entities_data}
        if isinstance(constraints_data, list):
            constraints_data = {item["id"]: item for item in constraints_data}
        if isinstance(variables_data, list):
            variables_data = {item["name"]: item for item in variables_data}
        return Sketch(
            id=data["id"],
            name=data["name"],
            visible=data.get("visible", True),
            style=self._style_from_dict(data.get("style")),
            entities={
                eid: self._sketch_entity_from_dict(item)
                for eid, item in entities_data.items()
            },
            constraints={
                cid: self._sketch_constraint_from_dict(item)
                for cid, item in constraints_data.items()
            },
            variables={
                vid: self._variable_from_dict(item)
                for vid, item in variables_data.items()
            },
            metadata=Metadata(data.get("metadata", {})),
        )

    def _variable_to_dict(self, variable: Variable) -> dict:
        return {"name": variable.name, "expression": variable.expression}

    def _variable_from_dict(self, data: dict) -> Variable:
        return Variable(name=data["name"], expression=data["expression"])

    def _sketch_constraint_to_dict(self, constraint: SketchConstraint) -> dict:
        return {
            "id": constraint.id,
            "name": constraint.name,
            "type": constraint.type.value,
            "references": list(constraint.references),
            "value": self._scalar_to_dict(constraint.value) if constraint.value is not None else None,
            "entity_references": list(constraint.entity_references),
            "enabled": constraint.enabled,
            "driving": constraint.driving,
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
            enabled=data.get("enabled", True),
            driving=data.get("driving", True),
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
            "selectable": entity.selectable,
            "style": self._style_to_dict(entity.style),
            "metadata": entity.metadata.values,
        }
        if isinstance(entity, SketchPoint):
            base["x"] = self._expression_to_dict(entity.x)
            base["y"] = self._expression_to_dict(entity.y)
        elif isinstance(entity, SketchLineSegment):
            base["start_point_id"] = entity.start_point_id
            base["end_point_id"] = entity.end_point_id
        elif isinstance(entity, SketchCircle):
            base["center_point_id"] = entity.center_point_id
            base["radius"] = self._expression_to_dict(entity.radius)
        elif isinstance(entity, SketchArc):
            base["center_point_id"] = entity.center_point_id
            base["start_point_id"] = entity.start_point_id
            base["end_point_id"] = entity.end_point_id
        elif isinstance(entity, SketchInfiniteLine):
            base["point_a_id"] = entity.point_a_id
            base["point_b_id"] = entity.point_b_id
        elif isinstance(entity, SketchSpline):
            base["control_point_ids"] = entity.control_point_ids
        return base

    def _sketch_entity_from_dict(
        self,
        data: dict,
    ) -> SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine | SketchSpline:
        entity_type = SketchEntityType(data["type"])
        common = {
            "id": data["id"],
            "name": data["name"],
            "type": entity_type,
            "visible": data.get("visible", True),
            "construction": data.get("construction", False),
            "selectable": data.get("selectable", True),
            "style": self._style_from_dict(data.get("style")),
            "metadata": Metadata(data.get("metadata", {})),
        }
        if entity_type is SketchEntityType.POINT:
            return SketchPoint(
                x=self._expression_from_dict(data["x"]),
                y=self._expression_from_dict(data["y"]),
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
                radius=self._expression_from_dict(data["radius"]),
                **common,
            )
        if entity_type is SketchEntityType.ARC:
            # Fallback: support legacy 3-point arc serialization
            if "point_a_id" in data:
                return SketchArc(
                    center_point_id=data["point_a_id"],
                    start_point_id=data["point_b_id"],
                    end_point_id=data["point_c_id"],
                    **common,
                )
            return SketchArc(
                center_point_id=data["center_point_id"],
                start_point_id=data["start_point_id"],
                end_point_id=data["end_point_id"],
                **common,
            )
        if entity_type is SketchEntityType.SPLINE:
            return SketchSpline(
                control_point_ids=data.get("control_point_ids", []),
                **common,
            )
        return SketchInfiniteLine(
            point_a_id=data["point_a_id"],
            point_b_id=data["point_b_id"],
            **common,
        )

    # ------------------------------------------------------------------
    # Block diagram serialization (Paso 2.7)
    # ------------------------------------------------------------------

    def _block_diagram_to_dict(self, diagram: BlockDiagram) -> dict:
        return {
            "instances": {
                instance_id: {
                    "block_type": instance.block_type,
                    "parameters": instance.parameters,
                    "input_ports": [
                        {"name": p.name, "shape": p.shape} for p in instance.input_ports
                    ],
                    "output_ports": [
                        {"name": p.name, "shape": p.shape} for p in instance.output_ports
                    ],
                    "position": instance.position,
                }
                for instance_id, instance in diagram.instances.items()
            },
            "connections": [
                {
                    "src_instance": c.src_instance,
                    "src_port": c.src_port,
                    "dst_instance": c.dst_instance,
                    "dst_port": c.dst_port,
                }
                for c in diagram.connections
            ],
        }

    def _block_diagram_from_dict(self, data: dict | None) -> BlockDiagram | None:
        if data is None:
            return None
        instances = {
            instance_id: BlockInstance(
                instance_id=instance_id,
                block_type=item["block_type"],
                parameters=item.get("parameters", {}),
                input_ports=[
                    PortSpec(p["name"], tuple(p["shape"])) for p in item.get("input_ports", [])
                ],
                output_ports=[
                    PortSpec(p["name"], tuple(p["shape"])) for p in item.get("output_ports", [])
                ],
                position=tuple(item.get("position", [0.0, 0.0])),
            )
            for instance_id, item in data.get("instances", {}).items()
        }
        connections = [
            Connection(
                src_instance=c["src_instance"],
                src_port=c["src_port"],
                dst_instance=c["dst_instance"],
                dst_port=c["dst_port"],
            )
            for c in data.get("connections", [])
        ]
        return BlockDiagram(instances=instances, connections=connections)

    # ------------------------------------------------------------------
    # Workspace serialization
    # ------------------------------------------------------------------

    def _workspace_to_dict(self, workspace: Workspace) -> dict:
        return {
            "baselines": [self._baseline_to_dict(b) for b in workspace.baselines],
            "active_baseline_id": workspace.active_baseline_id,
            "active_case_id": workspace.active_case_id,
            "selected_pose_id": workspace.selected_pose_id,
            "selected_analysis_id": workspace.selected_analysis_id,
            "cases": [self._case_to_dict(c) for c in workspace.cases],
            "poses": [self._workspace_pose_to_dict(p) for p in workspace.poses],
            "analyses": [self._analysis_to_dict(a) for a in workspace.analyses],
            "case_groups": [self._case_group_to_dict(cg) for cg in workspace.case_groups],
            "studies": [self._study_to_dict(s) for s in workspace.studies],
            "runs": [self._run_to_dict(r) for r in workspace.runs],
            "parameter_catalog": {
                k: self._parameter_descriptor_to_dict(v) for k, v in workspace.parameter_catalog.items()
            },
            "model_snapshots": dict(workspace.model_snapshots),
            "promotion_history": list(workspace.promotion_history),
            "next_sequence": workspace.next_sequence,
        }

    def _workspace_from_dict(self, data: dict | None) -> Workspace | None:
        if data is None:
            return None
        return Workspace(
            baselines=[self._baseline_from_dict(b) for b in data.get("baselines", [])],
            active_baseline_id=data.get("active_baseline_id"),
            active_case_id=data.get("active_case_id"),
            selected_pose_id=data.get("selected_pose_id"),
            selected_analysis_id=data.get("selected_analysis_id"),
            cases=[self._case_from_dict(c) for c in data.get("cases", [])],
            poses=[self._workspace_pose_from_dict(p) for p in data.get("poses", [])],
            analyses=[self._analysis_from_dict(a) for a in data.get("analyses", [])],
            case_groups=[self._case_group_from_dict(cg) for cg in data.get("case_groups", [])],
            studies=[self._study_from_dict(s) for s in data.get("studies", [])],
            runs=[self._run_from_dict(r) for r in data.get("runs", [])],
            parameter_catalog={
                k: self._parameter_descriptor_from_dict(v)
                for k, v in data.get("parameter_catalog", {}).items()
            },
            model_snapshots=data.get("model_snapshots", {}),
            promotion_history=data.get("promotion_history", []),
            next_sequence=data.get("next_sequence", 1),
        )

    def _parameter_descriptor_to_dict(self, descriptor: ParameterDescriptor) -> dict:
        return {
            "path": descriptor.path,
            "tag": descriptor.tag,
            "display_name": descriptor.display_name,
            "unit": descriptor.unit,
            "dimension": descriptor.dimension,
            "default_value": descriptor.default_value,
            "entity_id": descriptor.entity_id,
            "property_name": descriptor.property_name,
        }

    def _parameter_descriptor_from_dict(self, data: dict) -> ParameterDescriptor:
        return ParameterDescriptor(
            path=data["path"],
            tag=data.get("tag", "invariant"),
            display_name=data.get("display_name", ""),
            unit=data.get("unit", ""),
            dimension=data.get("dimension", ""),
            default_value=data.get("default_value"),
            entity_id=data.get("entity_id"),
            property_name=data.get("property_name"),
        )

    def _scalar_value_to_dict(self, value: ScalarValue) -> dict:
        return {"value": value.value, "unit": value.unit}

    def _scalar_value_from_dict(self, data: dict) -> ScalarValue:
        return ScalarValue(value=float(data["value"]), unit=data.get("unit", ""))

    def _tolerance_to_dict(self, tolerance: Tolerance) -> dict:
        result: dict = {"metric_key": tolerance.metric_key}
        if tolerance.absolute is not None:
            result["absolute"] = tolerance.absolute
        if tolerance.relative is not None:
            result["relative"] = tolerance.relative
        return result

    def _tolerance_from_dict(self, data: dict) -> Tolerance:
        return Tolerance(
            metric_key=data["metric_key"],
            absolute=data.get("absolute"),
            relative=data.get("relative"),
        )

    def _metric_definition_to_dict(self, metric: MetricDefinition) -> dict:
        return {
            "key": metric.key,
            "name": metric.name,
            "extractor": metric.extractor,
            "unit": metric.unit,
        }

    def _metric_definition_from_dict(self, data: dict) -> MetricDefinition:
        return MetricDefinition(
            key=data["key"],
            name=data["name"],
            extractor=data["extractor"],
            unit=data.get("unit", ""),
        )

    def _baseline_to_dict(self, baseline: Baseline) -> dict:
        return {
            "id": baseline.id,
            "name": baseline.name,
            "description": baseline.description,
            "source_run_id": baseline.source_run_id,
            "model_snapshot_id": baseline.model_snapshot_id,
            "model_hash": baseline.model_hash,
            "invariant_parameter_keys": baseline.invariant_parameter_keys,
            "approval_status": baseline.approval_status,
            "approved_run_id": baseline.approved_run_id,
            "tolerances": {
                k: self._tolerance_to_dict(v) for k, v in baseline.tolerances.items()
            },
            "metrics": {
                k: self._metric_definition_to_dict(v) for k, v in baseline.metrics.items()
            },
            "metadata": baseline.metadata,
        }

    def _baseline_from_dict(self, data: dict) -> Baseline:
        return Baseline(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            source_run_id=data.get("source_run_id"),
            model_snapshot_id=data.get("model_snapshot_id"),
            model_hash=data.get("model_hash"),
            invariant_parameter_keys=data.get("invariant_parameter_keys", []),
            approval_status=data.get("approval_status"),
            approved_run_id=data.get("approved_run_id"),
            tolerances={
                k: self._tolerance_from_dict(v)
                for k, v in data.get("tolerances", {}).items()
            },
            metrics={
                k: self._metric_definition_from_dict(v)
                for k, v in data.get("metrics", {}).items()
            },
            metadata=data.get("metadata", {}),
        )

    def _case_to_dict(self, case: Case) -> dict:
        result = {
            "id": case.id,
            "name": case.name,
            "baseline_id": case.baseline_id,
            "parent_case_id": case.parent_case_id,
            "model_snapshot_id": case.model_snapshot_id,
            "invariant_values": {
                k: self._scalar_value_to_dict(v) for k, v in case.invariant_values.items()
            },
            "metadata": case.metadata,
        }
        # Structural diffs
        if case.added_entities:
            result["added_entities"] = {
                domain: [self._entity_to_dict_by_domain(domain, entity) for entity in entities]
                for domain, entities in case.added_entities.items()
            }
        if case.removed_entity_ids:
            result["removed_entity_ids"] = case.removed_entity_ids
        if case.reference_overrides:
            result["reference_overrides"] = case.reference_overrides
        return result

    def _entity_to_dict_by_domain(self, domain: str, entity: dict) -> dict:
        # added_entities stores serialized dicts; pass through
        return entity

    def _case_from_dict(self, data: dict) -> Case:
        return Case(
            id=data["id"],
            name=data["name"],
            baseline_id=data.get("baseline_id"),
            parent_case_id=data.get("parent_case_id"),
            model_snapshot_id=data.get("model_snapshot_id"),
            invariant_values={
                k: self._scalar_value_from_dict(v)
                for k, v in data.get("invariant_values", {}).items()
            },
            added_entities=data.get("added_entities", {}),
            removed_entity_ids=data.get("removed_entity_ids", []),
            reference_overrides=data.get("reference_overrides", {}),
            metadata=data.get("metadata", {}),
        )

    def _workspace_pose_to_dict(self, pose: WorkspacePose) -> dict:
        return {
            "id": pose.id,
            "name": pose.name,
            "baseline_id": pose.baseline_id,
            "case_id": pose.case_id,
            "project_pose_id": pose.project_pose_id,
            "is_default": pose.is_default,
            "parent_pose_id": pose.parent_pose_id,
            "requires_recompute": pose.requires_recompute,
            "solve_failed": pose.solve_failed,
            "metadata": pose.metadata,
        }

    def _workspace_pose_from_dict(self, data: dict) -> WorkspacePose:
        return WorkspacePose(
            id=data["id"],
            name=data["name"],
            baseline_id=data.get("baseline_id"),
            case_id=data.get("case_id"),
            project_pose_id=data.get("project_pose_id"),
            is_default=data.get("is_default", False),
            parent_pose_id=data.get("parent_pose_id"),
            requires_recompute=data.get("requires_recompute", True),
            solve_failed=data.get("solve_failed", False),
            metadata=data.get("metadata", {}),
        )

    def _analysis_to_dict(self, analysis: Analysis) -> dict:
        return {
            "id": analysis.id,
            "name": analysis.name,
            "analysis_type": analysis.analysis_type,
            "baseline_id": analysis.baseline_id,
            "case_id": analysis.case_id,
            "workspace_pose_id": analysis.workspace_pose_id,
            "config": self._study_config_to_dict(analysis.config),
            "metadata": analysis.metadata,
        }

    def _analysis_from_dict(self, data: dict) -> Analysis:
        return Analysis(
            id=data["id"],
            name=data["name"],
            analysis_type=data.get("analysis_type", "dynamic"),
            baseline_id=data.get("baseline_id"),
            case_id=data.get("case_id"),
            workspace_pose_id=data.get("workspace_pose_id"),
            config=self._study_config_from_dict(data.get("config", {})),
            metadata=data.get("metadata", {}),
        )

    def _sweep_parameter_to_dict(self, sp: SweepParameter) -> dict:
        return {
            "parameter_path": sp.parameter_path,
            "values": [self._scalar_value_to_dict(v) for v in sp.values],
        }

    def _sweep_parameter_from_dict(self, data: dict) -> SweepParameter:
        return SweepParameter(
            parameter_path=data["parameter_path"],
            values=[
                self._scalar_value_from_dict(v) for v in data.get("values", [])
            ],
        )

    def _case_group_to_dict(self, cg: CaseGroup) -> dict:
        return {
            "id": cg.id,
            "name": cg.name,
            "baseline_id": cg.baseline_id,
            "sweep_parameters": [
                self._sweep_parameter_to_dict(sp) for sp in cg.sweep_parameters
            ],
            "generated_case_ids": cg.generated_case_ids,
        }

    def _case_group_from_dict(self, data: dict) -> CaseGroup:
        return CaseGroup(
            id=data["id"],
            name=data["name"],
            baseline_id=data.get("baseline_id", ""),
            sweep_parameters=[
                self._sweep_parameter_from_dict(sp)
                for sp in data.get("sweep_parameters", [])
            ],
            generated_case_ids=data.get("generated_case_ids", []),
        )

    def _study_config_to_dict(self, config: StudyConfig) -> dict:
        return {
            "duration": config.duration,
            "steps": config.steps,
            "translation_driver_mode": config.translation_driver_mode,
            "solver_settings": config.solver_settings,
        }

    def _study_config_from_dict(self, data: dict) -> StudyConfig:
        return StudyConfig(
            duration=data.get("duration", 1.0),
            steps=data.get("steps", 100),
            translation_driver_mode=data.get("translation_driver_mode", "constraint"),
            solver_settings=data.get("solver_settings", {}),
        )

    def _study_mask_to_dict(self, mask: StudyMask) -> dict:
        return {
            "include_cases": mask.include_cases,
            "exclude_cases": mask.exclude_cases,
            "include_baseline": mask.include_baseline,
        }

    def _study_mask_from_dict(self, data: dict) -> StudyMask:
        return StudyMask(
            include_cases=data.get("include_cases"),
            exclude_cases=data.get("exclude_cases"),
            include_baseline=data.get("include_baseline", True),
        )

    def _study_overlay_to_dict(self, overlay: StudyOverlay | None) -> dict | None:
        if overlay is None:
            return None
        result: dict = {
            "parameter_overrides": {
                k: self._scalar_value_to_dict(v)
                for k, v in overlay.parameter_overrides.items()
            },
        }
        if overlay.block_diagram_overlay is not None:
            result["block_diagram_overlay"] = self._block_diagram_to_dict(
                overlay.block_diagram_overlay
            )
        return result

    def _study_overlay_from_dict(self, data: dict | None) -> StudyOverlay | None:
        if data is None:
            return None
        return StudyOverlay(
            parameter_overrides={
                k: self._scalar_value_from_dict(v)
                for k, v in data.get("parameter_overrides", {}).items()
            },
            block_diagram_overlay=self._block_diagram_from_dict(
                data.get("block_diagram_overlay")
            ),
        )

    def _study_to_dict(self, study: Study) -> dict:
        result: dict = {
            "id": study.id,
            "name": study.name,
            "study_type": study.study_type,
            "config": self._study_config_to_dict(study.config),
            "variable_values": {
                k: self._scalar_value_to_dict(v) for k, v in study.variable_values.items()
            },
            "mask": self._study_mask_to_dict(study.mask),
        }
        if study.overlay is not None:
            result["overlay"] = self._study_overlay_to_dict(study.overlay)
        return result

    def _study_from_dict(self, data: dict) -> Study:
        return Study(
            id=data["id"],
            name=data["name"],
            study_type=data.get("study_type", "dynamic"),
            config=self._study_config_from_dict(data.get("config", {})),
            variable_values={
                k: self._scalar_value_from_dict(v)
                for k, v in data.get("variable_values", {}).items()
            },
            mask=self._study_mask_from_dict(data.get("mask", {})),
            overlay=self._study_overlay_from_dict(data.get("overlay")),
        )

    def _result_ref_to_dict(self, ref: ResultRef) -> dict:
        return {
            "run_entry_id": ref.run_entry_id,
            "artifact_path": ref.artifact_path,
            "checksum": ref.checksum,
        }

    def _result_ref_from_dict(self, data: dict) -> ResultRef:
        return ResultRef(
            run_entry_id=data["run_entry_id"],
            artifact_path=data["artifact_path"],
            checksum=data["checksum"],
        )

    def _artifact_ref_to_dict(self, ref: ArtifactRef) -> dict:
        return {
            "kind": ref.kind,
            "path": ref.path,
            "checksum": ref.checksum,
            "metadata": ref.metadata,
        }

    def _artifact_ref_from_dict(self, data: dict) -> ArtifactRef:
        return ArtifactRef(
            kind=data["kind"],
            path=data["path"],
            checksum=data.get("checksum", ""),
            metadata=data.get("metadata", {}),
        )

    def _run_entry_to_dict(self, entry: RunEntry) -> dict:
        result: dict = {
            "id": entry.id,
            "scope": entry.scope,
            "baseline_id": entry.baseline_id,
            "case_id": entry.case_id,
            "status": entry.status,
            "fingerprint": entry.fingerprint,
            "stale_reasons": entry.stale_reasons,
            "started_at": entry.started_at,
            "finished_at": entry.finished_at,
            "updated_at": entry.updated_at,
            "artifacts": [self._artifact_ref_to_dict(a) for a in entry.artifacts],
            "metrics": entry.metrics,
            "error_message": entry.error_message,
        }
        if entry.result_ref is not None:
            result["result_ref"] = self._result_ref_to_dict(entry.result_ref)
        return result

    def _run_entry_from_dict(self, data: dict) -> RunEntry:
        ref_data = data.get("result_ref")
        return RunEntry(
            id=data["id"],
            scope=data["scope"],
            baseline_id=data.get("baseline_id"),
            case_id=data.get("case_id"),
            status=data.get("status", "not_run"),
            fingerprint=data.get("fingerprint", ""),
            stale_reasons=data.get("stale_reasons", []),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            updated_at=data.get("updated_at"),
            result_ref=self._result_ref_from_dict(ref_data) if ref_data else None,
            artifacts=[self._artifact_ref_from_dict(a) for a in data.get("artifacts", [])],
            metrics=data.get("metrics", {}),
            error_message=data.get("error_message", ""),
        )

    def _run_to_dict(self, run: Run) -> dict:
        return {
            "id": run.id,
            "study_id": run.study_id,
            "created_at": run.created_at,
            "analysis_id": run.analysis_id,
            "status": run.status,
            "entries": [self._run_entry_to_dict(e) for e in run.entries],
        }

    def _run_from_dict(self, data: dict) -> Run:
        return Run(
            id=data["id"],
            study_id=data.get("study_id"),
            created_at=data["created_at"],
            analysis_id=data.get("analysis_id"),
            status=data.get("status", "not_run"),
            entries=[self._run_entry_from_dict(e) for e in data.get("entries", [])],
        )
