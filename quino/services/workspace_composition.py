from __future__ import annotations

import copy
import hashlib
import json
from typing import Callable

from quino.domain.model import (
    Body,
    Driver,
    Joint,
    Load,
    Parameter,
    Project,
    ScalarProperty,
    Sensor,
    Slider,
    Spring,
)
from quino.domain.workspace import Case, ScalarValue, Study, StudyOverlay
from quino.services.workspace_catalog import build_parameter_catalog


# ------------------------------------------------------------------
# Adapter for BlockDiagram.instances (dict) to expose as list-like
# ------------------------------------------------------------------

class _DictAsListView:
    """Adapter to expose dict[id, entity] as a list-like for the composer."""

    def __init__(self, d: dict):
        self._d = d

    def append(self, item):
        self._d[item.instance_id] = item

    def __iter__(self):
        return iter(self._d.values())

    def __contains__(self, item):
        return item in self._d.values()


def _block_instances_view(project: Project) -> _DictAsListView:
    if project.model.control_graph is None:
        return _DictAsListView({})
    return _DictAsListView(project.model.control_graph.instances)


def _block_connections_view(project: Project) -> list:
    if project.model.control_graph is None:
        return []
    return project.model.control_graph.connections


def compose_project(base: Project, study: Study | None = None, case: Case | None = None) -> Project:
    """Return a deep-copied Project with structural deltas and parameter overrides applied.

    Override priority (lowest to highest):
    1. Project base
    2. Case structural deltas (remove / add / reference overrides)
    3. Case.invariant_values
    4. Study.variable_values
    5. StudyOverlay.parameter_overrides
    """
    composed = copy.deepcopy(base)
    _validate_workspace_override_scope(base, study, case)

    if case is not None:
        for inherited_case in _resolve_case_chain(base, case):
            _apply_structural_deltas(composed, inherited_case)
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
# Structural delta application
# ------------------------------------------------------------------

_ENTITY_DOMAIN_LISTS = {
    "bodies": lambda p: p.model.bodies,
    "joints": lambda p: p.model.joints,
    "sliders": lambda p: p.model.sliders,
    "drivers": lambda p: p.model.drivers,
    "loads": lambda p: p.model.loads,
    "sensors": lambda p: p.model.sensors,
    "springs": lambda p: p.model.springs,
    "blocks": _block_instances_view,
    "connections": _block_connections_view,
}


def _apply_structural_deltas(project: Project, case: Case) -> None:
    """Apply structural deltas (added/removed entities and reference overrides) from *case* to *project*."""
    # 1. Remove entities (and their dependents)
    for entity_id in case.removed_entity_ids:
        _remove_entity_from_project(project, entity_id)

    # 2. Add new entities
    from quino.serialization.json_io import JsonMapper

    mapper = JsonMapper()
    deserializers = {
        "bodies": mapper._body_from_dict,
        "joints": mapper._joint_from_dict,
        "sliders": mapper._slider_from_dict,
        "drivers": mapper._driver_from_dict,
        "loads": mapper._load_from_dict,
        "sensors": mapper._sensor_from_dict,
        "springs": mapper._spring_from_dict,
        "blocks": mapper._block_instance_from_dict,
        "connections": mapper._block_connection_from_dict,
    }
    for domain, entities_data in case.added_entities.items():
        if not entities_data:
            continue
        target_list = _ENTITY_DOMAIN_LISTS.get(domain)
        if target_list is None:
            continue
        deserializer = deserializers.get(domain)
        if deserializer is None:
            continue
        # Ensure control_graph exists before appending blocks or connections
        if domain in ("blocks", "connections") and project.model.control_graph is None:
            from quino.domain.blocks import BlockDiagram
            project.model.control_graph = BlockDiagram()
        for entity_data in entities_data:
            entity = deserializer(entity_data)
            target_list(project).append(entity)

    # 3. Apply reference overrides
    for entity_id, overrides in case.reference_overrides.items():
        entity = _find_entity_in_project(project, entity_id)
        if entity is None:
            continue
        for prop, value in overrides.items():
            if hasattr(entity, prop):
                setattr(entity, prop, value)


def _find_entity_in_project(project: Project, entity_id: str) -> Any | None:
    """Find any model entity by id across all domains."""
    for domain, getter in _ENTITY_DOMAIN_LISTS.items():
        for item in getter(project):
            if getattr(item, "id", None) == entity_id:
                return item
    # Markers live inside bodies
    for body in project.model.bodies:
        for marker in body.markers:
            if marker.id == entity_id:
                return marker
    # BlockInstance uses instance_id rather than id
    if project.model.control_graph is not None:
        inst = project.model.control_graph.instances.get(entity_id)
        if inst is not None:
            return inst
    return None


