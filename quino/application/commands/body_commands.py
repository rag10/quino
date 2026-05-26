from __future__ import annotations

import math

from quino.application._context import ServiceContext
from quino.domain.inputs import MarkerInput, PropertyValueInput
from quino.domain.model import (
    Body,
    CoMAnchor,
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
        project = self._ctx.effective_project()
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

    def _default_com_anchor_for(self, body_type: BodyType, structural_markers: list[Marker]):
        """Initial anchor inferred from the body's structural markers."""
        from quino.domain.model import CoMAnchor
        if body_type is BodyType.POINT_MASS and len(structural_markers) == 1:
            return CoMAnchor(kind="marker", data={"marker_id": structural_markers[0].id})
        if body_type is BodyType.BAR and len(structural_markers) == 2:
            return CoMAnchor(kind="bar_percent", data={"percent": 50.0})
        return CoMAnchor(
            kind="barycentric",
            data={"weights": {m.id: 1.0 for m in structural_markers}},
        )

    def _sync_special_com_marker(self, body: Body) -> None:
        """Keep the COM marker (legacy cache) and the CoMAnchor (canonical)
        coherent with the body's structural markers.

        Schema 0.3.0+ no longer carries a COM marker; the anchor is the
        source of truth. When the legacy cache is absent (typical for files
        loaded at 0.3.0), this is a no-op."""
        try:
            com_marker = body.com_marker()
        except ValueError:
            # 0.3.0+ body — no legacy COM marker to refresh; anchor
            # already drives derivation. Nothing to sync.
            return
        structural = body.structural_markers()
        if body.type is BodyType.POINT_MASS and len(structural) == 1:
            base = structural[0]
            com_marker.x = self._scalar(base.x.expression, base.x.unit, Dimension.LENGTH)
            com_marker.y = self._scalar(base.y.expression, base.y.unit, Dimension.LENGTH)
            com_marker.metadata.values.pop("position_percent", None)
            from quino.domain.model import CoMAnchor
            body.com = CoMAnchor(kind="marker", data={"marker_id": base.id})
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
        from quino.domain.model import CoMAnchor
        body.com = CoMAnchor(kind="bar_percent", data={"percent": clamped})

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
            com=self._default_com_anchor_for(actual_type, structural_markers),
            style=Style(),
        )
        body.markers.append(self._make_com_marker(body))
        if not self._ctx.add_entity_to_case(body, "bodies"):
            project.model.bodies.append(body)
        self._ctx.invalidate_pose_state()
        return body.id

    def create_bar(self, name: str, start: MarkerInput, end: MarkerInput) -> str:
        return self.create_body(name=name, markers=[start, end], body_type=BodyType.BAR.value)

    def create_punctual_mass(self, name: str, x: str, y: str) -> str:
        return self.create_body(name=name, markers=[MarkerInput(x, y, "P")], body_type=BodyType.POINT_MASS.value)

    def _locate_created_body(self, body_id: str):
        """Return (body_obj, owner_dict_or_None). When a case is active and
        the body was just added by the case, ``body_obj`` is a Body deserialized
        from the case's added_entities[bodies] entry; mutating it must be
        reflected back into the dict via _serialize_body_into_case_dict.
        Outside case mode, returns the live Body in project.model.bodies."""
        case = self._ctx.get_active_case()
        project = self._project
        # Try baseline first
        for body in project.model.bodies:
            if body.id == body_id:
                return body, None
        # Try case added_entities
        if case is not None:
            from quino.serialization.json_io import JsonMapper
            mapper = JsonMapper()
            for ent in case.added_entities.get("bodies", []):
                if ent.get("id") == body_id:
                    body_obj = mapper._body_from_dict(ent)
                    return body_obj, ent
        raise ValueError(f"Unknown body: {body_id}")

    def _persist_body_back_to_case(self, body_obj, owner_dict) -> None:
        """Re-serialize the in-memory Body back into its case dict so changes
        (e.g. metadata flags) take effect when the case is composed."""
        from quino.serialization.json_io import JsonMapper
        mapper = JsonMapper()
        owner_dict.update(mapper._body_to_dict(body_obj))

    def _tag_joint_internal_ground(self, joint_id: str) -> None:
        case = self._ctx.get_active_case()
        project = self._project
        # Live baseline joint
        for j in project.model.joints:
            if j.id == joint_id:
                j.metadata.values["internal_ground_anchor"] = True
                return
        # Case-added joint
        if case is not None:
            for ent in case.added_entities.get("joints", []):
                if ent.get("id") == joint_id:
                    meta = ent.setdefault("metadata", {})
                    values = meta.setdefault("values", {})
                    values["internal_ground_anchor"] = True
                    return

    def create_ground_anchor(self, name: str, x: str, y: str) -> tuple[str, str]:
        """Create a PointMass body + rigid ground joint as one undo step.

        Returns (body_id, structural_marker_id).
        """
        # Use the effective project for name-uniqueness check so cases see
        # bodies added by parents.
        existing_bodies = list(self._ctx.effective_project().model.bodies)
        self._ctx.validation.ensure_unique_name(existing_bodies, name)
        with self._ctx.operation():
            body_id = self.create_body(name=name, markers=[MarkerInput(x, y, "P")], body_type=BodyType.POINT_MASS.value)
            body, owner_dict = self._locate_created_body(body_id)
            structural = next(m for m in body.markers if m.type is MarkerType.STRUCTURAL)
            body.metadata.values["ground_anchor"] = True
            body.metadata.values["ground_marker_id"] = structural.id
            if owner_dict is not None:
                self._persist_body_back_to_case(body, owner_dict)
            joint_id = self._ctx.connect_marker_to_ground(structural.id, joint_type="rigid", name=f"Ground_{name}")
            self._tag_joint_internal_ground(joint_id)
        return body_id, structural.id

    def create_free_ground(self, name: str, x: str, y: str) -> tuple[str, str]:
        """Create a movable ground entity represented by a fixed point-mass anchor.

        Internally this reuses the existing rigid marker-to-ground topology so the
        solver backend does not need a new primitive. The body itself is tagged in
        metadata so the GUI can render and interact with it as a dedicated Ground.
        """
        existing_bodies = list(self._ctx.effective_project().model.bodies)
        self._ctx.validation.ensure_unique_name(existing_bodies, name)
        with self._ctx.operation():
            body_id = self.create_body(name=name, markers=[MarkerInput(x, y, "P")], body_type=BodyType.POINT_MASS.value)
            body, owner_dict = self._locate_created_body(body_id)
            structural = next(m for m in body.markers if m.type is MarkerType.STRUCTURAL)
            body.metadata.values["ground_anchor"] = True
            body.metadata.values["ground_marker_id"] = structural.id
            if owner_dict is not None:
                self._persist_body_back_to_case(body, owner_dict)
            joint_id = self._ctx.connect_marker_to_ground(structural.id, joint_type="rigid", name=f"Ground_{name}")
            self._tag_joint_internal_ground(joint_id)
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

    def _move_marker_into_case(
        self,
        case,
        marker: Marker,
        marker_id: str,
        x_expression: str,
        y_expression: str,
    ) -> None:
        """Apply a marker move as a case overlay, dragging joint counterparts.

        Joints (especially rigid ones) require both endpoints to stay
        coincident. In case mode we don't mutate baseline markers; instead
        we compute the geometric delta and emit one ``markers/<id>/{x,y}``
        override for the moved marker AND each marker directly linked to
        it via a joint that already had coincident endpoints. This mirrors
        the baseline behaviour of ``_translate_direct_joint_counterparts``.
        """
        from quino.domain.workspace import ScalarValue as _WsScalarValue
        from quino.domain.types import JointEndpointKind

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

        self._ctx.snapshot()
        # Primary override for the dragged marker.
        case.invariant_values[f"markers/{marker_id}/x"] = _WsScalarValue(
            value=float(target_x), unit="mm"
        )
        case.invariant_values[f"markers/{marker_id}/y"] = _WsScalarValue(
            value=float(target_y), unit="mm"
        )

        # Propagate to counterparts of joints that were already coincident
        # with this marker. Look up joints through the effective (composed)
        # project so joints added by the case chain are also considered.
        if abs(delta_x) > 1e-12 or abs(delta_y) > 1e-12:
            eff = self._ctx.effective_project()
            for joint in eff.model.joints:
                ep_a, ep_b = joint.endpoint_a, joint.endpoint_b
                counterpart_id: str | None = None
                if ep_a.kind is JointEndpointKind.MARKER and ep_a.marker_id == marker_id:
                    if ep_b.kind is JointEndpointKind.MARKER:
                        counterpart_id = ep_b.marker_id
                elif ep_b.kind is JointEndpointKind.MARKER and ep_b.marker_id == marker_id:
                    if ep_a.kind is JointEndpointKind.MARKER:
                        counterpart_id = ep_a.marker_id
                if counterpart_id is None or counterpart_id == marker_id:
                    continue
                # Resolve the counterpart marker in the effective (composed)
                # project so we read its already-composed coordinates.
                counterpart = None
                for b in eff.model.bodies:
                    for m in b.markers:
                        if m.id == counterpart_id:
                            counterpart = m
                            break
                    if counterpart is not None:
                        break
                if counterpart is None:
                    continue
                # Were the two markers coincident? If not, the joint was
                # already disassembled; don't drag.
                cx_eval = self._ctx.expressions.evaluate_property(counterpart.x, project.parameters)
                cy_eval = self._ctx.expressions.evaluate_property(counterpart.y, project.parameters)
                cx_mm = self._ctx.units.convert(self._ctx.units.quantity(cx_eval.value, cx_eval.unit), "mm")
                cy_mm = self._ctx.units.convert(self._ctx.units.quantity(cy_eval.value, cy_eval.unit), "mm")
                if abs(cx_mm - current_x) > 1e-6 or abs(cy_mm - current_y) > 1e-6:
                    continue
                # Emit override for the counterpart so the joint stays
                # assembled after composition.
                case.invariant_values[f"markers/{counterpart_id}/x"] = _WsScalarValue(
                    value=float(cx_mm + delta_x), unit="mm"
                )
                case.invariant_values[f"markers/{counterpart_id}/y"] = _WsScalarValue(
                    value=float(cy_mm + delta_y), unit="mm"
                )
        self._ctx.invalidate_pose_state()

    def move_marker(self, marker_id: str, x_expression: str, y_expression: str) -> None:
        # Geometry change → may invalidate simulation runs of the active case.
        if not self._ctx.confirm_invalidation_if_runs_exist():
            return
        self._ctx.discard_runs_for_active_case()
        marker = self._ctx.find_entity(marker_id)
        if not isinstance(marker, Marker):
            raise ValueError("move_marker requires a marker entity")
        body = self._find_body_by_marker(marker_id)
        case = self._ctx.get_active_case()
        if case is not None and marker.type is not MarkerType.COM:
            self._move_marker_into_case(case, marker, marker_id, x_expression, y_expression)
            return
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

    # ------------------------------------------------------------------
    # CoMAnchor editing API
    # ------------------------------------------------------------------

    def set_com_anchor(self, body_id: str, anchor: CoMAnchor) -> None:
        """Replace the body's CoMAnchor. Routes through the active case as
        a structural override when a case is active."""
        body = self._find_body(body_id)
        if body.type is BodyType.POINT_MASS:
            raise ValueError("CoM of a point mass is locked to its marker")
        if not self._ctx.confirm_invalidation_if_runs_exist():
            return
        self._ctx.discard_runs_for_active_case()
        case = self._ctx.get_active_case()
        if case is not None:
            self._emit_com_anchor_override(case, body_id, anchor)
            self._ctx.invalidate_pose_state()
            return
        self._ctx.snapshot()
        body.com = anchor
        # Keep the legacy COM marker (still inside body.markers as a cache)
        # in sync so consumers that haven't migrated yet still get a sane
        # absolute value. For non-bar_percent kinds we update the cache from
        # the anchor's derived position rather than the bar percent path.
        try:
            self._refresh_com_marker_cache(body)
        except Exception:
            pass
        self._ctx.invalidate_pose_state()

    def _refresh_com_marker_cache(self, body: Body) -> None:
        """Refresh the legacy COM marker's x/y from the canonical anchor.

        No-op when the body has no legacy COM marker (i.e. 0.3.0+ loads).
        """
        from quino.services.com_geometry import com_local_position
        try:
            com_marker = body.com_marker()
        except ValueError:
            return
        lx, ly = com_local_position(self._project, body)
        com_marker.x = self._scalar(self._mm_expression(lx), "mm", Dimension.LENGTH)
        com_marker.y = self._scalar(self._mm_expression(ly), "mm", Dimension.LENGTH)
        if body.com.kind == "bar_percent":
            com_marker.metadata.values["position_percent"] = float(body.com.data.get("percent", 50.0))
        else:
            com_marker.metadata.values.pop("position_percent", None)

    def set_com_percent(self, body_id: str, percent: float) -> None:
        body = self._find_body(body_id)
        if body.type is not BodyType.BAR:
            raise ValueError("set_com_percent only applies to bars")
        clamped = max(0.0, min(100.0, float(percent)))
        self.set_com_anchor(body_id, CoMAnchor(kind="bar_percent", data={"percent": clamped}))

    def set_com_offset(self, body_id: str, lx_mm: float, ly_mm: float) -> None:
        self.set_com_anchor(
            body_id,
            CoMAnchor(kind="local_offset", data={"lx": float(lx_mm), "ly": float(ly_mm)}),
        )

    def set_com_weight(self, body_id: str, marker_id: str, weight: float) -> None:
        body = self._find_body(body_id)
        if body.type is not BodyType.BODY:
            raise ValueError("set_com_weight only applies to generic bodies")
        current_data = body.com.data if body.com.kind == "barycentric" else {}
        weights = dict(current_data.get("weights", {}))
        if not weights:
            weights = {m.id: 1.0 for m in body.structural_markers()}
        weights[marker_id] = max(0.0, float(weight))
        self.set_com_anchor(body_id, CoMAnchor(kind="barycentric", data={"weights": weights}))

    def drag_com_to_world(self, body_id: str, x_mm: float, y_mm: float) -> None:
        """Map a world-space drag to the most appropriate anchor kind."""
        body = self._find_body(body_id)
        if body.type is BodyType.POINT_MASS:
            raise ValueError("CoM of a point mass is locked to its marker")
        project = self._project
        lx, ly = self._world_to_body_local(project, body, x_mm, y_mm)
        if body.type is BodyType.BAR and len(body.structural_markers()) == 2:
            anchor = self._bar_drag_to_anchor(project, body, lx, ly)
        else:
            anchor = self._body_drag_to_anchor(project, body, lx, ly)
        self.set_com_anchor(body_id, anchor)

    # ------------------------------------------------------------------
    # CoMAnchor helpers
    # ------------------------------------------------------------------

    def _bar_drag_to_anchor(self, project, body, lx, ly) -> CoMAnchor:
        m1, m2 = body.structural_markers()
        x1 = self._ctx.expressions.evaluate_property(m1.x, project.parameters).value
        y1 = self._ctx.expressions.evaluate_property(m1.y, project.parameters).value
        x2 = self._ctx.expressions.evaluate_property(m2.x, project.parameters).value
        y2 = self._ctx.expressions.evaluate_property(m2.y, project.parameters).value
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            return CoMAnchor(kind="local_offset", data={"lx": float(lx), "ly": float(ly)})
        t = ((lx - x1) * dx + (ly - y1) * dy) / length_sq
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        residual = math.hypot(lx - proj_x, ly - proj_y)
        if 0.0 - 1e-6 <= t <= 1.0 + 1e-6 and residual <= 1e-4:
            percent = max(0.0, min(1.0, t)) * 100.0
            return CoMAnchor(kind="bar_percent", data={"percent": float(percent)})
        return CoMAnchor(kind="local_offset", data={"lx": float(lx), "ly": float(ly)})

    def _body_drag_to_anchor(self, project, body, lx, ly) -> CoMAnchor:
        import numpy as np
        structural = body.structural_markers()
        if not structural:
            return CoMAnchor(kind="local_offset", data={"lx": float(lx), "ly": float(ly)})
        coords = []
        for m in structural:
            x = self._ctx.expressions.evaluate_property(m.x, project.parameters).value
            y = self._ctx.expressions.evaluate_property(m.y, project.parameters).value
            coords.append((float(x), float(y)))
        n = len(coords)
        if n == 1:
            only = structural[0]
            if abs(lx - coords[0][0]) <= 1e-4 and abs(ly - coords[0][1]) <= 1e-4:
                return CoMAnchor(kind="marker", data={"marker_id": only.id})
            return CoMAnchor(kind="local_offset", data={"lx": float(lx), "ly": float(ly)})
        A = np.array(
            [[x for x, _ in coords], [y for _, y in coords], [1.0] * n],
            dtype=float,
        )
        b = np.array([lx, ly, 1.0], dtype=float)
        weights, *_ = np.linalg.lstsq(A, b, rcond=None)
        weights = np.maximum(weights, 0.0)
        total = float(weights.sum())
        if total <= 1e-12:
            return CoMAnchor(kind="local_offset", data={"lx": float(lx), "ly": float(ly)})
        weights = weights / total
        rx = float(sum(w * x for w, (x, _) in zip(weights, coords)))
        ry = float(sum(w * y for w, (_, y) in zip(weights, coords)))
        if math.hypot(lx - rx, ly - ry) > 1e-4:
            return CoMAnchor(kind="local_offset", data={"lx": float(lx), "ly": float(ly)})
        weight_map = {m.id: float(w) for m, w in zip(structural, weights)}
        return CoMAnchor(kind="barycentric", data={"weights": weight_map})

    def _world_to_body_local(self, project, body, x_mm, y_mm) -> tuple[float, float]:
        """Convert world coords to body-local (reference frame).

        For bars the local frame is anchored at the first structural marker
        with x-axis along the segment. For other body kinds we use the
        body's reference origin (first structural marker) and an axis-aligned
        frame; this matches how MechanismAssembler treats generic bodies.
        """
        structural = body.structural_markers()
        if not structural:
            return float(x_mm), float(y_mm)
        first = structural[0]
        ox = self._ctx.expressions.evaluate_property(first.x, project.parameters).value
        oy = self._ctx.expressions.evaluate_property(first.y, project.parameters).value
        angle = 0.0
        if body.type is BodyType.BAR and len(structural) == 2:
            second = structural[1]
            sx = self._ctx.expressions.evaluate_property(second.x, project.parameters).value
            sy = self._ctx.expressions.evaluate_property(second.y, project.parameters).value
            # The bar's local frame for anchor storage uses world-aligned axes
            # at the bar's reference position. We return world-coords directly:
            # markers themselves are stored in world coords, so lx == world x.
            # (angle local frame conversion not needed because anchors are
            # evaluated in the same coordinate system as the markers.)
            _ = (sx, sy, angle, ox, oy)
        return float(x_mm), float(y_mm)

    def _emit_com_anchor_override(self, case, body_id: str, anchor: CoMAnchor) -> None:
        """Persist a CoM change as a case structural override; clear stale
        per-payload parameter overrides for the same body."""
        self._ctx.snapshot()
        overrides = case.reference_overrides.setdefault(body_id, {})
        overrides["com_anchor"] = {"kind": anchor.kind, "data": dict(anchor.data)}
        stale_prefixes = (
            f"bodies/{body_id}/com_percent",
            f"bodies/{body_id}/com_offset_x",
            f"bodies/{body_id}/com_offset_y",
            f"bodies/{body_id}/com_weight/",
        )
        for key in list(case.invariant_values):
            if key in stale_prefixes[:3] or key.startswith(stale_prefixes[3]):
                case.invariant_values.pop(key, None)
