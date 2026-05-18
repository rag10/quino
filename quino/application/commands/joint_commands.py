"""Joint-related commands extracted from ApplicationService.

Handles sliders, joints, drivers, and all geometric helpers that
translate/rotate joints when connected entities move.
"""
from __future__ import annotations

import math
import re

from quino.application._context import ServiceContext
from quino.domain.inputs import JointEndpointInput, PropertyValueInput, SliderInput
from quino.domain.model import (
    Body,
    Driver,
    Joint,
    JointEndpoint,
    Marker,
    Project,
    ScalarProperty,
    Slider,
)
from quino.domain.types import (
    Dimension,
    DriverType,
    JointEndpointKind,
    JointType,
)


class JointCommands:
    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    @property
    def _project(self) -> Project:
        project = self._ctx.project_provider()
        if project is None:
            raise ValueError("No project loaded")
        return project

    # ------------------------------------------------------------------
    # Small numeric helpers
    # ------------------------------------------------------------------

    def _scalar(self, expression: str, unit: str, dimension: Dimension) -> ScalarProperty:
        return ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension)

    def _mm_expression(self, value: float) -> str:
        return f"{value:.6g} mm"

    # ------------------------------------------------------------------
    # Endpoint helpers
    # ------------------------------------------------------------------

    def _make_endpoint(self, endpoint: JointEndpointInput) -> JointEndpoint:
        return JointEndpoint(
            kind=endpoint.kind,
            body_id=endpoint.body_id,
            marker_id=endpoint.marker_id,
            slider_id=endpoint.slider_id,
        )

    def _validate_endpoint_input(self, endpoint: JointEndpointInput, project: Project) -> None:
        if endpoint.kind is JointEndpointKind.MARKER:
            if endpoint.body_id is None or endpoint.marker_id is None:
                raise ValueError("Marker endpoints require body_id and marker_id")
            body = None
            for b in project.model.bodies:
                if b.id == endpoint.body_id:
                    body = b
                    break
            if body is None:
                raise ValueError(f"Body not found: {endpoint.body_id}")
            marker = None
            for m in body.markers:
                if m.id == endpoint.marker_id:
                    marker = m
                    break
            if marker is None:
                raise ValueError(f"Marker not found: {endpoint.marker_id} in body {endpoint.body_id}")
            return
        if endpoint.kind is JointEndpointKind.SLIDER:
            if endpoint.slider_id is None:
                raise ValueError("Slider endpoints require slider_id")
            slider = None
            for s in project.model.sliders:
                if s.id == endpoint.slider_id:
                    slider = s
                    break
            if slider is None:
                raise ValueError(f"Slider not found: {endpoint.slider_id}")
            return
        if endpoint.kind is JointEndpointKind.GROUND:
            return
        raise ValueError(f"Unsupported endpoint kind: {endpoint.kind}")

    # ------------------------------------------------------------------
    # Joint finders
    # ------------------------------------------------------------------

    def _find_joint(self, joint_id: str) -> Joint:
        project = self._project
        for joint in project.model.joints:
            if joint.id == joint_id:
                return joint
        raise ValueError(f"Unknown joint: {joint_id}")

    def _find_body_by_marker(self, marker_id: str) -> Body:
        project = self._project
        for body in project.model.bodies:
            if any(marker.id == marker_id for marker in body.markers):
                return body
        raise ValueError(f"Unknown marker: {marker_id}")

    # ------------------------------------------------------------------
    # Duplication / topology checks
    # ------------------------------------------------------------------

    def _ensure_joint_not_duplicate(self, candidate: Joint) -> None:
        project = self._project
        new_key = self._ctx.validation._joint_key(candidate)
        for joint in project.model.joints:
            if self._ctx.validation._joint_key(joint) == new_key:
                raise ValueError("Duplicate joint between the same endpoints")

    def _joint_has_slider(self, joint: Joint) -> bool:
        return joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER

    def _marker_slider_endpoints(self, joint: Joint) -> tuple[JointEndpoint | None, JointEndpoint | None]:
        marker_endpoint = None
        slider_endpoint = None
        for endpoint in (joint.endpoint_a, joint.endpoint_b):
            if endpoint.kind is JointEndpointKind.MARKER:
                marker_endpoint = endpoint
            elif endpoint.kind is JointEndpointKind.SLIDER:
                slider_endpoint = endpoint
        return marker_endpoint, slider_endpoint

    def _joints_for_marker(self, marker_id: str) -> list[Joint]:
        project = self._project
        return [
            joint
            for joint in project.model.joints
            if joint.endpoint_a.marker_id == marker_id or joint.endpoint_b.marker_id == marker_id
        ]

    def _translate_direct_joint_counterparts(
        self,
        marker_id: str,
        joints: list[Joint],
        delta_x_mm: float,
        delta_y_mm: float,
    ) -> set[str]:
        # Direct-only: move immediate counterparts of marker_id, no BFS transitives
        moved_marker_ids: set[str] = {marker_id}
        moved_slider_ids: set[str] = set()
        for joint in joints:
            ep_a, ep_b = joint.endpoint_a, joint.endpoint_b
            counterpart_marker_id: str | None = None
            counterpart_slider_id: str | None = None
            if ep_a.kind is JointEndpointKind.MARKER and ep_a.marker_id == marker_id:
                if ep_b.kind is JointEndpointKind.MARKER:
                    counterpart_marker_id = ep_b.marker_id
                elif ep_b.kind is JointEndpointKind.SLIDER:
                    counterpart_slider_id = ep_b.slider_id
            elif ep_b.kind is JointEndpointKind.MARKER and ep_b.marker_id == marker_id:
                if ep_a.kind is JointEndpointKind.MARKER:
                    counterpart_marker_id = ep_a.marker_id
                elif ep_a.kind is JointEndpointKind.SLIDER:
                    counterpart_slider_id = ep_a.slider_id
            else:
                continue
            if counterpart_marker_id and counterpart_marker_id not in moved_marker_ids:
                linked_marker = self._ctx.find_entity(counterpart_marker_id)
                if isinstance(linked_marker, Marker):
                    self._translate_marker_expression(linked_marker, delta_x_mm, delta_y_mm)
                    moved_marker_ids.add(counterpart_marker_id)
            if counterpart_slider_id and counterpart_slider_id not in moved_slider_ids:
                linked_slider = self._ctx.find_entity(counterpart_slider_id)
                if isinstance(linked_slider, Slider):
                    self._translate_slider_expression(
                        linked_slider,
                        delta_x_mm,
                        delta_y_mm,
                        moved_marker_ids=moved_marker_ids,
                    )
                    moved_slider_ids.add(counterpart_slider_id)
        return moved_marker_ids

    # ------------------------------------------------------------------
    # Expression arithmetic helpers
    # ------------------------------------------------------------------

    _OFFSET_RE = re.compile(r'^\((.*)\)\s+([+-])\s+([\d.]+)\s+(mm|m|deg|rad)$')

    def _offset_expression(self, expression: str, delta: float, unit: str) -> str:
        if abs(delta) < 1e-12:
            return expression
        sign = "+" if delta >= 0 else "-"
        return f"({expression}) {sign} {abs(delta):.6f} {unit}"

    def _strip_offset(self, expression: str) -> str:
        """Undo the outermost offset wrapper added by _offset_expression."""
        match = self._OFFSET_RE.match(expression.strip())
        if not match:
            return expression.strip()
        return match.group(1).strip()

    def _evaluate_scalar_as(self, scalar: ScalarProperty, unit: str) -> float:
        result = self._ctx.expressions.evaluate_property(
            scalar,
            self._project.parameters,
        )
        return self._ctx.units.convert(
            self._ctx.units.quantity(result.value, result.unit),
            unit,
        )

    def _slider_center_mm(self, slider: Slider) -> tuple[float, float]:
        return (
            self._evaluate_scalar_as(slider.origin_x, "mm"),
            self._evaluate_scalar_as(slider.origin_y, "mm"),
        )

    # ------------------------------------------------------------------
    # Marker / slider expression translation helpers
    # ------------------------------------------------------------------

    def _translate_marker_expression(
        self,
        marker: Marker,
        delta_x_mm: float,
        delta_y_mm: float,
    ) -> None:
        marker.x.expression = self._offset_expression(marker.x.expression, delta_x_mm, "mm")
        marker.y.expression = self._offset_expression(marker.y.expression, delta_y_mm, "mm")

    def _set_marker_absolute_mm(self, marker: Marker, x_mm: float, y_mm: float) -> None:
        marker.x.expression = f"{x_mm:.6f} mm"
        marker.y.expression = f"{y_mm:.6f} mm"

    def _markers_linked_to_slider(self, slider_id: str) -> list[Marker]:
        project = self._project
        marker_ids: list[str] = []
        for joint in project.model.joints:
            endpoints = (joint.endpoint_a, joint.endpoint_b)
            has_slider = any(
                endpoint.kind is JointEndpointKind.SLIDER and endpoint.slider_id == slider_id
                for endpoint in endpoints
            )
            if not has_slider:
                continue
            for endpoint in endpoints:
                if endpoint.kind is JointEndpointKind.MARKER and endpoint.marker_id is not None:
                    marker_ids.append(endpoint.marker_id)
        markers: list[Marker] = []
        seen: set[str] = set()
        for marker_id in marker_ids:
            if marker_id in seen:
                continue
            entity = self._ctx.find_entity(marker_id)
            if isinstance(entity, Marker):
                markers.append(entity)
                seen.add(marker_id)
        return markers

    def _translate_markers_linked_to_slider(
        self,
        slider_id: str,
        delta_x_mm: float,
        delta_y_mm: float,
        moved_marker_ids: set[str],
    ) -> None:
        for linked_marker in self._markers_linked_to_slider(slider_id):
            if linked_marker.id in moved_marker_ids:
                continue
            self._translate_marker_expression(linked_marker, delta_x_mm, delta_y_mm)
            moved_marker_ids.add(linked_marker.id)

    def _translate_slider_expression(
        self,
        slider: Slider,
        delta_x_mm: float,
        delta_y_mm: float,
        moved_marker_ids: set[str] | None = None,
    ) -> None:
        slider.origin_x.expression = self._offset_expression(
            slider.origin_x.expression,
            delta_x_mm,
            "mm",
        )
        slider.origin_y.expression = self._offset_expression(
            slider.origin_y.expression,
            delta_y_mm,
            "mm",
        )
        self._translate_markers_linked_to_slider(
            slider.id,
            delta_x_mm,
            delta_y_mm,
            moved_marker_ids or set(),
        )

    # ------------------------------------------------------------------
    # Slider geometry mutators
    # ------------------------------------------------------------------

    def _move_slider_origin(self, slider_id: str, x_expression: str, y_expression: str) -> None:
        slider = self._ctx.find_entity(slider_id)
        if not isinstance(slider, Slider):
            raise ValueError("move_slider_origin requires a slider entity")
        new_x = ScalarProperty(
            expression=x_expression,
            unit=slider.origin_x.unit,
            expected_dimension=Dimension.LENGTH,
        )
        new_y = ScalarProperty(
            expression=y_expression,
            unit=slider.origin_y.unit,
            expected_dimension=Dimension.LENGTH,
        )
        target_x = self._evaluate_scalar_as(new_x, "mm")
        target_y = self._evaluate_scalar_as(new_y, "mm")
        current_x = self._evaluate_scalar_as(slider.origin_x, "mm")
        current_y = self._evaluate_scalar_as(slider.origin_y, "mm")
        delta_x = target_x - current_x
        delta_y = target_y - current_y
        if abs(delta_x) < 1e-12 and abs(delta_y) < 1e-12:
            if (
                slider.origin_x.expression != x_expression
                or slider.origin_y.expression != y_expression
            ):
                self._ctx.snapshot()
                slider.origin_x = new_x
                slider.origin_y = new_y
                self._ctx.invalidate_pose_state()
            return
        self._ctx.snapshot()
        slider.origin_x = new_x
        slider.origin_y = new_y
        moved_marker_ids: set[str] = set()
        self._translate_markers_linked_to_slider(slider.id, delta_x, delta_y, moved_marker_ids)
        self._ctx.invalidate_pose_state()

    def _rotate_slider(self, slider_id: str, angle_expression: str) -> None:
        slider = self._ctx.find_entity(slider_id)
        if not isinstance(slider, Slider):
            raise ValueError("rotate_slider requires a slider entity")
        new_angle = ScalarProperty(
            expression=angle_expression,
            unit=slider.angle.unit,
            expected_dimension=Dimension.ANGLE,
        )
        old_angle = self._evaluate_scalar_as(slider.angle, "rad")
        target_angle = self._evaluate_scalar_as(new_angle, "rad")
        origin_x = self._evaluate_scalar_as(slider.origin_x, "mm")
        origin_y = self._evaluate_scalar_as(slider.origin_y, "mm")
        old_axis = (math.cos(old_angle), math.sin(old_angle))
        new_axis = (math.cos(target_angle), math.sin(target_angle))
        linked_markers = self._markers_linked_to_slider(slider.id)
        marker_targets: list[tuple[Marker, float, float]] = []
        for marker in linked_markers:
            marker_x = self._evaluate_scalar_as(marker.x, "mm")
            marker_y = self._evaluate_scalar_as(marker.y, "mm")
            slider_coordinate = (
                (marker_x - origin_x) * old_axis[0]
                + (marker_y - origin_y) * old_axis[1]
            )
            marker_targets.append(
                (
                    marker,
                    origin_x + slider_coordinate * new_axis[0],
                    origin_y + slider_coordinate * new_axis[1],
                )
            )
        if abs(target_angle - old_angle) < 1e-12:
            if slider.angle.expression == angle_expression:
                return
            self._ctx.snapshot()
            slider.angle = new_angle
            self._ctx.invalidate_pose_state()
            return
        self._ctx.snapshot()
        slider.angle = new_angle
        for marker, marker_x, marker_y in marker_targets:
            self._set_marker_absolute_mm(marker, marker_x, marker_y)
        self._ctx.invalidate_pose_state()

    # ------------------------------------------------------------------
    # Friction accessors
    # ------------------------------------------------------------------

    def joint_friction_mode(self, joint: Joint) -> str | None:
        if joint.endpoint_a.kind is JointEndpointKind.SLIDER or joint.endpoint_b.kind is JointEndpointKind.SLIDER:
            return "translation"
        if joint.type is JointType.REVOLUTE:
            return "rotation"
        return None

    def joint_friction_values(self, joint: Joint) -> tuple[float, float]:
        coulomb = joint.metadata.values.get("friction_coulomb", 0.0)
        viscous = joint.metadata.values.get("friction_viscous", 0.0)
        try:
            return float(coulomb), float(viscous)
        except (TypeError, ValueError):
            return 0.0, 0.0

    def joint_friction_pin_radius(self, joint: Joint) -> float:
        r = joint.metadata.values.get("friction_pin_radius", 0.0)
        try:
            return float(r)
        except (TypeError, ValueError):
            return 0.0

    def joint_supports_angular_limits(self, joint: Joint) -> bool:
        return joint.type is JointType.REVOLUTE and not self._joint_has_slider(joint)

    def joint_angular_limit_expression(self, joint: Joint, path: str) -> str | None:
        value = joint.metadata.values.get(path)
        return value if isinstance(value, str) and value.strip() else None

    def joint_angular_limit_value(self, joint: Joint, path: str, *, unit: str = "deg") -> float | None:
        expression = self.joint_angular_limit_expression(joint, path)
        if expression is None:
            return None
        scalar = self._scalar(expression, "deg", Dimension.ANGLE)
        result = self._ctx.expressions.evaluate_property(scalar, self._project.parameters)
        return self._ctx.units.convert(
            self._ctx.units.quantity(result.value, result.unit),
            unit,
        )

    def _update_joint_friction_property(self, joint: Joint, path: str, value: PropertyValueInput) -> None:
        if self.joint_friction_mode(joint) is None:
            raise ValueError("This joint topology does not support friction")
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError(f"{path} requires a numeric value")
        if path == "friction_pin_radius":
            scalar = self._scalar(value.value, "mm", Dimension.LENGTH)
            result = self._ctx.expressions.evaluate_property(scalar, self._project.parameters)
            numeric = result.value
        else:
            try:
                numeric = float(value.value.strip().replace(",", "."))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path} must be a number") from exc
        self._ctx.snapshot()
        joint.metadata.values[path] = numeric

    def _update_joint_angular_limit_property(self, joint: Joint, path: str, value: PropertyValueInput) -> None:
        if not self.joint_supports_angular_limits(joint):
            raise ValueError("This joint topology does not support angular limits")
        if value.kind == "null":
            self._ctx.snapshot()
            joint.metadata.values.pop(path, None)
            return
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError(f"{path} requires an angular expression")
        expression = value.value.strip()
        if not expression or expression.lower() == "none":
            self._ctx.snapshot()
            joint.metadata.values.pop(path, None)
            return
        scalar = self._scalar(expression, "deg", Dimension.ANGLE)
        result = self._ctx.expressions.evaluate_property(scalar, self._project.parameters)
        limit_deg = self._ctx.units.convert(
            self._ctx.units.quantity(result.value, result.unit),
            "deg",
        )
        if limit_deg < 0.0:
            raise ValueError(f"{path} must be non-negative")
        self._ctx.snapshot()
        joint.metadata.values[path] = expression

    # ------------------------------------------------------------------
    # Public commands — sliders
    # ------------------------------------------------------------------

    def create_slider(self, name: str, slider: SliderInput) -> str:
        project = self._project
        self._ctx.validation.ensure_unique_name(project.model.sliders, name)
        slider_obj = Slider(
            id=self._ctx.ids.new("slider"),
            name=name,
            origin_x=self._scalar(slider.origin_x, "mm", Dimension.LENGTH),
            origin_y=self._scalar(slider.origin_y, "mm", Dimension.LENGTH),
            angle=self._scalar(slider.angle, "deg", Dimension.ANGLE),
            travel_min=self._scalar(slider.travel_min, "mm", Dimension.LENGTH) if slider.travel_min is not None else None,
            travel_max=self._scalar(slider.travel_max, "mm", Dimension.LENGTH) if slider.travel_max is not None else None,
        )
        self._ctx.expressions.evaluate_property(slider_obj.origin_x, project.parameters)
        self._ctx.expressions.evaluate_property(slider_obj.origin_y, project.parameters)
        self._ctx.expressions.evaluate_property(slider_obj.angle, project.parameters)
        if slider_obj.travel_min is not None:
            self._ctx.expressions.evaluate_property(slider_obj.travel_min, project.parameters)
        if slider_obj.travel_max is not None:
            self._ctx.expressions.evaluate_property(slider_obj.travel_max, project.parameters)
        self._ctx.snapshot()
        project.model.sliders.append(slider_obj)
        self._ctx.invalidate_pose_state()
        return slider_obj.id

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
        project = self._project
        start_x_value = self._ctx.expressions.evaluate_expression(start_x, project.parameters)
        start_y_value = self._ctx.expressions.evaluate_expression(start_y, project.parameters)
        end_x_value = self._ctx.expressions.evaluate_expression(end_x, project.parameters)
        end_y_value = self._ctx.expressions.evaluate_expression(end_y, project.parameters)
        sx = self._ctx.units.convert(start_x_value, "mm")
        sy = self._ctx.units.convert(start_y_value, "mm")
        ex = self._ctx.units.convert(end_x_value, "mm")
        ey = self._ctx.units.convert(end_y_value, "mm")
        origin_x = f"{0.5 * (sx + ex):.3f} mm"
        origin_y = f"{0.5 * (sy + ey):.3f} mm"
        angle_quantity = self._ctx.units.quantity(math.atan2(ey - sy, ex - sx), "rad")
        angle = f"{self._ctx.units.convert(angle_quantity, 'deg'):.6f} deg"
        half_length = 0.5 * ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
        return self.create_slider(
            name,
            SliderInput(
                origin_x,
                origin_y,
                angle,
                travel_min if travel_min is not None else f"{-half_length:.3f} mm",
                travel_max if travel_max is not None else f"{half_length:.3f} mm",
            ),
        )

    # ------------------------------------------------------------------
    # Public commands — joints
    # ------------------------------------------------------------------

    def create_joint(
        self,
        name: str,
        joint_type: str,
        endpoint_a: JointEndpointInput,
        endpoint_b: JointEndpointInput,
    ) -> str:
        project = self._project
        self._ctx.validation.ensure_unique_name(project.model.joints, name)
        self._validate_endpoint_input(endpoint_a, project)
        self._validate_endpoint_input(endpoint_b, project)
        joint = Joint(
            id=self._ctx.ids.new("joint"),
            name=name,
            type=JointType(joint_type),
            endpoint_a=self._make_endpoint(endpoint_a),
            endpoint_b=self._make_endpoint(endpoint_b),
        )
        self._ensure_joint_not_duplicate(joint)
        self._ctx.snapshot()
        project.model.joints.append(joint)
        # Invalidate entity index on the facade — there is no ctx field for it,
        # so we signal it via invalidate_pose_state which already handles the rest.
        # The entity index is rebuilt lazily; topology change forces rebuild via
        # _entity_index = None in ApplicationService._snapshot(). This is correct.
        self._ctx.invalidate_pose_state()
        return joint.id

    def create_rigid_joint(
        self,
        name: str,
        endpoint_a: JointEndpointInput,
        endpoint_b: JointEndpointInput,
    ) -> str:
        return self.create_joint(name, JointType.RIGID.value, endpoint_a, endpoint_b)

    def create_driver(
        self,
        name: str,
        driver_type: str,
        target_joint_id: str,
        expression: str,
        unit: str,
    ) -> str:
        project = self._project
        self._ctx.validation.ensure_unique_name(project.model.drivers, name)
        joint = self._find_joint(target_joint_id)
        dtype = DriverType(driver_type)
        if any(driver.target_joint_id == target_joint_id for driver in project.model.drivers):
            raise ValueError("Only one driver per joint is supported in V1")
        if dtype is DriverType.ROTATION and joint.type is not JointType.REVOLUTE:
            raise ValueError("Rotation drivers require a revolute joint")
        if dtype is DriverType.TRANSLATION and not self._joint_has_slider(joint):
            raise ValueError("Translation drivers require a slider joint")
        law = ScalarProperty(
            expression=expression,
            unit=unit,
            expected_dimension=Dimension.ANGLE if dtype is DriverType.ROTATION else Dimension.LENGTH,
        )
        self._ctx.expressions.evaluate_property(
            law,
            project.parameters,
            variables={"t": self._ctx.units.quantity(0.0, "s")},
        )
        self._ctx.snapshot()
        driver = Driver(
            id=self._ctx.ids.new("driver"),
            name=name,
            type=dtype,
            target_joint_id=target_joint_id,
            law=law,
        )
        project.model.drivers.append(driver)
        return driver.id

    def set_joint_type(self, joint_id: str, joint_type: str) -> None:
        joint = self._find_joint(joint_id)
        new_type = JointType(joint_type)
        if joint.type is new_type:
            return
        if any(driver.target_joint_id == joint_id for driver in self._project.model.drivers):
            raise ValueError("Cannot change joint type while it has a driver attached")
        self._ctx.snapshot()
        joint.type = new_type
        self._ctx.invalidate_pose_state()

    def connect_marker_to_ground(
        self, marker_id: str, joint_type: str = "revolute", name: str | None = None
    ) -> str:
        body = self._find_body_by_marker(marker_id)
        return self.create_joint(
            name=name or f"Ground_{marker_id}",
            joint_type=joint_type,
            endpoint_a=JointEndpointInput(JointEndpointKind.MARKER, body_id=body.id, marker_id=marker_id),
            endpoint_b=JointEndpointInput(JointEndpointKind.GROUND),
        )

    def connect_marker_to_slider(
        self,
        marker_id: str,
        slider_id: str,
        joint_type: str = "revolute",
        name: str | None = None,
        align: str = "marker_to_slider",
    ) -> str:
        body = self._find_body_by_marker(marker_id)
        marker = self._ctx.find_entity(marker_id)
        slider = self._ctx.find_entity(slider_id)
        if not isinstance(marker, Marker):
            raise ValueError("connect_marker_to_slider requires a marker")
        if not isinstance(slider, Slider):
            raise ValueError("connect_marker_to_slider requires a slider")
        if align not in {"marker_to_slider", "slider_to_marker", "none"}:
            raise ValueError("align must be marker_to_slider, slider_to_marker, or none")
        joint_name = name or f"{marker_id}_{slider_id}"
        joint_enum = JointType(joint_type)
        endpoint_a = JointEndpointInput(JointEndpointKind.MARKER, body_id=body.id, marker_id=marker_id)
        endpoint_b = JointEndpointInput(JointEndpointKind.SLIDER, slider_id=slider_id)
        candidate = Joint(
            id="__candidate__",
            name=joint_name,
            type=joint_enum,
            endpoint_a=self._make_endpoint(endpoint_a),
            endpoint_b=self._make_endpoint(endpoint_b),
        )
        project = self._project
        self._ctx.validation.ensure_unique_name(project.model.joints, joint_name)
        self._validate_endpoint_input(endpoint_a, project)
        self._validate_endpoint_input(endpoint_b, project)
        self._ensure_joint_not_duplicate(candidate)

        with self._ctx.operation():
            if align != "none":
                target_x, target_y = self._slider_center_mm(slider)
                target_x_expr = self._mm_expression(target_x)
                target_y_expr = self._mm_expression(target_y)
                project = self._project
                new_x = ScalarProperty(expression=target_x_expr, unit=marker.x.unit, expected_dimension=marker.x.expected_dimension)
                new_y = ScalarProperty(expression=target_y_expr, unit=marker.y.unit, expected_dimension=marker.y.expected_dimension)
                current_x_eval = self._ctx.expressions.evaluate_property(marker.x, project.parameters)
                current_y_eval = self._ctx.expressions.evaluate_property(marker.y, project.parameters)
                current_x = self._ctx.units.convert(self._ctx.units.quantity(current_x_eval.value, current_x_eval.unit), "mm")
                current_y = self._ctx.units.convert(self._ctx.units.quantity(current_y_eval.value, current_y_eval.unit), "mm")
                delta_x = target_x - current_x
                delta_y = target_y - current_y
                if abs(delta_x) > 1e-12 or abs(delta_y) > 1e-12:
                    marker.x = new_x
                    marker.y = new_y
                    linked_joints = self._ctx.joints_for_marker(marker_id)
                    if linked_joints:
                        self._ctx.translate_direct_joint_counterparts(marker_id, linked_joints, delta_x, delta_y)
            return self.create_joint(
                name=joint_name,
                joint_type=joint_enum.value,
                endpoint_a=endpoint_a,
                endpoint_b=endpoint_b,
            )

    def update_slider_geometry(
        self,
        slider_id: str,
        origin_x: str | None = None,
        origin_y: str | None = None,
        angle: str | None = None,
        travel_min: str | None = None,
        travel_max: str | None = None,
    ) -> None:
        """Atomically update all slider geometry properties in a single snapshot."""
        slider = self._ctx.find_entity(slider_id)
        if not isinstance(slider, Slider):
            raise ValueError("update_slider_geometry requires a slider entity")

        old_ox = self._evaluate_scalar_as(slider.origin_x, "mm")
        old_oy = self._evaluate_scalar_as(slider.origin_y, "mm")
        old_angle = self._evaluate_scalar_as(slider.angle, "rad")
        old_axis = (math.cos(old_angle), math.sin(old_angle))

        new_ox = self._evaluate_scalar_as(
            ScalarProperty(expression=origin_x, unit=slider.origin_x.unit, expected_dimension=Dimension.LENGTH), "mm"
        ) if origin_x is not None else old_ox
        new_oy = self._evaluate_scalar_as(
            ScalarProperty(expression=origin_y, unit=slider.origin_y.unit, expected_dimension=Dimension.LENGTH), "mm"
        ) if origin_y is not None else old_oy
        new_angle = self._evaluate_scalar_as(
            ScalarProperty(expression=angle, unit=slider.angle.unit, expected_dimension=Dimension.ANGLE), "rad"
        ) if angle is not None else old_angle
        new_axis = (math.cos(new_angle), math.sin(new_angle))

        changed = (
            (origin_x is not None and slider.origin_x.expression != origin_x)
            or (origin_y is not None and slider.origin_y.expression != origin_y)
            or (angle is not None and slider.angle.expression != angle)
            or (travel_min is not None and (
                (slider.travel_min is None and travel_min != "")
                or (slider.travel_min is not None and slider.travel_min.expression != travel_min)
            ))
            or (travel_max is not None and (
                (slider.travel_max is None and travel_max != "")
                or (slider.travel_max is not None and slider.travel_max.expression != travel_max)
            ))
        )

        linked_markers = self._markers_linked_to_slider(slider.id)
        marker_targets: list[tuple[Marker, float, float]] = []
        for marker in linked_markers:
            mx = self._evaluate_scalar_as(marker.x, "mm")
            my = self._evaluate_scalar_as(marker.y, "mm")
            slider_coordinate = (mx - old_ox) * old_axis[0] + (my - old_oy) * old_axis[1]
            marker_targets.append((
                marker,
                new_ox + slider_coordinate * new_axis[0],
                new_oy + slider_coordinate * new_axis[1],
            ))

        if not changed and not marker_targets:
            return

        self._ctx.snapshot()
        if origin_x is not None:
            slider.origin_x = ScalarProperty(
                expression=origin_x, unit=slider.origin_x.unit, expected_dimension=Dimension.LENGTH
            )
        if origin_y is not None:
            slider.origin_y = ScalarProperty(
                expression=origin_y, unit=slider.origin_y.unit, expected_dimension=Dimension.LENGTH
            )
        if angle is not None:
            slider.angle = ScalarProperty(
                expression=angle, unit=slider.angle.unit, expected_dimension=Dimension.ANGLE
            )
        if travel_min is not None:
            if travel_min == "" or travel_min.lower() == "none":
                slider.travel_min = None
            else:
                slider.travel_min = ScalarProperty(
                    expression=travel_min, unit="mm", expected_dimension=Dimension.LENGTH
                )
        if travel_max is not None:
            if travel_max == "" or travel_max.lower() == "none":
                slider.travel_max = None
            else:
                slider.travel_max = ScalarProperty(
                    expression=travel_max, unit="mm", expected_dimension=Dimension.LENGTH
                )
        for marker, marker_x, marker_y in marker_targets:
            self._set_marker_absolute_mm(marker, marker_x, marker_y)
        self._ctx.invalidate_pose_state()
