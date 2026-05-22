from __future__ import annotations

from quino.gui.analysis_modes._base import AnalysisModeController

_REGISTRY: dict[str, type[AnalysisModeController]] = {}


def register_mode(kind: str):
    def wrap(cls):
        _REGISTRY[kind] = cls
        return cls

    return wrap


def mode_controller_for(kind: str) -> type[AnalysisModeController]:
    if kind not in _REGISTRY:
        from quino.gui.analysis_modes import dynamic  # noqa: F401
        from quino.gui.analysis_modes import kinematic  # noqa: F401
        from quino.gui.analysis_modes import static  # noqa: F401
        from quino.gui.analysis_modes import equilibrium  # noqa: F401
        from quino.gui.analysis_modes import stub  # noqa: F401
    cls = _REGISTRY.get(kind)
    if cls is None:
        from quino.gui.analysis_modes.stub import StubModeController

        return StubModeController
    return cls
