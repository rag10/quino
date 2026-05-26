# quino/services/case_cascading.py
from __future__ import annotations

import copy
import uuid

from quino.domain.workspace import (
    Case,
    CaseOverlay,
    EntityOverlay,
    Workspace,
)
from quino.services.cascade_property_registry import cascadable_properties
from quino.services.case_overlay_validator import _entity_lookup


_DOMAIN_LIST_ACCESSORS = {
    "bodies":   lambda m: m.bodies,
    "joints":   lambda m: m.joints,
    "sliders":  lambda m: m.sliders,
    "drivers":  lambda m: m.drivers,
    "loads":    lambda m: m.loads,
    "sensors":  lambda m: m.sensors,
    "springs":  lambda m: m.springs,
}


class CascadingEngine:
    """Façade for the five mutation operations.

    All workspace mutations that affect cases/poses MUST go through this
    class. Direct mutation of case.model or case.overlay from outside is
    a contract violation.
    """

    def __init__(self, workspace: Workspace) -> None:
        self._ws = workspace

    # ---- fork_case --------------------------------------------------
    def fork_case(self, parent_case_id: str, name: str) -> str:
        if parent_case_id not in self._ws.cases:
            raise KeyError(f"Parent case {parent_case_id!r} not found")
        parent = self._ws.cases[parent_case_id]

        new_id = f"case-{uuid.uuid4().hex[:8]}"
        child = Case(
            id=new_id,
            name=name,
            parent_case_id=parent_case_id,
            model=copy.deepcopy(parent.model),
            poses=copy.deepcopy(parent.poses),
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

    def _build_fork_overlay(self, parent: Case) -> CaseOverlay:
        overlay = CaseOverlay()
        for ent_id, (_ent, cls) in _entity_lookup(parent).items():
            try:
                props = set(cascadable_properties(cls))
            except ValueError:
                props = set()
            overlay.entities[ent_id] = EntityOverlay(
                origin="inherited",
                linked_properties=props,
            )
        for pose in parent.poses:
            overlay.poses[pose.id] = EntityOverlay(origin="inherited")
        # Control graph connections (if present)
        if parent.model.control_graph is not None:
            for conn in parent.model.control_graph.connections:
                overlay.inherited_connections.add(
                    (conn.src_instance, conn.src_port, conn.dst_instance, conn.dst_port)
                )
        return overlay

    # ---- edit_property ----------------------------------------------
    def edit_property(self, case_id: str, entity_id: str, prop: str, new_value: object) -> None:
        case = self._ws.cases[case_id]
        entity = self._find_entity(case, entity_id)
        if entity is None:
            raise KeyError(f"Entity {entity_id!r} not found in case {case_id!r}")

        setattr(entity, prop, new_value)
        if case.overlay is not None:
            entry = case.overlay.entities.get(entity_id)
            if entry is not None and entry.origin == "inherited":
                entry.linked_properties.discard(prop)

        self._propagate_edit_to_descendants(case_id, entity_id, prop, new_value)

    def _propagate_edit_to_descendants(self, source_case_id: str, entity_id: str, prop: str, new_value: object) -> None:
        import copy as _copy
        for child_id in self._direct_children(source_case_id):
            child = self._ws.cases[child_id]
            assert child.overlay is not None
            entry = child.overlay.entities.get(entity_id)
            if entry is None or entity_id in child.overlay.deleted_inherited_entity_ids:
                continue
            if entry.origin != "inherited":
                continue
            if prop in entry.linked_properties:
                child_entity = self._find_entity(child, entity_id)
                if child_entity is not None:
                    setattr(child_entity, prop, _copy.deepcopy(new_value))
                self._propagate_edit_to_descendants(child_id, entity_id, prop, new_value)
            else:
                child_entity = self._find_entity(child, entity_id)
                child_value = getattr(child_entity, prop, None) if child_entity is not None else None
                child.metadata.setdefault("divergence_warnings", []).append({
                    "path": f"entities/{entity_id}/{prop}",
                    "parent_case_id": source_case_id,
                    "parent_value": _to_serializable(new_value),
                    "child_value": _to_serializable(child_value),
                })

    # ---- add_entity -------------------------------------------------
    def add_entity(self, case_id: str, entity: object, domain: str) -> None:
        case = self._ws.cases[case_id]
        accessor = _DOMAIN_LIST_ACCESSORS.get(domain)
        if accessor is None:
            raise ValueError(f"Unknown domain {domain!r}")
        target_list = accessor(case.model)
        target_list.append(entity)

        if case.overlay is not None:
            ent_id = getattr(entity, "id", None)
            if ent_id is None:
                raise ValueError(f"Entity in domain {domain!r} has no .id")
            case.overlay.entities[ent_id] = EntityOverlay(origin="local")
            # Markers contained in a Body need their own entries
            if domain == "bodies":
                for marker in getattr(entity, "markers", []):
                    case.overlay.entities[marker.id] = EntityOverlay(origin="local")

    # ---- remove_entity ----------------------------------------------
    def remove_entity(self, case_id: str, entity_id: str) -> None:
        case = self._ws.cases[case_id]
        target = self._find_entity(case, entity_id)
        if target is None:
            return  # idempotent

        was_inherited = (
            case.overlay is not None
            and entity_id in case.overlay.entities
            and case.overlay.entities[entity_id].origin == "inherited"
        )

        self._remove_entity_from_model(case, entity_id)

        if case.overlay is not None:
            case.overlay.entities.pop(entity_id, None)
            if was_inherited:
                case.overlay.deleted_inherited_entity_ids.add(entity_id)

        # Cascade to direct children
        for child_id in self._direct_children(case_id):
            self._cascade_removal(child_id, entity_id)

    def _cascade_removal(self, child_id: str, entity_id: str) -> None:
        child = self._ws.cases[child_id]
        assert child.overlay is not None
        if entity_id in child.overlay.deleted_inherited_entity_ids:
            return
        entry = child.overlay.entities.get(entity_id)
        if entry is None:
            return

        # "untouched" = inherited AND the child has not customised any property
        # (all cascadable props are still linked, none have been unlinked)
        # AND no existing divergence warning for this entity
        has_divergence = any(
            w.get("path", "").startswith(f"entities/{entity_id}/")
            for w in child.metadata.get("divergence_warnings", [])
        )
        # Determine if ALL cascadable properties are still linked (nothing overridden)
        from quino.services.case_overlay_validator import _entity_lookup as _lu
        child_ent_entry = _lu(child).get(entity_id)
        if child_ent_entry is not None:
            _, cls = child_ent_entry
            try:
                from quino.services.cascade_property_registry import cascadable_properties as _cp
                all_props = set(_cp(cls))
            except ValueError:
                all_props = set()
        else:
            all_props = set()
        fully_linked = entry.linked_properties == all_props if all_props else not entry.linked_properties
        untouched = (
            entry.origin == "inherited"
            and fully_linked
            and not has_divergence
        )

        if untouched:
            self._remove_entity_from_model(child, entity_id)
            child.overlay.entities.pop(entity_id, None)
            for gc_id in self._direct_children(child_id):
                self._cascade_removal(gc_id, entity_id)
        else:
            # Keep the entity, flip to local, record warning
            entry.origin = "local"
            entry.linked_properties.clear()
            child.metadata.setdefault("divergence_warnings", []).append({
                "kind": "deleted_in_parent",
                "path": f"entities/{entity_id}",
            })

    def _remove_entity_from_model(self, case: "Case", entity_id: str) -> None:
        m = case.model
        # Use in-place mutation in case slots=True prevents field reassignment
        new_bodies = [b for b in m.bodies if b.id != entity_id]
        m.bodies.clear(); m.bodies.extend(new_bodies)
        for body in m.bodies:
            new_markers = [mk for mk in body.markers if mk.id != entity_id]
            body.markers.clear(); body.markers.extend(new_markers)
            new_edge = [mid for mid in body.edge_order if mid != entity_id]
            body.edge_order.clear(); body.edge_order.extend(new_edge)
        new_joints = [j for j in m.joints if j.id != entity_id]
        m.joints.clear(); m.joints.extend(new_joints)
        new_sliders = [s for s in m.sliders if s.id != entity_id]
        m.sliders.clear(); m.sliders.extend(new_sliders)
        new_drivers = [d for d in m.drivers if d.id != entity_id]
        m.drivers.clear(); m.drivers.extend(new_drivers)
        new_loads = [l for l in m.loads if l.id != entity_id]
        m.loads.clear(); m.loads.extend(new_loads)
        new_sensors = [s for s in m.sensors if s.id != entity_id]
        m.sensors.clear(); m.sensors.extend(new_sensors)
        new_springs = [sp for sp in m.springs if sp.id != entity_id]
        m.springs.clear(); m.springs.extend(new_springs)
        if m.control_graph is not None:
            m.control_graph.instances.pop(entity_id, None)
            m.control_graph.connections = [
                c for c in m.control_graph.connections
                if c.src_instance != entity_id and c.dst_instance != entity_id
            ]

    # ---- reparent_case ----------------------------------------------
    def reparent_case(self, case_id: str, new_parent_case_id: str | None) -> None:
        case = self._ws.cases[case_id]
        if new_parent_case_id is not None and self._would_form_cycle(case_id, new_parent_case_id):
            raise ValueError(
                f"Reparenting {case_id!r} under {new_parent_case_id!r} would form a cycle"
            )

        case.parent_case_id = new_parent_case_id

        if new_parent_case_id is None:
            case.overlay = None
            if case_id not in self._ws.root_case_ids:
                self._ws.root_case_ids.append(case_id)
        else:
            from quino.services.case_overlay_validator import rebuild_overlay
            rebuild_overlay(case, self._ws.cases[new_parent_case_id])
            if case_id in self._ws.root_case_ids:
                self._ws.root_case_ids.remove(case_id)

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

    # ---- helpers ----------------------------------------------------
    def _direct_children(self, case_id: str) -> list[str]:
        return [c.id for c in self._ws.cases.values() if c.parent_case_id == case_id]

    def _find_entity(self, case: "Case", entity_id: str) -> object | None:
        m = case.model
        for body in m.bodies:
            if body.id == entity_id:
                return body
            for marker in body.markers:
                if marker.id == entity_id:
                    return marker
        for joint in m.joints:
            if joint.id == entity_id:
                return joint
        for slider in m.sliders:
            if slider.id == entity_id:
                return slider
        for driver in m.drivers:
            if driver.id == entity_id:
                return driver
        for load in m.loads:
            if load.id == entity_id:
                return load
        for sensor in m.sensors:
            if sensor.id == entity_id:
                return sensor
        for spring in m.springs:
            if spring.id == entity_id:
                return spring
        if m.control_graph is not None:
            return m.control_graph.instances.get(entity_id)
        return None


def _to_serializable(value: object) -> object:
    """Best-effort serialisation for divergence warning payloads."""
    if hasattr(value, "expression"):
        return getattr(value, "expression")
    if hasattr(value, "__dict__"):
        return repr(value)
    return repr(value)
