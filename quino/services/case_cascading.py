from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

from quino.domain.blocks import BlockDiagram, BlockInstance, Connection
from quino.domain.types import MarkerType
from quino.domain.workspace import (
    Analysis,
    Case,
    CaseOverlay,
    EntityOverlay,
    Workspace,
    create_default_pose,
)
from quino.services.cascade_property_category import is_model_affecting
from quino.services.cascade_property_registry import cascadable_properties
from quino.services.case_overlay_validator import _entity_lookup, rebuild_overlay
from quino.services.run_invalidation import mark_runs_stale_for_case


_DOMAIN_LIST_ACCESSORS = {
    "bodies":   lambda m: m.bodies,
    "joints":   lambda m: m.joints,
    "sliders":  lambda m: m.sliders,
    "drivers":  lambda m: m.drivers,
    "loads":    lambda m: m.loads,
    "sensors":  lambda m: m.sensors,
    "springs":  lambda m: m.springs,
}

ConnectionKey = tuple[str, str, str, str]


@dataclass(slots=True)
class CascadeConflict:
    case_id: str
    path: str
    reason: str
    parent_value: object | None = None
    child_value: object | None = None


@dataclass(slots=True)
class OperationResult:
    modified_case_ids: set[str] = field(default_factory=set)
    stale_case_ids: set[str] = field(default_factory=set)
    skipped_case_ids: set[str] = field(default_factory=set)
    conflicts: list[CascadeConflict] = field(default_factory=list)
    applied_changes: list[str] = field(default_factory=list)

    def merge(self, other: "OperationResult") -> None:
        self.modified_case_ids.update(other.modified_case_ids)
        self.stale_case_ids.update(other.stale_case_ids)
        self.skipped_case_ids.update(other.skipped_case_ids)
        self.conflicts.extend(other.conflicts)
        self.applied_changes.extend(other.applied_changes)


class CascadeCancelled(RuntimeError):
    """Raised when a caller requests cancellation for a conflicting cascade."""


def _new_case_id() -> str:
    return f"case-{uuid.uuid4().hex[:8]}"


def _new_pose_id() -> str:
    return f"pose-{uuid.uuid4().hex[:8]}"


def _new_analysis_id() -> str:
    return f"analysis-{uuid.uuid4().hex[:8]}"


def _entity_id(entity: object) -> str:
    ent_id = getattr(entity, "id", None)
    if ent_id is None:
        ent_id = getattr(entity, "instance_id", None)
    if ent_id is None:
        raise ValueError(f"Entity {entity!r} has no stable id")
    return str(ent_id)


def _connection_key(conn: Connection) -> ConnectionKey:
    return (conn.src_instance, conn.src_port, conn.dst_instance, conn.dst_port)


def _is_model_affecting_property(prop: str) -> bool:
    """Thin wrapper kept for callers within this module."""
    return is_model_affecting(prop)


