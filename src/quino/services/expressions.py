from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass

from quino.domain.model import Parameter, ScalarProperty
from quino.domain.types import Dimension
from quino.services.units import Quantity, UnitService


@dataclass(slots=True)
class EvaluationResult:
    value: float
    unit: str
    dimension: Dimension


class ExpressionService:
    _number_unit_pattern = re.compile(r"(?P<num>(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?)\s+(?P<unit>[A-Za-z_][A-Za-z0-9_]*)")

    def __init__(self, unit_service: UnitService) -> None:
        self.unit_service = unit_service

    def evaluate_property(
        self,
        prop: ScalarProperty,
        parameters: list[Parameter],
        seen: set[str] | None = None,
        variables: dict[str, Quantity] | None = None,
    ) -> EvaluationResult:
        quantity = self.evaluate_expression(prop.expression, parameters, seen=seen, variables=variables)
        if not quantity.is_pure(prop.expected_dimension):
            raise ValueError(
                f"Expected {prop.expected_dimension.value} but got {quantity.dimension_text}"
            )
        value = self.unit_service.convert(quantity, prop.unit)
        return EvaluationResult(value=value, unit=prop.unit, dimension=prop.expected_dimension)

    def evaluate_expression(
        self,
        expression: str,
        parameters: list[Parameter],
        seen: set[str] | None = None,
        variables: dict[str, Quantity] | None = None,
    ) -> Quantity:
        parameter_map = {parameter.name: parameter for parameter in parameters}
        env = self._environment()
        if variables:
            env.update(variables)
        prepared = self._prepare(expression)
        node = ast.parse(prepared, mode="eval")
        return self._eval_node(node.body, env, parameter_map, seen or set(), variables or {})

    def _environment(self) -> dict[str, object]:
        env: dict[str, object] = {}
        for unit in self.unit_service._UNITS:
            env[unit] = self.unit_service.quantity(1.0, unit)
        env["pi"] = Quantity(math.pi, {})
        env["sin"] = self._sin
        env["cos"] = self._cos
        env["abs"] = self._abs
        return env

    def _prepare(self, expression: str) -> str:
        return self._number_unit_pattern.sub(
            lambda match: f"({match.group('num')}*{match.group('unit')})",
            expression,
        )

    def _eval_node(
        self,
        node: ast.AST,
        env: dict[str, object],
        parameter_map: dict[str, Parameter],
        seen: set[str],
        variables: dict[str, Quantity],
    ) -> Quantity:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Quantity(float(node.value), {})
        if isinstance(node, ast.Name):
            value = env.get(node.id)
            if isinstance(value, Quantity):
                return value
            parameter = parameter_map.get(node.id)
            if parameter is None:
                raise ValueError(f"Unknown symbol: {node.id}")
            if node.id in seen:
                raise ValueError(f"Cyclic parameter dependency detected at {node.id}")
            return self.evaluate_expression(
                parameter.expression,
                list(parameter_map.values()),
                seen | {node.id},
                variables=variables,
            )
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, env, parameter_map, seen, variables)
            right = self._eval_node(node.right, env, parameter_map, seen, variables)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if left.dimensions != right.dimensions:
                    raise ValueError("Incompatible dimensions for addition/subtraction")
                value = left.value_si + right.value_si if isinstance(node.op, ast.Add) else left.value_si - right.value_si
                return Quantity(value, dict(left.dimensions))
            if isinstance(node.op, ast.Mult):
                return Quantity(left.value_si * right.value_si, self._combine_dimensions(left.dimensions, right.dimensions, 1))
            if isinstance(node.op, ast.Div):
                if right.value_si == 0:
                    raise ValueError("Division by zero")
                return Quantity(left.value_si / right.value_si, self._combine_dimensions(left.dimensions, right.dimensions, -1))
            raise ValueError("Unsupported binary operator")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            value = self._eval_node(node.operand, env, parameter_map, seen, variables)
            return Quantity(-value.value_si, dict(value.dimensions))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            return self._eval_node(node.operand, env, parameter_map, seen, variables)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func = env.get(node.func.id)
            if func is None or not callable(func):
                raise ValueError(f"Unsupported function: {node.func.id}")
            args = [self._eval_node(arg, env, parameter_map, seen, variables) for arg in node.args]
            return func(*args)
        raise ValueError("Unsupported expression")

    def _sin(self, value: Quantity) -> Quantity:
        if not value.is_pure(Dimension.ANGLE):
            raise ValueError("sin expects an angle")
        return Quantity(math.sin(value.value_si), {})

    def _cos(self, value: Quantity) -> Quantity:
        if not value.is_pure(Dimension.ANGLE):
            raise ValueError("cos expects an angle")
        return Quantity(math.cos(value.value_si), {})

    def _abs(self, value: Quantity) -> Quantity:
        return Quantity(abs(value.value_si), dict(value.dimensions))

    def _combine_dimensions(
        self,
        left: dict[Dimension, int],
        right: dict[Dimension, int],
        sign: int,
    ) -> dict[Dimension, int]:
        combined = dict(left)
        for dimension, exponent in right.items():
            combined[dimension] = combined.get(dimension, 0) + sign * exponent
            if combined[dimension] == 0:
                del combined[dimension]
        return combined
