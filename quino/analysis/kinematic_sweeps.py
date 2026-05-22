from __future__ import annotations

import math
from abc import ABC, abstractmethod

from quino.domain.workspace import SweepDef
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
