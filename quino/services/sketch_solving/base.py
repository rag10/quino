# quino/services/sketch_solving/base.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SketchSolveResult:
    success: bool
    positions: dict[str, tuple[float, float]]
    iterations: int
    max_error: float
    message: str | None = None
    constraint_errors: dict[str, float] = field(default_factory=dict)
    bad_constraints: list[str] = field(default_factory=list)
    radius_updates: dict[str, float] = field(default_factory=dict)
    bad_constraint_details: dict[str, str] = field(default_factory=dict)
    """Map from constraint id to human-readable failure description (one per bad_constraints entry)."""


@dataclass
class DofResult:
    """Per-point DOF analysis derived from Solvespace via perturbation testing.

    point_dof maps each SketchPoint.id to its remaining degrees of freedom (0, 1, or 2).
    fully_constrained_point_ids is the set of points with dof==0.
    fully_constrained_entity_ids is the set of entities (line/circle/arc) whose
    referenced points are all fully constrained.
    total_free_dof is the sum of point_dof values.
    """
    point_dof: dict[str, int]
    fully_constrained_point_ids: set[str]
    fully_constrained_entity_ids: set[str]
    total_free_dof: int
