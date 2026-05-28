from __future__ import annotations

import math
from abc import ABC, abstractmethod

from quino.domain.workspace import SweepDef
from quino.pose.geometry import marker_world_position
from quino.pose.model import PoseConstraint
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService


class SweepStrategy(ABC):
    def __init__(self, sweep: SweepDef) -> None:
        self.sweep = sweep

    @abstractmethod
    def constraints(self, value: float) -> list[PoseConstraint]:
        raise NotImplementedError

    def label(self) -> str:
        return self.sweep.label or self.sweep.variable_kind


_STRATEGIES: dict[str, type[SweepStrategy]] = {}


def register_strategy(variable_kind: str):
    def wrapper(cls):
        _STRATEGIES[variable_kind] = cls
        return cls

    return wrapper


def strategy_for(sweep: SweepDef) -> SweepStrategy:
    cls = _STRATEGIES.get(sweep.variable_kind)
    if cls is None:
        raise ValueError(f"Unknown sweep variable_kind {sweep.variable_kind!r}")
    return cls(sweep)


@register_strategy("marker_x")
class MarkerXStrategy(SweepStrategy):
    def constraints(self, value: float) -> list[PoseConstraint]:
        marker_id = self.sweep.target_ids[0]
        return [
            PoseConstraint(
                id=f"sweep_{self.sweep.id}",
                kind="marker_projected_coordinate",
                target_id=marker_id,
                metadata={
                    "axis_x": 1.0,
                    "axis_y": 0.0,
                    "value": value,
                    "reference_x": 0.0,
                    "reference_y": 0.0,
                },
            )
        ]


@register_strategy("marker_y")
class MarkerYStrategy(SweepStrategy):
    def constraints(self, value: float) -> list[PoseConstraint]:
        marker_id = self.sweep.target_ids[0]
        return [
            PoseConstraint(
                id=f"sweep_{self.sweep.id}",
                kind="marker_projected_coordinate",
                target_id=marker_id,
                metadata={
                    "axis_x": 0.0,
                    "axis_y": 1.0,
                    "value": value,
                    "reference_x": 0.0,
                    "reference_y": 0.0,
                },
            )
        ]


@register_strategy("slider_stroke")
class SliderStrokeStrategy(SweepStrategy):
    def __init__(self, sweep: SweepDef) -> None:
        super().__init__(sweep)
        self._axis = (1.0, 0.0)
        self._reference = (0.0, 0.0)

    def bind_geometry(self, *, axis: tuple[float, float], reference: tuple[float, float]) -> None:
        self._axis = axis
        self._reference = reference

    def constraints(self, value: float) -> list[PoseConstraint]:
        slider_id, marker_id = self.sweep.target_ids[0], self.sweep.target_ids[1]
        return [
            PoseConstraint(
                id=f"sweep_{self.sweep.id}",
                kind="marker_projected_coordinate",
                target_id=marker_id,
                metadata={
                    "axis_x": self._axis[0],
                    "axis_y": self._axis[1],
                    "value": value,
                    "reference_x": self._reference[0],
                    "reference_y": self._reference[1],
                    "slider_id": slider_id,
                },
            )
        ]


class _AngleStrategyBase(SweepStrategy):
    def __init__(self, sweep: SweepDef) -> None:
        super().__init__(sweep)
        self._body_a_id: str | None = None
        self._body_b_id: str | None = None
        self._local_phi_a = 0.0
        self._local_phi_b = 0.0

    def bind_bodies(
        self,
        *,
        body_a_id: str,
        body_b_id: str,
        local_phi_a: float,
        local_phi_b: float,
    ) -> None:
        self._body_a_id = body_a_id
        self._body_b_id = body_b_id
        self._local_phi_a = local_phi_a
        self._local_phi_b = local_phi_b

    def constraints(self, value: float) -> list[PoseConstraint]:
        if self._body_a_id is None or self._body_b_id is None:
            raise RuntimeError(f"{self.__class__.__name__} not bound to bodies")
        return [
            PoseConstraint(
                id=f"sweep_{self.sweep.id}",
                kind="relative_body_angle",
                target_id=self._body_a_id,
                metadata={
                    "body_a_id": self._body_a_id,
                    "body_b_id": self._body_b_id,
                    "local_phi_a": self._local_phi_a,
                    "local_phi_b": self._local_phi_b,
                    "angle": value,
                },
            )
        ]


@register_strategy("angle_horizontal")
class AngleHorizontalStrategy(_AngleStrategyBase):
    pass


@register_strategy("angle_vertical")
class AngleVerticalStrategy(_AngleStrategyBase):
    pass


