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

    # --------------------------------------------------------------- entities

    def add_entity(self, case_id: str, entity: object, domain: str) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        self._append_entity_to_model(case, entity, domain)
        ent_id = _entity_id(entity)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:add:{domain}/{ent_id}")
        for child_id in self._direct_children(case_id):
            self._propagate_add(child_id, entity, domain, result)
        self._apply_staleness(result, f"model entity added: {domain}/{ent_id}")
        return result

    def _propagate_add(self, case_id: str, entity: object, domain: str, result: OperationResult) -> None:
        case = self._ws.cases[case_id]
        ent_id = _entity_id(entity)
        if self._find_entity(case, ent_id) is not None:
            return
        if self._missing_dependencies(entity, case):
            return
        cloned = copy.deepcopy(entity)
        self._append_entity_to_model(case, cloned, domain)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:add:{domain}/{ent_id}")
        for gc_id in self._direct_children(case_id):
            self._propagate_add(gc_id, entity, domain, result)

    def remove_entity(self, case_id: str, entity_id: str) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        if self._find_entity(case, entity_id) is None:
            return result
        closure = self._collect_removal_closure(case, {entity_id})
        snapshot = {rid: copy.deepcopy(self._find_entity(case, rid)) for rid in closure
                    if self._find_entity(case, rid) is not None}
        for rid in closure:
            self._remove_entity_from_model(case, rid)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:remove:{','.join(sorted(closure))}")
        for child_id in self._direct_children(case_id):
            self._propagate_remove(child_id, snapshot, result)
        self._apply_staleness(result, f"model entity removed: {entity_id}")
        return result

    def _propagate_remove(self, case_id: str, snapshot: dict[str, object], result: OperationResult) -> None:
        case = self._ws.cases[case_id]
        removable: set[str] = set()
        for rid, parent_ent in snapshot.items():
            child_ent = self._find_entity(case, rid)
            if child_ent is None:
                continue
            if child_ent == parent_ent:
                removable.add(rid)
        if not removable:
            return
        closure = self._collect_removal_closure(case, removable)
        for rid in closure:
            self._remove_entity_from_model(case, rid)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:remove:{','.join(sorted(closure))}")
        for gc_id in self._direct_children(case_id):
            self._propagate_remove(gc_id, snapshot, result)

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

    def _collect_removal_closure(self, case: Case, initial_ids: set[str]) -> set[str]:
        pending = set(initial_ids)
        result = set(initial_ids)
        while pending:
            current = pending.pop()
            new = self._dependent_ids(case, current) - result
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
            if any(ep.body_id in ids or ep.marker_id in ids or ep.slider_id in ids
                   for ep in (joint.endpoint_a, joint.endpoint_b)):
                out.add(joint.id)
        for driver in m.drivers:
            if driver.target_joint_id in ids:
                out.add(driver.id)
        for load in m.loads:
            if load.target_marker_id in ids:
                out.add(load.id)
        for sensor in m.sensors:
            if any(mid in ids for mid in sensor.marker_ids):
                out.add(sensor.id)
        for spring in m.springs:
            if any(ep.body_id in ids or ep.marker_id in ids
                   for ep in (spring.endpoint_a, spring.endpoint_b)):
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
            m.control_graph.connections[:] = [
                c for c in m.control_graph.connections
                if c.src_instance != entity_id and c.dst_instance != entity_id
            ]

    def _missing_dependencies(self, entity: object, case: Case) -> set[str]:
        ids = set(entity_lookup(case).keys())
        missing: set[str] = set()
        if hasattr(entity, "endpoint_a") and hasattr(entity, "endpoint_b"):
            for ep in (entity.endpoint_a, entity.endpoint_b):
                for attr in ("body_id", "marker_id", "slider_id"):
                    ref = getattr(ep, attr, None)
                    if ref is not None and ref not in ids:
                        missing.add(ref)
        if hasattr(entity, "target_joint_id") and entity.target_joint_id not in ids:
            missing.add(entity.target_joint_id)
        if hasattr(entity, "target_marker_id") and entity.target_marker_id not in ids:
            missing.add(entity.target_marker_id)
        if hasattr(entity, "marker_ids"):
            missing.update(ref for ref in entity.marker_ids if ref not in ids)
        return missing

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
            poses=self._clone_poses(parent),
            analyses=self._clone_analyses_reset(parent),
            sensor_outputs={},
            reaction_outputs={},
        )
        self._ws.cases[new_id] = child
        return new_id

    def duplicate_case(self, source_case_id: str, name: str | None = None) -> str:
        if source_case_id not in self._ws.cases:
            raise KeyError(f"Case {source_case_id!r} not found")
        source = self._ws.cases[source_case_id]
        new_id = _new_case_id()
        duplicate = Case(
            id=new_id,
            name=name or f"{source.name} copy",
            description=source.description,
            parent_case_id=source.parent_case_id,
            model=copy.deepcopy(source.model),
            poses=self._clone_poses(source),
            analyses=self._clone_analyses_reset(source),
            sensor_outputs={},
            reaction_outputs={},
            metadata=copy.deepcopy(source.metadata),
        )
        self._ws.cases[new_id] = duplicate
        if duplicate.parent_case_id is None and new_id not in self._ws.root_case_ids:
            self._ws.root_case_ids.append(new_id)
        return new_id

    def _clone_poses(self, source: Case):
        cloned = copy.deepcopy(source.poses)
        for pose in cloned:
            pose.id = _new_pose_id()
        if not any(p.is_default for p in cloned):
            cloned.insert(0, create_default_pose(_new_pose_id()))
        return cloned

    def _clone_analyses_reset(self, source: Case) -> list[Analysis]:
        cloned: list[Analysis] = copy.deepcopy(source.analyses)
        for analysis in cloned:
            analysis.id = _new_analysis_id()
            analysis.pose_id = None
            analysis.status = "to_be_run"
            analysis.created_at = None
            analysis.finished_at = None
            analysis.result_ref = None
            analysis.artifacts = []
            analysis.warnings = []
            analysis.error_message = ""
            analysis.config_snapshot = {}
            for metric in analysis.metrics:
                metric.result = None
        return cloned

    def reparent_case(self, case_id: str, new_parent_case_id: str | None) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        if new_parent_case_id is not None and self._would_form_cycle(case_id, new_parent_case_id):
            raise ValueError(f"Reparenting {case_id!r} under {new_parent_case_id!r} would form a cycle")
        old_parent = case.parent_case_id
        case.parent_case_id = new_parent_case_id
        if old_parent is None and case_id in self._ws.root_case_ids:
            self._ws.root_case_ids.remove(case_id)
        if new_parent_case_id is None and case_id not in self._ws.root_case_ids:
            self._ws.root_case_ids.append(case_id)
        for cid in {case_id, *self._all_descendants(case_id)}:
            self._mark_modified(result, cid, model_affecting=True)
        self._apply_staleness(result, "case reparented")
        return result

    def _would_form_cycle(self, case_id: str, candidate_parent_id: str) -> bool:
        current: str | None = candidate_parent_id
        seen: set[str] = set()
        while current is not None:
            if current == case_id or current in seen:
                return True
            seen.add(current)
            current = self._ws.cases[current].parent_case_id
        return False

    # --------------------------------------------------------------- blocks

    def add_connection(self, case_id: str, connection: Connection) -> OperationResult:
        result = OperationResult()
        case = self._ws.cases[case_id]
        self._ensure_diagram(case).connections.append(connection)
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:add_connection:{_connection_key(connection)}")
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
        diagram.connections[:] = [c for c in diagram.connections if _connection_key(c) != key]
        self._mark_modified(result, case_id, model_affecting=True)
        result.applied_changes.append(f"{case_id}:remove_connection:{key}")
        for child_id in self._direct_children(case_id):
            self._propagate_connection_remove(child_id, key, result)
        self._apply_staleness(result, "block connection removed")
        return result

    def _propagate_connection_add(self, case_id, connection, result) -> None:
        case = self._ws.cases[case_id]
        diagram = case.model.control_graph
        if diagram is None or connection.src_instance not in diagram.instances or \
                connection.dst_instance not in diagram.instances:
            return
        key = _connection_key(connection)
        if key not in {_connection_key(c) for c in diagram.connections}:
            diagram.connections.append(copy.deepcopy(connection))
            self._mark_modified(result, case_id, model_affecting=True)
        for gc_id in self._direct_children(case_id):
            self._propagate_connection_add(gc_id, connection, result)

    def _propagate_connection_remove(self, case_id, key, result) -> None:
        case = self._ws.cases[case_id]
        diagram = case.model.control_graph
        if diagram is None:
            return
        if key not in {_connection_key(c) for c in diagram.connections}:
            return
        diagram.connections[:] = [c for c in diagram.connections if _connection_key(c) != key]
        self._mark_modified(result, case_id, model_affecting=True)
        for gc_id in self._direct_children(case_id):
            self._propagate_connection_remove(gc_id, key, result)

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
