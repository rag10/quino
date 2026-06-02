from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from quino.application._context import ServiceContext
from quino.domain.workspace import (
    Analysis,
    Case,
    Workspace,
    create_default_pose,
)


class WorkspaceCommands:
    """Command-service for workspace-level operations (cases, analyses, runs).

    NOTE: This class is in transition.  The previous implementation used the
    old domain model (Baseline, WorkspacePose, ws.cases as list).  In the
    case-as-model redesign (Task 16+) the Workspace holds cases as a dict and
    no longer has Baseline or WorkspacePose objects.

    Task 17 will rewrite the methods here to use CascadingEngine.  For now
    the class is kept importable and the methods that the GUI or tests still
    call are forwarded to the workspace state via context.
    """

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    # ------------------------------------------------------------------ helpers

    @property
    def _workspace(self) -> Workspace | None:
        return self._ctx.workspace_provider()

    def _ensure_workspace(self) -> Workspace:
        ws = self._workspace
        if ws is None:
            raise ValueError("No active workspace")
        return ws

    # ------------------------------------------------------------------ baseline (no-op shims)
    # The Baseline concept was removed in the case-as-model redesign.
    # These stubs keep call sites in GUI/tests alive until Task 25 cleans them.

    def create_baseline(self, name: str) -> None:
        """No-op: Baseline was removed in case-as-model redesign."""
        pass

    def rename_baseline(self, baseline_id: str, name: str) -> None:
        pass

    def delete_baseline(self, baseline_id: str) -> None:
        pass

    # ------------------------------------------------------------------ case operations

    def create_case(
        self,
        name: str,
        baseline_id: str | None = None,
        parent_case_id: str | None = None,
    ) -> Case:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        if parent_case_id is not None:
            return self.fork_case(parent_case_id, name)
        new_id = self._ctx.ids.new("case")
        from quino.domain.model import Model
        case = Case(
            id=new_id,
            name=name,
            model=Model(),
            poses=[create_default_pose(self._ctx.ids.new("pose"))],
        )
        ws.cases[new_id] = case
        if new_id not in ws.root_case_ids:
            ws.root_case_ids.append(new_id)
        return case

    def fork_case(self, parent_case_id: str, name: str) -> Case:
        """Fork a case using CascadingEngine."""
        from quino.services.case_cascading import CascadingEngine
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        engine = CascadingEngine(ws)
        new_id = engine.fork_case(parent_case_id, name)
        ws.selected_case_id = new_id
        self._clear_invalid_selections(ws)
        return ws.cases[new_id]

    def duplicate_case(self, case_id: str, *, new_name: str | None = None) -> Case:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        from quino.services.case_cascading import CascadingEngine
        engine = CascadingEngine(ws)
        new_id = engine.duplicate_case(case_id, new_name)
        ws.selected_case_id = new_id
        self._clear_invalid_selections(ws)
        return ws.cases[new_id]

    def rename_case(self, case_id: str, name: str) -> None:
        self._ctx.snapshot()
        case = self._find_case(case_id)
        case.name = name

    def delete_case(self, case_id: str) -> None:
        ws = self._ensure_workspace()
        if case_id in ws.root_case_ids and len(ws.root_case_ids) == 1:
            raise ValueError("Cannot delete the last root case")
        self._ctx.snapshot()
        descendant_ids = self._collect_descendant_case_ids(ws, case_id)
        remove_ids = {case_id, *descendant_ids}
        for rid in remove_ids:
            ws.cases.pop(rid, None)
        ws.root_case_ids = [cid for cid in ws.root_case_ids if cid not in remove_ids]
        if ws.selected_case_id in remove_ids:
            ws.selected_case_id = next(iter(ws.cases), None)

    # ------------------------------------------------------------------ working context

    def set_working_context(
        self,
        *,
        case_id: str | None = None,
        baseline_id: str | None = None,
    ) -> None:
        """Select the active case for editing."""
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.selected_case_id = case_id
        self._clear_invalid_selections(ws)

    # ------------------------------------------------------------------ pose (workspace-level)

    def create_pose(
        self,
        name: str,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
        project_pose_id: str | None = None,
        is_default: bool = False,
    ) -> object:
        """Create a pose on the target case (or active case if not specified)."""
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        target_case_id = case_id or ws.selected_case_id
        if target_case_id is None:
            raise ValueError("No active case to create a pose on")
        from quino.domain.workspace import Pose
        case = ws.cases.get(target_case_id)
        if case is None:
            raise ValueError(f"Case {target_case_id!r} not found")
        pose_id = self._ctx.ids.new("pose")
        pose = Pose(id=pose_id, name=name, is_default=is_default)
        case.poses.append(pose)
        return pose

    def rename_pose(self, pose_id: str, name: str) -> None:
        pose = self._find_pose_across_cases(pose_id)
        if pose is None:
            return
        if getattr(pose, "is_default", False):
            raise ValueError("Cannot rename the reference pose")
        self._ctx.snapshot()
        pose.name = name

    def delete_pose(self, pose_id: str, *, cascade: bool = False) -> None:
        ws = self._ensure_workspace()
        pose = self._find_pose_across_cases(pose_id)
        if pose is None:
            return
        if getattr(pose, "is_default", False):
            raise ValueError("Cannot delete the reference pose")
        owner_case = self._find_case_for_pose(pose_id)
        if owner_case is None:
            return
        bound_analyses = [a for a in owner_case.analyses if a.pose_id == pose_id]
        if bound_analyses and not cascade:
            raise ValueError(
                f"Cannot delete pose with {len(bound_analyses)} analyses; "
                "delete its analyses first or pass cascade=True"
            )
        self._ctx.snapshot()
        if cascade:
            removed_analysis_ids = {a.id for a in bound_analyses}
            owner_case.analyses = [a for a in owner_case.analyses if a.id not in removed_analysis_ids]
        owner_case.poses = [p for p in owner_case.poses if p.id != pose_id]
        if ws.selected_pose_id == pose_id:
            fallback = next((p.id for p in owner_case.poses if not p.is_default), None)
            ws.selected_pose_id = fallback
            try:
                self._ctx.set_current_pose_id(fallback)
            except Exception:
                pass
        if ws.selected_analysis_id is not None and all(a.id != ws.selected_analysis_id for a in owner_case.analyses):
            ws.selected_analysis_id = None

    def duplicate_pose(self, pose_id: str, *, new_name: str | None = None):
        import copy as _copy
        self._ensure_workspace()
        owner_case = self._find_case_for_pose(pose_id)
        if owner_case is None:
            raise ValueError(f"Pose {pose_id!r} not found")
        src = next(p for p in owner_case.poses if p.id == pose_id)
        self._ctx.snapshot()
        new_pose = _copy.deepcopy(src)
        new_pose.id = self._ctx.ids.new("pose")
        new_pose.name = new_name or f"{src.name} copy"
        new_pose.is_default = False
        owner_case.poses.append(new_pose)
        return new_pose

    def set_selected_pose(self, pose_id: str | None) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        if pose_id is not None:
            owner = self._find_case_for_pose(pose_id)
            if owner is None:
                raise ValueError(f"Pose {pose_id!r} not found")
            ws.selected_case_id = owner.id
            pose = next(p for p in owner.poses if p.id == pose_id)
            try:
                self._ctx.set_current_pose_id(None if pose.is_default else pose_id)
            except Exception:
                pass
            if ws.selected_analysis_id is not None:
                analysis = next((a for a in owner.analyses if a.id == ws.selected_analysis_id), None)
                if analysis is None or analysis.pose_id != pose_id:
                    ws.selected_analysis_id = None
        else:
            try:
                self._ctx.set_current_pose_id(None)
            except Exception:
                pass
        ws.selected_pose_id = pose_id

    # ------------------------------------------------------------------ analysis

    def create_analysis(
        self,
        name: str,
        *,
        analysis_type: str = "dynamic",
        baseline_id: str | None = None,
        case_id: str | None = None,
        workspace_pose_id: str | None = None,
        config=None,
    ) -> Analysis:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        target_case_id = case_id or ws.selected_case_id
        if target_case_id is None:
            raise ValueError("No case specified for analysis")
        case = ws.cases.get(target_case_id)
        if case is None:
            raise ValueError(f"Case {target_case_id!r} not found")
        if workspace_pose_id is None:
            default_pose = next((p for p in case.poses if p.is_default), None)
            workspace_pose_id = default_pose.id if default_pose is not None else None
        elif all(p.id != workspace_pose_id for p in case.poses):
            raise ValueError(f"Pose {workspace_pose_id!r} not found in case {target_case_id!r}")
        analysis_id = self._ctx.ids.new("analysis")
        analysis = Analysis(
            id=analysis_id,
            name=name,
            analysis_type=analysis_type,
            pose_id=workspace_pose_id,
            config=config,
        )
        case.analyses.append(analysis)
        return analysis

    def rename_analysis(self, analysis_id: str, name: str) -> None:
        self._ctx.snapshot()
        analysis = self._find_analysis_across_cases(analysis_id)
        if analysis is not None:
            analysis.name = name

    def delete_analysis(self, analysis_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        for case in ws.cases.values():
            before = len(case.analyses)
            case.analyses = [a for a in case.analyses if a.id != analysis_id]
            if len(case.analyses) < before:
                # Run state lives on the Analysis itself, so removing the
                # analysis already drops its run state.
                if ws.selected_analysis_id == analysis_id:
                    ws.selected_analysis_id = None
                break

    def duplicate_analysis(self, analysis_id: str, *, new_name: str | None = None) -> Analysis:
        import copy as _copy
        ws = self._ensure_workspace()
        for case in ws.cases.values():
            src = next((a for a in case.analyses if a.id == analysis_id), None)
            if src is None:
                continue
            self._ctx.snapshot()
            new_analysis = _copy.deepcopy(src)
            new_analysis.id = self._ctx.ids.new("analysis")
            new_analysis.name = new_name or f"{src.name} copy"
            case.analyses.append(new_analysis)
            return new_analysis
        raise ValueError(f"Analysis {analysis_id!r} not found")

    def delete_run(self, run_id: str) -> None:
        # Fase 1.10: the ``Run`` entity and ``Case.runs`` were removed; run state
        # now lives flattened on ``Analysis``. Standalone run deletion no longer
        # applies; the migrated semantics (resetting an analysis' run state) are
        # deferred to a later Fase. No-op for now to keep the API importable.
        return None

    def set_selected_analysis(self, analysis_id: str | None) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        if analysis_id is not None:
            owner, analysis = self._find_case_and_analysis(analysis_id)
            if owner is None or analysis is None:
                raise ValueError(f"Analysis {analysis_id!r} not found")
            ws.selected_case_id = owner.id
            ws.selected_pose_id = analysis.pose_id
        ws.selected_analysis_id = analysis_id

    def _clear_invalid_selections(self, ws: Workspace) -> None:
        case = ws.cases.get(ws.selected_case_id) if ws.selected_case_id is not None else None
        if case is None:
            ws.selected_pose_id = None
            ws.selected_analysis_id = None
            return
        if ws.selected_pose_id is not None and all(p.id != ws.selected_pose_id for p in case.poses):
            ws.selected_pose_id = None
        if (
            ws.selected_analysis_id is not None
            and all(a.id != ws.selected_analysis_id for a in case.analyses)
        ):
            ws.selected_analysis_id = None

    def run_analysis(
        self,
        analysis_id: str,
        simulation_runner=None,
        project_dir: Path | None = None,
    ) -> Analysis:
        raise NotImplementedError(
            "WorkspaceCommands.run_analysis is not yet implemented in the case-as-model redesign"
        )

    def refresh_parameter_catalog(self) -> None:
        """No-op stub until Task 17 updates the catalog service."""
        pass

    # ------------------------------------------------------------------ finders

    def _find_case(self, case_id: str) -> Case:
        ws = self._ensure_workspace()
        case = ws.cases.get(case_id)
        if case is None:
            raise ValueError(f"Case {case_id!r} not found")
        return case

    def _find_pose_across_cases(self, pose_id: str):
        ws = self._workspace
        if ws is None:
            return None
        # Prefer the active case if it owns the pose, otherwise fall back to
        # global search. This protects against legacy workspaces with colliding
        # pose IDs across cases (id_service didn't observe pose ids before).
        active = ws.cases.get(ws.selected_case_id) if ws.selected_case_id else None
        if active is not None:
            for p in active.poses:
                if p.id == pose_id:
                    return p
        for case in ws.cases.values():
            for p in case.poses:
                if p.id == pose_id:
                    return p
        return None

    def _find_analysis_across_cases(self, analysis_id: str):
        ws = self._workspace
        if ws is None:
            return None
        for case in ws.cases.values():
            for a in case.analyses:
                if a.id == analysis_id:
                    return a
        return None

    def _find_case_for_pose(self, pose_id: str) -> Case | None:
        ws = self._workspace
        if ws is None:
            return None
        active = ws.cases.get(ws.selected_case_id) if ws.selected_case_id else None
        if active is not None and any(p.id == pose_id for p in active.poses):
            return active
        for case in ws.cases.values():
            if any(p.id == pose_id for p in case.poses):
                return case
        return None

    def _find_case_and_analysis(self, analysis_id: str) -> tuple[Case | None, Analysis | None]:
        ws = self._workspace
        if ws is None:
            return None, None
        active = ws.cases.get(ws.selected_case_id) if ws.selected_case_id else None
        if active is not None:
            analysis = next((a for a in active.analyses if a.id == analysis_id), None)
            if analysis is not None:
                return active, analysis
        for case in ws.cases.values():
            analysis = next((a for a in case.analyses if a.id == analysis_id), None)
            if analysis is not None:
                return case, analysis
        return None, None

    def _collect_descendant_case_ids(self, ws: Workspace, case_id: str) -> set[str]:
        descendants: set[str] = set()
        frontier = [case_id]
        while frontier:
            current = frontier.pop()
            children = [cid for cid, c in ws.cases.items() if c.parent_case_id == current]
            for child in children:
                if child not in descendants:
                    descendants.add(child)
                    frontier.append(child)
        return descendants

    # ------------------------------------------------------------------ study (stub)

    def run_study(self, *args, **kwargs):
        raise NotImplementedError("run_study not yet implemented in case-as-model redesign")
