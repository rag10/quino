"""Backwards-compat shim. The implementation lives in quino.services.sketch_solving."""
from quino.services.sketch_solving import SketchSolveResult, SketchSolver

__all__ = ["SketchSolver", "SketchSolveResult"]
