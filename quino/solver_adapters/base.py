from __future__ import annotations

from abc import ABC, abstractmethod

from quino.domain.model import Project, SimulationResult


class SolverAdapter(ABC):
    name: str

    def is_available(self) -> bool:
        return True

    @abstractmethod
    def run(self, project: Project, duration: float = 1.0, steps: int = 100, cancel_event=None, log_path=None) -> SimulationResult:
        raise NotImplementedError