def _remove_entity_from_project(project: Project, entity_id: str) -> None:
    """Remove an entity and all its dependents from the project."""
    # Find what kind of entity this is
    entity = _find_entity_in_project(project, entity_id)
    if entity is None:
        return

    if isinstance(entity, Body):
        marker_ids = {marker.id for marker in entity.markers}
        # Remove joints connected to these markers
        removed_joint_ids = {
            joint.id
            for joint in project.model.joints
            if joint.endpoint_a.marker_id in marker_ids or joint.endpoint_b.marker_id in marker_ids
        }
        # Also joints connected to this body via endpoint body_id
        removed_joint_ids.update({
            joint.id
            for joint in project.model.joints
            if joint.endpoint_a.body_id == entity_id or joint.endpoint_b.body_id == entity_id
        })
        project.model.joints = [j for j in project.model.joints if j.id not in removed_joint_ids]
        # Remove drivers of removed joints
        project.model.drivers = [d for d in project.model.drivers if d.target_joint_id not in removed_joint_ids]
        # Remove loads on these markers
        project.model.loads = [load for load in project.model.loads if load.target_marker_id not in marker_ids]
        # Remove sensors referencing these markers
        project.model.sensors = [s for s in project.model.sensors if not any(m in marker_ids for m in s.marker_ids)]
        # Remove springs connected to these markers
        project.model.springs = [
            sp for sp in project.model.springs
            if not (
                (sp.endpoint_a.marker_id in marker_ids and sp.endpoint_a.kind.value == "marker")
                or (sp.endpoint_b.marker_id in marker_ids and sp.endpoint_b.kind.value == "marker")
            )
        ]
        # Remove the body itself
        project.model.bodies = [b for b in project.model.bodies if b.id != entity_id]
        return

    if isinstance(entity, Slider):
        removed_joint_ids = {
            joint.id
            for joint in project.model.joints
            if joint.endpoint_a.slider_id == entity_id or joint.endpoint_b.slider_id == entity_id
        }
        project.model.joints = [j for j in project.model.joints if j.id not in removed_joint_ids]
        project.model.drivers = [d for d in project.model.drivers if d.target_joint_id not in removed_joint_ids]
        project.model.sliders = [s for s in project.model.sliders if s.id != entity_id]
        return

    if isinstance(entity, Joint):
        project.model.joints = [j for j in project.model.joints if j.id != entity_id]
        project.model.drivers = [d for d in project.model.drivers if d.target_joint_id != entity_id]
        return

    if isinstance(entity, Driver):
        project.model.drivers = [d for d in project.model.drivers if d.id != entity_id]
        return

    if isinstance(entity, Marker):
        # Find the body that owns this marker
        body = next((b for b in project.model.bodies if any(m.id == entity_id for m in b.markers)), None)
        if body is not None:
            # Remove joints connected to this marker
            removed_joint_ids = {
                joint.id
                for joint in project.model.joints
                if joint.endpoint_a.marker_id == entity_id or joint.endpoint_b.marker_id == entity_id
            }
            project.model.joints = [j for j in project.model.joints if j.id not in removed_joint_ids]
            project.model.drivers = [d for d in project.model.drivers if d.target_joint_id not in removed_joint_ids]
            project.model.loads = [load for load in project.model.loads if load.target_marker_id != entity_id]
            project.model.sensors = [s for s in project.model.sensors if entity_id not in s.marker_ids]
            project.model.springs = [
                sp for sp in project.model.springs
                if not (
                    (sp.endpoint_a.marker_id == entity_id and sp.endpoint_a.kind.value == "marker")
                    or (sp.endpoint_b.marker_id == entity_id and sp.endpoint_b.kind.value == "marker")
                )
            ]
            # Remove marker from body
            body.markers = [m for m in body.markers if m.id != entity_id]
            body.edge_order = [mid for mid in body.edge_order if mid != entity_id]
        return

    # Generic removal for loads, sensors, springs
    if isinstance(entity, Load):
        project.model.loads = [load for load in project.model.loads if load.id != entity_id]
    elif isinstance(entity, Sensor):
        project.model.sensors = [s for s in project.model.sensors if s.id != entity_id]
    elif isinstance(entity, Spring):
        project.model.springs = [sp for sp in project.model.springs if sp.id != entity_id]

    # BlockInstance removal (Connections have no id and are not removed by entity_id)
    from quino.domain.blocks import BlockInstance
    if isinstance(entity, BlockInstance):
        cg = project.model.control_graph
        if cg is not None:
            cg.instances.pop(entity.instance_id, None)


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
        # Property is unset; create a new ScalarProperty with the appropriate
        # dimension inferred from the property name.
        from quino.domain.types import Dimension
        dim_map: dict[str, Dimension] = {
            "mass": Dimension.MASS,
            "x": Dimension.LENGTH,
            "y": Dimension.LENGTH,
            "origin_x": Dimension.LENGTH,
            "origin_y": Dimension.LENGTH,
            "travel_min": Dimension.LENGTH,
            "travel_max": Dimension.LENGTH,
            "angle": Dimension.ANGLE,
            "angle_limit_positive": Dimension.ANGLE,
            "angle_limit_negative": Dimension.ANGLE,
            "fx": Dimension.FORCE,
            "fy": Dimension.FORCE,
            "law": Dimension.ANGLE,  # overridden per-entity below
        }
        expected = dim_map.get(prop)
        if prop == "law":
            if isinstance(obj, Driver):
                from quino.domain.types import DriverType
                expected = Dimension.ANGLE if obj.type is DriverType.ROTATION else Dimension.LENGTH
            else:
                expected = Dimension.FORCE
        if expected is None:
            raise ValueError(f"Property {prop!r} on {obj.__class__.__name__} is None and has no known dimension")
        new_expr = _scalar_to_expression(scalar)
        new_unit = scalar.unit if scalar.unit else _default_unit_for_dimension(expected)
        setattr(
            obj,
            prop,
            ScalarProperty(
                expression=new_expr,
                unit=new_unit,
                expected_dimension=expected,
            ),
        )
        return
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


def _default_unit_for_dimension(dimension) -> str:
    from quino.domain.types import Dimension
    return {
        Dimension.LENGTH: "mm",
        Dimension.ANGLE: "deg",
        Dimension.MASS: "kg",
        Dimension.FORCE: "N",
        Dimension.TORQUE: "N*mm",
        Dimension.TIME: "s",
    }.get(dimension, "")


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
