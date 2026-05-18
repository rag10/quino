from __future__ import annotations

from quino.application._context import ServiceContext
from quino.domain.inputs import PropertyValueInput
from quino.domain.model import (
    Load,
    Metadata,
    ScalarProperty,
    Sensor,
    Spring,
    SpringEndpoint,
)
from quino.domain.types import Dimension, SensorType, SpringType


class ForceCommands:
    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    @property
    def _project(self):
        project = self._ctx.project_provider()
        if project is None:
            raise ValueError("No project loaded")
        return project

    def _scalar(self, expression: str, unit: str, dimension: Dimension) -> ScalarProperty:
        return ScalarProperty(expression=expression, unit=unit, expected_dimension=dimension)

    def _require_spring(self, spring_id: str) -> Spring:
        project = self._project
        spring = next((sp for sp in project.model.springs if sp.id == spring_id), None)
        if spring is None:
            raise ValueError(f"Spring {spring_id} not found")
        return spring

    # ------------------------------------------------------------------ sensors

    def create_sensor(self, name: str, sensor_type: str, marker_ids: list[str]) -> str:
        project = self._project
        sensor_id = self._ctx.ids.new("sensor")
        sensor = Sensor(
            id=sensor_id,
            name=name,
            type=SensorType(sensor_type),
            marker_ids=marker_ids,
            metadata=Metadata(),
        )
        self._ctx.snapshot()
        project.model.sensors.append(sensor)
        return sensor_id

    def delete_sensor(self, sensor_id: str) -> None:
        project = self._project
        self._ctx.snapshot()
        project.model.sensors = [s for s in project.model.sensors if s.id != sensor_id]

    def rename_sensor(self, sensor_id: str, name: str) -> None:
        project = self._project
        sensor = next((s for s in project.model.sensors if s.id == sensor_id), None)
        if sensor is not None:
            self._ctx.snapshot()
            sensor.name = name

    # ------------------------------------------------------------------ loads

    def create_load(self, name: str, marker_id: str, fx_expression: str, fy_expression: str) -> str:
        project = self._project
        self._ctx.validation.ensure_unique_name(project.model.loads, name)
        load_id = self._ctx.ids.new("load")
        fx = ScalarProperty(expression=fx_expression, unit="N", expected_dimension=Dimension.FORCE)
        fy = ScalarProperty(expression=fy_expression, unit="N", expected_dimension=Dimension.FORCE)
        variables = self._ctx.load_expression_variables(project, time_value=0.0)
        self._ctx.expressions.evaluate_property(fx, project.parameters, variables=variables)
        self._ctx.expressions.evaluate_property(fy, project.parameters, variables=variables)
        load = Load(
            id=load_id,
            name=name,
            target_marker_id=marker_id,
            fx=fx,
            fy=fy,
            metadata=Metadata(),
        )
        self._ctx.snapshot()
        project.model.loads.append(load)
        return load_id

    def delete_load(self, load_id: str) -> None:
        project = self._project
        self._ctx.snapshot()
        project.model.loads = [ld for ld in project.model.loads if ld.id != load_id]

    def rename_load(self, load_id: str, name: str) -> None:
        project = self._project
        load = next((ld for ld in project.model.loads if ld.id == load_id), None)
        if load is not None:
            self._ctx.snapshot()
            load.name = name

    def update_load_property(self, load_id: str, property_path: str, expression: str) -> None:
        project = self._project
        load = next((ld for ld in project.model.loads if ld.id == load_id), None)
        if load is None:
            raise ValueError(f"Load {load_id} not found")
        scalar = self._ctx.build_validated_scalar_property(load, property_path, expression)
        self._ctx.expressions.evaluate_property(
            scalar,
            project.parameters,
            variables=self._ctx.load_expression_variables(project, time_value=0.0),
        )
        self._ctx.snapshot()
        self._ctx.assign_scalar_property(load, property_path, scalar)

    # ------------------------------------------------------------------ springs

    def create_spring(
        self,
        name: str,
        spring_type: str,
        endpoint_a: SpringEndpoint,
        endpoint_b: SpringEndpoint,
    ) -> str:
        project = self._project
        spring_id = self._ctx.ids.new("spring")
        is_rotational = spring_type in ("rotational_spring", "rotational_actuator")
        rest_value = ScalarProperty(
            expression="0 deg" if is_rotational else "0 mm",
            unit="deg" if is_rotational else "mm",
            expected_dimension=Dimension.ANGLE if is_rotational else Dimension.LENGTH,
        )
        law = None
        if spring_type in ("linear_actuator", "rotational_actuator"):
            law = ScalarProperty(
                expression="0 N*mm" if is_rotational else "0 N",
                unit="N*mm" if is_rotational else "N",
                expected_dimension=Dimension.TORQUE if is_rotational else Dimension.FORCE,
            )
        spring = Spring(
            id=spring_id,
            name=name,
            spring_type=SpringType(spring_type),
            endpoint_a=endpoint_a,
            endpoint_b=endpoint_b,
            rest_value=rest_value,
            law=law,
            metadata=Metadata({"stiffness": 0.0, "damping": 0.0}),
        )
        self._ctx.snapshot()
        project.model.springs.append(spring)
        return spring_id

    def delete_spring(self, spring_id: str) -> None:
        project = self._project
        self._ctx.snapshot()
        project.model.springs = [sp for sp in project.model.springs if sp.id != spring_id]

    def rename_spring(self, spring_id: str, name: str) -> None:
        spring = self._require_spring(spring_id)
        self._ctx.snapshot()
        spring.name = name

    def get_spring(self, spring_id: str) -> Spring:
        return self._require_spring(spring_id)

    def spring_stiffness(self, spring: Spring) -> float:
        try:
            return float(spring.metadata.values.get("stiffness", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def spring_damping(self, spring: Spring) -> float:
        try:
            return float(spring.metadata.values.get("damping", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def update_spring_property(self, spring_id: str, property_path: str, value: PropertyValueInput) -> None:
        spring = self._require_spring(spring_id)
        project = self._project
        if value.kind != "expression" or not isinstance(value.value, str):
            raise ValueError(f"{property_path} requires an expression value")
        if property_path in ("stiffness", "damping"):
            try:
                numeric = float(value.value.strip().replace(",", "."))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{property_path} must be a plain number") from exc
            self._ctx.snapshot()
            spring.metadata.values[property_path] = numeric
            return
        if property_path == "rest_value":
            is_rotational = spring.spring_type in (SpringType.ROTATIONAL_SPRING, SpringType.ROTATIONAL_ACTUATOR)
            scalar = self._scalar(
                value.value,
                "deg" if is_rotational else "mm",
                Dimension.ANGLE if is_rotational else Dimension.LENGTH,
            )
            self._ctx.expressions.evaluate_property(scalar, project.parameters)
            self._ctx.snapshot()
            spring.rest_value = scalar
            return
        if property_path == "law":
            is_rotational = spring.spring_type in (SpringType.ROTATIONAL_ACTUATOR,)
            scalar = self._scalar(
                value.value,
                "N*mm" if is_rotational else "N",
                Dimension.TORQUE if is_rotational else Dimension.FORCE,
            )
            self._ctx.expressions.evaluate_property(
                scalar,
                project.parameters,
                variables={"t": self._ctx.units.quantity(0.0, "s")},
            )
            self._ctx.snapshot()
            spring.law = scalar
            return
        raise ValueError(f"Unknown spring property: {property_path}")
