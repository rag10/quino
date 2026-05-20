from __future__ import annotations

import copy
from typing import Callable

from quino.domain.model import (
    Body,
    Driver,
    Load,
    Parameter,
    Project,
    ScalarProperty,
    Spring,
)
from quino.domain.workspace import Case, ScalarValue, Study, StudyOverlay


def compose_project(base: Project, study: Study, case: Case | None = None) -> Project:
    """Return a deep-copied Project with parameter overrides applied.

    Override priority (lowest to highest):
    1. Project base
    2. Case.invariant_values
    3. Study.variable_values
    4. StudyOverlay.parameter_overrides
    """
    composed = copy.deepcopy(base)

    if case is not None:
        for path, scalar in case.invariant_values.items():
            _apply_parameter_override(composed, path, scalar)

    for path, scalar in study.variable_values.items():
        _apply_parameter_override(composed, path, scalar)

    if study.overlay is not None:
        for path, scalar in study.overlay.parameter_overrides.items():
            _apply_parameter_override(composed, path, scalar)

    return composed


# ------------------------------------------------------------------
# Parameter path resolvers
# ------------------------------------------------------------------

def _apply_parameter_override(project: Project, path: str, scalar: ScalarValue) -> None:
    """Apply a scalar override to a project property identified by *path*.

    Path format: ``<domain>/<id>/<property>`` or
    ``block_diagram/instances/<id>/parameters/<key>``.
    """
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid parameter path: {path!r}")

    domain = parts[0]
    resolver = _PARAMETER_RESOLVERS.get(domain)
    if resolver is None:
        raise ValueError(f"Unknown parameter domain {domain!r} in path {path!r}")

    resolver(project, parts, scalar)


def _resolve_project_parameter(project: Project, parts: list[str], scalar: ScalarValue) -> None:
    if len(parts) != 2:
        raise ValueError(f"Invalid parameter path: {'/'.join(parts)!r}")
    param_id = parts[1]
    param = _find_by_id(project.parameters, param_id)
    if param is None:
        raise ValueError(f"Parameter {param_id!r} not found")
    param.expression = _scalar_to_expression(scalar)
    if scalar.unit:
        param.unit = scalar.unit


def _resolve_body_property(project: Project, parts: list[str], scalar: ScalarValue) -> None:
    if len(parts) != 3:
        raise ValueError(f"Invalid body path: {'/'.join(parts)!r}")
    body_id, prop = parts[1], parts[2]
    body = _find_by_id(project.model.bodies, body_id)
    if body is None:
        raise ValueError(f"Body {body_id!r} not found")
    _set_scalar_property(body, prop, scalar)


def _resolve_load_property(project: Project, parts: list[str], scalar: ScalarValue) -> None:
    if len(parts) != 3:
        raise ValueError(f"Invalid load path: {'/'.join(parts)!r}")
    load_id, prop = parts[1], parts[2]
    load = _find_by_id(project.model.loads, load_id)
    if load is None:
        raise ValueError(f"Load {load_id!r} not found")
    _set_scalar_property(load, prop, scalar)


def _resolve_spring_property(project: Project, parts: list[str], scalar: ScalarValue) -> None:
    if len(parts) != 3:
        raise ValueError(f"Invalid spring path: {'/'.join(parts)!r}")
    spring_id, prop = parts[1], parts[2]
    spring = _find_by_id(project.model.springs, spring_id)
    if spring is None:
        raise ValueError(f"Spring {spring_id!r} not found")
    _set_scalar_property(spring, prop, scalar)


def _resolve_driver_property(project: Project, parts: list[str], scalar: ScalarValue) -> None:
    if len(parts) != 3:
        raise ValueError(f"Invalid driver path: {'/'.join(parts)!r}")
    driver_id, prop = parts[1], parts[2]
    driver = _find_by_id(project.model.drivers, driver_id)
    if driver is None:
        raise ValueError(f"Driver {driver_id!r} not found")
    _set_scalar_property(driver, prop, scalar)


def _resolve_block_parameter(project: Project, parts: list[str], scalar: ScalarValue) -> None:
    if len(parts) != 5 or parts[1] != "instances" or parts[3] != "parameters":
        raise ValueError(f"Invalid block diagram path: {'/'.join(parts)!r}")
    instance_id, key = parts[2], parts[4]
    if project.block_diagram is None:
        raise ValueError("Project has no block diagram")
    instance = project.block_diagram.instances.get(instance_id)
    if instance is None:
        raise ValueError(f"Block instance {instance_id!r} not found")
    instance.parameters[key] = scalar.value


_PARAMETER_RESOLVERS: dict[str, Callable[[Project, list[str], ScalarValue], None]] = {
    "parameters": _resolve_project_parameter,
    "bodies": _resolve_body_property,
    "loads": _resolve_load_property,
    "springs": _resolve_spring_property,
    "drivers": _resolve_driver_property,
    "block_diagram": _resolve_block_parameter,
}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _find_by_id(items: list, item_id: str):
    for item in items:
        if getattr(item, "id", None) == item_id:
            return item
    return None


def _scalar_to_expression(scalar: ScalarValue) -> str:
    if scalar.unit:
        return f"{scalar.value:g} {scalar.unit}"
    return f"{scalar.value:g}"


def _set_scalar_property(obj, prop: str, scalar: ScalarValue) -> None:
    """Set a ScalarProperty field on *obj* identified by *prop*."""
    current = getattr(obj, prop, None)
    if current is None:
        raise ValueError(f"Property {prop!r} on {obj.__class__.__name__} is None")
    if not isinstance(current, ScalarProperty):
        raise ValueError(f"Property {prop!r} on {obj.__class__.__name__} is not a scalar")
    new_expr = _scalar_to_expression(scalar)
    new_unit = scalar.unit if scalar.unit else current.unit
    # Create a new ScalarProperty to avoid mutating the original in case of
    # shared references (though deepcopy should have handled that).
    setattr(
        obj,
        prop,
        ScalarProperty(
            expression=new_expr,
            unit=new_unit,
            expected_dimension=current.expected_dimension,
        ),
    )
