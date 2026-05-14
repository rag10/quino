from __future__ import annotations

from dataclasses import dataclass
import math

from quino.domain.types import Dimension


@dataclass(frozen=True, slots=True)
class Quantity:
    value_si: float
    dimensions: dict[Dimension, int]

    def to(self, factor: float) -> float:
        return self.value_si / factor

    @property
    def dimension_text(self) -> str:
        if not self.dimensions:
            return Dimension.UNITLESS.value
        parts: list[str] = []
        for dimension in sorted(self.dimensions, key=lambda item: item.value):
            exponent = self.dimensions[dimension]
            if exponent == 1:
                parts.append(dimension.value)
            else:
                parts.append(f"{dimension.value}^{exponent}")
        return "*".join(parts)

    def is_unitless(self) -> bool:
        return not self.dimensions

    def is_pure(self, dimension: Dimension) -> bool:
        if dimension is Dimension.UNITLESS:
            return not self.dimensions
        if dimension is Dimension.INERTIA:
            return self.dimensions == {Dimension.MASS: 1, Dimension.LENGTH: 2}
        if dimension is Dimension.TORQUE:
            return self.dimensions == {Dimension.FORCE: 1, Dimension.LENGTH: 1}
        return self.dimensions == {dimension: 1}


class UnitService:
    _UNITS: dict[str, tuple[Dimension, float]] = {
        "mm": (Dimension.LENGTH, 0.001),
        "m": (Dimension.LENGTH, 1.0),
        "deg": (Dimension.ANGLE, math.pi / 180.0),
        "rad": (Dimension.ANGLE, 1.0),
        "kg": (Dimension.MASS, 1.0),
        "N": (Dimension.FORCE, 1.0),
        "s": (Dimension.TIME, 1.0),
        "unitless": (Dimension.UNITLESS, 1.0),
        "kgmm2": (Dimension.INERTIA, 1e-6),
        "kgm2": (Dimension.INERTIA, 1.0),
        "N*mm": (Dimension.TORQUE, 1e-3),
        "N*m": (Dimension.TORQUE, 1.0),
    }

    # Maps each Dimension to its SI base-dimension exponents
    _UNIT_DIMS: dict[Dimension, dict[Dimension, int]] = {
        Dimension.LENGTH: {Dimension.LENGTH: 1},
        Dimension.ANGLE: {Dimension.ANGLE: 1},
        Dimension.MASS: {Dimension.MASS: 1},
        Dimension.TIME: {Dimension.TIME: 1},
        Dimension.INERTIA: {Dimension.MASS: 1, Dimension.LENGTH: 2},
        Dimension.FORCE: {Dimension.FORCE: 1},
        Dimension.TORQUE: {Dimension.FORCE: 1, Dimension.LENGTH: 1},
        Dimension.UNITLESS: {},
    }

    def is_known(self, unit: str) -> bool:
        return unit in self._UNITS

    def dimension(self, unit: str) -> Dimension:
        if unit not in self._UNITS:
            raise ValueError(f"Unknown unit: {unit}")
        return self._UNITS[unit][0]

    def factor(self, unit: str) -> float:
        if unit not in self._UNITS:
            raise ValueError(f"Unknown unit: {unit}")
        return self._UNITS[unit][1]

    def known_units(self) -> set[str]:
        return set(self._UNITS.keys())

    def quantity(self, value: float, unit: str) -> Quantity:
        dimension = self.dimension(unit)
        return Quantity(value * self.factor(unit), dict(self._UNIT_DIMS[dimension]))

    def convert(self, quantity: Quantity, unit: str) -> float:
        target_dimension = self.dimension(unit)
        expected = self._UNIT_DIMS[target_dimension]  # read-only comparison, no copy needed
        if quantity.dimensions != expected:
            raise ValueError("Incompatible dimensions")
        return quantity.to(self.factor(unit))
