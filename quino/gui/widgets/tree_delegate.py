from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class TreeBranchDelegate(QtWidgets.QStyledItemDelegate):
    """Custom delegate that draws tree branch lines and visibility checkbox."""

    visibility_toggled = QtCore.Signal(str)  # entity_id

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> None:
        super().paint(painter, option, index)

        # Draw branch lines
        if not index.parent().isValid():
            return  # Skip root items

        tree = self.parent()
        if not isinstance(tree, QtWidgets.QTreeWidget):
            return

        item = tree.itemFromIndex(index)
        if item is None:
            return

        # Calculate positions
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#d0d0d0"), 1))

        # Vertical line for branch
        indent = tree.indentation()
        parent_item = item.parent()
        if parent_item is not None:
            depth = 0
            temp = parent_item
            while temp.parent() is not None:
                depth += 1
                temp = temp.parent()

            # Draw vertical line
            x = option.rect.left() + indent * depth - indent // 2
            painter.drawLine(int(x), int(option.rect.top()), int(x), int(option.rect.bottom()))

            # Draw horizontal line to item
            y = option.rect.center().y()
            painter.drawLine(int(x), int(y), int(option.rect.left()), int(y))

        painter.restore()

    def createEditor(self, parent: QtWidgets.QWidget, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> QtWidgets.QWidget | None:
        # Don't create inline editors
        return None

    def editorEvent(self, event: QtCore.QEvent, model: QtCore.QAbstractItemModel, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex) -> bool:
        # Handle right-click context menu for visibility toggle
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            mouse_event = event
            if mouse_event.button() == QtCore.Qt.MouseButton.RightButton:
                tree = self.parent()
                if isinstance(tree, QtWidgets.QTreeWidget):
                    item = tree.itemFromIndex(index)
                    if item is not None and item.parent() is not None:  # Skip root items
                        entity_id = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                        if entity_id:
                            self.visibility_toggled.emit(entity_id)
                            return True
        return super().editorEvent(event, model, option, index)
