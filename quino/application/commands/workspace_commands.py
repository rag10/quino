from __future__ import annotations

from pathlib import Path
from typing import Callable

from quino.application._context import ServiceContext
from quino.domain.workspace import (
    Baseline,
    Case,
    CaseGroup,
    Run,
    Study,
    StudyConfig,
    StudyMask,
    Workspace,
)
from quino.services.workspace_invalidation import (
    invalidate_on_baseline_change,
    invalidate_on_case_change,
    invalidate_on_study_change,
)
from quino.services.workspace_runner import run_study as _run_study


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
        return project.workspace

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
        invalidate_on_baseline_change(self._project, baseline_id)

    # --- case --------------------------------------------------------------

    def create_case(self, name: str, baseline_id: str | None = None) -> Case:
        self._ctx.snapshot()
        case = Case(id=self._next_id("case"), name=name, baseline_id=baseline_id)
        self._ensure_workspace().cases.append(case)
        return case

    def rename_case(self, case_id: str, name: str) -> None:
        self._ctx.snapshot()
        case = self._find_case(case_id)
        case.name = name
        invalidate_on_case_change(self._project, case_id)

    def delete_case(self, case_id: str) -> None:
        self._ctx.snapshot()
        ws = self._ensure_workspace()
        ws.cases = [c for c in ws.cases if c.id != case_id]
        invalidate_on_case_change(self._project, case_id)

    def update_case_invariants(self, case_id: str, invariants: dict[str, float | str]) -> None:
        """Set invariant values on a case.

        *invariants* is a dict of path → value. If value is a float, unit is
        assumed empty; if a str, it is parsed as ``value unit``.
        """
        self._ctx.snapshot()
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
