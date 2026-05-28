"""Palette widget with draggable block types."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.blocks.library import BLOCK_REGISTRY
from quino.gui.icons import get_icon
from quino.gui.theme import INK_MUTED, apply_browser_tree_style


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
        self.setObjectName("blockPaletteTree")
        apply_browser_tree_style(self, icon_size=16, indentation=18, show_header=False)
        self.setDragEnabled(True)
        self.setMaximumWidth(220)
        self.setExpandsOnDoubleClick(False)
        self.itemActivated.connect(self._emit_block_request)
        self._populate()

    def _populate(self) -> None:
        for cat_name, block_names in palette_categories().items():
            cat_item = QtWidgets.QTreeWidgetItem([cat_name])
            cat_item.setIcon(0, get_icon("workspace-blocks", INK_MUTED, size=16))
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            cat_item.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_MUTED)))
            cat_item.setFlags(cat_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            for name in block_names:
                if name in BLOCK_REGISTRY:
                    child = QtWidgets.QTreeWidgetItem([name])
                    child.setIcon(0, get_icon("block-instance", INK_MUTED, size=16))
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
