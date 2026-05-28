# quino/application/_context.py
from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, ContextManager, TYPE_CHECKING

if TYPE_CHECKING:
    from quino.domain.workspace import Case, Workspace
    from quino.services.case_cascading import CascadingEngine

from quino.services.expressions import ExpressionService
from quino.services.ids import IdService
from quino.services.units import UnitService
from quino.services.validation import ValidationService


@dataclass
class ServiceContext:
    """Dependencias compartidas que los command-services reciben.

    No contiene la Workspace directamente: se accede vía `workspace_provider()`
    para que la fachada pueda reasignarla (load_workspace, new_workspace).
    """
    workspace_provider: Callable[[], "Workspace | None"]
    current_case_provider: Callable[[], "Case | None"]
    cascade_provider: Callable[[], "CascadingEngine | None"]
    operation: Callable[[], ContextManager]       # devuelve self._operation()
    snapshot: Callable[[], None]                  # self._snapshot
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
    set_current_pose_id: Callable[[str | None], None] = field(
        default_factory=lambda: (lambda _pid: None)
    )
    # Optional hook the GUI installs to ask the user before a numerically-
    # relevant edit invalidates persisted runs of the active case. Should
    # return True if the edit may proceed, False if it must be aborted.
    confirm_run_invalidation: Callable[[], bool] = field(
        default_factory=lambda: (lambda: True)
    )
    resolve_cascade_conflicts: Callable[[list], dict[str, str] | None] = field(
        default_factory=lambda: (lambda conflicts: {f"{c.case_id}:{c.path}": "accept" for c in conflicts})
    )

    def cascade_resolution_for(self, conflicts: list) -> dict[str, str] | None:
        if not conflicts:
            return {}
        return self.resolve_cascade_conflicts(conflicts)

    # ------------------------------------------------------------------
    # Back-compat: command-services use cascade_provider() for mutations,
    # but may still call project_provider() for read-only access (expressions,
    # parameter lookup, etc.) via _WorkspaceProjectProxy.
    # Remove once all reads are also migrated to workspace_provider() + current_case_provider().
    # ------------------------------------------------------------------
    def project_provider(self):
        """Shim: returns the active Case's model wrapper for backward compat.

        Returns a minimal proxy that exposes .model, .parameters, .sketch,
        .poses, etc from the current Case so old command-service code keeps
        working until Task 17.
        """
        ws = self.workspace_provider()
        if ws is None:
            return None
        case = self.current_case_provider()
        if case is None:
            # Return a _WorkspaceProjectProxy with no model
            return _WorkspaceProjectProxy(ws, case=None)
        return _WorkspaceProjectProxy(ws, case=case)

    def current_case(self) -> "Case | None":
        return self.current_case_provider()

    def affected_analysis_ids(self) -> set[str]:
        case = self.current_case_provider()
        if case is None:
            return set()
        return {a.id for a in case.analyses}

    def discard_runs_for_active_case(self) -> None:
        case = self.current_case_provider()
        if case is None:
            return
        analysis_ids = self.affected_analysis_ids()
        if not analysis_ids:
            return
        # Mark stale — import locally to avoid circular
        try:
            from quino.services.run_invalidation import _mark_set_stale
            _mark_set_stale(case, analysis_ids, "model edited")
        except (ImportError, TypeError):
            pass

    def confirm_invalidation_if_runs_exist(self) -> bool:
        case = self.current_case_provider()
        if case is None:
            return True
        analysis_ids = self.affected_analysis_ids()
        if not analysis_ids:
            return True
        has_ok_run = any(
            r.analysis_id in analysis_ids and r.status in {"ok", "partial"}
            for r in case.runs
        )
        if not has_ok_run:
            return True
        return bool(self.confirm_run_invalidation())

    # ------------------------------------------------------------------
    # Back-compat helpers (used by old command-service code via context)
    # ------------------------------------------------------------------

    def get_active_case(self):
        """Return the active Case if one is set, otherwise None."""
        return self.current_case_provider()

    def effective_project(self):
        """Return a read-only composed-project-style view for backward compat."""
        return self.project_provider()


# ---------------------------------------------------------------------------
# _WorkspaceProjectProxy — bridges old command-service expectations to the
# new Workspace/Case domain model.  Command-services that call
# ctx.project_provider() get one of these instead of a real Project.
# ---------------------------------------------------------------------------

class _WorkspaceProjectProxy:
    """Thin proxy that makes a (Workspace, Case) pair look like the old Project.

    Only the attributes that existing command-services access are provided.
    Mutation goes directly through the underlying Case / Workspace objects, so
    deepcopy-based undo still works correctly.
    """

    __slots__ = ("_ws", "_case")

    def __init__(self, ws: "Workspace", case: "Case | None") -> None:
        self._ws = ws
        self._case = case

    # --- model-level lists (route to Case.model) ---

    @property
    def model(self):
        return self._case.model if self._case is not None else None

    @property
    def parameters(self):
        return self._ws.parameters

    @parameters.setter
    def parameters(self, value):
        self._ws.parameters = value

    @property
    def sketch(self):
        return self._ws.sketch

    @sketch.setter
    def sketch(self, value):
        self._ws.sketch = value

    @property
    def poses(self):
        if self._case is None:
            return []
        return self._case.poses

    @poses.setter
    def poses(self, value):
        if self._case is not None:
            self._case.poses = value

    @property
    def runs(self):
        if self._case is None:
            return []
        return self._case.runs

    @property
    def analyses(self):
        if self._case is None:
            return []
        return self._case.analyses

    @property
    def sensor_outputs(self):
        if self._case is None:
            return {}
        return self._case.sensor_outputs

    @property
    def reaction_outputs(self):
        if self._case is None:
            return {}
        return self._case.reaction_outputs

    @property
    def simulation_initial_pose_id(self) -> "str | None":
        # Old model had this on Project; derive from Case.poses.
        # The auto-created reference pose (is_default=True with no body_poses)
        # is not a simulation initial pose — only a pose explicitly marked as
        # default AND containing body data acts as the simulation initial.
        if self._case is None:
            return None
        for p in self._case.poses:
            if getattr(p, "is_default", False) and p.body_poses:
                return p.id
        return None

    @simulation_initial_pose_id.setter
    def simulation_initial_pose_id(self, value):
        # Mark the target user pose as is_default; clear it on other user poses.
        # The auto-created reference pose (body_poses == {}) is left untouched —
        # it is always is_default=True and is never a simulation initial pose.
        if self._case is None:
            return
        for p in self._case.poses:
            if not p.body_poses:
                # Reference pose: keep its is_default flag intact.
                continue
            p.is_default = (p.id == value)

    @property
    def id(self) -> str:
        return self._ws.id

    @property
    def name(self) -> str:
        return self._ws.name

    @name.setter
    def name(self, value: str) -> None:
        self._ws.name = value

    @property
    def schema_version(self) -> str:
        return self._ws.schema_version

    @property
    def view_state(self):
        return self._ws.view_state

    @view_state.setter
    def view_state(self, value) -> None:
        self._ws.view_state = value

    @property
    def metadata(self):
        return getattr(self._ws, "metadata", None)

    @property
    def workspace(self):
        """Old Project.workspace accessor — returns None (no nested workspace)."""
        return None

    def __repr__(self) -> str:
        case_id = self._case.id if self._case is not None else None
        return f"<_WorkspaceProjectProxy ws={self._ws.id!r} case={case_id!r}>"
