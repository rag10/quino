"""GUI tests for the readable CaseDiffsWidget."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.model import Body, Marker, Model, ScalarProperty
from quino.domain.types import BodyType, Dimension, MarkerType
from quino.domain.workspace import Case, Workspace
from quino.gui.widgets.case_diffs_widget import CaseDiffsWidget
from quino.services.case_cascading import CascadingEngine


@pytest.fixture
def app(qtbot):
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _scalar(expr: str, unit: str, dim: Dimension) -> ScalarProperty:
    return ScalarProperty(expr, unit, dim)


def _make_workspace_with_body() -> tuple[ApplicationService, str]:
    service = ApplicationService()
    body = Body(
        id="b1", name="bar", type=BodyType.BAR,
        markers=[
            Marker(id="m1", name="m1", type=MarkerType.STRUCTURAL,
                   x=_scalar("0 mm", "mm", Dimension.LENGTH),
                   y=_scalar("0 mm", "mm", Dimension.LENGTH)),
            Marker(id="m2", name="m2", type=MarkerType.STRUCTURAL,
                   x=_scalar("100 mm", "mm", Dimension.LENGTH),
                   y=_scalar("0 mm", "mm", Dimension.LENGTH)),
        ],
        edge_order=["m1", "m2"], closed_shape=False,
        mass=_scalar("2 kg", "kg", Dimension.MASS),
    )
    root_case = Case(id="P", name="Root", model=Model(bodies=[body]))
    ws = Workspace(id="w", name="w", schema_version="0.3.0",
                   root_case_ids=["P"], cases={"P": root_case},
                   selected_case_id="P")
    service._workspace = ws
    return service, "P"


def _walk_items(tree: QtWidgets.QTreeWidget):
    out: list[QtWidgets.QTreeWidgetItem] = []
    it = QtWidgets.QTreeWidgetItemIterator(tree)
    while it.value():
        out.append(it.value())
        it += 1
    return out


def test_widget_shows_placeholder_for_root_case(app, qtbot):
    service, _ = _make_workspace_with_body()
    widget = CaseDiffsWidget(service)
    qtbot.addWidget(widget)
    widget.refresh()
    # Root case has no parent → placeholder, not tree.
    assert widget._stack.currentWidget() is widget._placeholder
    assert "root" in widget._placeholder.text().lower()


def test_widget_shows_placeholder_when_no_differences(app, qtbot):
    service, root_id = _make_workspace_with_body()
    engine = CascadingEngine(service._workspace)
    child_id = engine.fork_case(root_id, "Child")
    service._workspace.selected_case_id = child_id

    widget = CaseDiffsWidget(service)
    qtbot.addWidget(widget)
    widget.refresh()
    assert widget._stack.currentWidget() is widget._placeholder
    assert "no differences" in widget._placeholder.text().lower()


def test_widget_renders_mass_change_legibly(app, qtbot):
    service, root_id = _make_workspace_with_body()
    engine = CascadingEngine(service._workspace)
    child_id = engine.fork_case(root_id, "Child")
    service._workspace.selected_case_id = child_id
    # Edit child's mass.
    service._workspace.cases[child_id].model.bodies[0].mass = _scalar(
        "3 kg", "kg", Dimension.MASS,
    )

    widget = CaseDiffsWidget(service)
    qtbot.addWidget(widget)
    widget.refresh()

    assert widget._stack.currentWidget() is widget._tree
    items = _walk_items(widget._tree)
    texts = [(i.text(0), i.text(1), i.text(2)) for i in items]

    # An entity row "Body: bar" and a Mass row showing "2 kg" → "3 kg".
    assert any(t[0] == "Body: bar" for t in texts), texts
    mass_rows = [t for t in texts if "Mass" in t[0]]
    assert len(mass_rows) == 1
    label, parent_val, child_val = mass_rows[0]
    assert parent_val == "2 kg"
    assert child_val == "3 kg"
    # No raw dataclass dumps anywhere in the rendered tree.
    for label, pv, cv in texts:
        for col in (label, pv, cv):
            assert "ScalarProperty(" not in col
            assert "Metadata(" not in col
            assert "Style(" not in col


def test_double_click_emits_entity_selected(app, qtbot):
    service, root_id = _make_workspace_with_body()
    engine = CascadingEngine(service._workspace)
    child_id = engine.fork_case(root_id, "Child")
    service._workspace.selected_case_id = child_id
    service._workspace.cases[child_id].model.bodies[0].mass = _scalar(
        "3 kg", "kg", Dimension.MASS,
    )

    widget = CaseDiffsWidget(service)
    qtbot.addWidget(widget)
    widget.refresh()

    received: list[str] = []
    widget.entity_selected.connect(received.append)

    # Find an item carrying the entity id and trigger the double click.
    entity_item: QtWidgets.QTreeWidgetItem | None = None
    for item in _walk_items(widget._tree):
        if item.data(0, QtCore.Qt.ItemDataRole.UserRole) == "b1":
            entity_item = item
            break
    assert entity_item is not None
    widget._tree.itemDoubleClicked.emit(entity_item, 0)
    assert received == ["b1"]


def test_visual_changes_hidden_by_default_shown_when_toggled(app, qtbot):
    service, root_id = _make_workspace_with_body()
    engine = CascadingEngine(service._workspace)
    child_id = engine.fork_case(root_id, "Child")
    service._workspace.selected_case_id = child_id
    # Cosmetic-only change.
    service._workspace.cases[child_id].model.bodies[0].style.color = "#ff0000"

    widget = CaseDiffsWidget(service)
    qtbot.addWidget(widget)
    widget.refresh()
    # Default: hidden → placeholder.
    assert widget._stack.currentWidget() is widget._placeholder

    # Toggle on; we should now see the diff.
    widget._visual_toggle.setChecked(True)
    assert widget._stack.currentWidget() is widget._tree
    labels = [i.text(0) for i in _walk_items(widget._tree)]
    assert any("Color" in lbl for lbl in labels)
