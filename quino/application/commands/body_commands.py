from __future__ import annotations

import math

from quino.application._context import ServiceContext
from quino.domain.inputs import MarkerInput, PropertyValueInput
from quino.domain.model import (
    Body,
    Marker,
    ScalarProperty,
    Style,
)
from quino.domain.types import (
    BodyType,
    Dimension,
    MarkerType,
)


class BodyCommands:
    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    @property
    def _project(self):
        project = self._ctx.project_provider()
        if project is None:
            raise ValueError("No project loaded")
        return project

    # ------------------------------------------------------------------
    # Small numeric helpers (duplicated from ApplicationService)
    # ------------------------------------------------------------------

    def _scalar(self, expression: str, unit: str, dimension: Dimension) -> ScalarProperty:
        return ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension)

    def _mm_expression(self, value: float) -> str:
        return f"{value:.6g} mm"

    # ------------------------------------------------------------------
    # Private helpers — body/marker internals
    # ------------------------------------------------------------------

    def _make_marker(self, body_id: str, marker_input: MarkerInput, is_first: bool) -> Marker:
        marker_name = marker_input.name or ("A" if is_first else self._ctx.ids.new("mk"))
        return Marker(
            id=self._ctx.ids.new("marker"),
            name=marker_name,
            type=marker_input.marker_type,
            x=self._scalar(marker_input.x, "mm", Dimension.LENGTH),
            y=self._scalar(marker_input.y, "mm", Dimension.LENGTH),
            visible=marker_input.visible,
        )

    def _make_com_marker(self, body: Body) -> Marker:
        structural = body.structural_markers()
        project = self._project
        x_vals = [self._ctx.expressions.evaluate_property(m.x, project.parameters).value for m in structural]
        y_vals = [self._ctx.expressions.evaluate_property(m.y, project.parameters).value for m in structural]
        x_avg = sum(x_vals) / len(x_vals) if x_vals else 0.0
        y_avg = sum(y_vals) / len(y_vals) if y_vals else 0.0
        com_marker = Marker(
            id=self._ctx.ids.new("marker"),
            name="CoM",
            type=MarkerType.COM,
            x=self._scalar(self._mm_expression(x_avg), "mm", Dimension.LENGTH),
            y=self._scalar(self._mm_expression(y_avg), "mm", Dimension.LENGTH),
            visible=False,
        )
        if body.type is BodyType.BAR and len(structural) == 2:
            com_marker.metadata.values["position_percent"] = 50.0
        return com_marker

    def _find_body(self, body_id: str) -> Body:
        project = self._project
        for body in project.model.bodies:
            if body.id == body_id:
                return body
        raise ValueError(f"Unknown body: {body_id}")

    def _find_body_by_marker(self, marker_id: str) -> Body:
        project = self._project
        for body in project.model.bodies:
            if any(marker.id == marker_id for marker in body.markers):
                return body
        raise ValueError(f"Unknown marker: {marker_id}")

    def sync_all_special_com_markers(self) -> None:
        project = self._ctx.project_provider()
        if project is None:
            return
        for body in project.model.bodies:
            self._sync_special_com_marker(body)

    def _sync_special_com_marker(self, body: Body) -> None:
        com_marker = body.com_marker()
        structural = body.structural_markers()
        if body.type is BodyType.POINT_MASS and len(structural) == 1:
            base = structural[0]
            com_marker.x = self._scalar(base.x.expression, base.x.unit, Dimension.LENGTH)
            com_marker.y = self._scalar(base.y.expression, base.y.unit, Dimension.LENGTH)
            com_marker.metadata.values.pop("position_percent", None)
            return
        if body.type is BodyType.BAR and len(structural) == 2:
            self._set_bar_com_from_percent(body, self._bar_com_percent(body))

    def _bar_structural_data(self, body: Body) -> tuple[Marker, Marker, float, float, float, float]:
        if body.type is not BodyType.BAR or len(body.structural_markers()) != 2:
            raise ValueError("Bar CoM helpers require a bar with exactly two structural markers")
        first, second = body.structural_markers()
        project = self._project
        x1 = self._ctx.expressions.evaluate_property(first.x, project.parameters).value
        y1 = self._ctx.expressions.evaluate_property(first.y, project.parameters).value
        x2 = self._ctx.expressions.evaluate_property(second.x, project.parameters).value
        y2 = self._ctx.expressions.evaluate_property(second.y, project.parameters).value
        return first, second, x1, y1, x2, y2

    def _bar_length(self, body: Body) -> float:
        _, _, x1, y1, x2, y2 = self._bar_structural_data(body)
        return math.hypot(x2 - x1, y2 - y1)

    def _bar_com_percent(self, body: Body) -> float:
        com_marker = body.com_marker()
        stored = com_marker.metadata.values.get("position_percent")
        if stored is not None:
            try:
                return max(0.0, min(100.0, float(stored)))
            except (TypeError, ValueError):
                pass
        _, _, x1, y1, x2, y2 = self._bar_structural_data(body)
        length_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if length_sq <= 1e-12:
            return 0.0
        project = self._project
        cx = self._ctx.expressions.evaluate_property(com_marker.x, project.parameters).value
        cy = self._ctx.expressions.evaluate_property(com_marker.y, project.parameters).value
        t = ((cx - x1) * (x2 - x1) + (cy - y1) * (y2 - y1)) / length_sq
        return max(0.0, min(100.0, t * 100.0))

    def _set_bar_com_from_percent(self, body: Body, percent: float) -> None:
        com_marker = body.com_marker()
        _, _, x1, y1, x2, y2 = self._bar_structural_data(body)
        clamped = max(0.0, min(100.0, percent))
        t = clamped / 100.0
        cx = x1 + t * (x2 - x1)
        cy = y1 + t * (y2 - y1)
        com_marker.x = self._scalar(self._mm_expression(cx), "mm", Dimension.LENGTH)
        com_marker.y = self._scalar(self._mm_expression(cy), "mm", Dimension.LENGTH)
        com_marker.metadata.values["position_percent"] = clamped

    def _set_bar_com_from_distance(self, body: Body, distance_mm: float) -> None:
        length = self._bar_length(body)
        if length <= 1e-12:
            self._set_bar_com_from_percent(body, 0.0)
            return
        clamped_distance = max(0.0, min(distance_mm, length))
        self._set_bar_com_from_percent(body, clamped_distance / length * 100.0)

    def _set_bar_com_from_point(self, body: Body, x: float, y: float) -> None:
        _, _, x1, y1, x2, y2 = self._bar_structural_data(body)
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            self._set_bar_com_from_percent(body, 0.0)
            return
        t = ((x - x1) * dx + (y - y1) * dy) / length_sq
        self._set_bar_com_from_percent(body, t * 100.0)

    def _update_bar_com_property(self, body: Body, property_path: str, value: PropertyValueInput) -> None:
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError("Bar CoM properties require an expression value")
        if property_path == "position_percent":
            try:
                percent = float(value.value.strip().replace(",", "."))
            except ValueError as exc:
                raise ValueError("position_percent must be a number between 0 and 100") from exc
            self._ctx.snapshot()
            self._set_bar_com_from_percent(body, percent)
            return
        scalar = self._scalar(value.value, "mm", Dimension.LENGTH)
        evaluated = self._ctx.expressions.evaluate_property(scalar, self._project.parameters)
        self._ctx.snapshot()
        self._set_bar_com_from_distance(body, evaluated.value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_body(self, name: str, markers: list[MarkerInput], body_type: str = "body") -> str:
        project = self._project
        if not markers:
            raise ValueError("A body requires at least one structural marker")
        self._ctx.validation.ensure_unique_name(project.model.bodies, name)
        body_id = self._ctx.ids.new("body")
        marker_names: set[str] = set()
        structural_markers = [
            self._make_marker(body_id, marker_input, is_first=index == 0)
            for index, marker_input in enumerate(markers)
        ]
        for marker in structural_markers:
            if marker.name in marker_names:
                raise ValueError(f"Duplicate marker name in body creation: {marker.name}")
            marker_names.add(marker.name)
            self._ctx.expressions.evaluate_property(marker.x, project.parameters)
            self._ctx.expressions.evaluate_property(marker.y, project.parameters)
        self._ctx.snapshot()
        actual_type = BodyType(body_type)
        if len(structural_markers) == 1:
            actual_type = BodyType.POINT_MASS
        body = Body(
            id=body_id,
            name=name,
            type=actual_type,
            markers=structural_markers,
            edge_order=[marker.id for marker in structural_markers],
            closed_shape=actual_type is not BodyType.BAR,
            mass=None,
            style=Style(),
        )
        body.markers.append(self._make_com_marker(body))
        project.model.bodies.append(body)
        self._ctx.invalidate_pose_state()
        return body.id

    def create_bar(self, name: str, start: MarkerInput, end: MarkerInput) -> str:
        return self.create_body(name=name, markers=[start, end], body_type=BodyType.BAR.value)

    def create_punctual_mass(self, name: str, x: str, y: str) -> str:
        return self.create_body(name=name, markers=[MarkerInput(x, y, "P")], body_type=BodyType.POINT_MASS.value)

    def create_ground_anchor(self, name: str, x: str, y: str) -> tuple[str, str]:
        """Create a PointMass body + rigid ground joint as one undo step.

        Returns (body_id, structural_marker_id).
        """
        project = self._project
        self._ctx.validation.ensure_unique_name(project.model.bodies, name)
        with self._ctx.operation():
            body_id = self.create_body(name=name, markers=[MarkerInput(x, y, "P")], body_type=BodyType.POINT_MASS.value)
            body = next(b for b in project.model.bodies if b.id == body_id)
            structural = next(m for m in body.markers if m.type is MarkerType.STRUCTURAL)
            self._ctx.connect_marker_to_ground(structural.id, joint_type="rigid", name=f"Ground_{name}")
        return body_id, structural.id

    def get_marker_deletion_consequence(self, marker_id: str) -> str:
        """Returns 'to_bar', 'to_point_mass', or 'normal' for deleting a structural marker."""
        try:
            body = self._find_body_by_marker(marker_id)
        except ValueError:
            return "normal"
        marker = next((m for m in body.markers if m.id == marker_id), None)
        if marker is None or marker.type is not MarkerType.STRUCTURAL:
            return "normal"
        remaining = len(body.structural_markers()) - 1
        if remaining == 1:
            return "to_point_mass"
        if remaining == 2:
            return "to_bar"
        return "normal"

    def delete_structural_marker_convert_to_bar(self, marker_id: str) -> None:
        """Remove one structural marker from a 3-marker body and convert the result to a Bar."""
        project = self._project
        body = self._find_body_by_marker(marker_id)
        if len(body.structural_markers()) != 3:
            raise ValueError("delete_structural_marker_convert_to_bar requires exactly 3 structural markers")
        self._ctx.snapshot()
        removed_joint_ids = {
            joint.id
            for joint in project.model.joints
            if joint.endpoint_a.marker_id == marker_id or joint.endpoint_b.marker_id == marker_id
        }
        body.markers = [m for m in body.markers if m.id != marker_id]
        body.edge_order = [mid for mid in body.edge_order if mid != marker_id]
        project.model.joints = [
            j for j in project.model.joints
            if j.endpoint_a.marker_id != marker_id and j.endpoint_b.marker_id != marker_id
        ]
        project.model.drivers = [
            d for d in project.model.drivers if d.target_joint_id not in removed_joint_ids
        ]
        project.model.sensors = [
            s for s in project.model.sensors if marker_id not in s.marker_ids
        ]
        project.model.loads = [
            load for load in project.model.loads if load.target_marker_id != marker_id
        ]
        body.type = BodyType.BAR
        body.closed_shape = False
        body.com_marker().metadata.values["position_percent"] = 50.0
        self._set_bar_com_from_percent(body, 50.0)
        self._ctx.invalidate_pose_state()

    def add_marker_to_body(self, body_id: str, marker: MarkerInput) -> str:
        body = self._find_body(body_id)
        marker_name = marker.name or f"M{len(body.structural_markers()) + 1}"
        self._ctx.validation.ensure_unique_marker_name(body, marker_name)
        created = Marker(
            id=self._ctx.ids.new("marker"),
            name=marker_name,
            type=marker.marker_type,
            x=self._scalar(marker.x, "mm", Dimension.LENGTH),
            y=self._scalar(marker.y, "mm", Dimension.LENGTH),
            visible=marker.visible,
        )
        self._ctx.expressions.evaluate_property(created.x, self._project.parameters)
        self._ctx.expressions.evaluate_property(created.y, self._project.parameters)
        self._ctx.snapshot()
        body.markers.insert(len(body.structural_markers()), created)
        body.edge_order.append(created.id)
        if body.type is BodyType.BAR:
            body.type = BodyType.BODY
            body.closed_shape = True
        elif body.type is BodyType.POINT_MASS and len(body.structural_markers()) > 1:
            body.type = BodyType.BODY
            body.closed_shape = True
        self._sync_special_com_marker(body)
        self._ctx.invalidate_pose_state()
        return created.id

    def add_marker_to_body_at(
        self, body_id: str, x_expression: str, y_expression: str, name: str | None = None
    ) -> str:
        marker_name = name or f"M{len(self._find_body(body_id).structural_markers()) + 1}"
        return self.add_marker_to_body(body_id, MarkerInput(x_expression, y_expression, marker_name))

    def move_marker(self, marker_id: str, x_expression: str, y_expression: str) -> None:
        marker = self._ctx.find_entity(marker_id)
        if not isinstance(marker, Marker):
            raise ValueError("move_marker requires a marker entity")
        body = self._find_body_by_marker(marker_id)
        if marker.type is MarkerType.COM:
            if body.type is BodyType.POINT_MASS:
                raise ValueError("CoM of a point mass cannot be moved independently")
            if body.type is BodyType.BAR:
                project = self._project
                new_x = ScalarProperty(expression=x_expression, unit=marker.x.unit, expected_dimension=Dimension.LENGTH)
                new_y = ScalarProperty(expression=y_expression, unit=marker.y.unit, expected_dimension=Dimension.LENGTH)
                target_x_eval = self._ctx.expressions.evaluate_property(new_x, project.parameters)
                target_y_eval = self._ctx.expressions.evaluate_property(new_y, project.parameters)
                target_x = self._ctx.units.convert(self._ctx.units.quantity(target_x_eval.value, target_x_eval.unit), "mm")
                target_y = self._ctx.units.convert(self._ctx.units.quantity(target_y_eval.value, target_y_eval.unit), "mm")
                self._ctx.snapshot()
                self._set_bar_com_from_point(body, target_x, target_y)
                self._ctx.invalidate_pose_state()
                return
        project = self._project
        new_x = ScalarProperty(expression=x_expression, unit=marker.x.unit, expected_dimension=Dimension.LENGTH)
        new_y = ScalarProperty(expression=y_expression, unit=marker.y.unit, expected_dimension=Dimension.LENGTH)
        target_x_eval = self._ctx.expressions.evaluate_property(new_x, project.parameters)
        target_y_eval = self._ctx.expressions.evaluate_property(new_y, project.parameters)
        current_x_eval = self._ctx.expressions.evaluate_property(marker.x, project.parameters)
        current_y_eval = self._ctx.expressions.evaluate_property(marker.y, project.parameters)
        target_x = self._ctx.units.convert(self._ctx.units.quantity(target_x_eval.value, target_x_eval.unit), "mm")
        target_y = self._ctx.units.convert(self._ctx.units.quantity(target_y_eval.value, target_y_eval.unit), "mm")
        current_x = self._ctx.units.convert(self._ctx.units.quantity(current_x_eval.value, current_x_eval.unit), "mm")
        current_y = self._ctx.units.convert(self._ctx.units.quantity(current_y_eval.value, current_y_eval.unit), "mm")
        delta_x = target_x - current_x
        delta_y = target_y - current_y
        if abs(delta_x) < 1e-12 and abs(delta_y) < 1e-12:
            return
        linked_joints = self._ctx.joints_for_marker(marker_id)
        if linked_joints:
            self._ctx.snapshot()
            marker.x = new_x
            marker.y = new_y
            moved_marker_ids = self._ctx.translate_direct_joint_counterparts(marker_id, linked_joints, delta_x, delta_y)
            for moved_marker_id in moved_marker_ids:
                try:
                    moved_body = self._find_body_by_marker(moved_marker_id)
                    self._sync_special_com_marker(moved_body)
                except ValueError:
                    pass
            self._ctx.invalidate_pose_state()
            return
        self._ctx.snapshot()
        marker.x = new_x
        marker.y = new_y
        self._sync_special_com_marker(body)
        self._ctx.invalidate_pose_state()
