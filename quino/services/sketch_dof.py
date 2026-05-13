from __future__ import annotations

from dataclasses import dataclass

from quino.domain.model import (
    Sketch,
    SketchArc,
    SketchCircle,
    SketchInfiniteLine,
    SketchLineSegment,
    SketchPoint,
)
from quino.domain.types import SketchConstraintType


_CONSTRAINT_DOF_REMOVED: dict[SketchConstraintType, int] = {
    SketchConstraintType.FIX: 2,
    SketchConstraintType.HORIZONTAL: 1,
    SketchConstraintType.VERTICAL: 1,
    SketchConstraintType.COINCIDENT: 2,
    SketchConstraintType.DISTANCE: 1,
    SketchConstraintType.HORIZONTAL_DISTANCE: 1,
    SketchConstraintType.VERTICAL_DISTANCE: 1,
    SketchConstraintType.RADIUS: 1,
    SketchConstraintType.PARALLEL: 1,
    SketchConstraintType.PERPENDICULAR: 1,
    SketchConstraintType.EQUAL_LENGTH: 1,
    SketchConstraintType.ANGLE: 1,
    SketchConstraintType.MIDPOINT: 2,
    SketchConstraintType.COLLINEAR: 1,
    SketchConstraintType.SYMMETRIC: 2,
    SketchConstraintType.ON_CIRCLE: 1,
    SketchConstraintType.TANGENT: 1,
}


@dataclass
class DofResult:
    point_dof: dict[str, int]
    fully_constrained_point_ids: set[str]
    fully_constrained_entity_ids: set[str]
    total_free_dof: int


class SketchDofAnalyzer:
    def analyze(self, sketch: Sketch) -> DofResult:
        all_point_ids: set[str] = set()
        entity_point_map: dict[str, list[str]] = {}

        for entity in sketch.entities.values():
            if isinstance(entity, SketchPoint):
                all_point_ids.add(entity.id)
                entity_point_map[entity.id] = [entity.id]
            elif isinstance(entity, SketchLineSegment):
                all_point_ids.update([entity.start_point_id, entity.end_point_id])
                entity_point_map[entity.id] = [entity.start_point_id, entity.end_point_id]
            elif isinstance(entity, SketchCircle):
                all_point_ids.add(entity.center_point_id)
                entity_point_map[entity.id] = [entity.center_point_id]
            elif isinstance(entity, SketchArc):
                pts = [entity.center_point_id, entity.start_point_id, entity.end_point_id]
                all_point_ids.update(pts)
                entity_point_map[entity.id] = pts
            elif isinstance(entity, SketchInfiniteLine):
                all_point_ids.update([entity.point_a_id, entity.point_b_id])
                entity_point_map[entity.id] = [entity.point_a_id, entity.point_b_id]

        point_dof: dict[str, int] = {pid: 2 for pid in all_point_ids}

        for constraint in sketch.constraints.values():
            removed = (
                1
                if constraint.type is SketchConstraintType.COINCIDENT and constraint.entity_references
                else _CONSTRAINT_DOF_REMOVED.get(constraint.type, 0)
            )
            refs = constraint.references
            if constraint.type is SketchConstraintType.FIX:
                for ref in refs:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 2)
            elif constraint.type is SketchConstraintType.COINCIDENT:
                for ref in refs[: (1 if constraint.entity_references else 2)]:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            elif constraint.type is SketchConstraintType.MIDPOINT:
                for ref in refs:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            elif constraint.type is SketchConstraintType.SYMMETRIC:
                for ref in refs[:2]:
                    point_dof[ref] = max(0, point_dof.get(ref, 2) - 1)
            else:
                # Remove `removed` DOF from whichever referenced points still have freedom
                remaining = removed
                candidates = [r for r in refs if r in point_dof and point_dof[r] > 0]
                # Sort highest DOF first so we draw from the most-constrained-last point
                candidates.sort(key=lambda r: point_dof[r], reverse=True)
                for ref in candidates:
                    take = min(remaining, point_dof[ref])
                    point_dof[ref] -= take
                    remaining -= take
                    if remaining == 0:
                        break

        fully_constrained_point_ids = {pid for pid, dof in point_dof.items() if dof == 0}

        fully_constrained_entity_ids: set[str] = set()
        for entity_id, point_ids in entity_point_map.items():
            if point_ids and all(point_dof.get(pid, 2) == 0 for pid in point_ids):
                fully_constrained_entity_ids.add(entity_id)

        total_free_dof = sum(point_dof.values())

        return DofResult(
            point_dof=point_dof,
            fully_constrained_point_ids=fully_constrained_point_ids,
            fully_constrained_entity_ids=fully_constrained_entity_ids,
            total_free_dof=total_free_dof,
        )
