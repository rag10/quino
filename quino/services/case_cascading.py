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
