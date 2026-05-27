"""Derivation helpers for a body's CoM from its CoMAnchor.

The CoM is never stored as a Marker in QUINO; it is computed on every
read from the anchor (kind + payload) plus the body's structural markers
and current pose. This file is the single source of truth for that
derivation."""
from __future__ import annotations

import math

from quino.domain.model import Body
from quino.domain.workspace import Pose
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService

_expr = ExpressionService(UnitService())


def _eval_mm(project, scalar) -> float:
    """Evaluate a ScalarProperty and convert its value to mm."""
    evaluated = _expr.evaluate_property(scalar, project.parameters)
    return _expr.unit_service.convert(
        _expr.unit_service.quantity(evaluated.value, evaluated.unit), "mm"
    )


def _structural_xy(project, body: Body) -> list[tuple[str, float, float]]:
    """Return [(marker_id, x_mm, y_mm), ...] for the body's structural markers."""
    out: list[tuple[str, float, float]] = []
    for marker in body.structural_markers():
        out.append(
            (
                marker.id,
                _eval_mm(project, marker.x),
                _eval_mm(project, marker.y),
            )
        )
    return out


def com_local_position(project, body: Body) -> tuple[float, float]:
    """Return (lx, ly) in mm in the body's local frame."""
    anchor = body.com
    kind = anchor.kind
    data = anchor.data
    if kind == "bar_percent":
        markers = _structural_xy(project, body)
        if len(markers) < 2:
            raise ValueError(
                f"bar_percent anchor requires at least 2 structural markers (body {body.id!r})"
            )
        (_, x1, y1), (_, x2, y2) = markers[0], markers[-1]
        percent = float(data.get("percent", 50.0))
        t = max(0.0, min(100.0, percent)) / 100.0
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    if kind == "barycentric":
        markers = _structural_xy(project, body)
        if not markers:
            return (0.0, 0.0)
        weights_raw = data.get("weights", {}) or {}
        weights = [max(0.0, float(weights_raw.get(mid, 0.0))) for mid, _, _ in markers]
        total = sum(weights)
        if total <= 1e-12:
            # Fall back to equal weights so the CoM stays inside the hull.
            weights = [1.0] * len(markers)
            total = float(len(markers))
        norm = [w / total for w in weights]
        cx = sum(w * x for w, (_, x, _) in zip(norm, markers))
        cy = sum(w * y for w, (_, _, y) in zip(norm, markers))
        return (cx, cy)
    if kind == "local_offset":
        return (float(data.get("lx", 0.0)), float(data.get("ly", 0.0)))
    if kind == "marker":
        target_id = data.get("marker_id")
        for mid, x, y in _structural_xy(project, body):
            if mid == target_id:
                return (x, y)
        raise ValueError(
            f"marker anchor refers to unknown marker {target_id!r} (body {body.id!r})"
        )
    raise ValueError(f"Unknown CoMAnchor kind: {kind!r}")


def com_global_position(
    project, body: Body, pose: Pose | None = None,
) -> tuple[float, float]:
    """Return (gx, gy) in mm in the world frame for the given pose (or
    the reference configuration when ``pose is None``).

    Convention: ``com_local_position`` returns the CoM expressed in the
    body's reference world frame (same coordinate system as the body's
    structural markers as authored). A ``BodyPose`` describes the current
    pose of the body as a rigid-body motion from its reference: the body's
    anchor (first structural marker) is translated to ``(bp.x, bp.y)`` and
    rotated by ``bp.angle - body.reference_angle``. So to map the CoM from
    its reference position to the current pose we:

    1. Compute the CoM position relative to the body anchor in the
       reference configuration.
    2. Rotate that offset by the *delta* angle and translate by the
       anchor's current position.
    """
    com_ref_x, com_ref_y = com_local_position(project, body)
    if pose is None or body.id not in pose.body_poses:
        return (com_ref_x, com_ref_y)
    bp = pose.body_poses[body.id]
    # Anchor position in the reference configuration (= first structural marker).
    structural = body.structural_markers()
    if not structural:
        return (bp.x, bp.y)
    anchor_ref_x = _eval_mm(project, structural[0].x)
    anchor_ref_y = _eval_mm(project, structural[0].y)
    # Reference angle: orientation of the first edge in the reference config.
    if len(structural) >= 2:
        next_x = _eval_mm(project, structural[1].x)
        next_y = _eval_mm(project, structural[1].y)
        ref_angle = math.atan2(next_y - anchor_ref_y, next_x - anchor_ref_x)
    else:
        ref_angle = 0.0
    # CoM offset from anchor, expressed in the reference world frame.
    dx_ref = com_ref_x - anchor_ref_x
    dy_ref = com_ref_y - anchor_ref_y
    # Express that offset in the body's local frame (un-rotate by ref_angle).
    cos_r = math.cos(ref_angle)
    sin_r = math.sin(ref_angle)
    lx = cos_r * dx_ref + sin_r * dy_ref
    ly = -sin_r * dx_ref + cos_r * dy_ref
    # Rotate the local offset by the current body angle and translate.
    cos_a = math.cos(bp.angle)
    sin_a = math.sin(bp.angle)
    return (
        bp.x + cos_a * lx - sin_a * ly,
        bp.y + sin_a * lx + cos_a * ly,
    )
