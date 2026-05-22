from __future__ import annotations

import hashlib
import json
from pathlib import Path

from quino.analysis.runner import AnalysisResult, AnalysisRunner
from quino.analysis.static_runner import _effective_dof
from quino.domain.workspace import ResultRef, Run
from quino.services.equilibrium_finder import find_stable_equilibria
from quino.services.workspace_composition import compose_project


class EquilibriumAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        composed = self._compose(project, analysis)
        dof = _effective_dof(composed)
        errors: list[str] = []
        if dof <= 0:
            errors.append(f"DoF={dof}. Equilibrium analysis is meaningful only for DoF > 0.")
            return errors
        if composed.model.gravity is None and not composed.model.springs and not composed.model.loads:
            errors.append("No force source (gravity, springs or loads): no equilibrium to find.")
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
        try:
            equilibria = find_stable_equilibria(
                self._compose(project, analysis),
                analysis.config,
                initial_pose=initial_pose,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            return AnalysisResult(
                analysis_id=analysis.id,
                analysis_type="equilibrium",
                status="failed",
                error_message=str(exc),
            )
        if project_dir is not None and run is not None:
            self._persist_artifact(project_dir, run, equilibria)
        return AnalysisResult(
            analysis_id=analysis.id,
            analysis_type="equilibrium",
            status="ok" if equilibria else "partial",
        )

    def _compose(self, project, analysis):
        case = next(
            (case for case in (project.workspace.cases if project.workspace else []) if case.id == analysis.case_id),
            None,
        )
        return compose_project(project, case=case)

    def _persist_artifact(self, project_dir: Path, run: Run, equilibria: list[dict]) -> None:
        artifact_dir = project_dir / "artifacts" / f"run_{run.id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / "result.json"
        payload = {"type": "equilibrium", "equilibria": equilibria}
        path.write_text(json.dumps(payload), encoding="utf-8")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        run.result_ref = ResultRef(
            run_entry_id=run.id,
            artifact_path=str(path.relative_to(project_dir)),
            checksum=f"sha256:{checksum}",
        )
