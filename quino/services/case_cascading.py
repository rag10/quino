from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field

from quino.domain.blocks import BlockDiagram, Connection
from quino.domain.workspace import Analysis, Case, Workspace, create_default_pose
from quino.services.case_entities import entity_lookup
from quino.services.cascade_property_category import is_model_affecting
from quino.services.cascade_rules import should_cascade_value
from quino.services.run_invalidation import mark_runs_stale_for_case

_DOMAIN_LIST_ACCESSORS = {
    "bodies": lambda m: m.bodies,
    "joints": lambda m: m.joints,
    "sliders": lambda m: m.sliders,
    "drivers": lambda m: m.drivers,
    "loads": lambda m: m.loads,
    "sensors": lambda m: m.sensors,
    "springs": lambda m: m.springs,
}

# Topology / identity fields never flow through edit_property.
_SKIP_PROPS = {"id", "markers", "edge_order"}

ConnectionKey = tuple[str, str, str, str]


@dataclass(slots=True)
class OperationResult:
    modified_case_ids: set[str] = field(default_factory=set)
    stale_case_ids: set[str] = field(default_factory=set)
    applied_changes: list[str] = field(default_factory=list)

    def merge(self, other: "OperationResult") -> None:
        self.modified_case_ids.update(other.modified_case_ids)
        self.stale_case_ids.update(other.stale_case_ids)
        self.applied_changes.extend(other.applied_changes)


def _new_case_id() -> str:
    return f"case-{uuid.uuid4().hex[:8]}"


def _new_pose_id() -> str:
    return f"pose-{uuid.uuid4().hex[:8]}"


def _new_analysis_id() -> str:
    return f"analysis-{uuid.uuid4().hex[:8]}"


def _entity_id(entity: object) -> str:
    ent_id = getattr(entity, "id", None) or getattr(entity, "instance_id", None)
    if ent_id is None:
        raise ValueError(f"Entity {entity!r} has no stable id")
    return str(ent_id)


def _connection_key(conn: Connection) -> ConnectionKey:
    return (conn.src_instance, conn.src_port, conn.dst_instance, conn.dst_port)


class CascadingEngine:
    """Value-based cascading engine. No overlays."""

    def __init__(self, workspace: Workspace) -> None:
        self._ws = workspace

    # ------------------------------------------------------------- properties

    def edit_property(self, case_id: str, entity_id: str, prop: str, new_value: object) -> OperationResult:
        if prop in _SKIP_PROPS:
            raise ValueError(f"Property {prop!r} is structural and cannot be edited via cascade")
        result = OperationResult()
        case = self._ws.cases[case_id]
        entity = self._find_entity(case, entity_id)
        if entity is None:
            raise KeyError(f"Entity {entity_id!r} not found in case {case_id!r}")

        old_value = copy.deepcopy(self._get_property(entity, prop))
        self._set_property(entity, prop, copy.deepcopy(new_value))
        self._mark_modified(result, case_id, model_affecting=is_model_affecting(prop))
        result.applied_changes.append(f"{case_id}:{entity_id}/{prop}")

        for child_id in self._direct_children(case_id):
            self._propagate_edit(child_id, entity_id, prop, old_value, new_value, result)

        self._apply_staleness(result, f"model property changed: {entity_id}/{prop}")
        return result

    def _propagate_edit(self, case_id, entity_id, prop, old_value, new_value, result) -> None:
        case = self._ws.cases[case_id]
        entity = self._find_entity(case, entity_id)
        if entity is None:
            return
        child_value = self._get_property(entity, prop)
        if not should_cascade_value(old_parent=old_value, child=child_value):
            return
        self._set_property(entity, prop, copy.deepcopy(new_value))
        self._mark_modified(result, case_id, model_affecting=is_model_affecting(prop))
        result.applied_changes.append(f"{case_id}:{entity_id}/{prop}")
        for gc_id in self._direct_children(case_id):
            self._propagate_edit(gc_id, entity_id, prop, old_value, new_value, result)

    # ---------------------------------------------------------------- helpers

    def _find_entity(self, case: Case, entity_id: str) -> object | None:
        entry = entity_lookup(case).get(entity_id)
        return entry[0] if entry is not None else None

    def _direct_children(self, case_id: str) -> list[str]:
        return [c.id for c in self._ws.cases.values() if c.parent_case_id == case_id]

    def _all_descendants(self, case_id: str) -> set[str]:
        out: set[str] = set()
        frontier = list(self._direct_children(case_id))
        while frontier:
            current = frontier.pop()
            if current in out:
                continue
            out.add(current)
            frontier.extend(self._direct_children(current))
        return out

    def _get_property(self, entity: object, path: str) -> object:
        target: object = entity
        for part in path.split("."):
            target = target.get(part) if isinstance(target, dict) else getattr(target, part)
        return target

    def _set_property(self, entity: object, path: str, value: object) -> None:
        parts = path.split(".")
        if len(parts) == 1:
            setattr(entity, path, value)
            return
        target: object = entity
        for part in parts[:-1]:
            target = target.setdefault(part, {}) if isinstance(target, dict) else getattr(target, part)
        leaf = parts[-1]
        if isinstance(target, dict):
            target[leaf] = value
        else:
            setattr(target, leaf, value)

    def _mark_modified(self, result: OperationResult, case_id: str, *, model_affecting: bool) -> None:
        result.modified_case_ids.add(case_id)
        if model_affecting:
            result.stale_case_ids.add(case_id)

    def _apply_staleness(self, result: OperationResult, reason: str) -> None:
        for case_id in result.stale_case_ids:
            case = self._ws.cases.get(case_id)
            if case is not None:
                mark_runs_stale_for_case(case, reason=reason)
