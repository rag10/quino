from __future__ import annotations

from pathlib import Path
from typing import Callable

from quino.application._context import ServiceContext
from quino.domain.workspace import (
    Analysis,
    Baseline,
    Case,
    CaseGroup,
    Run,
    Study,
    StudyConfig,
    StudyMask,
    Workspace,
    WorkspacePose,
)
from quino.services.workspace_invalidation import (
    invalidate_on_analysis_change,
    invalidate_on_baseline_change,
    invalidate_on_case_change,
    invalidate_on_pose_change,
    invalidate_on_study_change,
)
from quino.services.workspace_catalog import build_parameter_catalog
from quino.services.workspace_runner import run_study as _run_study
from quino.services.workspace_runner import run_analysis as _run_analysis


class WorkspaceCommands:
    """Command-service for workspace operations (cases, studies, runs)."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    @property
    def _project(self):
        project = self._ctx.project_provider()
        if project is None:
            raise ValueError("No active project")
        return project

    def _ensure_workspace(self) -> Workspace:
        project = self._project
        if project.workspace is None:
            project.workspace = Workspace()
        if not project.workspace.parameter_catalog:
            project.workspace.parameter_catalog = build_parameter_catalog(project)
        return project.workspace

    def refresh_parameter_catalog(self) -> None:
        ws = self._ensure_workspace()
        ws.parameter_catalog = build_parameter_catalog(self._project)

    def _next_id(self, prefix: str) -> str:
        ws = self._ensure_workspace()
        seq = ws.next_sequence
        ws.next_sequence = seq + 1
        return f"{prefix}_{seq:03d}"

    # --- baseline ----------------------------------------------------------

    def create_baseline(self, name: str) -> Baseline:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        baseline = Baseline(id=self._next_id("baseline"), name=name)
        ws.baselines.append(baseline)
        if ws.active_baseline_id is None:
            ws.active_baseline_id = baseline.id
        self._ensure_default_pose(baseline_id=baseline.id)
        return baseline

    def rename_baseline(self, baseline_id: str, name: str) -> None:
        self._ctx.snapshot()
        baseline = self._find_baseline(baseline_id)
        baseline.name = name
        invalidate_on_baseline_change(self._project, baseline_id)

    def delete_baseline(self, baseline_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.baselines = [b for b in ws.baselines if b.id != baseline_id]
        ws.poses = [p for p in ws.poses if p.baseline_id != baseline_id]
        ws.analyses = [a for a in ws.analyses if a.baseline_id != baseline_id]
        if ws.active_baseline_id == baseline_id:
            ws.active_baseline_id = ws.baselines[0].id if ws.baselines else None
        invalidate_on_baseline_change(self._project, baseline_id)

    # --- case --------------------------------------------------------------

    def create_case(
        self,
        name: str,
        baseline_id: str | None = None,
        parent_case_id: str | None = None,
    ) -> Case:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        parent_case = self._find_case(parent_case_id) if parent_case_id is not None else None
        resolved_baseline_id = baseline_id or (
            parent_case.baseline_id if parent_case is not None else ws.active_baseline_id
        )
        case = Case(
            id=self._next_id("case"),
            name=name,
            baseline_id=resolved_baseline_id,
            parent_case_id=parent_case_id,
        )
        ws.cases.append(case)
        self._ensure_default_pose(case_id=case.id)
        return case

    def rename_case(self, case_id: str, name: str) -> None:
        self._ctx.snapshot()
        case = self._find_case(case_id)
        case.name = name
        invalidate_on_case_change(self._project, case_id)

    def delete_case(self, case_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        descendant_case_ids = self._collect_descendant_case_ids(ws, case_id)
        remove_case_ids = {case_id, *descendant_case_ids}
        ws.cases = [c for c in ws.cases if c.id not in remove_case_ids]
        ws.poses = [
            p for p in ws.poses
            if p.case_id not in remove_case_ids
        ]
        ws.analyses = [
            a for a in ws.analyses
            if a.case_id not in remove_case_ids
        ]
        invalidate_on_case_change(self._project, case_id)

    # --- workspace poses --------------------------------------------------

    def create_pose(
        self,
        name: str,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
        project_pose_id: str | None = None,
        is_default: bool = False,
    ) -> WorkspacePose:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        pose = WorkspacePose(
            id=self._next_id("wpose"),
            name=name,
            baseline_id=baseline_id,
            case_id=case_id,
            project_pose_id=project_pose_id,
            is_default=is_default,
        )
        if is_default:
            self._clear_default_pose(ws, baseline_id=baseline_id, case_id=case_id)
        ws.poses.append(pose)
        return pose

    def rename_pose(self, workspace_pose_id: str, name: str) -> None:
        self._ctx.snapshot()
        pose = self._find_pose(workspace_pose_id)
        pose.name = name
        invalidate_on_pose_change(self._project, workspace_pose_id)

    def delete_pose(self, workspace_pose_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        analysis_ids = [a.id for a in ws.analyses if a.workspace_pose_id == workspace_pose_id]
        ws.poses = [p for p in ws.poses if p.id != workspace_pose_id]
        ws.analyses = [a for a in ws.analyses if a.workspace_pose_id != workspace_pose_id]
        invalidate_on_pose_change(self._project, workspace_pose_id)
        for analysis_id in analysis_ids:
            invalidate_on_analysis_change(self._project, analysis_id)

    # --- analyses ---------------------------------------------------------

    def create_analysis(
        self,
        name: str,
        *,
        analysis_type: str = "dynamic",
        baseline_id: str | None = None,
        case_id: str | None = None,
        workspace_pose_id: str | None = None,
        config: StudyConfig | None = None,
    ) -> Analysis:
        self._ctx.snapshot()
        analysis = Analysis(
            id=self._next_id("analysis"),
            name=name,
            analysis_type=analysis_type,
            baseline_id=baseline_id,
            case_id=case_id,
            workspace_pose_id=workspace_pose_id,
            config=config or StudyConfig(),
        )
        self._ensure_workspace().analyses.append(analysis)
        return analysis

    def rename_analysis(self, analysis_id: str, name: str) -> None:
        self._ctx.snapshot()
        analysis = self._find_analysis(analysis_id)
        analysis.name = name
        invalidate_on_analysis_change(self._project, analysis_id)

    def delete_analysis(self, analysis_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.analyses = [a for a in ws.analyses if a.id != analysis_id]
        invalidate_on_analysis_change(self._project, analysis_id)

    def set_working_context(
        self,
        *,
        case_id: str | None = None,
        baseline_id: str | None = None,
    ) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.active_case_id = case_id
        ws.active_baseline_id = baseline_id
        if case_id is not None:
            valid_poses = [p for p in ws.poses if p.case_id == case_id]
        else:
            valid_poses = [p for p in ws.poses if p.baseline_id == baseline_id and p.case_id is None]
        if ws.selected_pose_id and not any(p.id == ws.selected_pose_id for p in valid_poses):
            ws.selected_pose_id = None

    def set_selected_pose(self, pose_id: str | None) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.selected_pose_id = pose_id

    def set_selected_analysis(self, analysis_id: str | None) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.selected_analysis_id = analysis_id

    def update_case_invariants(self, case_id: str, invariants: dict[str, float | str]) -> None:
        """Set invariant values on a case.

        *invariants* is a dict of path → value. If value is a float, unit is
        assumed empty; if a str, it is parsed as ``value unit``.
        """
        self._ctx.snapshot()
        self.refresh_parameter_catalog()
        case = self._find_case(case_id)
        from quino.domain.workspace import ScalarValue

        parsed: dict[str, ScalarValue] = {}
        for path, value in invariants.items():
            if isinstance(value, str):
                parts = value.split()
                if len(parts) == 2:
                    parsed[path] = ScalarValue(float(parts[0]), parts[1])
                else:
                    parsed[path] = ScalarValue(float(parts[0]), "")
            else:
                parsed[path] = ScalarValue(float(value), "")
        case.invariant_values = parsed
        invalidate_on_case_change(self._project, case_id)

    # --- case group --------------------------------------------------------

    def create_case_group(self, name: str, baseline_id: str) -> CaseGroup:
        self._ctx.snapshot()
        cg = CaseGroup(id=self._next_id("casegroup"), name=name, baseline_id=baseline_id)
        self._ensure_workspace().case_groups.append(cg)
        return cg

    def rename_case_group(self, case_group_id: str, name: str) -> None:
        self._ctx.snapshot()
        cg = self._find_case_group(case_group_id)
        cg.name = name

    def delete_case_group(self, case_group_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.case_groups = [cg for cg in ws.case_groups if cg.id != case_group_id]

    # --- study -------------------------------------------------------------

    def create_study(
        self,
        name: str,
        study_type: str = "dynamic",
        config: StudyConfig | None = None,
        mask: StudyMask | None = None,
    ) -> Study:
        self._ctx.snapshot()
        study = Study(
            id=self._next_id("study"),
            name=name,
            study_type=study_type,
            config=config or StudyConfig(),
            mask=mask or StudyMask(),
        )
        self._ensure_workspace().studies.append(study)
        return study

    def rename_study(self, study_id: str, name: str) -> None:
        self._ctx.snapshot()
        study = self._find_study(study_id)
        study.name = name
        invalidate_on_study_change(self._project, study_id)

    def delete_study(self, study_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.studies = [s for s in ws.studies if s.id != study_id]
        invalidate_on_study_change(self._project, study_id)

    def update_study_config(self, study_id: str, config: StudyConfig) -> None:
        self._ctx.snapshot()
        study = self._find_study(study_id)
        study.config = config
        invalidate_on_study_change(self._project, study_id)

    def update_study_variables(self, study_id: str, values: dict[str, float | str]) -> None:
        self._ctx.snapshot()
        self.refresh_parameter_catalog()
        study = self._find_study(study_id)
        from quino.domain.workspace import ScalarValue

        parsed: dict[str, ScalarValue] = {}
        for path, value in values.items():
            if isinstance(value, str):
                parts = value.split()
                if len(parts) == 2:
                    parsed[path] = ScalarValue(float(parts[0]), parts[1])
                else:
                    parsed[path] = ScalarValue(float(parts[0]), "")
            else:
                parsed[path] = ScalarValue(float(value), "")
        study.variable_values = parsed
        invalidate_on_study_change(self._project, study_id)

    def run_study(
        self,
        study_id: str,
        simulation_runner,
        project_dir: Path | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Run:
        self._ctx.snapshot()
        run = _run_study(
            self._project,
            study_id,
            simulation_runner,
            project_dir=project_dir,
            progress_callback=progress_callback,
        )
        return run

    def run_analysis(
        self,
        analysis_id: str,
        simulation_runner,
        project_dir: Path | None = None,
    ) -> Run:
        self._ctx.snapshot()
        return _run_analysis(
            self._project,
            analysis_id,
            simulation_runner,
            project_dir=project_dir,
        )

    # --- finders -----------------------------------------------------------

    def _find_baseline(self, baseline_id: str) -> Baseline:
        for b in self._ensure_workspace().baselines:
            if b.id == baseline_id:
                return b
        raise ValueError(f"Baseline {baseline_id!r} not found")

    def _find_case(self, case_id: str) -> Case:
        for c in self._ensure_workspace().cases:
            if c.id == case_id:
                return c
        raise ValueError(f"Case {case_id!r} not found")

    def _find_case_group(self, case_group_id: str) -> CaseGroup:
        for cg in self._ensure_workspace().case_groups:
            if cg.id == case_group_id:
                return cg
        raise ValueError(f"CaseGroup {case_group_id!r} not found")

    def _find_study(self, study_id: str) -> Study:
        for s in self._ensure_workspace().studies:
            if s.id == study_id:
                return s
        raise ValueError(f"Study {study_id!r} not found")

    def _find_pose(self, workspace_pose_id: str) -> WorkspacePose:
        for pose in self._ensure_workspace().poses:
            if pose.id == workspace_pose_id:
                return pose
        raise ValueError(f"Workspace pose {workspace_pose_id!r} not found")

    def _find_analysis(self, analysis_id: str) -> Analysis:
        for analysis in self._ensure_workspace().analyses:
            if analysis.id == analysis_id:
                return analysis
        raise ValueError(f"Analysis {analysis_id!r} not found")

    def _ensure_default_pose(
        self,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
    ) -> WorkspacePose:
        ws = self._ensure_workspace()
        existing = next(
            (
                pose
                for pose in ws.poses
                if pose.is_default and pose.baseline_id == baseline_id and pose.case_id == case_id
            ),
            None,
        )
        if existing is not None:
            return existing
        pose = WorkspacePose(
            id=self._next_id("wpose"),
            name="Pose default",
            baseline_id=baseline_id,
            case_id=case_id,
            is_default=True,
        )
        ws.poses.append(pose)
        return pose

    def _clear_default_pose(
        self,
        ws: Workspace,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
    ) -> None:
        for pose in ws.poses:
            if pose.baseline_id == baseline_id and pose.case_id == case_id:
                pose.is_default = False

    def _collect_descendant_case_ids(self, ws: Workspace, case_id: str) -> set[str]:
        descendants: set[str] = set()
        frontier = [case_id]
        while frontier:
            current = frontier.pop()
            children = [case.id for case in ws.cases if case.parent_case_id == current]
            for child in children:
                if child not in descendants:
                    descendants.add(child)
                    frontier.append(child)
        return descendants
