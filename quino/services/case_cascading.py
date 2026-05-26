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
