import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from quino.application.service import ApplicationService
from quino.domain.model import ScalarProperty
from quino.domain.types import Dimension
from quino.gui.widgets.divergences_dock import DivergencesDock
from quino.services.case_cascading import CascadingEngine


def _setup_divergence(service):
    service.new_workspace("Test")
    ws = service._workspace
    engine = CascadingEngine(ws)
    root_id = ws.root_case_ids[0]
    from quino.domain.model import Body, Marker
    from quino.domain.types import BodyType, MarkerType
    body = Body(
        id="b1", name="bar", type=BodyType.BAR,
        markers=[
            Marker(id="m1", name="A", type=MarkerType.STRUCTURAL,
                   x=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
                   y=ScalarProperty("0 mm", "mm", Dimension.LENGTH)),
            Marker(id="m2", name="B", type=MarkerType.STRUCTURAL,
                   x=ScalarProperty("100 mm", "mm", Dimension.LENGTH),
                   y=ScalarProperty("0 mm", "mm", Dimension.LENGTH)),
        ],
        edge_order=["m1", "m2"], closed_shape=False,
        mass=ScalarProperty("2 kg", "kg", Dimension.MASS),
    )
    ws.cases[root_id].model.bodies.append(body)
    child_id = engine.fork_case(root_id, "Child")
    engine.edit_property(child_id, "b1", "mass", ScalarProperty("3 kg", "kg", Dimension.MASS))
    engine.edit_property(root_id, "b1", "mass", ScalarProperty("5 kg", "kg", Dimension.MASS))
    return child_id


def test_dock_does_not_show_persistent_cascade_warnings(qtbot):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    service = ApplicationService()
    child_id = _setup_divergence(service)
    dock = DivergencesDock(service)
    qtbot.addWidget(dock)
    dock.show_case(child_id)
    assert dock.row_count() == 0
    assert service._workspace.cases[child_id].metadata.get("divergence_warnings") is None


def test_dock_keep_override_is_noop_without_persistent_warnings(qtbot):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    service = ApplicationService()
    child_id = _setup_divergence(service)
    dock = DivergencesDock(service)
    qtbot.addWidget(dock)
    dock.show_case(child_id)
    dock.keep_override(0)
    assert dock.row_count() == 0
    assert service._workspace.cases[child_id].metadata.get("divergence_warnings") is None
