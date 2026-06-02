from __future__ import annotations

import hashlib
import json
from pathlib import Path

from quino.analysis.runner import AnalysisResult, AnalysisRunner
from quino.analysis.static_runner import _effective_dof
from quino.domain.workspace import Analysis, ResultRef
from quino.services.metric_evaluator import evaluate_metrics
from quino.services.equilibrium_finder import find_stable_equilibria


class EquilibriumAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        dof = _effective_dof(project)
        errors: list[str] = []
        if dof <= 0:
            errors.append(f"DoF={dof}. Equilibrium analysis is meaningful only for DoF > 0.")
            return errors
        if project.model.gravity is None and not project.model.springs and not project.model.loads:
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
                project,
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
            artifact_path = self._persist_artifact(project_dir, run, equilibria)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            run.metrics = evaluate_metrics(list(analysis.config.metrics), artifact)
        return AnalysisResult(
            analysis_id=analysis.id,
            analysis_type="equilibrium",
            status="ok" if equilibria else "partial",
        )

    def _persist_artifact(self, project_dir: Path, run: Analysis, equilibria: list[dict]) -> Path:
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
        return path
