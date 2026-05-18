"""Helpers that synthesize auxiliary geometry inside the Solvespace SolverSystem.

These entities (aux points + aux lines) exist ONLY in the SolverSystem for one
solve() call. They MUST NOT enter the QUINO domain — the QUINO Project is the
single source of truth, and aux geometry would pollute it.

Used by HORIZONTAL_DISTANCE and VERTICAL_DISTANCE constraint handlers.

Geometry note
-------------
- HORIZONTAL_DISTANCE = |p2.x - p1.x|.  The natural Solvespace primitive is
  point-to-line distance.  A **vertical** line through p1 has constant X = p1.x,
  so distance(p2, vertical_line) = |p2.x - p1.x|.  We therefore build a
  *vertical* auxiliary line for horizontal-distance constraints.

- VERTICAL_DISTANCE = |p2.y - p1.y|.  A **horizontal** line through p1 has
  constant Y = p1.y, so distance(p2, horizontal_line) = |p2.y - p1.y|.  We
  therefore build a *horizontal* auxiliary line for vertical-distance constraints.

The aux point is initialised with a non-zero offset from the anchor so the line
is not degenerate (zero-length lines cannot be constrained horizontal/vertical).
"""
from __future__ import annotations

_OFFSET = 50.0  # mm — large enough to avoid degenerate geometry


def add_horizontal_distance_aux_line(sys, wp, anchor_point):
    """Create a vertical auxiliary line through `anchor_point`.

    The distance from any free point to this line equals the horizontal
    separation (|Δx|) between the free point and the anchor.

    Returns the line handle.  The aux endpoint is internal; callers only need
    the line to pass to sys.distance().
    """
    aux_pt = sys.add_point_2d(0.0, _OFFSET, wp)  # offset in Y to avoid zero length
    aux_line = sys.add_line_2d(anchor_point, aux_pt, wp)
    sys.vertical(aux_line, wp)
    return aux_line


def add_vertical_distance_aux_line(sys, wp, anchor_point):
    """Create a horizontal auxiliary line through `anchor_point`.

    The distance from any free point to this line equals the vertical
    separation (|Δy|) between the free point and the anchor.

    Returns the line handle.
    """
    aux_pt = sys.add_point_2d(_OFFSET, 0.0, wp)  # offset in X to avoid zero length
    aux_line = sys.add_line_2d(anchor_point, aux_pt, wp)
    sys.horizontal(aux_line, wp)
    return aux_line
