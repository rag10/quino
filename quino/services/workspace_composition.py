from __future__ import annotations

import copy
import hashlib
import json
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
from quino.services.workspace_catalog import build_parameter_catalog


def compose_project(base: Project, study: Study | None = None, case: Case | None = None) -> Project:
    """Return a deep-copied Project with parameter overrides applied.

    Override priority (lowest to highest):
    1. Project base
    2. Case.invariant_values
    3. Study.variable_values
    4. StudyOverlay.parameter_overrides
    """
    composed = copy.deepcopy(base)
    _validate_workspace_override_scope(base, study, case)

    if case is not None:
        for inherited_case in _resolve_case_chain(base, case):
            for path, scalar in inherited_case.invariant_values.items():
                _apply_parameter_override(composed, path, scalar)

    if study is not None:
        for path, scalar in study.variable_values.items():
            _apply_parameter_override(composed, path, scalar)

        if study.overlay is not None:
            for path, scalar in study.overlay.parameter_overrides.items():
                _apply_parameter_override(composed, path, scalar)

    return composed


def _validate_workspace_override_scope(base: Project, study: Study | None, case: Case | None) -> None:
    workspace = base.workspace
    if workspace is None:
        return

    workspace.parameter_catalog = build_parameter_catalog(base)
    catalog = workspace.parameter_catalog

    baseline_invariant_keys: set[str] = set()
    baseline_id = case.baseline_id if case is not None else workspace.active_baseline_id
    if baseline_id is not None:
        baseline = next((b for b in workspace.baselines if b.id == baseline_id), None)
        if baseline is not None:
            baseline_invariant_keys = set(baseline.invariant_parameter_keys)

    if case is not None:
        resolved_case_paths: dict[str, ScalarValue] = {}
        for inherited_case in _resolve_case_chain(base, case):
            resolved_case_paths.update(inherited_case.invariant_values)
        bad_case_paths = [
            path for path in resolved_case_paths
            if not _is_invariant_path(path, catalog, baseline_invariant_keys)
        ]
        if bad_case_paths:
            raise ValueError(
                "Case modifies non-invariant parameters: " + ", ".join(sorted(bad_case_paths))
            )

    if study is not None:
        bad_study_paths = [
            path for path in study.variable_values
            if not _is_variable_path(path, catalog, baseline_invariant_keys)
        ]
        if bad_study_paths:
            raise ValueError(
                "Study modifies non-variable parameters: " + ", ".join(sorted(bad_study_paths))
            )


def _is_invariant_path(
    path: str,
    catalog: dict[str, object],
    baseline_invariant_keys: set[str],
) -> bool:
    if path in baseline_invariant_keys:
        return True
    descriptor = catalog.get(path)
    if descriptor is None:
        return True
    return getattr(descriptor, "tag", "invariant") == "invariant"


def _is_variable_path(
    path: str,
    catalog: dict[str, object],
    baseline_invariant_keys: set[str],
) -> bool:
    if path in baseline_invariant_keys:
        return False
    descriptor = catalog.get(path)
    if descriptor is None:
        return True
    return getattr(descriptor, "tag", "invariant") == "variable"


# ------------------------------------------------------------------
# Parameter path resolvers
# ------------------------------------------------------------------

def _apply_parameter_override(project: Project, path: str, scalar: ScalarValue) -> None:
    """Apply a scalar override to a project property identified by *path*.

    Path format: ``<domain>/<id>/<property>`` or
    ``model/control_graph/instances/<id>/parameters/<key>``.
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
    if project.model.control_graph is None:
        raise ValueError("Project has no block diagram")
    instance = project.model.control_graph.instances.get(instance_id)
    if instance is None:
        raise ValueError(f"Block instance {instance_id!r} not found")
    instance.parameters[key] = scalar.value


def _resolve_model_control_graph_parameter(project: Project, parts: list[str], scalar: ScalarValue) -> None:
    if len(parts) < 2:
        raise ValueError(f"Invalid model path: {'/'.join(parts)!r}")
    if parts[1] != "control_graph":
        raise ValueError(f"Unknown model path: {'/'.join(parts)!r}")
    _resolve_block_parameter(project, parts[1:], scalar)


_PARAMETER_RESOLVERS: dict[str, Callable[[Project, list[str], ScalarValue], None]] = {
    "parameters": _resolve_project_parameter,
    "bodies": _resolve_body_property,
    "loads": _resolve_load_property,
    "springs": _resolve_spring_property,
    "drivers": _resolve_driver_property,
    "block_diagram": _resolve_block_parameter,
    "model": _resolve_model_control_graph_parameter,
}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _find_by_id(items: list, item_id: str):
    for item in items:
        if getattr(item, "id", None) == item_id:
            return item
    return None


def _resolve_case_chain(project: Project, case: Case) -> list[Case]:
    workspace = project.workspace
    if workspace is None or case.parent_case_id is None:
        return [case]

    by_id = {item.id: item for item in workspace.cases}
    chain: list[Case] = []
    current: Case | None = case
    seen: set[str] = set()
    while current is not None:
        if current.id in seen:
            raise ValueError(f"Case inheritance cycle detected at {current.id!r}")
        seen.add(current.id)
        chain.append(current)
        current = by_id.get(current.parent_case_id) if current.parent_case_id is not None else None
    chain.reverse()
    return chain


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


def compose_project_hash(project: Project) -> str:
    """Return a stable hash of the composed project payload.

    Workspace runtime state and result caches are intentionally excluded because
    they are not part of the executable model definition.
    """
    from quino.serialization.json_io import JsonMapper

    payload = JsonMapper().dump(project)
    payload.pop("workspace", None)
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
