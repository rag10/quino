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
