from __future__ import annotations

import hashlib
import json
from pathlib import Path

from quino.analysis.runner import AnalysisResult, AnalysisRunner
from quino.domain.workspace import ResultRef, Run
from quino.services.mechanism_dof import compute_mechanism_dof
from quino.services.static_solver import solve_static
from quino.services.workspace_composition import compose_project


def _effective_dof(project) -> int:
    dof = compute_mechanism_dof(project, pose_constraint_count=0).total_dof
    return max(dof - len(project.model.drivers), 0)


class StaticAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        composed = self._compose(project, analysis)
        dof = _effective_dof(composed)
        errors: list[str] = []
        if dof != 0:
            errors.append(
                f"DoF={dof}. Static analysis requires DoF=0. "
                "Lock drivers or add model constraints before running."
            )
            return errors
        if not composed.model.loads and composed.model.gravity is None and not composed.model.springs:
            errors.append("WARNING: No external loads; equilibrium is trivial.")
        return errors

    def run(
        self,
        project,
        analysis,
        *,
        initial_pose=None,
        cancel_event=None,
        run=None,
        project_dir: Path | None = None,
    ) -> AnalysisResult:
        if cancel_event is not None and cancel_event.is_set():
            return AnalysisResult(
                analysis_id=analysis.id,
                analysis_type="static",
                status="to_be_run",
                error_message="Cancelled by user",
            )
        try:
            report = solve_static(self._compose(project, analysis), analysis.config)
        except Exception as exc:
            return AnalysisResult(
                analysis_id=analysis.id,
                analysis_type="static",
                status="failed",
                error_message=str(exc),
            )
        if project_dir is not None and run is not None:
            self._persist_artifact(project_dir, run, report)
        return AnalysisResult(
            analysis_id=analysis.id,
            analysis_type="static",
            status="ok",
        )

    def _compose(self, project, analysis):
        case = next(
            (case for case in (project.workspace.cases if project.workspace else []) if case.id == analysis.case_id),
            None,
        )
        return compose_project(project, case=case)

    def _persist_artifact(self, project_dir: Path, run: Run, report: dict) -> None:
        artifact_dir = project_dir / "artifacts" / f"run_{run.id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / "result.json"
        payload = {"type": "static", **report}
        path.write_text(json.dumps(payload), encoding="utf-8")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        run.result_ref = ResultRef(
            run_entry_id=run.id,
            artifact_path=str(path.relative_to(project_dir)),
            checksum=f"sha256:{checksum}",
        )
