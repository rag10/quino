"""Main container widget for the block diagram editor."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.domain.blocks import BlockDiagram

from .block_canvas import BlockDiagramScene, BlockEditorCanvas
from .palette import BlockPalette


class BlockEditorWidget(QtWidgets.QWidget):
    """Integrated block editor: palette + canvas.

    Block properties are shown in the main application inspector panel;
    this widget no longer contains an embedded inspector column.
    """

    diagramChanged = QtCore.Signal()  # emitted when user modifies the diagram
    blockSelected = QtCore.Signal(str)  # forwarded from scene: instance_id
    selectionCleared = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._diagram: BlockDiagram | None = None
        self._app_service = None

    def set_app_service(self, app_service) -> None:
        """Wire the editor to an ApplicationService so mutations route through
        BlockCommands (which routes to the active case when set)."""
        self._app_service = app_service
        self._scene.set_app_service(app_service)

    def _setup_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Left: palette
        self._palette = BlockPalette(self)
        layout.addWidget(self._palette)

        # Center: toolbar + canvas, stacked vertically.
        center = QtWidgets.QWidget(self)
        center_layout = QtWidgets.QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self._toolbar = self._build_toolbar()
        center_layout.addWidget(self._toolbar)

        self._scene = BlockDiagramScene(parent=self)
        self._canvas = BlockEditorCanvas(self._scene, parent=self)
        self._canvas.setAcceptDrops(True)
        center_layout.addWidget(self._canvas, stretch=1)

        layout.addWidget(center, stretch=1)

        # Wiring
        self._palette.blockTypeRequested.connect(self._add_block_from_palette)
        self._scene.blockSelected.connect(self.blockSelected.emit)
        self._scene.selectionCleared.connect(self.selectionCleared.emit)
        self._scene.diagramChanged.connect(self.diagramChanged.emit)

    def _build_toolbar(self) -> QtWidgets.QToolBar:
        bar = QtWidgets.QToolBar(self)
        bar.setIconSize(QtCore.QSize(16, 16))
        bar.setMovable(False)

        def _add(name: str, tip: str, slot) -> QtWidgets.QToolButton:
            btn = QtWidgets.QToolButton(bar)
            btn.setText(name)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
            return btn

        self._btn_delete = _add("Delete", "Delete selected block(s) or connection(s) (Del)", self._delete_selected)
        bar.addSeparator()
        self._btn_fit = _add("Fit", "Fit diagram to view", lambda: self._canvas.fit_blocks())
        self._btn_layout = _add("Auto layout", "Topologically lay out blocks left to right", lambda: self._scene.auto_layout())
        bar.addSeparator()
        self._btn_validate = _add("Validate", "Re-run validation (highlights cycles and unconnected inputs)", lambda: self._scene.validate_and_highlight())
        self._btn_clear = _add("Clear", "Remove all blocks from the diagram", self._clear_with_confirm)
        return bar

    def _delete_selected(self) -> None:
        # Reuse view-level delete (which calls back into scene)
        try:
            self._canvas._delete_selected()
        except AttributeError:
            pass

    def _clear_with_confirm(self) -> None:
        if not self._scene._block_items:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Clear block diagram",
            "Remove all blocks from the diagram? This cannot be undone via this dialog (use undo).",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self._scene.clear_diagram()

    # -- public API ---------------------------------------------------------

    def set_diagram(self, diagram: BlockDiagram | None) -> None:
        self._diagram = diagram
        if diagram is not None:
            self._scene.set_diagram(diagram)
        else:
            self._scene.set_diagram(BlockDiagram())

    def set_project(self, project) -> None:
        """No-op stub kept for call-site compatibility (inspector removed)."""

    def set_selected(self, instance_id: str | None) -> None:
        """Highlight an instance in the diagram WITHOUT scrolling the view.

        Use ``reveal(instance_id)`` to also bring the block on-screen (e.g.
        after a model-tree click). Recentering on every selection felt
        intrusive while editing, so the default is "highlight in place".
        """
        self._scene.set_selected(instance_id)

    def reveal(self, instance_id: str | None) -> None:
        """Select *and* scroll the view so the named block is visible.

        Used when a selection originates from outside the canvas (model
        tree, search) and the block may not currently be on screen.
        Triggers no movement if the block is already fully visible.
        """
        self._scene.set_selected(instance_id)
        if instance_id is None:
            return
        item = self._scene._block_items.get(instance_id)
        if item is None:
            return
        visible_rect = self._canvas.mapToScene(
            self._canvas.viewport().rect()
        ).boundingRect()
        if visible_rect.contains(item.sceneBoundingRect()):
            return
        self._canvas.center_block(instance_id)

    def fit_blocks(self) -> None:
        self._canvas.fit_blocks()

    def center_block(self, instance_id: str) -> None:
        self._canvas.center_block(instance_id)

    def diagram(self) -> BlockDiagram | None:
        self._scene.sync_to_diagram()
        return self._diagram

    def _add_block_from_palette(self, block_type: str) -> None:
        center = self._canvas.mapToScene(self._canvas.viewport().rect().center())
        self._scene.add_block(block_type, center)

    # -- drag & drop --------------------------------------------------------

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        block_type = event.mimeData().text()
        pos = self._canvas.mapToScene(event.pos() - self._canvas.pos())
        self._scene.add_block(block_type, pos)
        event.acceptProposedAction()
