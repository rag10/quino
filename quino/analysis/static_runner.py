from __future__ import annotations

import hashlib
import json
from pathlib import Path

from quino.analysis.runner import AnalysisResult, AnalysisRunner
from quino.domain.workspace import Analysis, ResultRef
from quino.services.mechanism_dof import compute_mechanism_dof
from quino.services.static_solver import solve_static


def _effective_dof(project) -> int:
    dof = compute_mechanism_dof(project, pose_constraint_count=0).total_dof
    return max(dof - len(project.model.drivers), 0)


class StaticAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        dof = _effective_dof(project)
        errors: list[str] = []
        if dof != 0:
            errors.append(
                f"DoF={dof}. Static analysis requires DoF=0. "
                "Lock drivers or add model constraints before running."
            )
            return errors
        if not project.model.loads and project.model.gravity is None and not project.model.springs:
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
            report = solve_static(project, analysis.config)
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

    def _persist_artifact(self, project_dir: Path, run: Analysis, report: dict) -> Path:
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
        return path