@register_strategy("angle_between_segments")
class AngleBetweenSegmentsStrategy(_AngleStrategyBase):
    pass


def slider_axis_for(project, slider_id: str) -> tuple[float, float, float, float]:
    slider = next(slider for slider in project.model.sliders if slider.id == slider_id)
    unit_service = UnitService()
    expression_service = ExpressionService(unit_service)
    angle_rad = unit_service.convert(
        expression_service.evaluate_expression(slider.angle.expression, project.parameters),
        "rad",
    )
    ref_x = expression_service.evaluate_property(slider.origin_x, project.parameters).value
    ref_y = expression_service.evaluate_property(slider.origin_y, project.parameters).value
    return (math.cos(angle_rad), math.sin(angle_rad), ref_x, ref_y)


def body_of_marker(project, marker_id: str) -> str:
    for body in project.model.bodies:
        if any(marker.id == marker_id for marker in body.markers):
            return body.id
    raise ValueError(f"Marker {marker_id!r} not found")


def segment_local_angle(project, marker_a_id: str, marker_b_id: str) -> float:
    ax, ay = marker_world_position(project, marker_a_id, None)
    bx, by = marker_world_position(project, marker_b_id, None)
    return math.atan2(by - ay, bx - ax)


def compute_sweep_base_value(project, sweep: SweepDef, initial_pose) -> float:
    """Return the absolute value of the sweep variable in the given initial pose.

    This is the value that the solver would see if the sweep value were 0 in
    relative mode — i.e. the value that keeps the mechanism at *initial_pose*.
    """
    kind = sweep.variable_kind

    if kind == "marker_x":
        mx, _ = marker_world_position(project, sweep.target_ids[0], initial_pose)
        return mx

    if kind == "marker_y":
        _, my = marker_world_position(project, sweep.target_ids[0], initial_pose)
        return my

    if kind == "slider_stroke":
        ax, ay, rx, ry = slider_axis_for(project, sweep.target_ids[0])
        mx, my = marker_world_position(project, sweep.target_ids[1], initial_pose)
        return ax * (mx - rx) + ay * (my - ry)

    if kind in {"angle_horizontal", "angle_vertical", "angle_between_segments"}:
        # Build a temporary strategy so we can reuse bind logic.
        strategy = strategy_for(sweep)
        if isinstance(strategy, _AngleStrategyBase):
            if kind == "angle_between_segments":
                body_a = body_of_marker(project, sweep.target_ids[0])
                body_b = body_of_marker(project, sweep.target_ids[2])
                local_phi_a = segment_local_angle(project, sweep.target_ids[0], sweep.target_ids[1])
                local_phi_b = segment_local_angle(project, sweep.target_ids[2], sweep.target_ids[3])
                strategy.bind_bodies(
                    body_a_id=body_a,
                    body_b_id=body_b,
                    local_phi_a=local_phi_a,
                    local_phi_b=local_phi_b,
                )
            elif kind == "angle_horizontal":
                marker_a, marker_b = sweep.target_ids[0], sweep.target_ids[1]
                strategy.bind_bodies(
                    body_a_id=body_of_marker(project, marker_a),
                    body_b_id="__ground__",
                    local_phi_a=segment_local_angle(project, marker_a, marker_b),
                    local_phi_b=0.0,
                )
            elif kind == "angle_vertical":
                marker_a, marker_b = sweep.target_ids[0], sweep.target_ids[1]
                strategy.bind_bodies(
                    body_a_id=body_of_marker(project, marker_a),
                    body_b_id="__ground__",
                    local_phi_a=segment_local_angle(project, marker_a, marker_b),
                    local_phi_b=math.pi / 2.0,
                )

            if initial_pose is None:
                # Fallback to sketch reference angle.
                if kind == "angle_horizontal":
                    return strategy._local_phi_a
                if kind == "angle_vertical":
                    return strategy._local_phi_a - math.pi / 2.0
                return strategy._local_phi_a - strategy._local_phi_b

            body_a_pose = initial_pose.body_poses.get(strategy._body_a_id)
            body_a_angle = body_a_pose.angle if body_a_pose is not None else 0.0
            if kind == "angle_horizontal":
                return body_a_angle + strategy._local_phi_a
            if kind == "angle_vertical":
                return body_a_angle + strategy._local_phi_a - math.pi / 2.0
            body_b_pose = initial_pose.body_poses.get(strategy._body_b_id)
            body_b_angle = body_b_pose.angle if body_b_pose is not None else 0.0
            return (body_a_angle + strategy._local_phi_a) - (body_b_angle + strategy._local_phi_b)

    raise ValueError(f"Cannot compute base value for sweep kind {kind!r}")
