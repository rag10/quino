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
    """Sketch DOF analysis.

    point_dof maps each SketchPoint.id to its remaining degrees of freedom (0, 1, or 2).
    fully_constrained_point_ids is intentionally reserved for points that are
    constrained relative to an anchored component.  Points that are rigidly
    defined but belong to a floating component are reported separately so the
    GUI can still let the user drag that component.
    """
    point_dof: dict[str, int]
    fully_constrained_point_ids: set[str]
    fully_constrained_entity_ids: set[str]
    total_free_dof: int
    fixed_point_ids: set[str] = field(default_factory=set)
    floating_point_ids: set[str] = field(default_factory=set)
    floating_entity_ids: set[str] = field(default_factory=set)
    component_ids_by_point: dict[str, int] = field(default_factory=dict)
    component_has_fix: dict[int, bool] = field(default_factory=dict)
    total_system_dof: int | None = None
