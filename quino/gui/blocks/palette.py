"""Palette widget with draggable block types."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.blocks.library import BLOCK_REGISTRY


def palette_categories() -> dict[str, list[str]]:
    return {
        "Sources": ["Constant", "Step", "Ramp", "Sine"],
        "Math": ["Gain", "Adder", "Product", "Saturation", "DeadZone"],
        "Routing": ["Mux", "Demux"],
        "Stateful": ["Integrator", "IntegratorLimited", "UnitDelay"],
        "Control": ["PID", "DerivativeFiltered"],
        "Electrical": ["Resistor", "Inductor", "Capacitor", "DCMotor"],
        "Hydraulic": ["HydraulicPump", "HydraulicOrifice", "HydraulicChamber"],
        "Model Interface": ["ModelSensor", "LoadCommand", "SpringCommand", "DriverCommand"],
        "Legacy MBS Interface": ["MBSSensor", "MBSActuator"],
    }


class BlockPalette(QtWidgets.QTreeWidget):
    """Tree widget listing available block types by category."""

    blockTypeRequested = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setMaximumWidth(220)
        self.itemActivated.connect(self._emit_block_request)
        self._populate()

    def _populate(self) -> None:
        for cat_name, block_names in palette_categories().items():
            cat_item = QtWidgets.QTreeWidgetItem([cat_name])
            cat_item.setFlags(cat_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            for name in block_names:
                if name in BLOCK_REGISTRY:
                    child = QtWidgets.QTreeWidgetItem([name])
                    child.setData(0, QtCore.Qt.ItemDataRole.UserRole, name)
                    cat_item.addChild(child)
            self.addTopLevelItem(cat_item)
            cat_item.setExpanded(True)

    def startDrag(self, supportedActions: QtCore.Qt.DropAction) -> None:
        item = self.currentItem()
        block_type = self._block_type_for_item(item)
        if not block_type:
            return
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setText(block_type)
        drag.setMimeData(mime)
        drag.exec(QtCore.Qt.DropAction.CopyAction)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.pos())
        block_type = self._block_type_for_item(item)
        if block_type:
            self.blockTypeRequested.emit(block_type)
            return
        super().mouseDoubleClickEvent(event)

    def _emit_block_request(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        block_type = self._block_type_for_item(item)
        if block_type:
            self.blockTypeRequested.emit(block_type)

    def _block_type_for_item(self, item: QtWidgets.QTreeWidgetItem | None) -> str | None:
        if item is None:
            return None
        block_type = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not block_type:
            return None
        return str(block_type)
