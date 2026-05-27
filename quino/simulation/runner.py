from __future__ import annotations

from quino.domain.model import SimulationResult
from quino.solver_adapters.base import SolverAdapter


class SimulationRunner:
    def __init__(self, adapter: SolverAdapter) -> None:
        self.adapter = adapter

    def backend_name(self) -> str:
        return self.adapter.name

    def backend_available(self) -> bool:
        return self.adapter.is_available()

    def describe_backend(self) -> str:
        availability = "available" if self.backend_available() else "unavailable"
        return f"{self.backend_name()} ({availability})"

    def run(self, project, duration: float = 1.0, steps: int = 100, cancel_event=None, log_path=None, initial_pose=None) -> SimulationResult:
        import inspect
        sig = inspect.signature(self.adapter.run)
        kwargs = {"duration": duration, "steps": steps}
        if "cancel_event" in sig.parameters:
            kwargs["cancel_event"] = cancel_event
        if "log_path" in sig.parameters:
            kwargs["log_path"] = log_path
        if "initial_pose" in sig.parameters:
            kwargs["initial_pose"] = initial_pose
        return self.adapter.run(project, **kwargs)
