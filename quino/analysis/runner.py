from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalysisResult:
    analysis_id: str
    analysis_type: str
    status: str  # "ok" | "failed"
    frames: list[Any] = field(default_factory=list)
    scalars: dict[str, float] = field(default_factory=dict)
    error_message: str = ""


class AnalysisRunner(ABC):
    @abstractmethod
    def validate(self, project, analysis) -> list[str]: ...

    @abstractmethod
    def run(self, project, analysis, *, initial_pose) -> AnalysisResult: ...
