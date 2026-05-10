from __future__ import annotations

import math
from dataclasses import dataclass

from quino.domain.model import Project, Sketch, SketchCircle, SketchArc, SketchConstraint, SketchPoint
from quino.domain.types import SketchConstraintType
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService


@dataclass(slots=True)
class SketchSolveResult:
    success: bool
    positions: dict[str, tuple[float, float]]
    iterations: int
    max_error: float
    message: str | None = None


class SketchSolver:
    def __init__(self, expression_service: ExpressionService, unit_service: UnitService) -> None:
        self.expression_service = expression_service
        self.unit_service = unit_service

    def solve(
        self,
        project: Project,
        *,
        locked_point_ids: set[str] | None = None,
        max_iterations: int = 120,
        tolerance: float = 1e-6,
    ) -> SketchSolveResult:
        sketch = project.sketch
        if sketch is None:
            return SketchSolveResult(True, {}, 0, 0.0, None)

        point_map = {point.id: point for point in sketch.points()}
        positions = {
            point.id: self._evaluate_point(project, point)
            for point in point_map.values()
        }
        if not sketch.constraints:
            return SketchSolveResult(True, positions, 0, 0.0, None)

        locked_axes: dict[str, list[bool]] = {
            point_id: [False, False] for point_id in point_map
        }
        for point_id in (locked_point_ids or set()):
            if point_id in locked_axes:
                locked_axes[point_id] = [True, True]
        for constraint in sketch.constraints:
            if constraint.type is SketchConstraintType.FIX:
                for point_id in constraint.references:
                    if point_id in locked_axes:
                        locked_axes[point_id] = [True, True]

        max_error = 0.0
        for iteration in range(max_iterations):
            max_error = 0.0
            for constraint in sketch.constraints:
                error = self._apply_constraint(project, sketch, constraint, positions, locked_axes, tolerance)
                max_error = max(max_error, error)
            if max_error <= tolerance:
                return SketchSolveResult(True, positions, iteration + 1, max_error, None)

        return SketchSolveResult(
            False,
            positions,
            max_iterations,
            max_error,
            f"Sketch solver did not converge (max error {max_error:.3g} mm)",
        )

    # ------------------------------------------------------------------
    # Per-constraint dispatch
    # ------------------------------------------------------------------

    def _evaluate_point(self, project: Project, point: SketchPoint) -> tuple[float, float]:
        x = self.expression_service.evaluate_property(point.x, project.parameters).value
        y = self.expression_service.evaluate_property(point.y, project.parameters).value
        return x, y

    def _apply_constraint(
        self,
        project: Project,
        sketch: Sketch,
        constraint: SketchConstraint,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        refs = [pid for pid in constraint.references if pid in positions]
        t = constraint.type

        if t is SketchConstraintType.FIX or not refs:
            return 0.0
        if t is SketchConstraintType.COINCIDENT and len(refs) == 2:
            ex = self._apply_axis_pair(refs[0], refs[1], positions, locked_axes, 0, tolerance)
            ey = self._apply_axis_pair(refs[0], refs[1], positions, locked_axes, 1, tolerance)
            return ex + ey
        if t is SketchConstraintType.HORIZONTAL and len(refs) == 2:
            return self._apply_axis_pair(refs[0], refs[1], positions, locked_axes, 1, tolerance)
        if t is SketchConstraintType.VERTICAL and len(refs) == 2:
            return self._apply_axis_pair(refs[0], refs[1], positions, locked_axes, 0, tolerance)
        if t is SketchConstraintType.DISTANCE and len(refs) == 2 and constraint.value is not None:
            target = self.expression_service.evaluate_property(constraint.value, project.parameters).value
            return self._apply_distance(refs[0], refs[1], target, positions, locked_axes, tolerance)
        if t is SketchConstraintType.PARALLEL and len(refs) == 4:
            return self._apply_parallel(refs, positions, locked_axes, tolerance)
        if t is SketchConstraintType.PERPENDICULAR and len(refs) == 4:
            return self._apply_perpendicular(refs, positions, locked_axes, tolerance)
        if t is SketchConstraintType.EQUAL_LENGTH and len(refs) == 4:
            return self._apply_equal_length(refs, positions, locked_axes, tolerance)
        if t is SketchConstraintType.ANGLE and len(refs) == 3 and constraint.value is not None:
            quantity = self.expression_service.evaluate_expression(
                constraint.value.expression,
                project.parameters,
            )
            target_rad = self.unit_service.convert(quantity, "rad")
            return self._apply_angle(refs, target_rad, positions, locked_axes, tolerance)
        if t is SketchConstraintType.MIDPOINT and len(refs) == 3:
            return self._apply_midpoint(refs, positions, locked_axes, tolerance)
        if t is SketchConstraintType.COLLINEAR and len(refs) == 3:
            return self._apply_collinear(refs, positions, locked_axes, tolerance)
        if t is SketchConstraintType.SYMMETRIC and len(refs) == 4:
            return self._apply_symmetric(refs, positions, locked_axes, tolerance)
        if t is SketchConstraintType.ON_CIRCLE and len(refs) == 1 and constraint.entity_references:
            return self._apply_on_circle(
                project,
                refs,
                constraint.entity_references,
                sketch,
                positions,
                locked_axes,
                tolerance,
            )
        if t is SketchConstraintType.TANGENT and len(refs) == 2 and constraint.entity_references and constraint.value is not None:
            sign = self.expression_service.evaluate_property(constraint.value, project.parameters).value
            return self._apply_tangent(
                project,
                refs,
                constraint.entity_references,
                sign,
                sketch,
                positions,
                locked_axes,
                tolerance,
            )
        return 0.0

    # ------------------------------------------------------------------
    # Existing helpers
    # ------------------------------------------------------------------

    def _apply_axis_pair(
        self,
        point_a_id: str,
        point_b_id: str,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        axis: int,
        tolerance: float,
    ) -> float:
        a = list(positions[point_a_id])
        b = list(positions[point_b_id])
        error = b[axis] - a[axis]
        if abs(error) <= tolerance:
            return abs(error)
        a_locked = locked_axes[point_a_id][axis]
        b_locked = locked_axes[point_b_id][axis]
        if a_locked and b_locked:
            return abs(error)
        if a_locked:
            b[axis] = a[axis]
        elif b_locked:
            a[axis] = b[axis]
        else:
            mid = 0.5 * (a[axis] + b[axis])
            a[axis] = mid
            b[axis] = mid
        positions[point_a_id] = (a[0], a[1])
        positions[point_b_id] = (b[0], b[1])
        return abs(error)

    def _apply_distance(
        self,
        point_a_id: str,
        point_b_id: str,
        target: float,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        ax, ay = positions[point_a_id]
        bx, by = positions[point_b_id]
        dx, dy = bx - ax, by - ay
        distance = math.hypot(dx, dy)
        if distance <= 1e-12:
            dx, dy, distance = 1.0, 0.0, 1.0
        error = distance - target
        if abs(error) <= tolerance:
            return abs(error)
        ux, uy = dx / distance, dy / distance
        a_locked = all(locked_axes[point_a_id])
        b_locked = all(locked_axes[point_b_id])
        if a_locked and b_locked:
            return abs(error)
        if a_locked:
            positions[point_b_id] = (ax + target * ux, ay + target * uy)
        elif b_locked:
            positions[point_a_id] = (bx - target * ux, by - target * uy)
        else:
            c = 0.5 * error
            positions[point_a_id] = (ax + c * ux, ay + c * uy)
            positions[point_b_id] = (bx - c * ux, by - c * uy)
        return abs(error)

    # ------------------------------------------------------------------
    # New constraint solvers
    # ------------------------------------------------------------------

    def _apply_parallel(
        self,
        refs: list[str],
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs[0..1] = line 1, refs[2..3] = line 2. Force parallel directions."""
        ax, ay = positions[refs[0]]; bx, by = positions[refs[1]]
        cx, cy = positions[refs[2]]; dx, dy = positions[refs[3]]
        d1x, d1y = bx - ax, by - ay
        d2x, d2y = dx - cx, dy - cy
        len1 = math.hypot(d1x, d1y)
        len2 = math.hypot(d2x, d2y)
        if len1 < 1e-12 or len2 < 1e-12:
            return 0.0
        phi1 = math.atan2(d1y, d1x)
        phi2 = math.atan2(d2y, d2x)
        delta = self._wrap_angle(phi2 - phi1)
        target = math.pi if abs(abs(delta) - math.pi) < abs(delta) else 0.0
        correction = self._wrap_angle(delta - target)
        error = abs(math.sin(correction))
        if error <= tolerance:
            return error
        self._rotate_line(refs[0], refs[1], 0.5 * correction, positions, locked_axes)
        self._rotate_line(refs[2], refs[3], -0.5 * correction, positions, locked_axes)
        return error

    def _apply_perpendicular(
        self,
        refs: list[str],
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs[0..1] = line 1, refs[2..3] = line 2. Force perpendicular directions."""
        ax, ay = positions[refs[0]]; bx, by = positions[refs[1]]
        cx, cy = positions[refs[2]]; dx, dy = positions[refs[3]]
        d1x, d1y = bx - ax, by - ay
        d2x, d2y = dx - cx, dy - cy
        len1 = math.hypot(d1x, d1y)
        len2 = math.hypot(d2x, d2y)
        if len1 < 1e-12 or len2 < 1e-12:
            return 0.0
        u1x, u1y = d1x / len1, d1y / len1
        # Error: |cos(angle)| = |dot / (len1*len2)|
        dot = d1x * d2x + d1y * d2y
        error = abs(dot) / (len1 * len2)
        if error <= tolerance:
            return error
        # Target for d2: perpendicular to u1 — pick the 90° rotation closest to current d2
        n1x, n1y = -u1y, u1x   # 90° CCW from u1
        if (d2x * n1x + d2y * n1y) < 0:
            n1x, n1y = u1y, -u1x  # 90° CW
        td2x = n1x * len2
        td2y = n1y * len2
        # Also rotate line 1 toward perpendicular with line 2
        u2x, u2y = d2x / len2, d2y / len2
        n2x, n2y = u2y, -u2x   # 90° CCW from u2 (perpendicular partner)
        if (d1x * n2x + d1y * n2y) < 0:
            n2x, n2y = -u2y, u2x
        td1x = n2x * len1
        td1y = n2y * len1
        self._adjust_line_direction(refs[0], refs[1], d1x, d1y, td1x, td1y, ax, ay, bx, by, positions, locked_axes)
        self._adjust_line_direction(refs[2], refs[3], d2x, d2y, td2x, td2y, cx, cy, dx, dy, positions, locked_axes)
        return error

    def _apply_equal_length(
        self,
        refs: list[str],
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs[0..1] = line 1, refs[2..3] = line 2. Force equal lengths."""
        ax, ay = positions[refs[0]]; bx, by = positions[refs[1]]
        cx, cy = positions[refs[2]]; dx, dy = positions[refs[3]]
        d1x, d1y = bx - ax, by - ay
        d2x, d2y = dx - cx, dy - cy
        len1 = math.hypot(d1x, d1y)
        len2 = math.hypot(d2x, d2y)
        error = abs(len1 - len2)
        if error <= tolerance:
            return error
        target = 0.5 * (len1 + len2)
        if len1 > 1e-12:
            self._scale_line(refs[0], refs[1], target / len1, ax, ay, bx, by, d1x, d1y, positions, locked_axes)
        if len2 > 1e-12:
            self._scale_line(refs[2], refs[3], target / len2, cx, cy, dx, dy, d2x, d2y, positions, locked_axes)
        return error

    def _apply_angle(
        self,
        refs: list[str],
        target_rad: float,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs[0]=vertex, refs[1]=arm1 point, refs[2]=arm2 point. Angle at vertex."""
        vx, vy = positions[refs[0]]
        ax, ay = positions[refs[1]]
        bx, by = positions[refs[2]]
        d1x, d1y = ax - vx, ay - vy
        d2x, d2y = bx - vx, by - vy
        len1 = math.hypot(d1x, d1y)
        len2 = math.hypot(d2x, d2y)
        if len1 < 1e-12 or len2 < 1e-12:
            return 0.0
        # Signed angle from arm1 to arm2 (CCW positive)
        cross = d1x * d2y - d1y * d2x
        dot   = d1x * d2x + d1y * d2y
        current = math.atan2(cross, dot)
        delta = target_rad - current
        # Wrap delta to [-π, π]
        while delta > math.pi:
            delta -= 2 * math.pi
        while delta < -math.pi:
            delta += 2 * math.pi
        error = abs(delta)
        if error <= tolerance:
            return error
        v_locked = all(locked_axes[refs[0]])
        a_locked = all(locked_axes[refs[1]])
        b_locked = all(locked_axes[refs[2]])
        if a_locked and b_locked:
            return error
        # Decide how much of delta to give to each arm
        if a_locked:
            rot_b = delta
            rot_a = 0.0
        elif b_locked:
            rot_a = -delta
            rot_b = 0.0
        else:
            rot_a = -delta * 0.5
            rot_b = delta * 0.5
        if rot_a != 0.0:
            ca, sa = math.cos(rot_a), math.sin(rot_a)
            positions[refs[1]] = (vx + ca * d1x - sa * d1y, vy + sa * d1x + ca * d1y)
        if rot_b != 0.0:
            cb, sb = math.cos(rot_b), math.sin(rot_b)
            positions[refs[2]] = (vx + cb * d2x - sb * d2y, vy + sb * d2x + cb * d2y)
        return error

    def _apply_midpoint(
        self,
        refs: list[str],
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs[0]=midpoint, refs[1]=end1, refs[2]=end2. mid = (end1+end2)/2."""
        mx, my = positions[refs[0]]
        ax, ay = positions[refs[1]]
        bx, by = positions[refs[2]]
        tx = 0.5 * (ax + bx)
        ty = 0.5 * (ay + by)
        ex, ey = tx - mx, ty - my
        error = math.hypot(ex, ey)
        if error <= tolerance:
            return error
        m_locked = all(locked_axes[refs[0]])
        a_locked = all(locked_axes[refs[1]])
        b_locked = all(locked_axes[refs[2]])
        if m_locked:
            # Mid is fixed: adjust ends so their midpoint matches
            if not a_locked and not b_locked:
                # Move both ends equally toward satisfying mid = (a+b)/2
                # 2*mid = a+b → adjust a and b symmetrically
                cx2, cy2 = 2.0 * mx, 2.0 * my
                half_dx = (cx2 - (ax + bx)) * 0.5
                half_dy = (cy2 - (ay + by)) * 0.5
                positions[refs[1]] = (ax + half_dx, ay + half_dy)
                positions[refs[2]] = (bx + half_dx, by + half_dy)
            elif not a_locked:
                positions[refs[1]] = (2.0 * mx - bx, 2.0 * my - by)
            elif not b_locked:
                positions[refs[2]] = (2.0 * mx - ax, 2.0 * my - ay)
        else:
            positions[refs[0]] = (tx, ty)
        return error

    def _apply_collinear(
        self,
        refs: list[str],
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs = [p1, p2, p3]. All three points must be collinear."""
        max_err = 0.0
        # For each point, project it onto the line defined by the other two (Gauss-Seidel)
        for i in range(3):
            ia, ib = [j for j in range(3) if j != i]
            ax, ay = positions[refs[ia]]
            bx, by = positions[refs[ib]]
            px, py = positions[refs[i]]
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy)
            if length < 1e-12:
                continue
            ux, uy = dx / length, dy / length
            # Distance from p to line AB
            cross = (px - ax) * uy - (py - ay) * ux
            error = abs(cross)
            max_err = max(max_err, error)
            if error <= tolerance:
                continue
            if all(locked_axes[refs[i]]):
                continue
            # Project p onto line AB
            t_proj = (px - ax) * ux + (py - ay) * uy
            proj_x = ax + t_proj * ux
            proj_y = ay + t_proj * uy
            alpha = 0.5
            positions[refs[i]] = (
                px + alpha * (proj_x - px),
                py + alpha * (proj_y - py),
            )
        return max_err

    def _apply_symmetric(
        self,
        refs: list[str],
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs = [p1, p2, axis_p1, axis_p2]. p1 and p2 symmetric about axis line."""
        ax, ay = positions[refs[2]]
        bx, by = positions[refs[3]]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 1e-12:
            return 0.0
        ux, uy = dx / length, dy / length
        p1x, p1y = positions[refs[0]]
        p2x, p2y = positions[refs[1]]
        # Reflection of p1 about axis
        def reflect(px: float, py: float) -> tuple[float, float]:
            # signed distance from point to axis
            t = (px - ax) * ux + (py - ay) * uy
            foot_x = ax + t * ux
            foot_y = ay + t * uy
            return (2.0 * foot_x - px, 2.0 * foot_y - py)

        r1x, r1y = reflect(p1x, p1y)
        error = math.hypot(p2x - r1x, p2y - r1y)
        if error <= tolerance:
            return error
        p1_locked = all(locked_axes[refs[0]])
        p2_locked = all(locked_axes[refs[1]])
        if p1_locked and p2_locked:
            return error
        if p1_locked:
            positions[refs[1]] = (r1x, r1y)
        elif p2_locked:
            # reflection of p2 must equal p1
            r2x, r2y = reflect(p2x, p2y)
            positions[refs[0]] = (r2x, r2y)
        else:
            # Move p2 toward r1 and p1 toward reflect(p2) symmetrically
            r2x, r2y = reflect(p2x, p2y)
            positions[refs[0]] = (0.5 * (p1x + r2x), 0.5 * (p1y + r2y))
            positions[refs[1]] = (0.5 * (p2x + r1x), 0.5 * (p2y + r1y))
        return error

    def _apply_on_circle(
        self,
        project: Project,
        refs: list[str],
        entity_refs: list[str],
        sketch: Sketch,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs = [point_id]. entity_refs = [circle_entity_id]. Project point onto circle."""
        circle = next((e for e in sketch.entities if e.id == entity_refs[0] and isinstance(e, (SketchCircle, SketchArc))), None)
        if circle is None or not hasattr(circle, "center_point_id"):
            return 0.0
        if circle.center_point_id not in positions:
            return 0.0
        radius = self.expression_service.evaluate_property(circle.radius, project.parameters).value
        if radius <= 0.0:
            return 0.0
        cx, cy = positions[circle.center_point_id]
        px, py = positions[refs[0]]
        dx, dy = px - cx, py - cy
        dist = math.hypot(dx, dy)
        error = abs(dist - radius)
        if error <= tolerance:
            return error
        if all(locked_axes[refs[0]]):
            return error
        if dist < 1e-12:
            # Point at center: move along +x
            positions[refs[0]] = (cx + radius, cy)
        else:
            positions[refs[0]] = (cx + (radius / dist) * dx, cy + (radius / dist) * dy)
        return error

    def _apply_tangent(
        self,
        project: Project,
        refs: list[str],
        entity_refs: list[str],
        sign: float,
        sketch: Sketch,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs = [line_p1, line_p2]. entity_refs = [circle_entity_id].
        sign=+1 → exterior tangency (center on positive side of line),
        sign=-1 → interior."""
        circle = next((e for e in sketch.entities if e.id == entity_refs[0] and isinstance(e, (SketchCircle, SketchArc))), None)
        if circle is None or not hasattr(circle, "center_point_id"):
            return 0.0
        if circle.center_point_id not in positions:
            return 0.0
        radius = self.expression_service.evaluate_property(circle.radius, project.parameters).value
        if radius <= 0.0:
            return 0.0
        cx, cy = positions[circle.center_point_id]
        p1x, p1y = positions[refs[0]]
        p2x, p2y = positions[refs[1]]
        dx, dy = p2x - p1x, p2y - p1y
        length = math.hypot(dx, dy)
        if length < 1e-12:
            return 0.0
        # Normal to line (perpendicular, pointing left of direction p1→p2)
        nx, ny = -dy / length, dx / length
        # Signed distance from center to line
        h = (cx - p1x) * nx + (cy - p1y) * ny
        target = sign * radius
        error = h - target
        if abs(error) <= tolerance:
            return abs(error)
        p1_locked = all(locked_axes[refs[0]])
        p2_locked = all(locked_axes[refs[1]])
        if p1_locked and p2_locked:
            return abs(error)
        # Shift both line points perpendicular by -error/2
        shift = -error * 0.5
        if p1_locked:
            shift = -error
            positions[refs[1]] = (p2x + shift * nx, p2y + shift * ny)
        elif p2_locked:
            shift = -error
            positions[refs[0]] = (p1x + shift * nx, p1y + shift * ny)
        else:
            positions[refs[0]] = (p1x + shift * nx, p1y + shift * ny)
            positions[refs[1]] = (p2x + shift * nx, p2y + shift * ny)
        return abs(error)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _adjust_line_direction(
        self,
        pid_a: str, pid_b: str,
        d_cur_x: float, d_cur_y: float,
        d_tgt_x: float, d_tgt_y: float,
        ax: float, ay: float,
        bx: float, by: float,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
    ) -> None:
        """Move line endpoints so its direction vector changes from d_cur to d_tgt,
        keeping the midpoint fixed when both ends are free."""
        delta_x = d_tgt_x - d_cur_x
        delta_y = d_tgt_y - d_cur_y
        a_locked = all(locked_axes[pid_a])
        b_locked = all(locked_axes[pid_b])
        if a_locked and b_locked:
            return
        if a_locked:
            # Keep a, move b: b += delta (since d = b - a)
            positions[pid_b] = (bx + delta_x, by + delta_y)
        elif b_locked:
            # Keep b, move a: a -= delta
            positions[pid_a] = (ax - delta_x, ay - delta_y)
        else:
            # Move symmetrically from midpoint
            positions[pid_a] = (ax - delta_x * 0.5, ay - delta_y * 0.5)
            positions[pid_b] = (bx + delta_x * 0.5, by + delta_y * 0.5)

    def _scale_line(
        self,
        pid_a: str, pid_b: str,
        scale: float,
        ax: float, ay: float,
        bx: float, by: float,
        dx: float, dy: float,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
    ) -> None:
        """Scale a line segment to a new length (scale = new_len / current_len)."""
        a_locked = all(locked_axes[pid_a])
        b_locked = all(locked_axes[pid_b])
        if a_locked and b_locked:
            return
        if a_locked:
            positions[pid_b] = (ax + scale * dx, ay + scale * dy)
        elif b_locked:
            positions[pid_a] = (bx - scale * dx, by - scale * dy)
        else:
            mid_x = 0.5 * (ax + bx)
            mid_y = 0.5 * (ay + by)
            half = 0.5 * scale
            positions[pid_a] = (mid_x - half * dx, mid_y - half * dy)
            positions[pid_b] = (mid_x + half * dx, mid_y + half * dy)

    def _rotate_line(
        self,
        pid_a: str,
        pid_b: str,
        angle: float,
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
    ) -> None:
        if abs(angle) <= 1e-12:
            return
        ax, ay = positions[pid_a]
        bx, by = positions[pid_b]
        a_locked = all(locked_axes[pid_a])
        b_locked = all(locked_axes[pid_b])
        if a_locked and b_locked:
            return
        c = math.cos(angle)
        s = math.sin(angle)
        if a_locked:
            dx, dy = bx - ax, by - ay
            positions[pid_b] = (ax + c * dx - s * dy, ay + s * dx + c * dy)
            return
        if b_locked:
            dx, dy = ax - bx, ay - by
            positions[pid_a] = (bx + c * dx - s * dy, by + s * dx + c * dy)
            return
        mx = 0.5 * (ax + bx)
        my = 0.5 * (ay + by)
        dax, day = ax - mx, ay - my
        dbx, dby = bx - mx, by - my
        positions[pid_a] = (mx + c * dax - s * day, my + s * dax + c * day)
        positions[pid_b] = (mx + c * dbx - s * dby, my + s * dbx + c * dby)

    def _wrap_angle(self, angle: float) -> float:
        while angle <= -math.pi:
            angle += 2.0 * math.pi
        while angle > math.pi:
            angle -= 2.0 * math.pi
        return angle

    def _apply_perpendicular(
        self,
        refs: list[str],
        positions: dict[str, tuple[float, float]],
        locked_axes: dict[str, list[bool]],
        tolerance: float,
    ) -> float:
        """refs[0..1] = line 1, refs[2..3] = line 2. Force perpendicular directions."""
        ax, ay = positions[refs[0]]
        bx, by = positions[refs[1]]
        cx, cy = positions[refs[2]]
        dx, dy = positions[refs[3]]
        d1x, d1y = bx - ax, by - ay
        d2x, d2y = dx - cx, dy - cy
        len1 = math.hypot(d1x, d1y)
        len2 = math.hypot(d2x, d2y)
        if len1 < 1e-12 or len2 < 1e-12:
            return 0.0
        phi1 = math.atan2(d1y, d1x)
        phi2 = math.atan2(d2y, d2x)
        delta = self._wrap_angle(phi2 - phi1)
        target = math.pi * 0.5 if abs(delta - math.pi * 0.5) <= abs(delta + math.pi * 0.5) else -math.pi * 0.5
        correction = self._wrap_angle(delta - target)
        error = abs(math.cos(delta))
        if error <= tolerance:
            return error
        self._rotate_line(refs[0], refs[1], 0.5 * correction, positions, locked_axes)
        self._rotate_line(refs[2], refs[3], -0.5 * correction, positions, locked_axes)
        return error
