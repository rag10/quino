from __future__ import annotations

import hashlib
import math
import re

from quino.application._context import ServiceContext
from quino.domain.inputs import PropertyValueInput
from quino.domain.model import (
    Expression,
    Parameter,
    Project,
    ScalarProperty,
    Sketch,
    SketchArc,
    SketchCircle,
    SketchConstraint,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
    SketchSpline,
    Style,
    ValidationMessage,
    ValidationReport,
)
from quino.domain.sketch_constraints import CONSTRAINT_SPECS
from quino.domain.types import (
    Dimension,
    SketchConstraintType,
    SketchEntityType,
)
from quino.services.sketch_solver import SketchSolveResult, SketchSolver


_PLAIN_NUMBER_RE = re.compile(r"^\s*[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)\s*$")
_OFFSET_RE = re.compile(r'^\((.*)\)\s+([+-])\s+([\d.]+)\s+(mm|m|deg|rad)$')


class SketchCommands:
    """Command-service for sketch operations (entities, constraints, solve)."""

    def __init__(self, ctx: ServiceContext, solver: SketchSolver) -> None:
        self._ctx = ctx
        self._solver = solver
        self._solve_cache: tuple[str, SketchSolveResult] | None = None

    @property
    def _project(self) -> Project:
        project = self._ctx.project_provider()
        if project is None:
            raise ValueError("No active project")
        return project

    # --- internal state hooks (called from ApplicationService) ---------------

    def invalidate_cache(self) -> None:
        """Drop the cached solver result. Called from facade's _snapshot."""
        self._solve_cache = None

    # --- public sketch API ---------------------------------------------------

    def create_sketch(self, name: str = "Main Sketch") -> str:
        project = self._project
        if project.sketch is not None:
            return project.sketch.id
        self._ctx.snapshot()
        project.sketch = Sketch(
            id=self._ctx.ids.new("sketch"),
            name=name,
            visible=True,
            style=Style(color="#9aa0a6", line_width=1.0, marker_size=4.0),
        )
        origin_id = self.create_sketch_point("0 mm", "0 mm", name="O")
        self.create_sketch_constraint("fix", [origin_id])
        return project.sketch.id

    def delete_sketch(self) -> None:
        project = self._project
        if project.sketch is None:
            return
        self._ctx.snapshot()
        project.sketch = None

    def create_sketch_point(self, x: str, y: str, name: str | None = None, visible: bool = True) -> str:
        project = self._project
        sketch = self._require_sketch(create_if_missing=True)
        point = SketchPoint(
            id=self._ctx.ids.new("skpt"),
            name=name or self._next_sketch_name("Point"),
            type=SketchEntityType.POINT,
            x=Expression(x),
            y=Expression(y),
            visible=visible,
        )
        self._validate_sketch_entity_name(point.name)
        self._evaluate_sketch_expression(point.x, project.parameters)
        self._evaluate_sketch_expression(point.y, project.parameters)
        self._ctx.snapshot()
        sketch.entities[point.id] = point
        return point.id

    def move_sketch_point(self, point_id: str, x: str, y: str) -> None:
        project = self._project
        point = self._find_sketch_point(point_id)
        x_expr = Expression(x)
        y_expr = Expression(y)
        self._evaluate_sketch_expression(x_expr, project.parameters)
        self._evaluate_sketch_expression(y_expr, project.parameters)
        self._ctx.snapshot()
        point.x = x_expr
        point.y = y_expr
        self._apply_sketch_constraints(set())

    def create_sketch_line_segment(
        self,
        start_point_id: str,
        end_point_id: str,
        name: str | None = None,
    ) -> str:
        self._ensure_sketch_point_exists(start_point_id)
        self._ensure_sketch_point_exists(end_point_id)
        if start_point_id == end_point_id:
            raise ValueError("Line segment requires two distinct points")
        sketch = self._require_sketch(create_if_missing=True)
        entity = SketchLineSegment(
            id=self._ctx.ids.new("skline"),
            name=name or self._next_sketch_name("Line"),
            type=SketchEntityType.LINE_SEGMENT,
            start_point_id=start_point_id,
            end_point_id=end_point_id,
        )
        self._validate_sketch_entity_name(entity.name)
        self._ctx.snapshot()
        sketch.entities[entity.id] = entity
        return entity.id

    def create_sketch_circle(
        self,
        center_point_id: str,
        radius: str,
        name: str | None = None,
        edge_point_id: str | None = None,
    ) -> str:
        project = self._project
        self._ensure_sketch_point_exists(center_point_id)
        entity = SketchCircle(
            id=self._ctx.ids.new("skcircle"),
            name=name or self._next_sketch_name("Circle"),
            type=SketchEntityType.CIRCLE,
            center_point_id=center_point_id,
            radius=Expression(radius),
        )
        self._validate_sketch_entity_name(entity.name)
        radius_eval = self._evaluate_sketch_expression(entity.radius, project.parameters)
        if radius_eval <= 0:
            raise ValueError("Circle radius must be positive")
        sketch = self._require_sketch(create_if_missing=True)
        self._ctx.snapshot()
        sketch.entities[entity.id] = entity
        if edge_point_id is not None:
            edge_pt = self._find_sketch_point(edge_point_id)
            if edge_pt is not None:
                edge_pt.visible = False
        return entity.id

    def create_sketch_arc(
        self,
        point_a_id: str,
        point_b_id: str,
        point_c_id: str,
        name: str | None = None,
    ) -> str:
        refs = [point_a_id, point_b_id, point_c_id]
        if len(set(refs)) < 3:
            raise ValueError("Arc requires three distinct points")
        for point_id in refs:
            self._ensure_sketch_point_exists(point_id)
        sketch = self._require_sketch(create_if_missing=True)
        entity = SketchArc(
            id=self._ctx.ids.new("skarc"),
            name=name or self._next_sketch_name("Arc"),
            type=SketchEntityType.ARC,
            center_point_id=point_a_id,
            start_point_id=point_b_id,
            end_point_id=point_c_id,
        )
        self._validate_sketch_entity_name(entity.name)
        self._ctx.snapshot()
        sketch.entities[entity.id] = entity
        return entity.id

    def create_sketch_arc_by_center(
        self,
        cx: float, cy: float,
        sx: float, sy: float,
        ex: float, ey: float,
        name: str | None = None,
    ) -> str:
        """Create an arc defined by center + start + end points (arc_center_mode=True)."""
        sketch = self._require_sketch(create_if_missing=True)
        with self._ctx.operation():
            center_id = self.create_sketch_point(self._mm_expression(cx), self._mm_expression(cy))
            start_id = self.create_sketch_point(self._mm_expression(sx), self._mm_expression(sy))
            end_id = self.create_sketch_point(self._mm_expression(ex), self._mm_expression(ey))
            entity = SketchArc(
                id=self._ctx.ids.new("skarc"),
                name=name or self._next_sketch_name("Arc"),
                type=SketchEntityType.ARC,
                center_point_id=center_id,
                start_point_id=start_id,
                end_point_id=end_id,
            )
            self._validate_sketch_entity_name(entity.name)
            sketch.entities[entity.id] = entity
            self._apply_sketch_constraints(set())
        return entity.id

    def create_sketch_infinite_line(
        self,
        point_a_id: str,
        point_b_id: str,
        name: str | None = None,
    ) -> str:
        self._ensure_sketch_point_exists(point_a_id)
        self._ensure_sketch_point_exists(point_b_id)
        if point_a_id == point_b_id:
            raise ValueError("Infinite line requires two distinct points")
        sketch = self._require_sketch(create_if_missing=True)
        entity = SketchInfiniteLine(
            id=self._ctx.ids.new("skinf"),
            name=name or self._next_sketch_name("InfiniteLine"),
            type=SketchEntityType.INFINITE_LINE,
            point_a_id=point_a_id,
            point_b_id=point_b_id,
        )
        self._validate_sketch_entity_name(entity.name)
        self._ctx.snapshot()
        sketch.entities[entity.id] = entity
        return entity.id

    def create_sketch_rectangle(
        self,
        corner_a: tuple[float, float],
        corner_b: tuple[float, float],
        name: str | None = None,
    ) -> list[str]:
        """Create an axis-aligned rectangle as points, line segments and H/V constraints."""
        if abs(corner_a[0] - corner_b[0]) <= 1e-9 or abs(corner_a[1] - corner_b[1]) <= 1e-9:
            raise ValueError("Rectangle requires non-zero width and height")
        self._require_sketch(create_if_missing=True)
        prefix = name or self._next_sketch_name("Rectangle")
        with self._ctx.operation():
            p1 = self.create_sketch_point(self._mm_expression(corner_a[0]), self._mm_expression(corner_a[1]), f"{prefix} P1")
            p2 = self.create_sketch_point(self._mm_expression(corner_b[0]), self._mm_expression(corner_a[1]), f"{prefix} P2")
            p3 = self.create_sketch_point(self._mm_expression(corner_b[0]), self._mm_expression(corner_b[1]), f"{prefix} P3")
            p4 = self.create_sketch_point(self._mm_expression(corner_a[0]), self._mm_expression(corner_b[1]), f"{prefix} P4")
            l1 = self.create_sketch_line_segment(p1, p2, f"{prefix} Bottom")
            l2 = self.create_sketch_line_segment(p2, p3, f"{prefix} Right")
            l3 = self.create_sketch_line_segment(p3, p4, f"{prefix} Top")
            l4 = self.create_sketch_line_segment(p4, p1, f"{prefix} Left")
            self.create_sketch_constraint(SketchConstraintType.HORIZONTAL.value, [p1, p2], name=f"{prefix} H1")
            self.create_sketch_constraint(SketchConstraintType.VERTICAL.value, [p2, p3], name=f"{prefix} V1")
            self.create_sketch_constraint(SketchConstraintType.HORIZONTAL.value, [p3, p4], name=f"{prefix} H2")
            self.create_sketch_constraint(SketchConstraintType.VERTICAL.value, [p4, p1], name=f"{prefix} V2")
        return [p1, p2, p3, p4, l1, l2, l3, l4]

    def move_sketch_point_with_solver(self, point_id: str, x: str, y: str) -> None:
        """Move a sketch point while treating the drag target as locked for the solver."""
        project = self._project
        point = self._find_sketch_point(point_id)
        x_expr = Expression(x)
        y_expr = Expression(y)
        self._evaluate_sketch_expression(x_expr, project.parameters)
        self._evaluate_sketch_expression(y_expr, project.parameters)
        with self._ctx.operation():
            point.x = x_expr
            point.y = y_expr
            self._apply_sketch_constraints({point_id})

    def toggle_sketch_construction(self, entity_ids: list[str] | set[str]) -> bool:
        sketch = self._require_sketch()
        target_ids = [entity_id for entity_id in entity_ids if entity_id in sketch.entities]
        if not target_ids:
            raise ValueError("Select at least one sketch entity")
        next_value = not all(sketch.entities[entity_id].construction for entity_id in target_ids)
        with self._ctx.operation():
            for entity_id in target_ids:
                sketch.entities[entity_id].construction = next_value
        return next_value

    def edit_distance_constraint_value(
        self,
        constraint_id: str,
        value: str,
        *,
        label_position: tuple[float, float] | None = None,
    ) -> None:
        constraint = self._find_sketch_constraint(constraint_id)
        if constraint.type not in {
            SketchConstraintType.DISTANCE,
            SketchConstraintType.HORIZONTAL_DISTANCE,
            SketchConstraintType.VERTICAL_DISTANCE,
            SketchConstraintType.RADIUS,
        }:
            raise ValueError("Only distance/radius constraints can be edited with this helper")
        with self._ctx.operation():
            scalar = self._scalar(value, "mm", Dimension.LENGTH)
            eval_result = self._ctx.expressions.evaluate_property(scalar, self._project.parameters)
            if eval_result.value <= 0:
                raise ValueError("Distance constraint must be positive")
            constraint.value = scalar
            if label_position is not None:
                constraint.metadata.values["label_position"] = [label_position[0], label_position[1]]
            self._apply_sketch_constraints({constraint.references[0]} if constraint.references else set())

    def apply_sketch_constraint_from_entities(
        self,
        constraint_type: str,
        entity_ids: list[str],
        value: str | None = None,
    ) -> str:
        """Create a sketch constraint using selected points/curves when their types are compatible."""
        ctype = SketchConstraintType(constraint_type)
        refs: list[str] = []
        entity_refs: list[str] = []
        for entity_id in entity_ids:
            entity = self._find_sketch_entity(entity_id)
            if isinstance(entity, SketchPoint):
                refs.append(entity.id)
            elif isinstance(entity, (SketchLineSegment, SketchInfiniteLine)):
                if ctype is SketchConstraintType.COINCIDENT:
                    entity_refs.append(entity.id)
                else:
                    refs.extend(self._line_point_ids(entity))
            elif isinstance(entity, (SketchCircle, SketchArc)):
                if ctype is SketchConstraintType.COINCIDENT:
                    entity_refs.append(entity.id)
                else:
                    entity_refs.append(entity.id)
        if ctype in {
            SketchConstraintType.HORIZONTAL,
            SketchConstraintType.VERTICAL,
            SketchConstraintType.DISTANCE,
            SketchConstraintType.HORIZONTAL_DISTANCE,
            SketchConstraintType.VERTICAL_DISTANCE,
            SketchConstraintType.RADIUS,
            SketchConstraintType.COINCIDENT,
            SketchConstraintType.MIDPOINT,
            SketchConstraintType.COLLINEAR,
            SketchConstraintType.SYMMETRIC,
        }:
            return self.create_sketch_constraint(ctype.value, refs, value=value, entity_references=entity_refs or None)
        if ctype in {
            SketchConstraintType.PARALLEL,
            SketchConstraintType.PERPENDICULAR,
            SketchConstraintType.EQUAL_LENGTH,
            SketchConstraintType.ANGLE,
        }:
            return self.create_sketch_constraint(ctype.value, refs, value=value)
        if ctype in {SketchConstraintType.ON_CIRCLE, SketchConstraintType.TANGENT}:
            return self.create_sketch_constraint(ctype.value, refs, value=value, entity_references=entity_refs)
        raise ValueError(f"Unsupported sketch constraint type: {constraint_type}")

    def create_sketch_constraint(
        self,
        constraint_type: str,
        references: list[str],
        value: str | None = None,
        name: str | None = None,
        entity_references: list[str] | None = None,
    ) -> str:
        project = self._project
        sketch = self._require_sketch(create_if_missing=True)
        constraint_enum = SketchConstraintType(constraint_type)
        normalized_refs = list(references)
        normalized_entity_refs = list(entity_references) if entity_references else []
        if constraint_enum is SketchConstraintType.DISTANCE and len(normalized_refs) == 1 and len(normalized_entity_refs) == 1:
            constraint_enum = SketchConstraintType.RADIUS
        self._validate_sketch_constraint_references(constraint_enum, normalized_refs, normalized_entity_refs)
        scalar_value = None
        if constraint_enum in {
            SketchConstraintType.DISTANCE,
            SketchConstraintType.HORIZONTAL_DISTANCE,
            SketchConstraintType.VERTICAL_DISTANCE,
            SketchConstraintType.RADIUS,
        }:
            is_radius_form = constraint_enum is SketchConstraintType.RADIUS
            if is_radius_form:
                entity = self._find_sketch_entity(normalized_entity_refs[0])
                if value is None:
                    current_radius = self._evaluate_sketch_expression(
                        entity.radius, project.parameters
                    )
                    default_value = f"{current_radius:.6g} mm"
                else:
                    default_value = value
            elif constraint_enum is SketchConstraintType.HORIZONTAL_DISTANCE:
                default_value = value or self._current_sketch_projected_distance_expression(
                    normalized_refs[0], normalized_refs[1], axis=0
                )
            elif constraint_enum is SketchConstraintType.VERTICAL_DISTANCE:
                default_value = value or self._current_sketch_projected_distance_expression(
                    normalized_refs[0], normalized_refs[1], axis=1
                )
            else:
                default_value = value or self._current_sketch_distance_expression(
                    normalized_refs[0], normalized_refs[1]
                )
            scalar_value = self._scalar(default_value, "mm", Dimension.LENGTH)
            distance_eval = self._ctx.expressions.evaluate_property(scalar_value, project.parameters)
            if distance_eval.value <= 0:
                raise ValueError("Distance constraint must be positive")
        elif constraint_enum is SketchConstraintType.ANGLE:
            default_value = value or self._current_sketch_angle_expression(
                normalized_refs[0], normalized_refs[1], normalized_refs[2]
            )
            default_value = self._normalize_angle_expression(default_value)
            scalar_value = self._scalar(default_value, "deg", Dimension.ANGLE)
            angle_eval = self._ctx.expressions.evaluate_property(scalar_value, project.parameters)
            if angle_eval.value == 0.0:
                raise ValueError("Angle constraint value cannot be zero")
        elif constraint_enum is SketchConstraintType.TANGENT:
            sign_str = value if value is not None else "1"
            try:
                sign_val = float(sign_str.strip())
            except Exception:
                raise ValueError("Tangent sign must be +1 or -1")
            if sign_val not in (1.0, -1.0):
                raise ValueError("Tangent sign must be +1 or -1")
            scalar_value = self._scalar(sign_str, "unitless", Dimension.UNITLESS)
        elif value is not None:
            raise ValueError(f"{constraint_enum.value} constraint does not take a value")
        constraint = SketchConstraint(
            id=self._ctx.ids.new("skcon"),
            name=name or self._next_sketch_constraint_name(self._constraint_name_prefix(constraint_enum)),
            type=constraint_enum,
            references=normalized_refs,
            value=scalar_value,
            entity_references=normalized_entity_refs,
        )
        self._validate_sketch_constraint_name(constraint.name)
        self._ctx.snapshot()
        sketch.constraints[constraint.id] = constraint
        if constraint_enum is SketchConstraintType.TANGENT:
            self._create_tangent_helper_geometry(constraint, sketch, project)
        locked_refs = (
            set()
            if constraint_enum is SketchConstraintType.COINCIDENT and normalized_entity_refs
            else ({normalized_refs[0]} if normalized_refs else set())
        )
        self._apply_sketch_constraints(locked_refs)
        return constraint.id

    def update_sketch_constraint(self, constraint_id: str, property_path: str, value: PropertyValueInput) -> None:
        project = self._project
        constraint = self._find_sketch_constraint(constraint_id)
        if property_path == "name":
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Constraint name updates require a string value")
            self._validate_sketch_constraint_name(value.value, constraint_id=constraint_id)
            self._ctx.snapshot()
            constraint.name = value.value
            return
        if property_path == "value":
            if constraint.type not in {
                SketchConstraintType.DISTANCE,
                SketchConstraintType.HORIZONTAL_DISTANCE,
                SketchConstraintType.VERTICAL_DISTANCE,
                SketchConstraintType.RADIUS,
                SketchConstraintType.ANGLE,
            }:
                raise ValueError("Only distance and angle constraints expose a scalar value")
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Constraint value requires an expression input")
            if constraint.type in {
                SketchConstraintType.DISTANCE,
                SketchConstraintType.HORIZONTAL_DISTANCE,
                SketchConstraintType.VERTICAL_DISTANCE,
                SketchConstraintType.RADIUS,
            }:
                scalar = self._scalar(value.value, "mm", Dimension.LENGTH)
                eval_result = self._ctx.expressions.evaluate_property(scalar, project.parameters)
                if eval_result.value <= 0:
                    raise ValueError("Distance constraint must be positive")
            else:
                scalar = self._scalar(self._normalize_angle_expression(value.value), "deg", Dimension.ANGLE)
                eval_result = self._ctx.expressions.evaluate_property(scalar, project.parameters)
                if eval_result.value == 0.0:
                    raise ValueError("Angle constraint value cannot be zero")
            self._ctx.snapshot()
            constraint.value = scalar
            self._apply_sketch_constraints({constraint.references[0]} if constraint.references else set())
            return
        if property_path in {"label_x", "label_y"}:
            if constraint.type not in {
                SketchConstraintType.DISTANCE,
                SketchConstraintType.HORIZONTAL_DISTANCE,
                SketchConstraintType.VERTICAL_DISTANCE,
                SketchConstraintType.RADIUS,
            }:
                raise ValueError("Only distance/radius constraints expose label position")
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Constraint label position requires an expression input")
            scalar = self._scalar(value.value, "mm", Dimension.LENGTH)
            eval_result = self._ctx.expressions.evaluate_property(scalar, project.parameters)
            label_x, label_y = self._current_sketch_constraint_label_position(constraint)
            if property_path == "label_x":
                label_x = eval_result.value
            else:
                label_y = eval_result.value
            self._ctx.snapshot()
            constraint.metadata.values["label_position"] = [label_x, label_y]
            return
        raise ValueError(f"Unsupported sketch constraint property path: {property_path}")

    def delete_sketch_constraint(self, constraint_id: str) -> None:
        sketch = self._require_sketch()
        self._find_sketch_constraint(constraint_id)
        self._ctx.snapshot()
        if constraint_id in sketch.constraints:
            del sketch.constraints[constraint_id]
        self._apply_sketch_constraints(set())

    def solve_sketch(self) -> ValidationReport:
        report = ValidationReport()
        result = self._apply_sketch_constraints(set(), strict=True)
        if result.success:
            report.messages.append(ValidationMessage("info", "sketch_solved", "Sketch solved", None))
            return report

        # Translate UUID-based bad_constraints into human descriptions.
        sketch = self._project.sketch
        if sketch is not None and result.bad_constraints:
            for cid in result.bad_constraints:
                constraint = sketch.constraints.get(cid)
                if constraint is None:
                    continue
                detail = result.bad_constraint_details.get(cid, "constraint could not be applied")
                label = constraint.name or constraint.type.value
                report.messages.append(
                    ValidationMessage(
                        "warning",
                        "sketch_constraint_failed",
                        f"{label}: {detail}",
                        None,
                    )
                )
            return report

        # Solver failed without per-constraint bad list (overall convergence)
        report.messages.append(
            ValidationMessage(
                "warning",
                "sketch_not_solved",
                result.message or "Sketch solver did not converge",
                None,
            )
        )
        return report

    def update_sketch_entity(self, entity_id: str, property_path: str, value: PropertyValueInput) -> None:
        entity = self._find_sketch_entity(entity_id)
        if property_path == "name":
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Sketch name updates require a string value")
            self._validate_sketch_entity_name(value.value, entity_id=entity_id)
            self._ctx.snapshot()
            entity.name = value.value
            return
        if property_path in {"visible", "construction"}:
            if value.kind != "boolean" or not isinstance(value.value, bool):
                raise ValueError("Sketch boolean property requires a boolean input")
            self._ctx.snapshot()
            setattr(entity, property_path, value.value)
            return
        if property_path.startswith("style."):
            self._ctx.apply_style_update(entity, property_path, value)
            return
        project = self._project
        if isinstance(entity, SketchPoint) and property_path in {"x", "y"}:
            if value.kind != "expression" or not isinstance(value.value, str):
                raise ValueError("Sketch point coordinates require an expression value")
            expr = Expression(value.value)
            self._evaluate_sketch_expression(expr, project.parameters)
            self._ctx.snapshot()
            setattr(entity, property_path, expr)
            self._apply_sketch_constraints(set())
            return
        if isinstance(entity, SketchCircle):
            if property_path == "center_point_id":
                if value.kind != "expression" or not isinstance(value.value, str):
                    raise ValueError("center_point_id requires a point id")
                self._ensure_sketch_point_exists(value.value)
                self._ctx.snapshot()
                entity.center_point_id = value.value
                return
            if property_path == "radius":
                if value.kind != "expression" or not isinstance(value.value, str):
                    raise ValueError("Circle radius requires an expression value")
                expr = Expression(value.value)
                radius_eval = self._evaluate_sketch_expression(expr, project.parameters)
                if radius_eval <= 0:
                    raise ValueError("Circle radius must be positive")
                self._ctx.snapshot()
                entity.radius = expr
                return
        if isinstance(entity, SketchLineSegment) and property_path in {"start_point_id", "end_point_id"}:
            self._update_sketch_point_reference(entity, property_path, value)
            return
        if isinstance(entity, SketchInfiniteLine) and property_path in {"point_a_id", "point_b_id"}:
            self._update_sketch_point_reference(entity, property_path, value)
            return
        if isinstance(entity, SketchArc) and property_path in {"center_point_id", "start_point_id", "end_point_id"}:
            self._update_sketch_point_reference(entity, property_path, value)
            return
        raise ValueError(f"Unsupported sketch property path: {property_path}")

    def delete_sketch_entity(self, entity_id: str) -> None:
        sketch = self._require_sketch()
        entity = self._find_sketch_entity(entity_id)
        self._ctx.snapshot()
        if isinstance(entity, SketchPoint):
            dependent_ids = {
                item.id
                for item in sketch.entities.values()
                if (
                    isinstance(item, SketchLineSegment)
                    and entity_id in {item.start_point_id, item.end_point_id}
                )
                or (
                    isinstance(item, SketchCircle)
                    and entity_id == item.center_point_id
                )
                or (
                    isinstance(item, SketchArc)
                    and entity_id in {item.center_point_id, item.start_point_id, item.end_point_id}
                )
                or (
                    isinstance(item, SketchInfiniteLine)
                    and entity_id in {item.point_a_id, item.point_b_id}
                )
            }
            for cid in list(sketch.constraints.keys()):
                if entity_id in sketch.constraints[cid].references:
                    del sketch.constraints[cid]
            for eid in list(sketch.entities.keys()):
                if eid == entity_id or eid in dependent_ids:
                    del sketch.entities[eid]
            self._apply_sketch_constraints(set())
            return
        for cid in list(sketch.constraints.keys()):
            if entity_id in sketch.constraints[cid].entity_references:
                del sketch.constraints[cid]
        if entity_id in sketch.entities:
            del sketch.entities[entity_id]
        self._apply_sketch_constraints(set())

    def set_sketch_visible(self, visible: bool) -> None:
        project = self._project
        if project.sketch is None:
            return
        if project.sketch.visible == visible:
            return
        self._ctx.snapshot()
        project.sketch.visible = visible

    # --- private helpers (sketch-scoped) ------------------------------------

    def _require_sketch(self, create_if_missing: bool = False) -> Sketch:
        project = self._project
        if project.sketch is None:
            if not create_if_missing:
                raise ValueError("Project has no sketch")
            project.sketch = Sketch(
                id=self._ctx.ids.new("sketch"),
                name="Main Sketch",
                visible=True,
                style=Style(color="#9aa0a6", line_width=1.0, marker_size=4.0),
            )
        return project.sketch

    def _evaluate_sketch_expression(self, expression: Expression, parameters: list[Parameter]) -> float:
        quantity = self._ctx.expressions.evaluate_expression(expression.text, parameters)
        return self._ctx.units.convert(quantity, expression.unit)

    def _find_sketch_entity(
        self,
        entity_id: str,
    ) -> SketchPoint | SketchLineSegment | SketchCircle | SketchArc | SketchInfiniteLine | SketchSpline:
        sketch = self._require_sketch()
        entity = sketch.entities.get(entity_id)
        if entity is None:
            raise ValueError(f"Unknown sketch entity: {entity_id}")
        return entity

    def _find_sketch_point(self, point_id: str) -> SketchPoint:
        point = self._find_sketch_entity(point_id)
        if not isinstance(point, SketchPoint):
            raise ValueError(f"Sketch entity is not a point: {point_id}")
        return point

    def _find_sketch_constraint(self, constraint_id: str) -> SketchConstraint:
        sketch = self._require_sketch()
        constraint = sketch.constraints.get(constraint_id)
        if constraint is None:
            raise ValueError(f"Unknown sketch constraint: {constraint_id}")
        return constraint

    def _line_point_ids(self, entity: SketchLineSegment | SketchInfiniteLine) -> list[str]:
        if isinstance(entity, SketchLineSegment):
            return [entity.start_point_id, entity.end_point_id]
        return [entity.point_a_id, entity.point_b_id]

    def _ensure_sketch_point_exists(self, point_id: str) -> None:
        self._find_sketch_point(point_id)

    def _validate_sketch_entity_name(self, new_name: str, entity_id: str | None = None) -> None:
        sketch = self._require_sketch(create_if_missing=True)
        for entity in sketch.entities.values():
            if entity.name == new_name and entity.id != entity_id:
                raise ValueError(f"Sketch name already exists: {new_name}")

    def _validate_sketch_constraint_name(self, new_name: str, constraint_id: str | None = None) -> None:
        sketch = self._require_sketch(create_if_missing=True)
        for constraint in sketch.constraints.values():
            if constraint.name == new_name and constraint.id != constraint_id:
                raise ValueError(f"Sketch constraint name already exists: {new_name}")

    def _next_sketch_name(self, prefix: str) -> str:
        sketch = self._require_sketch(create_if_missing=True)
        existing = {entity.name for entity in sketch.entities.values()}
        index = 1
        candidate = f"{prefix}{index}"
        while candidate in existing:
            index += 1
            candidate = f"{prefix}{index}"
        return candidate

    def _next_sketch_constraint_name(self, prefix: str) -> str:
        sketch = self._require_sketch(create_if_missing=True)
        existing = {constraint.name for constraint in sketch.constraints.values()}
        index = 1
        candidate = f"{prefix}{index}"
        while candidate in existing:
            index += 1
            candidate = f"{prefix}{index}"
        return candidate

    def _constraint_name_prefix(self, constraint_type: SketchConstraintType) -> str:
        return {
            SketchConstraintType.FIX: "Fix",
            SketchConstraintType.HORIZONTAL: "Horizontal",
            SketchConstraintType.VERTICAL: "Vertical",
            SketchConstraintType.DISTANCE: "Distance",
            SketchConstraintType.HORIZONTAL_DISTANCE: "HorizontalDistance",
            SketchConstraintType.VERTICAL_DISTANCE: "VerticalDistance",
            SketchConstraintType.RADIUS: "Radius",
            SketchConstraintType.COINCIDENT: "Coincident",
            SketchConstraintType.PARALLEL: "Parallel",
            SketchConstraintType.PERPENDICULAR: "Perpendicular",
            SketchConstraintType.EQUAL_LENGTH: "EqualLength",
            SketchConstraintType.ANGLE: "Angle",
            SketchConstraintType.MIDPOINT: "Midpoint",
            SketchConstraintType.COLLINEAR: "Collinear",
            SketchConstraintType.SYMMETRIC: "Symmetric",
            SketchConstraintType.ON_CIRCLE: "OnCircle",
            SketchConstraintType.TANGENT: "Tangent",
        }[constraint_type]

    def _validate_sketch_constraint_references(
        self,
        constraint_type: SketchConstraintType,
        references: list[str],
        entity_references: list[str] | None = None,
    ) -> None:
        for point_id in references:
            self._ensure_sketch_point_exists(point_id)
        # Special case: DISTANCE with 1 point + 1 circle entity = radius constraint
        if constraint_type in {
            SketchConstraintType.DISTANCE,
            SketchConstraintType.HORIZONTAL_DISTANCE,
            SketchConstraintType.VERTICAL_DISTANCE,
            SketchConstraintType.RADIUS,
        }:
            if len(references) == 1 and len(entity_references or []) == 1:
                entity = self._find_sketch_entity((entity_references or [])[0])
                if not isinstance(entity, (SketchCircle, SketchArc)):
                    raise ValueError("Distance radius constraint requires a circle or arc entity reference")
                return  # valid radius form — skip generic checks below
        if constraint_type is SketchConstraintType.COINCIDENT and len(references) == 1 and len(entity_references or []) == 1:
            entity = self._find_sketch_entity((entity_references or [])[0])
            if not isinstance(entity, (SketchLineSegment, SketchInfiniteLine, SketchCircle, SketchArc)):
                raise ValueError("Coincident point-entity constraint requires a line, circle, or arc entity reference")
            return
        if constraint_type is SketchConstraintType.TANGENT:
            entity_refs = entity_references or []
            if len(references) == 2 and len(entity_refs) == 1:
                entity = self._find_sketch_entity(entity_refs[0])
                if not isinstance(entity, (SketchCircle, SketchArc)):
                    raise ValueError("Tangent constraint requires a circle or arc entity reference")
                return
            if len(references) == 0 and len(entity_refs) == 2:
                first = self._find_sketch_entity(entity_refs[0])
                second = self._find_sketch_entity(entity_refs[1])
                if not isinstance(first, (SketchCircle, SketchArc)) or not isinstance(second, (SketchCircle, SketchArc)):
                    raise ValueError("Curve-curve tangent requires two circle or arc entity references")
                if entity_refs[0] == entity_refs[1]:
                    raise ValueError("Tangent constraint requires two distinct curve entities")
                return
            raise ValueError("Tangent constraint requires either 1 line + 1 circle/arc or 2 circles/arcs")
        spec = CONSTRAINT_SPECS.get(constraint_type)
        expected_pts = spec.points if spec is not None else 2
        if len(references) != expected_pts:
            raise ValueError(f"{constraint_type.value} constraint requires {expected_pts} point reference(s)")
        _segment_pair_types = {
            SketchConstraintType.PARALLEL,
            SketchConstraintType.PERPENDICULAR,
            SketchConstraintType.EQUAL_LENGTH,
        }
        if constraint_type in _segment_pair_types:
            # Allow shared endpoint between segments but reject within-segment duplicates
            if references[0] == references[1] or references[2] == references[3]:
                raise ValueError("Constraint references must be distinct within each segment")
        elif len(set(references)) != len(references):
            raise ValueError("Constraint references must be distinct")
        expected_ents = spec.entities if spec is not None else 0
        actual_ents = len(entity_references) if entity_references else 0
        if actual_ents != expected_ents:
            raise ValueError(f"{constraint_type.value} constraint requires {expected_ents} entity reference(s)")
        if entity_references:
            for entity_id in entity_references:
                entity = self._find_sketch_entity(entity_id)
                if constraint_type is SketchConstraintType.ON_CIRCLE and not isinstance(entity, (SketchCircle, SketchArc)):
                    raise ValueError("On-circle constraint requires a circle or arc entity reference")
                if constraint_type is SketchConstraintType.TANGENT and not isinstance(entity, (SketchCircle, SketchArc)):
                    raise ValueError("Tangent constraint requires a circle or arc entity reference")

    def _create_tangent_helper_geometry(self, constraint: SketchConstraint, sketch: Sketch, project: Project) -> None:
        if len(constraint.references) != 2 or len(constraint.entity_references) != 1:
            return
        line_entity = self._find_line_entity_by_points(constraint.references, sketch)
        if line_entity is None:
            return
        curve_entity = self._find_sketch_entity(constraint.entity_references[0])
        if not isinstance(curve_entity, (SketchCircle, SketchArc)):
            return
        center = self._find_sketch_point(curve_entity.center_point_id)
        line_a = self._find_sketch_point(constraint.references[0])
        line_b = self._find_sketch_point(constraint.references[1])
        cx = self._evaluate_sketch_expression(center.x, project.parameters)
        cy = self._evaluate_sketch_expression(center.y, project.parameters)
        ax = self._evaluate_sketch_expression(line_a.x, project.parameters)
        ay = self._evaluate_sketch_expression(line_a.y, project.parameters)
        bx = self._evaluate_sketch_expression(line_b.x, project.parameters)
        by = self._evaluate_sketch_expression(line_b.y, project.parameters)
        dx = bx - ax
        dy = by - ay
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            tx, ty = cx, cy
        else:
            t = ((cx - ax) * dx + (cy - ay) * dy) / denom
            tx = ax + t * dx
            ty = ay + t * dy
        helper = SketchPoint(
            id=self._ctx.ids.new("skpt"),
            name=self._next_sketch_name("TangentPoint"),
            type=SketchEntityType.POINT,
            x=Expression(self._mm_expression(tx)),
            y=Expression(self._mm_expression(ty)),
            visible=True,
            construction=True,
        )
        sketch.entities[helper.id] = helper
        line_constraint = SketchConstraint(
            id=self._ctx.ids.new("skcon"),
            name=self._next_sketch_constraint_name("Coincident"),
            type=SketchConstraintType.COINCIDENT,
            references=[helper.id],
            entity_references=[line_entity.id],
        )
        sketch.constraints[line_constraint.id] = line_constraint
        curve_constraint = SketchConstraint(
            id=self._ctx.ids.new("skcon"),
            name=self._next_sketch_constraint_name("Coincident"),
            type=SketchConstraintType.COINCIDENT,
            references=[helper.id],
            entity_references=[curve_entity.id],
        )
        sketch.constraints[curve_constraint.id] = curve_constraint

    def _find_line_entity_by_points(
        self,
        point_ids: list[str],
        sketch: Sketch,
    ) -> SketchLineSegment | SketchInfiniteLine | None:
        target = tuple(point_ids[:2])
        reversed_target = (target[1], target[0])
        for entity in sketch.entities.values():
            if isinstance(entity, SketchLineSegment):
                refs = (entity.start_point_id, entity.end_point_id)
            elif isinstance(entity, SketchInfiniteLine):
                refs = (entity.point_a_id, entity.point_b_id)
            else:
                continue
            if refs == target or refs == reversed_target:
                return entity
        return None

    def _current_sketch_angle_expression(
        self, vertex_id: str, arm1_id: str, arm2_id: str
    ) -> str:
        """Return current angle (degrees) at vertex between arm1 and arm2 as an expression string."""
        project = self._project
        pv = self._find_sketch_point(vertex_id)
        p1 = self._find_sketch_point(arm1_id)
        p2 = self._find_sketch_point(arm2_id)
        vx = self._evaluate_sketch_expression(pv.x, project.parameters)
        vy = self._evaluate_sketch_expression(pv.y, project.parameters)
        ax = self._evaluate_sketch_expression(p1.x, project.parameters)
        ay = self._evaluate_sketch_expression(p1.y, project.parameters)
        bx = self._evaluate_sketch_expression(p2.x, project.parameters)
        by = self._evaluate_sketch_expression(p2.y, project.parameters)
        d1x, d1y = ax - vx, ay - vy
        d2x, d2y = bx - vx, by - vy
        cross = d1x * d2y - d1y * d2x
        dot = d1x * d2x + d1y * d2y
        angle_rad = math.atan2(cross, dot)
        angle_deg = math.degrees(angle_rad)
        if angle_deg < 0:
            angle_deg += 360.0
        return f"{angle_deg:.4g}"

    def _current_sketch_angle_degrees(
        self, vertex_id: str, arm1_id: str, arm2_id: str
    ) -> float:
        """Return current angle in degrees at vertex (for GUI dialog default)."""
        expr = self._current_sketch_angle_expression(vertex_id, arm1_id, arm2_id)
        return float(expr)

    def _current_sketch_distance_expression(self, point_a_id: str, point_b_id: str) -> str:
        project = self._project
        point_a = self._find_sketch_point(point_a_id)
        point_b = self._find_sketch_point(point_b_id)
        ax = self._evaluate_sketch_expression(point_a.x, project.parameters)
        ay = self._evaluate_sketch_expression(point_a.y, project.parameters)
        bx = self._evaluate_sketch_expression(point_b.x, project.parameters)
        by = self._evaluate_sketch_expression(point_b.y, project.parameters)
        return self._mm_expression(math.hypot(bx - ax, by - ay))

    def _current_sketch_projected_distance_expression(self, point_a_id: str, point_b_id: str, *, axis: int) -> str:
        project = self._project
        point_a = self._find_sketch_point(point_a_id)
        point_b = self._find_sketch_point(point_b_id)
        values_a = (
            self._evaluate_sketch_expression(point_a.x, project.parameters),
            self._evaluate_sketch_expression(point_a.y, project.parameters),
        )
        values_b = (
            self._evaluate_sketch_expression(point_b.x, project.parameters),
            self._evaluate_sketch_expression(point_b.y, project.parameters),
        )
        return self._mm_expression(abs(values_b[axis] - values_a[axis]))

    def _current_sketch_constraint_label_position(self, constraint: SketchConstraint) -> tuple[float, float]:
        label_position = constraint.metadata.values.get("label_position")
        if isinstance(label_position, list) and len(label_position) == 2:
            return float(label_position[0]), float(label_position[1])
        project = self._project
        refs = [self._find_sketch_point(point_id) for point_id in constraint.references]
        points = [
            (
                self._evaluate_sketch_expression(point.x, project.parameters),
                self._evaluate_sketch_expression(point.y, project.parameters),
            )
            for point in refs
        ]
        if constraint.type is SketchConstraintType.RADIUS and len(points) == 1:
            x, y = points[0]
            return x + 10.0, y
        if not points:
            return 0.0, 0.0
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def _sketch_signature(self, sketch: Sketch) -> str:
        data = ""
        for point in sketch.points():
            data += f"{point.id}:{point.x.text}:{point.y.text};"
        for entity in sketch.entities.values():
            data += f"{entity.id}:{entity.type.value};"
            if isinstance(entity, SketchCircle):
                data += f"radius:{entity.radius.text};"
        for constraint in sketch.constraints.values():
            val_expr = constraint.value.expression if constraint.value is not None else ""
            data += f"{constraint.id}:{constraint.type.value}:{','.join(constraint.references)}:{','.join(constraint.entity_references)}:{val_expr};"
        return hashlib.md5(data.encode()).hexdigest()

    def _apply_sketch_constraints(
        self,
        locked_point_ids: set[str],
        *,
        strict: bool = False,
    ):
        project = self._project
        if project.sketch is None:
            return SketchSolveResult(True, {}, 0, 0.0, None)
        if not project.sketch.constraints:
            project.sketch.solve_error = None
            return SketchSolveResult(True, {}, 0, 0.0, None)
        sig = self._sketch_signature(project.sketch)
        if self._solve_cache is not None and self._solve_cache[0] == sig:
            result = self._solve_cache[1]
        else:
            result = self._solver.solve(project, locked_point_ids=locked_point_ids)
            self._solve_cache = (sig, result)
        # Persist bad_constraint_ids on the domain so the canvas can highlight them.
        project.sketch.bad_constraint_ids = list(result.bad_constraints)
        if result.success:
            project.sketch.solve_error = None
            for point_id, (x, y) in result.positions.items():
                point = self._find_sketch_point(point_id)
                old_x = self._evaluate_sketch_expression(point.x, project.parameters)
                old_y = self._evaluate_sketch_expression(point.y, project.parameters)
                dx = x - old_x
                dy = y - old_y
                if abs(dx) > 1e-9:
                    if self._is_literal_expression(point.x.text):
                        point.x = Expression(self._mm_expression(x))
                    else:
                        base_x = self._strip_offset(point.x.text)
                        base_val_x = self._ctx.expressions.evaluate_expression(base_x, project.parameters).value
                        total_dx = x - base_val_x
                        point.x = Expression(self._offset_expression(base_x, total_dx, "mm"))
                if abs(dy) > 1e-9:
                    if self._is_literal_expression(point.y.text):
                        point.y = Expression(self._mm_expression(y))
                    else:
                        base_y = self._strip_offset(point.y.text)
                        base_val_y = self._ctx.expressions.evaluate_expression(base_y, project.parameters).value
                        total_dy = y - base_val_y
                        point.y = Expression(self._offset_expression(base_y, total_dy, "mm"))
            for circle_id, radius in result.radius_updates.items():
                entity = project.sketch.entities.get(circle_id)
                if isinstance(entity, SketchCircle):
                    entity.radius = Expression(self._mm_expression(radius))
        else:
            project.sketch.solve_error = result.message or "Solver did not converge"
        return result

    def _update_sketch_point_reference(
        self,
        entity: SketchLineSegment | SketchArc | SketchInfiniteLine,
        property_path: str,
        value: PropertyValueInput,
    ) -> None:
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError(f"{property_path} requires a point id")
        self._ensure_sketch_point_exists(value.value)
        if isinstance(entity, SketchLineSegment):
            updated_refs = {
                "start_point_id": entity.start_point_id,
                "end_point_id": entity.end_point_id,
            }
        elif isinstance(entity, SketchInfiniteLine):
            updated_refs = {"point_a_id": entity.point_a_id, "point_b_id": entity.point_b_id}
        else:
            updated_refs = {
                "center_point_id": entity.center_point_id,
                "start_point_id": entity.start_point_id,
                "end_point_id": entity.end_point_id,
            }
        updated_refs[property_path] = value.value
        if len(set(updated_refs.values())) != len(updated_refs):
            raise ValueError("Sketch references must remain distinct")
        self._ctx.snapshot()
        setattr(entity, property_path, value.value)

    # --- duplicated small numeric helpers (sketch-local copies) -------------

    def _scalar(self, expression: str, unit: str, dimension: Dimension) -> ScalarProperty:
        return ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension)

    def _mm_expression(self, value: float) -> str:
        return f"{value:.6g} mm"

    def _normalize_angle_expression(self, expression: str) -> str:
        stripped = expression.strip()
        if _PLAIN_NUMBER_RE.fullmatch(stripped):
            return f"{stripped} deg"
        return expression

    def _is_literal_expression(self, expression: str) -> bool:
        """Return True if expression is a plain number with optional unit (no parameters)."""
        cleaned = expression.strip()
        for unit in ("mm", "m", "deg", "rad", "s"):
            if cleaned.endswith(unit):
                cleaned = cleaned[: -len(unit)].strip()
                break
        try:
            float(cleaned)
            return True
        except ValueError:
            return False

    def _offset_expression(self, expression: str, delta: float, unit: str) -> str:
        if abs(delta) < 1e-12:
            return expression
        sign = "+" if delta >= 0 else "-"
        return f"({expression}) {sign} {abs(delta):.6f} {unit}"

    def _strip_offset(self, expression: str) -> str:
        """Undo the outermost offset wrapper added by _offset_expression."""
        match = _OFFSET_RE.match(expression.strip())
        if not match:
            return expression.strip()
        return match.group(1).strip()
