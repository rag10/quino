# quino/application/_context.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, ContextManager

from quino.domain.model import Project
from quino.services.expressions import ExpressionService
from quino.services.ids import IdService
from quino.services.units import UnitService
from quino.services.validation import ValidationService


@dataclass
class ServiceContext:
    """Dependencias compartidas que los command-services reciben.

    No contiene el Project directamente: se accede vía `project_provider()` para
    que la fachada pueda reasignarlo (load_project, new_project).
    """
    project_provider: Callable[[], Project]      # devuelve self._project
    operation: Callable[[], ContextManager]      # devuelve self._operation()
    snapshot: Callable[[], None]                 # self._snapshot
    invalidate_pose_state: Callable[[], None]
    ids: IdService
    expressions: ExpressionService
    units: UnitService
    validation: ValidationService
    find_entity: Callable[[str], object]
    sync_all_special_com_markers: Callable[[], None]
    load_expression_variables: Callable[..., dict]
    build_validated_scalar_property: Callable[[object, str, str], object]
    assign_scalar_property: Callable[[object, str, object], None]
    apply_style_update: Callable[[object, str, object], None]
    connect_marker_to_ground: Callable[..., str]
    joints_for_marker: Callable[[str], list]
    translate_direct_joint_counterparts: Callable[..., set]
    set_current_pose_id: Callable[[str | None], None] = lambda _pid: None
    # Optional hook the GUI installs to ask the user before a numerically-
    # relevant edit (i.e. not a cosmetic style change) invalidates persisted
    # runs of the active case. Should return True if the edit may proceed,
    # False if it must be aborted.
    confirm_run_invalidation: Callable[[], bool] = lambda: True

    def confirm_invalidation_if_runs_exist(self) -> bool:
        """If a case is active AND has analyses with at least one ok run,
        delegate to *confirm_run_invalidation*. Otherwise return True
        (no confirmation needed)."""
        project = self.project_provider()
        if project is None or project.workspace is None:
            return True
        ws = project.workspace
        if ws.active_case_id is None:
            return True
        analysis_ids = {
            a.id for a in ws.analyses if a.case_id == ws.active_case_id
        }
        if not analysis_ids:
            return True
        has_ok_run = any(
            r.analysis_id in analysis_ids
            and any(e.status == "ok" for e in r.entries)
            for r in ws.runs
        )
        if not has_ok_run:
            return True
        return bool(self.confirm_run_invalidation())

    def discard_runs_for_active_case(self) -> None:
        """Hard-delete all runs of the active case's analyses + their
        on-disk artifacts. Called after the user has confirmed an edit
        that invalidates them."""
        project = self.project_provider()
        if project is None or project.workspace is None:
            return
        ws = project.workspace
        if ws.active_case_id is None:
            return
        analysis_ids = {
            a.id for a in ws.analyses if a.case_id == ws.active_case_id
        }
        kept: list = []
        for run in ws.runs:
            if run.analysis_id in analysis_ids:
                for entry in run.entries:
                    if entry.result_ref is not None:
                        try:
                            from pathlib import Path
                            # We can't resolve project_dir from here; the
                            # GUI takes care of physical cleanup. The model
                            # update alone is enough to make runs vanish
                            # from the UI.
                        except Exception:
                            pass
                continue
            kept.append(run)
        ws.runs = kept

    def get_active_case(self):
        """Return the active Case if one is set, otherwise None."""
        project = self.project_provider()
        ws = project.workspace if project is not None else None
        if ws is None or ws.active_case_id is None:
            return None
        return next((c for c in ws.cases if c.id == ws.active_case_id), None)

    def effective_project(self):
        """Return a read-only composed project view (baseline + case chain).

        In case mode, returns the project with structural deltas applied so
        commands can validate inputs against entities added by the case.
        Outside case mode, returns the raw project.

        IMPORTANT: do NOT mutate the returned project — it may be a
        deep-copy clone. Mutations must go via case routing helpers.
        """
        project = self.project_provider()
        case = self.get_active_case()
        if case is None:
            return project
        from quino.services.workspace_composition import compose_project
        try:
            return compose_project(project, case=case)
        except Exception:
            return project

    def add_entity_to_case(self, entity, domain: str) -> bool:
        """If a case is active, serialize *entity* and append it to
        case.added_entities[*domain*].  Return True when redirected
        (caller must NOT add the entity to project.model)."""
        case = self.get_active_case()
        if case is None:
            return False
        from quino.serialization.json_io import JsonMapper
        mapper = JsonMapper()
        serializer = {
            "bodies": mapper._body_to_dict,
            "joints": mapper._joint_to_dict,
            "sliders": mapper._slider_to_dict,
            "drivers": mapper._driver_to_dict,
            "loads": mapper._load_to_dict,
            "sensors": mapper._sensor_to_dict,
            "springs": mapper._spring_to_dict,
            "blocks": mapper._block_instance_to_dict,
            "connections": mapper._block_connection_to_dict,
        }.get(domain)
        if serializer is None:
            return False
        case.added_entities.setdefault(domain, []).append(serializer(entity))
        return True

    def remove_entity_from_case(self, entity_id: str) -> bool:
        """If a case is active, record *entity_id* as removed.
        If the entity was previously added by this case, it is removed
        from added_entities instead.  Return True when handled
        (caller should still remove from project.model so the baseline
        stays consistent)."""
        case = self.get_active_case()
        if case is None:
            return False
        # If the entity was added by this same case, remove from added_entities
        for domain, entities in case.added_entities.items():
            for i, ent in enumerate(entities):
                if ent.get("id") == entity_id:
                    entities.pop(i)
                    if not entities:
                        case.added_entities.pop(domain, None)
                    return True
        # Otherwise record as removed from baseline
        if entity_id not in case.removed_entity_ids:
            case.removed_entity_ids.append(entity_id)
        return True

    def add_marker_removal_to_case(self, marker_id: str, body_id: str) -> bool:
        """Record a marker removal in the active case.
        Markers don't have their own domain in added_entities, so we
        store reference overrides on the body to indicate the marker
        is removed.  Return True when handled."""
        case = self.get_active_case()
        if case is None:
            return False
        overrides = case.reference_overrides.setdefault(body_id, {})
        removed = overrides.setdefault("removed_markers", [])
        if marker_id not in removed:
            removed.append(marker_id)
        return True
