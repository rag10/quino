from __future__ import annotations

from quino.application._context import ServiceContext
from quino.domain.model import Parameter


class ParameterCommands:
    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    @property
    def _project(self):
        project = self._ctx.project_provider()
        if project is None:
            raise ValueError("No active project")
        return project

    def _validate_parameter_definition(
        self, expression: str, unit: str, parameter_id: str | None = None
    ) -> None:
        project = self._project
        parameter_map = [
            parameter
            for parameter in project.parameters
            if parameter.id != parameter_id
        ]
        quantity = self._ctx.expressions.evaluate_expression(expression, parameter_map)
        self._ctx.units.convert(quantity, unit)

    def _find_parameter(self, parameter_id: str) -> Parameter:
        project = self._project
        for parameter in project.parameters:
            if parameter.id == parameter_id:
                return parameter
        raise ValueError(f"Unknown parameter: {parameter_id}")

    def create(self, name: str, expression: str, unit: str, description: str = "") -> str:
        project = self._project
        self._ctx.validation.ensure_unique_name(project.parameters, name)
        self._validate_parameter_definition(expression, unit)
        self._ctx.snapshot()
        parameter = Parameter(
            id=self._ctx.ids.new("param"),
            name=name,
            expression=expression,
            unit=unit,
            description=description,
        )
        project.parameters.append(parameter)
        return parameter.id

    def update(
        self,
        parameter_id: str,
        *,
        expression: str | None = None,
        unit: str | None = None,
        description: str | None = None,
    ) -> None:
        project = self._project
        parameter = self._find_parameter(parameter_id)
        new_expression = expression if expression is not None else parameter.expression
        new_unit = unit if unit is not None else parameter.unit
        new_description = description if description is not None else parameter.description
        self._validate_parameter_definition(new_expression, new_unit, parameter_id=parameter_id)
        self._ctx.snapshot()
        parameter.expression = new_expression
        parameter.unit = new_unit
        parameter.description = new_description
        self._ctx.sync_all_special_com_markers()

    def update_definition(
        self,
        parameter_id: str,
        name: str,
        expression: str,
        unit: str,
        description: str = "",
    ) -> None:
        project = self._project
        parameter = self._ctx.find_entity(parameter_id)
        if not isinstance(parameter, Parameter):
            raise ValueError("update_parameter_definition requires a Parameter")
        if parameter.name != name:
            self._ctx.validation.ensure_unique_name(
                [p for p in project.parameters if p.id != parameter_id], name
            )
        self._validate_parameter_definition(expression, unit)
        changed = (
            parameter.name != name
            or parameter.expression != expression
            or parameter.unit != unit
            or parameter.description != description
        )
        if not changed:
            return
        self._ctx.snapshot()
        parameter.name = name
        parameter.expression = expression
        parameter.unit = unit
        parameter.description = description
        self._ctx.sync_all_special_com_markers()

    def delete(self, parameter_id: str) -> None:
        project = self._project
        self._ctx.snapshot()
        project.parameters = [parameter for parameter in project.parameters if parameter.id != parameter_id]
