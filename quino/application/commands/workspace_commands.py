from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from quino.application._context import ServiceContext
from quino.domain.workspace import (
    Analysis,
    Case,
    Run,
    Workspace,
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
        new_id = self._ctx.ids.new("case")
        parent = ws.cases.get(parent_case_id) if parent_case_id else None
        from quino.domain.model import Model
        case = Case(
            id=new_id,
            name=name,
            parent_case_id=parent_case_id,
            model=Model(),
        )
        ws.cases[new_id] = case
        if new_id not in ws.root_case_ids and parent_case_id is None:
            ws.root_case_ids.append(new_id)
        return case

    def fork_case(self, parent_case_id: str, name: str) -> Case:
        """Fork a case using CascadingEngine."""
        from quino.services.case_cascading import CascadingEngine
        ws = self._ensure_workspace()
        engine = CascadingEngine(ws)
        new_id = engine.fork_case(parent_case_id, name)
        self._ctx.snapshot()
        return ws.cases[new_id]

    def duplicate_case(self, case_id: str, *, new_name: str | None = None) -> Case:
        import copy as _copy
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        source = ws.cases.get(case_id)
        if source is None:
            raise ValueError(f"Case {case_id!r} not found")
        target_name = new_name or f"{source.name} copy"
        new_id = self._ctx.ids.new("case")
        new_case = Case(
            id=new_id,
            name=target_name,
            parent_case_id=source.parent_case_id,
            model=_copy.deepcopy(source.model),
        )
        ws.cases[new_id] = new_case
        return new_case

    def rename_case(self, case_id: str, name: str) -> None:
        self._ctx.snapshot()
        case = self._find_case(case_id)
        case.name = name

    def delete_case(self, case_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
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
        self._ctx.snapshot()
        pose = self._find_pose_across_cases(pose_id)
        if pose is not None:
            pose.name = name

    def delete_pose(self, pose_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        for case in ws.cases.values():
            before = len(case.poses)
            case.poses = [p for p in case.poses if p.id != pose_id]
            if len(case.poses) < before:
                break
        if ws.selected_pose_id == pose_id:
            ws.selected_pose_id = None

    def set_selected_pose(self, pose_id: str | None) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.selected_pose_id = pose_id
        if pose_id is None:
            try:
                self._ctx.set_current_pose_id(None)
            except Exception:
                pass

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
                break

    def set_selected_analysis(self, analysis_id: str | None) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.selected_analysis_id = analysis_id

    def run_analysis(
        self,
        analysis_id: str,
        simulation_runner=None,
        project_dir: Path | None = None,
    ) -> Run:
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
