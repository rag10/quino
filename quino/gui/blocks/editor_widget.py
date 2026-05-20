"""Main container widget for the block diagram editor."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.domain.blocks import BlockDiagram

from .block_canvas import BlockDiagramScene, BlockEditorCanvas
from .inspector import BlockInspector
from .palette import BlockPalette


class BlockEditorWidget(QtWidgets.QWidget):
    """Integrated block editor: palette + canvas + inspector."""

    diagramChanged = QtCore.Signal()  # emitted when user modifies the diagram

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._diagram: BlockDiagram | None = None
        self._project = None

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

        # Right: inspector
        self._inspector = BlockInspector(self)
        self._inspector.setMaximumWidth(260)
        layout.addWidget(self._inspector)

        # Wiring
        self._scene.blockSelected.connect(self._on_block_selected)
        self._scene.selectionCleared.connect(self._inspector._clear_form)
        self._scene.diagramChanged.connect(self.diagramChanged.emit)
        self._inspector.parametersChanged.connect(self._on_parameters_changed)

    # -- public API ---------------------------------------------------------

    def set_diagram(self, diagram: BlockDiagram | None) -> None:
        self._diagram = diagram
        if diagram is not None:
            self._scene.set_diagram(diagram)
        else:
            self._scene.set_diagram(BlockDiagram())
        self._inspector._clear_form()

    def set_project(self, project) -> None:
        self._project = project
        self._inspector.set_project(project)

    def diagram(self) -> BlockDiagram | None:
        self._scene.sync_to_diagram()
        return self._diagram

    # -- event handlers -----------------------------------------------------

    def _on_block_selected(self, instance_id: str) -> None:
        if self._diagram is None:
            return
        inst = self._diagram.instances.get(instance_id)
        if inst is None:
            return
        self._inspector.set_block(instance_id, inst.block_type, inst.parameters)

    def _on_parameters_changed(self, instance_id: str, new_params: dict) -> None:
        if self._diagram is None:
            return
        inst = self._diagram.instances.get(instance_id)
        if inst is None:
            return
        # Update domain object
        for k, v in new_params.items():
            inst.parameters[k] = v
        # Update visual item
        item = self._scene._block_items.get(instance_id)
        if item is not None:
            item.set_parameters(inst.parameters)
            item.update()
        self.diagramChanged.emit()

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
