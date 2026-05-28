"""Sketch solver backend powered by python-solvespace.

Translates QUINO sketch entities and constraints to Solvespace SolverSystem
calls, runs solve(), and reads back positions and updated radii.

Each call to solve() builds a fresh SolverSystem (no state between calls) —
the domain (Project) is the single source of truth.

NOTE: Constraint emission is NOT yet implemented (tasks T5-T9 will add it).
Sketches with constraints are currently solved "as if all constraints were
absent" — points stay where their expressions evaluated them.
"""
from __future__ import annotations

import math

import python_solvespace as ps

from quino.domain.model import (
    Expression,
    Sketch,
    SketchArc,
    SketchCircle,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
)
from quino.domain.types import SketchConstraintType
from quino.services.expressions import ExpressionService
from quino.services.sketch_solving.base import DofResult, SketchSolveResult
from quino.services.units import UnitService


class SolvespaceBackend:
    name = "solvespace"

    def __init__(self, expression_service: ExpressionService, unit_service: UnitService) -> None:
        self._expressions = expression_service
        self._units = unit_service

    def solve(
        self,
        project,
        *,
        locked_point_ids: set[str] | None = None,
        max_iterations: int = 200,
        tolerance: float = 1e-6,
    ) -> SketchSolveResult:
        sketch = project.sketch
        if sketch is None:
            return SketchSolveResult(True, {}, 0, 0.0, None)

        point_map = {p.id: p for p in sketch.points()}
        if not sketch.constraints:
            # No constraints — evaluate initial positions and return.
            positions = {
                pid: self._evaluate_point(project, p) for pid, p in point_map.items()
            }
            return SketchSolveResult(True, positions, 0, 0.0, None)

        try:
            return self._solve_with_system(project, sketch, locked_point_ids or set())
        except Exception as exc:  # noqa: BLE001 — paranoid mapping guard
            return SketchSolveResult(
                success=False,
                positions={
                    pid: self._evaluate_point(project, p) for pid, p in point_map.items()
                },
                iterations=0,
                max_error=math.inf,
                message=f"Solvespace mapping error: {exc}",
            )

    def _solve_with_system(
        self,
        project,
        sketch: Sketch,
        locked: set[str],
    ) -> SketchSolveResult:
        sys = ps.SolverSystem()
        wp = sys.create_2d_base()
        nm_3d = sys.entity(0)  # pre-created Z-normal, needed for circles/arcs.

        # Identify fixed points: explicit locked + FIX constraint references.
        fixed_ids: set[str] = set(locked)
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                fixed_ids.update(c.references)

        # Build point handles.
        point_handles: dict[str, object] = {}
        point_map = {p.id: p for p in sketch.points()}
        for pid, p in point_map.items():
            x, y = self._evaluate_point(project, p)
            handle = sys.add_point_2d(x, y, wp)
            if pid in fixed_ids:
                sys.dragged(handle, wp)
            point_handles[pid] = handle

        # Build geometric entity handles (line / circle / arc).
        entity_handles: dict[str, object] = {}
        radius_entities: dict[str, object] = {}
        for entity in sketch.entities.values():
            self._create_entity(
                sys, wp, nm_3d, entity, point_handles, entity_handles, radius_entities, project,
            )

        # Emit geometric constraints (FIX is already handled above via dragged).
        from quino.services.sketch_solving.constraint_mapping import emit_constraint
        bad_constraints: list[str] = []
        bad_constraint_details: dict[str, str] = {}
        constrained_radii: set[str] = set()
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                continue
            if c.type is SketchConstraintType.RADIUS:
                # Track which circle/arc entities have an explicit radius constraint
                # so we don't double-constrain their radii below.
                constrained_radii.update(c.entity_references or [])
                constrained_radii.update(c.references or [])
            if c.type is SketchConstraintType.TANGENT:
                # Tangent constraints work by equating distances to radii; the
                # radii must therefore stay free, so don't auto-lock them.
                constrained_radii.update(c.entity_references or [])
            try:
                emit_constraint(
                    sys, wp, c,
                    points=point_handles,
                    entities=entity_handles,
                    project=project,
                    expressions=self._expressions,
                    units=self._units,
                )
            except (ValueError, TypeError) as exc:
                # ValueError: malformed constraint (handled by mapping).
                # TypeError: python-solvespace native rejection (e.g. tangent
                # called with circle entities, which is not yet supported by
                # the C++ kernel binding). Mark as bad rather than crashing.
                bad_constraints.append(c.id)
                bad_constraint_details[c.id] = str(exc)

        # Lock the radius of every circle/arc that is NOT covered by a user RADIUS
        # constraint. Without this, the `add_distance` entity for the radius is a
        # free parameter and Solvespace will happily move it together with the
        # points to satisfy on_circle / tangent constraints.
        for entity in sketch.entities.values():
            if entity.id in constrained_radii:
                continue
            handle = entity_handles.get(entity.id)
            if handle is None:
                continue
            if isinstance(entity, (SketchCircle, SketchArc)):
                radius_mm = self._evaluate_radius(entity, project)
                if radius_mm is not None:
                    sys.diameter(handle, 2.0 * radius_mm)

        result_code = sys.solve()
        success = result_code == ps.ResultFlag.OKAY and not bad_constraints

        positions = {
            pid: self._read_point(sys, handle) for pid, handle in point_handles.items()
        }

        # Read back updated radii for circles. (Arcs don't have a tracked radius entity yet;
        # their radius is implicit in start/end positions, which positions[] already covers.)
        radius_updates: dict[str, float] = {}
        for entity_id, rad_entity in radius_entities.items():
            try:
                new_radius = float(sys.params(rad_entity.params)[0])
            except Exception:
                continue
            radius_updates[entity_id] = new_radius

        return SketchSolveResult(
            success=success,
            positions=positions,
            iterations=0,
            max_error=0.0 if success else math.inf,
            message=None if success else f"Solver did not converge ({len(bad_constraints)} bad constraint{'s' if len(bad_constraints) != 1 else ''})",
            bad_constraints=bad_constraints,
            radius_updates=radius_updates,
            bad_constraint_details=bad_constraint_details,
        )

    def _evaluate_point(self, project, point: SketchPoint) -> tuple[float, float]:
        x = self._evaluate_expression(point.x, project.parameters)
        y = self._evaluate_expression(point.y, project.parameters)
        return (x, y)

    def _evaluate_expression(self, expression: Expression, parameters: list) -> float:
        quantity = self._expressions.evaluate_expression(expression.text, parameters)
        return float(self._units.convert(quantity, expression.unit))

    def _create_entity(
        self,
        sys,
        wp,
        nm_3d,
        entity,
        points: dict[str, object],
        entities: dict[str, object],
        radius_entities: dict[str, object],
        project,
    ) -> None:
        if isinstance(entity, SketchLineSegment):
            handle = sys.add_line_2d(
                points[entity.start_point_id], points[entity.end_point_id], wp,
            )
            entities[entity.id] = handle
        elif isinstance(entity, SketchInfiniteLine):
            handle = sys.add_line_2d(
                points[entity.point_a_id], points[entity.point_b_id], wp,
            )
            entities[entity.id] = handle
        elif isinstance(entity, SketchCircle):
            radius_mm = self._evaluate_expression(entity.radius, project.parameters)
            rad_entity = sys.add_distance(radius_mm, wp)
            handle = sys.add_circle(nm_3d, points[entity.center_point_id], rad_entity, wp)
            entities[entity.id] = handle
            radius_entities[entity.id] = rad_entity
        elif isinstance(entity, SketchArc):
            handle = sys.add_arc(
                nm_3d,
                points[entity.center_point_id],
                points[entity.start_point_id],
                points[entity.end_point_id],
                wp,
            )
            entities[entity.id] = handle
        # otherwise: unsupported entity type (e.g. SketchSpline), ignored for now.

    def _evaluate_radius(self, entity, project) -> float | None:
        """Evaluate the declared radius (mm) of a SketchCircle or SketchArc."""
        if isinstance(entity, SketchCircle):
            return self._evaluate_expression(entity.radius, project.parameters)
        if isinstance(entity, SketchArc):
            # Arc radius is the distance from center to start point at sketch time.
            center = next(
                (p for p in project.sketch.points() if p.id == entity.center_point_id),
                None,
            )
            start = next(
                (p for p in project.sketch.points() if p.id == entity.start_point_id),
                None,
            )
            if center is None or start is None:
                return None
            cx, cy = self._evaluate_point(project, center)
            sx, sy = self._evaluate_point(project, start)
            return ((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5
        return None

    @staticmethod
    def _read_point(sys, handle) -> tuple[float, float]:
        params = sys.params(handle.params)
        return (float(params[0]), float(params[1]))

    def analyze_dof(self, project: "Project") -> "DofResult":
        """Per-point DOF analysis via Solvespace perturbation testing.

        For each non-fixed SketchPoint and each axis, build a temp solver
        system equivalent to the sketch with the test point initialised at a
        perturbed location. If Solvespace lets the point stay near the
        perturbation, the axis is free; if it pulls the point back, the axis
        is constrained.
        """
        from quino.services.sketch_solving.base import DofResult

        sketch = project.sketch
        if sketch is None:
            return DofResult({}, set(), set(), 0)

        points = list(sketch.points())
        if not points:
            return DofResult({}, set(), set(), 0)

        # Solve once to get reference positions and identify points that
        # cannot meaningfully be tested (broken sketches).
        ref_result = self.solve(project)
        ref_positions = ref_result.positions if ref_result.success else {}

        # Identify points fixed via FIX constraint (DOF=0 trivially, no test needed).
        fixed_ids: set[str] = set()
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                fixed_ids.update(c.references)

        epsilon = 1.0  # mm of perturbation
        threshold = epsilon * 0.3  # If the point ends within this of the target, the axis is free.

        point_dof: dict[str, int] = {}
        for p in points:
            if p.id in fixed_ids:
                point_dof[p.id] = 0
                continue
            ref_xy = ref_positions.get(p.id)
            if ref_xy is None:
                # Reference solve failed for this point — treat as fully free defensively.
                point_dof[p.id] = 2
                continue
            free_axes = 0
            for axis in (0, 1):
                if self._axis_is_free(project, sketch, p.id, ref_xy, axis, epsilon, threshold):
                    free_axes += 1
            point_dof[p.id] = free_axes

        fully_constrained_points = {pid for pid, dof in point_dof.items() if dof == 0}

        fully_constrained_entities: set[str] = set()
        for entity in sketch.entities.values():
            ref_point_ids = self._entity_point_ids(entity)
            if ref_point_ids and all(pid in fully_constrained_points for pid in ref_point_ids):
                fully_constrained_entities.add(entity.id)

        total_free_dof = sum(point_dof.values())
        return DofResult(
            point_dof=point_dof,
            fully_constrained_point_ids=fully_constrained_points,
            fully_constrained_entity_ids=fully_constrained_entities,
            total_free_dof=total_free_dof,
        )

    def _axis_is_free(
        self,
        project: "Project",
        sketch: "Sketch",
        point_id: str,
        ref_xy: tuple[float, float],
        axis: int,
        epsilon: float,
        threshold: float,
    ) -> bool:
        """True if perturbing point along the given axis (0=X, 1=Y) results in
        the solver leaving the point at the perturbed location."""
        ref_x, ref_y = ref_xy
        target = (
            (ref_x + epsilon, ref_y) if axis == 0 else (ref_x, ref_y + epsilon)
        )
        try:
            new_xy = self._solve_with_dragged_point(project, sketch, point_id, target)
        except Exception:
            return False
        if new_xy is None:
            return False
        new_x, new_y = new_xy
        if axis == 0:
            return abs(new_x - target[0]) < threshold
        return abs(new_y - target[1]) < threshold

    def _solve_with_dragged_point(
        self,
        project: "Project",
        sketch: "Sketch",
        dragged_id: str,
        target_xy: tuple[float, float],
    ) -> tuple[float, float] | None:
        """Build a fresh SolverSystem replicating the sketch with `dragged_id`
        initialised at target_xy. The dragged point is otherwise free — solver
        decides whether to keep it (axis free) or pull it back (constrained).

        Returns the resolved (x, y) of the dragged point, or None on failure.
        """
        from quino.services.sketch_solving.constraint_mapping import emit_constraint

        sys = ps.SolverSystem()
        wp = sys.create_2d_base()
        nm_3d = sys.entity(0)

        fixed_ids: set[str] = set()
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                fixed_ids.update(c.references)

        point_handles: dict[str, object] = {}
        for p in sketch.points():
            if p.id == dragged_id:
                # Initialise at perturbed target; otherwise FREE (no dragged()).
                handle = sys.add_point_2d(target_xy[0], target_xy[1], wp)
            else:
                x, y = self._evaluate_point(project, p)
                handle = sys.add_point_2d(x, y, wp)
                if p.id in fixed_ids:
                    sys.dragged(handle, wp)
            point_handles[p.id] = handle

        entity_handles: dict[str, object] = {}
        radius_entities: dict[str, object] = {}
        for entity in sketch.entities.values():
            self._create_entity(
                sys, wp, nm_3d, entity, point_handles, entity_handles, radius_entities, project,
            )

        constrained_radii: set[str] = set()
        for c in sketch.constraints.values():
            if c.type is SketchConstraintType.FIX:
                continue
            if c.type is SketchConstraintType.RADIUS:
                constrained_radii.update(c.entity_references or [])
                constrained_radii.update(c.references or [])
            if c.type is SketchConstraintType.TANGENT:
                constrained_radii.update(c.entity_references or [])
            try:
                emit_constraint(
                    sys, wp, c,
                    points=point_handles,
                    entities=entity_handles,
                    project=project,
                    expressions=self._expressions,
                    units=self._units,
                )
            except (ValueError, TypeError):
                # Bad constraint — skip; the solve may still succeed for DOF purposes.
                pass

        for entity in sketch.entities.values():
            if entity.id in constrained_radii:
                continue
            handle = entity_handles.get(entity.id)
            if handle is None:
                continue
            if isinstance(entity, (SketchCircle, SketchArc)):
                radius_mm = self._evaluate_radius(entity, project)
                if radius_mm is not None:
                    sys.diameter(handle, 2.0 * radius_mm)

        result_code = sys.solve()
        if result_code != ps.ResultFlag.OKAY:
            return None
        return self._read_point(sys, point_handles[dragged_id])

    @staticmethod
    def _entity_point_ids(entity) -> list[str]:
        """Return the SketchPoint ids referenced by a SketchEntity."""
        if isinstance(entity, SketchPoint):
            return [entity.id]
        if isinstance(entity, SketchLineSegment):
            return [entity.start_point_id, entity.end_point_id]
        if isinstance(entity, SketchInfiniteLine):
            return [entity.point_a_id, entity.point_b_id]
        if isinstance(entity, SketchCircle):
            return [entity.center_point_id]
        if isinstance(entity, SketchArc):
            return [entity.center_point_id, entity.start_point_id, entity.end_point_id]
        return []
