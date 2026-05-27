from __future__ import annotations

import json

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

            # Resolve the analysis's initial pose. Explicit argument wins; if
            # the caller didn't provide one, fall back to ``analysis.pose_id``
            # (the pose under which the analysis was created in the workspace
            # tree). Reference (is_default + empty body_poses) poses are
            # ignored — they carry no body coordinates.
            resolved_initial_pose = initial_pose
            if resolved_initial_pose is None and getattr(analysis, "pose_id", None):
                candidate = next(
                    (p for p in getattr(project, "poses", []) if p.id == analysis.pose_id),
                    None,
                )
                if candidate is not None and getattr(candidate, "body_poses", None):
                    resolved_initial_pose = candidate

            result: SimulationResult = simulation_runner.run(
                project,
                duration=analysis.config.duration,
                steps=analysis.config.steps,
                cancel_event=cancel_event,
                initial_pose=resolved_initial_pose,
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
                artifact_path = save_result_artifact(project_dir, run, result)
                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
                from quino.services.metric_evaluator import evaluate_metrics

                run.metrics = evaluate_metrics(list(analysis.config.metrics), artifact)

            # A crashed solve that produced some frames is "partial": the
            # available trajectory is still usable for playback / plotting.
            if result.success:
                status = "ok"
            elif result.frames:
                status = "partial"
            else:
                status = "failed"
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
