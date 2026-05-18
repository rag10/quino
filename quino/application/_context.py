# quino/application/_context.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, ContextManager

from quino.domain.model import Project
from quino.services.expressions import ExpressionService
from quino.services.ids import IdService
from quino.services.units import UnitService


@dataclass
class ServiceContext:
    """Dependencias compartidas que los command-services reciben.

    No contiene el Project directamente: se accede vía `project_provider()` para
    que la fachada pueda reasignarlo (load_project, new_project).
    """
    project_provider: Callable[[], Project]      # devuelve self._project
    operation: Callable[[], ContextManager]      # devuelve self._operation()
    snapshot: Callable[[], None]                 # self._snapshot
    invalidate_pose_state: Callable[[], None]
    ids: IdService
    expressions: ExpressionService
    units: UnitService
