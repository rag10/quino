"""Palette widget with draggable block types."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.blocks.library import BLOCK_REGISTRY


class BlockPalette(QtWidgets.QTreeWidget):
    """Tree widget listing available block types by category."""

    blockTypeRequested = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setMaximumWidth(220)
        self._populate()

    def _populate(self) -> None:
        categories = {
            "Sources": ["Constant", "Step", "Ramp", "Sine"],
            "Math": ["Gain", "Adder", "Product", "Saturation", "DeadZone"],
            "Routing": ["Mux", "Demux"],
            "Stateful": ["Integrator", "IntegratorLimited", "UnitDelay"],
            "Control": ["PID", "DerivativeFiltered"],
            "MBS Interface": ["MBSSensor", "MBSActuator"],
        }
        for cat_name, block_names in categories.items():
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
        if item is None:
            return
        block_type = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not block_type:
            return
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setText(block_type)
        drag.setMimeData(mime)
        drag.exec(QtCore.Qt.DropAction.CopyAction)
