from __future__ import annotations

from quino.domain.model import SimulationResult
from quino.analysis.runner import AnalysisResult, AnalysisRunner


class DynamicAnalysisRunner(AnalysisRunner):
    def validate(self, project, analysis) -> list[str]:
        errors: list[str] = []
        if not project.model.bodies:
            errors.append("No bodies in model")
        return errors

    def run(
        self,
        project,
        analysis,
        *,
        initial_pose=None,
        cancel_event=None,
        run=None,
        project_dir=None,
    ) -> AnalysisResult:
        try:
            from quino.services.workspace_runner import save_result_artifact

            from quino.services.expressions import ExpressionService
            from quino.services.units import UnitService
            from quino.simulation.runner import SimulationRunner
            from quino.solver_adapters.exudyn_adapter import ExudynAdapter

            simulation_runner = SimulationRunner(ExudynAdapter(ExpressionService(UnitService())))

            result: SimulationResult = simulation_runner.run(
                project,
                duration=analysis.config.duration,
                steps=analysis.config.steps,
                cancel_event=cancel_event,
            )

            cancelled = (
                cancel_event is not None and cancel_event.is_set()
            ) or (result.error == "Simulation cancelled by user")
            if cancelled:
                return AnalysisResult(
                    analysis_id=analysis.id,
                    analysis_type="dynamic",
                    status="to_be_run",
                    frames=result.frames,
                    error_message="Cancelled by user",
                )

            if project_dir is not None and run is not None:
                save_result_artifact(project_dir, run, result)

            status = "ok" if result.success else "failed"
            return AnalysisResult(
                analysis_id=analysis.id,
                analysis_type="dynamic",
                status=status,
                frames=result.frames,
                error_message=result.error or "",
            )
        except Exception as exc:
            return AnalysisResult(
                analysis_id=analysis.id,
                analysis_type="dynamic",
                status="failed",
                error_message=str(exc),
            )
