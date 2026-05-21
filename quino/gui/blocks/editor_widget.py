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

        # Center: canvas
        self._scene = BlockDiagramScene(parent=self)
        self._canvas = BlockEditorCanvas(self._scene, parent=self)
        self._canvas.setAcceptDrops(True)
        layout.addWidget(self._canvas, stretch=1)

        # Wiring
        self._palette.blockTypeRequested.connect(self._add_block_from_palette)
        self._scene.blockSelected.connect(self.blockSelected.emit)
        self._scene.selectionCleared.connect(self.selectionCleared.emit)
        self._scene.diagramChanged.connect(self.diagramChanged.emit)

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
        """Highlight an instance in the diagram (called from main inspector)."""
        self._scene.set_selected(instance_id)

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
