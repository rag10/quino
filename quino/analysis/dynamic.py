from __future__ import annotations

from quino.analysis.runner import AnalysisResult, AnalysisRunner


class DynamicAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        errors: list[str] = []
        if not project.model.bodies:
            errors.append("No bodies in model")
        return errors

    def run(self, project, analysis, *, initial_pose=None) -> AnalysisResult:
        try:
            from quino.services.workspace_runner import run_analysis as _run_analysis
            from quino.simulation.runner import SimulationRunner

            runner = SimulationRunner()
            run = _run_analysis(project, analysis.id, runner)
            status = "ok" if run.status == "ok" else "failed"
            error_message = ""
            if run.entries:
                entry = run.entries[0]
                if entry.status != "ok":
                    error_message = entry.error_message or ""
            return AnalysisResult(
                analysis_id=analysis.id,
                analysis_type="dynamic",
                status=status,
                error_message=error_message,
            )
        except Exception as exc:
            return AnalysisResult(
                analysis_id=analysis.id,
                analysis_type="dynamic",
                status="failed",
                error_message=str(exc),
            )