class CascadingEngine:
    """Mutation boundary for case-as-model workspaces.

    The engine owns model-level inheritance bookkeeping. Poses, analyses and
    runs are intentionally local to each case and never appear in CaseOverlay.
    """

    def __init__(self, workspace: Workspace) -> None:
        self._ws = workspace

    # ------------------------------------------------------------------ cases

    def fork_case(self, parent_case_id: str, name: str) -> str:
        if parent_case_id not in self._ws.cases:
            raise KeyError(f"Parent case {parent_case_id!r} not found")
        parent = self._ws.cases[parent_case_id]
        new_id = _new_case_id()
        child = Case(
            id=new_id,
            name=name,
            parent_case_id=parent_case_id,
            model=copy.deepcopy(parent.model),
            poses=[create_default_pose(_new_pose_id())],
            analyses=[],
            runs=[],
            sensor_outputs={},
            reaction_outputs={},
            tolerances=copy.deepcopy(parent.tolerances),
            metrics=copy.deepcopy(parent.metrics),
            overlay=self._build_fork_overlay(parent),
        )
        self._ws.cases[new_id] = child
        return new_id

    def duplicate_case(self, source_case_id: str, name: str | None = None) -> str:
        if source_case_id not in self._ws.cases:
            raise KeyError(f"Case {source_case_id!r} not found")
        source = self._ws.cases[source_case_id]
        new_id = _new_case_id()

        pose_id_map: dict[str, str] = {}
        cloned_poses = copy.deepcopy(source.poses)
        for pose in cloned_poses:
            old_id = pose.id
            pose.id = _new_pose_id()
            pose_id_map[old_id] = pose.id

        cloned_analyses: list[Analysis] = copy.deepcopy(source.analyses)
        for analysis in cloned_analyses:
            analysis.id = _new_analysis_id()
            if analysis.pose_id is not None:
                analysis.pose_id = pose_id_map.get(analysis.pose_id)

        duplicate = Case(
            id=new_id,
            name=name or f"{source.name} copy",
            description=source.description,
            parent_case_id=source.parent_case_id,
            model=copy.deepcopy(source.model),
            poses=cloned_poses,
            analyses=cloned_analyses,
            runs=[],
            sensor_outputs={},
            reaction_outputs={},
            overlay=copy.deepcopy(source.overlay),
            tolerances=copy.deepcopy(source.tolerances),
            metrics=copy.deepcopy(source.metrics),
            metadata=copy.deepcopy(source.metadata),
        )
        duplicate.metadata.pop("divergence_warnings", None)
        self._ws.cases[new_id] = duplicate
        if duplicate.parent_case_id is None and new_id not in self._ws.root_case_ids:
            self._ws.root_case_ids.append(new_id)
        return new_id

    def _build_fork_overlay(self, parent: Case) -> CaseOverlay:
        overlay = CaseOverlay()
        for ent_id, (ent, _cls) in _entity_lookup(parent).items():
            overlay.entities[ent_id] = EntityOverlay(
                origin="inherited",
                linked_properties=self._all_cascadable_props_for_entity(ent),
            )
        if parent.model.control_graph is not None:
            for conn in parent.model.control_graph.connections:
                overlay.inherited_connections.add(_connection_key(conn))
        return overlay

    # ------------------------------------------------------------- properties

    def edit_property(
        self,
        case_id: str,
        entity_id: str,
        prop: str,
        new_value: object,
        *,
        conflict_resolution: dict[str, str] | None = None,
    ) -> OperationResult:
        result = OperationResult()
        if self._has_cancel_resolution(conflict_resolution):
            conflicts = self.preview_edit_property(case_id, entity_id, prop, new_value).conflicts
            if conflicts:
                raise CascadeCancelled("Cascade cancelled by conflict resolution")

        case = self._ws.cases[case_id]
        entity = self._find_entity(case, entity_id)
        if entity is None:
            raise KeyError(f"Entity {entity_id!r} not found in case {case_id!r}")

        self._set_property(entity, prop, copy.deepcopy(new_value))
        self._unlink_property(case, entity_id, prop)
        self._mark_modified(result, case_id, model_affecting=_is_model_affecting_property(prop))
        result.applied_changes.append(f"{case_id}:entities/{entity_id}/{prop}")

        self._propagate_edit_to_descendants(
            case_id,
            entity_id,
            prop,
            new_value,
            result,
            conflict_resolution or {},
        )
        self._apply_staleness(result, f"model property changed: entities/{entity_id}/{prop}")
        return result

    def preview_edit_property(self, case_id: str, entity_id: str, prop: str, new_value: object) -> OperationResult:
        result = OperationResult()
        self._collect_edit_conflicts(case_id, entity_id, prop, new_value, result)
        return result

    def _propagate_edit_to_descendants(
        self,
        source_case_id: str,
        entity_id: str,
        prop: str,
        new_value: object,
        result: OperationResult,
        conflict_resolution: dict[str, str],
    ) -> None:
        for child_id in self._direct_children(source_case_id):
            child = self._ws.cases[child_id]
            if child.overlay is None:
                continue
            entry = child.overlay.entities.get(entity_id)
            path = f"entities/{entity_id}/{prop}"
            if entry is None or entity_id in child.overlay.deleted_inherited_entity_ids:
                self._record_conflict(result, child_id, path, "entity deleted or missing in child", new_value, None)
                result.skipped_case_ids.add(child_id)
                continue
            if entry.origin != "inherited" or not self._is_property_linked(entry, prop):
                child_entity = self._find_entity(child, entity_id)
                child_value = self._get_property(child_entity, prop) if child_entity is not None else None
                action = self._resolution_for(conflict_resolution, child_id, path)
                self._record_conflict(result, child_id, path, "local override", new_value, child_value)
                if action == "eliminate_diff":
                    entry.origin = "inherited"
                    entry.linked_properties.add(prop)
                    if child_entity is not None:
                        self._set_property(child_entity, prop, copy.deepcopy(new_value))
                    self._mark_modified(result, child_id, model_affecting=_is_model_affecting_property(prop))
                    result.applied_changes.append(f"{child_id}:{path}")
                    self._propagate_edit_to_descendants(child_id, entity_id, prop, new_value, result, conflict_resolution)
                else:
                    result.skipped_case_ids.add(child_id)
                continue

            child_entity = self._find_entity(child, entity_id)
            if child_entity is not None:
                self._set_property(child_entity, prop, copy.deepcopy(new_value))
                self._mark_modified(result, child_id, model_affecting=_is_model_affecting_property(prop))
                result.applied_changes.append(f"{child_id}:{path}")
            self._propagate_edit_to_descendants(child_id, entity_id, prop, new_value, result, conflict_resolution)

    def _collect_edit_conflicts(
        self,
        source_case_id: str,
        entity_id: str,
        prop: str,
        new_value: object,
        result: OperationResult,
    ) -> None:
        for child_id in self._direct_children(source_case_id):
            child = self._ws.cases[child_id]
            if child.overlay is None:
                continue
            entry = child.overlay.entities.get(entity_id)
            path = f"entities/{entity_id}/{prop}"
            if entry is None or entity_id in child.overlay.deleted_inherited_entity_ids:
                self._record_conflict(result, child_id, path, "entity deleted or missing in child", new_value, None)
                continue
            if entry.origin != "inherited" or not self._is_property_linked(entry, prop):
                child_entity = self._find_entity(child, entity_id)
                child_value = self._get_property(child_entity, prop) if child_entity is not None else None
                self._record_conflict(result, child_id, path, "local override", new_value, child_value)
                continue
            self._collect_edit_conflicts(child_id, entity_id, prop, new_value, result)

    # --------------------------------------------------------------- entities

    def add_entity(self, case_id: str, entity: object, domain: str) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        self._append_entity_to_model(case, entity, domain)

        ent_id = _entity_id(entity)
        if case.overlay is not None:
            self._add_overlay_for_entity(case.overlay, entity, origin="local")
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:add:{domain}/{ent_id}")

        self._propagate_add_to_descendants(case_id, entity, domain, result)
        self._apply_staleness(result, f"model entity added: {domain}/{ent_id}")
        return result

    def _propagate_add_to_descendants(self, source_case_id: str, entity: object, domain: str, result: OperationResult) -> None:
        ent_id = _entity_id(entity)
        for child_id in self._direct_children(source_case_id):
            child = self._ws.cases[child_id]
            if child.overlay is None:
                continue
            path = f"{domain}/{ent_id}"
            existing = self._find_entity(child, ent_id)
            if existing is not None:
                entry = child.overlay.entities.get(ent_id)
                if entry is not None and entry.origin == "local":
                    self._record_conflict(result, child_id, path, "local entity with same id already exists", entity, existing)
                    result.skipped_case_ids.add(child_id)
                    continue
                # Already inherited in this child; keep walking descendants.
                self._propagate_add_to_descendants(child_id, entity, domain, result)
                continue

            missing = self._missing_dependencies(entity, child)
            if missing:
                self._record_conflict(result, child_id, path, f"missing dependencies: {', '.join(sorted(missing))}", entity, None)
                result.skipped_case_ids.add(child_id)
                continue

            cloned = copy.deepcopy(entity)
            self._append_entity_to_model(child, cloned, domain)
            self._add_overlay_for_entity(child.overlay, cloned, origin="inherited")
            self._mark_modified(result, child_id, model_affecting=True)
            result.applied_changes.append(f"{child_id}:add:{path}")
            self._propagate_add_to_descendants(child_id, entity, domain, result)

    def remove_entity(self, case_id: str, entity_id: str) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        if self._find_entity(case, entity_id) is None:
            return result
        ids_to_remove = self._collect_removal_closure(case, {entity_id})
        for rid in ids_to_remove:
            was_inherited = (
                case.overlay is not None
                and rid in case.overlay.entities
                and case.overlay.entities[rid].origin == "inherited"
            )
            self._remove_entity_from_model(case, rid)
            if case.overlay is not None:
                case.overlay.entities.pop(rid, None)
                if was_inherited:
                    case.overlay.deleted_inherited_entity_ids.add(rid)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:remove:{','.join(sorted(ids_to_remove))}")

        for child_id in self._direct_children(case_id):
            self._cascade_removal(child_id, ids_to_remove, result)
        self._apply_staleness(result, f"model entity removed: {entity_id}")
        return result

    def _cascade_removal(self, child_id: str, ids_to_remove: set[str], result: OperationResult) -> None:
        child = self._ws.cases[child_id]
        if child.overlay is None:
            return
        removable: set[str] = set()
        blocked = False
        for rid in ids_to_remove:
            if rid in child.overlay.deleted_inherited_entity_ids:
                continue
            entry = child.overlay.entities.get(rid)
            if entry is None:
                continue
            if entry.origin == "inherited" and self._is_fully_linked(child, rid):
                removable.add(rid)
            else:
                entry.origin = "local"
                entry.linked_properties.clear()
                self._record_conflict(result, child_id, f"entities/{rid}", "local override blocks removal", None, None)
                blocked = True
        if blocked:
            result.skipped_case_ids.add(child_id)
            return
        if removable:
            closure = self._collect_removal_closure(child, removable)
            for rid in closure:
                self._remove_entity_from_model(child, rid)
                child.overlay.entities.pop(rid, None)
            self._mark_modified(result, child_id, model_affecting=True)
            result.applied_changes.append(f"{child_id}:remove:{','.join(sorted(closure))}")
        for gc_id in self._direct_children(child_id):
            self._cascade_removal(gc_id, ids_to_remove, result)

    # --------------------------------------------------------------- blocks

    def add_connection(self, case_id: str, connection: Connection) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        self._ensure_diagram(case).connections.append(connection)
        key = _connection_key(connection)
        if case.overlay is not None:
            case.overlay.inherited_connections.discard(key)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:add_connection:{key}")
        for child_id in self._direct_children(case_id):
            self._propagate_connection_add(child_id, connection, result)
        self._apply_staleness(result, "block connection added")
        return result

    def remove_connection(self, case_id: str, key: ConnectionKey) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        diagram = case.model.control_graph
        if diagram is None:
            return result
        object.__setattr__(diagram, "connections", [c for c in diagram.connections if _connection_key(c) != key])
        if case.overlay is not None and key in case.overlay.inherited_connections:
            case.overlay.inherited_connections.discard(key)
            case.overlay.deleted_inherited_connections.add(key)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:remove_connection:{key}")
        for child_id in self._direct_children(case_id):
            self._propagate_connection_remove(child_id, key, result)
        self._apply_staleness(result, "block connection removed")
        return result

    def _propagate_connection_add(self, child_id: str, connection: Connection, result: OperationResult) -> None:
        child = self._ws.cases[child_id]
        if child.overlay is None:
            return
        key = _connection_key(connection)
        diagram = child.model.control_graph
        if diagram is None or connection.src_instance not in diagram.instances or connection.dst_instance not in diagram.instances:
            self._record_conflict(result, child_id, f"connections/{key}", "missing block dependency", key, None)
            result.skipped_case_ids.add(child_id)
            return
        if key not in {_connection_key(c) for c in diagram.connections}:
            diagram.connections.append(copy.deepcopy(connection))
            child.overlay.inherited_connections.add(key)
            self._mark_modified(result, child_id, model_affecting=True)
            result.applied_changes.append(f"{child_id}:add_connection:{key}")
        for gc_id in self._direct_children(child_id):
            self._propagate_connection_add(gc_id, connection, result)

    def _propagate_connection_remove(self, child_id: str, key: ConnectionKey, result: OperationResult) -> None:
        child = self._ws.cases[child_id]
        if child.overlay is None:
            return
        if key in child.overlay.deleted_inherited_connections:
            return
        if key not in child.overlay.inherited_connections:
            self._record_conflict(result, child_id, f"connections/{key}", "local connection override", None, None)
            result.skipped_case_ids.add(child_id)
            return
        diagram = child.model.control_graph
        if diagram is not None:
            object.__setattr__(diagram, "connections", [c for c in diagram.connections if _connection_key(c) != key])
        child.overlay.inherited_connections.discard(key)
        child.overlay.deleted_inherited_connections.add(key)
        self._mark_modified(result, child_id, model_affecting=True)
        result.applied_changes.append(f"{child_id}:remove_connection:{key}")
        for gc_id in self._direct_children(child_id):
            self._propagate_connection_remove(gc_id, key, result)

    # --------------------------------------------------------------- reparent

    def reparent_case(self, case_id: str, new_parent_case_id: str | None) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        if new_parent_case_id is not None and self._would_form_cycle(case_id, new_parent_case_id):
            raise ValueError(
                f"Reparenting {case_id!r} under {new_parent_case_id!r} would form a cycle"
            )
        old_parent = case.parent_case_id
        case.parent_case_id = new_parent_case_id
        if old_parent is None and case_id in self._ws.root_case_ids:
            self._ws.root_case_ids.remove(case_id)
        if new_parent_case_id is None:
            case.overlay = None
            if case_id not in self._ws.root_case_ids:
                self._ws.root_case_ids.append(case_id)
        else:
            rebuild_overlay(case, self._ws.cases[new_parent_case_id])

        # Reparenting can change the effective model of the case and any
        # descendant whose inheritance chain is rerouted; invalidate them.
        affected = {case_id}
        affected.update(self._all_descendants(case_id))
        for cid in affected:
            self._mark_modified(result, cid, model_affecting=True)
        result.applied_changes.append(f"{case_id}:reparent:{new_parent_case_id}")
        self._apply_staleness(result, "case reparented")
        return result

    # ---------------------------------------------------------------- helpers

    def _append_entity_to_model(self, case: Case, entity: object, domain: str) -> None:
        if domain == "blocks":
            self._ensure_diagram(case).instances[_entity_id(entity)] = entity  # type: ignore[assignment]
            return
        accessor = _DOMAIN_LIST_ACCESSORS.get(domain)
        if accessor is None:
            raise ValueError(f"Unknown domain {domain!r}")
        accessor(case.model).append(entity)

    def _ensure_diagram(self, case: Case) -> BlockDiagram:
        if case.model.control_graph is None:
            case.model.control_graph = BlockDiagram()
        return case.model.control_graph

    def _add_overlay_for_entity(self, overlay: CaseOverlay, entity: object, *, origin: str) -> None:
        ent_id = _entity_id(entity)
        props = set() if origin == "local" else self._all_cascadable_props_for_entity(entity)
        overlay.entities[ent_id] = EntityOverlay(origin=origin, linked_properties=props)
        if hasattr(entity, "markers"):
            for marker in getattr(entity, "markers", []):
                if marker.type is not MarkerType.STRUCTURAL:
                    continue
                marker_props = set() if origin == "local" else self._all_cascadable_props_for_entity(marker)
                overlay.entities[marker.id] = EntityOverlay(origin=origin, linked_properties=marker_props)

    def _unlink_property(self, case: Case, entity_id: str, prop: str) -> None:
        if case.overlay is None:
            return
        entry = case.overlay.entities.get(entity_id)
        if entry is not None and entry.origin == "inherited":
            entry.linked_properties.discard(prop)
            root = prop.split(".", 1)[0]
            if root != prop:
                entry.linked_properties.discard(root)

    def _all_cascadable_props(self, cls: type) -> set[str]:
        try:
            return set(cascadable_properties(cls))
        except ValueError:
            return set()

    def _all_cascadable_props_for_entity(self, entity: object) -> set[str]:
        props = self._all_cascadable_props(type(entity))
        parameters = getattr(entity, "parameters", None)
        if isinstance(parameters, dict):
            props.discard("position")
            props.update(f"parameters.{key}" for key in parameters)
        metadata = getattr(entity, "metadata", None)
        values = getattr(metadata, "values", None)
        if isinstance(values, dict):
            props.update(f"metadata.values.{key}" for key in values)
        return props

    def _is_property_linked(self, entry: EntityOverlay, prop: str) -> bool:
        if prop in entry.linked_properties:
            return True
        root = prop.split(".", 1)[0]
        return root in entry.linked_properties

    def _is_fully_linked(self, case: Case, entity_id: str) -> bool:
        if case.overlay is None:
            return True
        entry = case.overlay.entities.get(entity_id)
        entity_entry = _entity_lookup(case).get(entity_id)
        if entry is None or entity_entry is None:
            return False
        entity, _cls = entity_entry
        return entry.origin == "inherited" and entry.linked_properties == self._all_cascadable_props_for_entity(entity)

    def _get_property(self, entity: object, path: str) -> object:
        target: object = entity
        parts = path.split(".")
        for part in parts:
            if isinstance(target, dict):
                target = target.get(part)
            else:
                target = getattr(target, part)
        return target

    def _set_property(self, entity: object, path: str, value: object) -> None:
        parts = path.split(".")
        if len(parts) == 1:
            setattr(entity, path, value)
            return
        target: object = entity
        for part in parts[:-1]:
            if isinstance(target, dict):
                target = target.setdefault(part, {})
            else:
                target = getattr(target, part)
        leaf = parts[-1]
        if isinstance(target, dict):
            target[leaf] = value
        else:
            setattr(target, leaf, value)

    def _collect_removal_closure(self, case: Case, initial_ids: set[str]) -> set[str]:
        pending = set(initial_ids)
        result = set(initial_ids)
        while pending:
            current = pending.pop()
            dependents = self._dependent_ids(case, current)
            new = dependents - result
            result.update(new)
            pending.update(new)
        return result

    def _dependent_ids(self, case: Case, entity_id: str) -> set[str]:
        m = case.model
        ids = {entity_id}
        for body in m.bodies:
            if body.id == entity_id:
                ids.update(marker.id for marker in body.markers)
        out: set[str] = set()
        for joint in m.joints:
            endpoints = (joint.endpoint_a, joint.endpoint_b)
            if any(ep.body_id in ids or ep.marker_id in ids or ep.slider_id in ids for ep in endpoints):
                out.add(joint.id)
        for driver in m.drivers:
            if driver.target_joint_id in ids:
                out.add(driver.id)
        for load in m.loads:
            if load.target_marker_id in ids:
                out.add(load.id)
        for sensor in m.sensors:
            if any(marker_id in ids for marker_id in sensor.marker_ids):
                out.add(sensor.id)
        for spring in m.springs:
            endpoints = (spring.endpoint_a, spring.endpoint_b)
            if any(ep.body_id in ids or ep.marker_id in ids for ep in endpoints):
                out.add(spring.id)
        return out

    def _remove_entity_from_model(self, case: Case, entity_id: str) -> None:
        m = case.model
        m.bodies[:] = [b for b in m.bodies if b.id != entity_id]
        for body in m.bodies:
            body.markers[:] = [mk for mk in body.markers if mk.id != entity_id]
            body.edge_order[:] = [mid for mid in body.edge_order if mid != entity_id]
        m.joints[:] = [j for j in m.joints if j.id != entity_id]
        m.sliders[:] = [s for s in m.sliders if s.id != entity_id]
        m.drivers[:] = [d for d in m.drivers if d.id != entity_id]
        m.loads[:] = [l for l in m.loads if l.id != entity_id]
        m.sensors[:] = [s for s in m.sensors if s.id != entity_id]
        m.springs[:] = [sp for sp in m.springs if sp.id != entity_id]
        if m.control_graph is not None:
            m.control_graph.instances.pop(entity_id, None)
            object.__setattr__(
                m.control_graph,
                "connections",
                [
                    c for c in m.control_graph.connections
                    if c.src_instance != entity_id and c.dst_instance != entity_id
                ],
            )

    def _missing_dependencies(self, entity: object, case: Case) -> set[str]:
        ids = set(_entity_lookup(case).keys())
        missing: set[str] = set()
        if hasattr(entity, "endpoint_a") and hasattr(entity, "endpoint_b"):
            for ep in (getattr(entity, "endpoint_a"), getattr(entity, "endpoint_b")):
                for attr in ("body_id", "marker_id", "slider_id"):
                    ref = getattr(ep, attr, None)
                    if ref is not None and ref not in ids:
                        missing.add(ref)
        if hasattr(entity, "target_joint_id") and getattr(entity, "target_joint_id") not in ids:
            missing.add(getattr(entity, "target_joint_id"))
        if hasattr(entity, "target_marker_id") and getattr(entity, "target_marker_id") not in ids:
            missing.add(getattr(entity, "target_marker_id"))
        if hasattr(entity, "marker_ids"):
            missing.update(ref for ref in getattr(entity, "marker_ids") if ref not in ids)
        if isinstance(entity, BlockInstance):
            return missing
        return missing

    def _find_entity(self, case: Case, entity_id: str) -> object | None:
        entry = _entity_lookup(case).get(entity_id)
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

    def _would_form_cycle(self, case_id: str, candidate_parent_id: str) -> bool:
        current: str | None = candidate_parent_id
        seen: set[str] = set()
        while current is not None:
            if current == case_id:
                return True
            if current in seen:
                return True
            seen.add(current)
            current = self._ws.cases[current].parent_case_id
        return False

    def _mark_modified(self, result: OperationResult, case_id: str, *, model_affecting: bool) -> None:
        result.modified_case_ids.add(case_id)
        if model_affecting:
            result.stale_case_ids.add(case_id)

    def _apply_staleness(self, result: OperationResult, reason: str) -> None:
        for case_id in result.stale_case_ids:
            case = self._ws.cases.get(case_id)
            if case is not None:
                mark_runs_stale_for_case(case, reason=reason)

    def _record_conflict(
        self,
        result: OperationResult,
        case_id: str,
        path: str,
        reason: str,
        parent_value: object | None,
        child_value: object | None,
    ) -> None:
        result.conflicts.append(
            CascadeConflict(
                case_id=case_id,
                path=path,
                reason=reason,
                parent_value=_to_serializable(parent_value),
                child_value=_to_serializable(child_value),
            )
        )

    def _resolution_for(self, resolutions: dict[str, str], case_id: str, path: str) -> str:
        return resolutions.get(f"{case_id}:{path}", resolutions.get(path, "accept"))

    def _has_cancel_resolution(self, resolutions: dict[str, str] | None) -> bool:
        return bool(resolutions and any(value == "cancel" for value in resolutions.values()))


def _to_serializable(value: object) -> object:
    if value is None:
        return None
    if hasattr(value, "expression"):
        return getattr(value, "expression")
    if isinstance(value, (str, int, float, bool, list, tuple, dict)):
        return value
    if hasattr(value, "__dict__"):
        return repr(value)
    return repr(value)
