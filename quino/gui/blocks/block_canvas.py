"""QGraphicsView/Scene for the block diagram editor."""

from __future__ import annotations

from typing import Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets

from quino.blocks.compiler import compile_diagram
from quino.blocks.library import BLOCK_REGISTRY, get_block_def
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec

from .block_items import BlockItem, ConnectionItem, PortItem, CONNECTION_COLOR, CONNECTION_SELECTED_COLOR


class BlockDiagramScene(QtWidgets.QGraphicsScene):
    """Scene that mirrors a BlockDiagram domain object."""

    blockSelected = QtCore.Signal(str)  # instance_id
    selectionCleared = QtCore.Signal()
    diagramChanged = QtCore.Signal()
    validationError = QtCore.Signal(str)  # error message

    def __init__(self, diagram: BlockDiagram | None = None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._diagram = diagram or BlockDiagram()
        self._block_items: dict[str, BlockItem] = {}
        self._connection_items: list[ConnectionItem] = []
        self._drag_line: QtWidgets.QGraphicsPathItem | None = None
        self._drag_src_port: PortItem | None = None
        self._temp_connection: ConnectionItem | None = None
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self._build_from_diagram()

    # -- accessors ----------------------------------------------------------

    @property
    def diagram(self) -> BlockDiagram:
        return self._diagram

    def set_diagram(self, diagram: BlockDiagram) -> None:
        self.clear()
        self._diagram = diagram
        self._block_items.clear()
        self._connection_items.clear()
        self._build_from_diagram()

    # -- build from domain --------------------------------------------------

    def _build_from_diagram(self) -> None:
        for inst_id, inst in self._diagram.instances.items():
            block_def = get_block_def(inst.block_type)
            input_names = [p.name for p in block_def.input_specs]
            output_names = [p.name for p in block_def.output_specs]
            pos = inst.parameters.get("_position", (0.0, 0.0))
            if isinstance(pos, list):
                pos = (pos[0], pos[1])
            item = BlockItem(
                instance_id=inst_id,
                block_type=inst.block_type,
                parameters=inst.parameters,
                input_ports=input_names,
                output_ports=output_names,
                position=pos,
            )
            self.addItem(item)
            self._block_items[inst_id] = item

        for conn in self._diagram.connections:
            src_block = self._block_items.get(conn.src_instance)
            dst_block = self._block_items.get(conn.dst_instance)
            if src_block is None or dst_block is None:
                continue
            src_port = src_block.output_ports.get(conn.src_port)
            dst_port = dst_block.input_ports.get(conn.dst_port)
            if src_port is None or dst_port is None:
                continue
            conn_item = ConnectionItem(src_port, dst_port)
            self.addItem(conn_item)
            self._connection_items.append(conn_item)

    # -- domain synchronization ---------------------------------------------

    def _sync_positions_to_diagram(self) -> None:
        for inst_id, item in self._block_items.items():
            inst = self._diagram.instances[inst_id]
            pos = item.pos()
            inst.parameters["_position"] = [round(pos.x(), 2), round(pos.y(), 2)]

    def _sync_connections_to_diagram(self) -> None:
        conns: list[Connection] = []
        for conn_item in self._connection_items:
            conns.append(Connection(
                src_instance=conn_item.src_port.parent_block.instance_id,
                src_port=conn_item.src_port.port_name,
                dst_instance=conn_item.dst_port.parent_block.instance_id,
                dst_port=conn_item.dst_port.port_name,
            ))
        self._diagram.connections = conns

    def sync_to_diagram(self) -> None:
        self._sync_positions_to_diagram()
        self._sync_connections_to_diagram()
        self.diagramChanged.emit()
        self.validate_and_highlight()

    def validate_and_highlight(self) -> None:
        """Compile the diagram and highlight errors visually."""
        # Reset all highlights
        for item in self._block_items.values():
            item.set_error(False)
        for port in self._input_ports_iter():
            port.set_error(False)
        for conn in self._connection_items:
            pen = conn.pen()
            pen.setStyle(QtCore.Qt.PenStyle.SolidLine)
            conn.setPen(pen)

        if not self._diagram.instances:
            return

        try:
            compile_diagram(self._diagram)
        except ValueError as exc:
            msg = str(exc)
            self.validationError.emit(msg)
            if "Algebraic cycle" in msg:
                # Extract cycle nodes from message
                # msg format: "Algebraic cycle detected among blocks: A -> B -> C. ..."
                cycle_part = msg.split("blocks: ")[1].split(".")[0]
                cycle_nodes = [n.strip() for n in cycle_part.split("->")]
                for node in cycle_nodes:
                    if node in self._block_items:
                        self._block_items[node].set_error(True)
            elif "is not connected" in msg:
                # Extract instance and port
                # msg format: "Input port 'in' on instance 'gain_001' is not connected"
                import re
                m = re.search(r"port '(.+?)' on instance '(.+?)'", msg)
                if m:
                    port_name, instance_id = m.group(1), m.group(2)
                    block = self._block_items.get(instance_id)
                    if block is not None:
                        port = block.input_ports.get(port_name)
                        if port is not None:
                            port.set_error(True)
        except Exception as exc:
            self.validationError.emit(str(exc))

    def _input_ports_iter(self):
        for item in self._block_items.values():
            for port in item.input_ports.values():
                yield port

    # -- block creation / deletion ------------------------------------------

    def add_block(self, block_type: str, position: QtCore.QPointF, instance_id: str | None = None) -> BlockItem | None:
        if block_type not in BLOCK_REGISTRY:
            return None
        block_def = get_block_def(block_type)
        if instance_id is None:
            instance_id = self._generate_instance_id(block_type)
        if instance_id in self._diagram.instances:
            instance_id = self._generate_instance_id(block_type)

        inst = BlockInstance(
            instance_id=instance_id,
            block_type=block_type,
            parameters={"_position": [position.x(), position.y()]},
            input_ports=[PortSpec(p.name, shape=p.shape) for p in block_def.input_specs],
            output_ports=[PortSpec(p.name, shape=p.shape) for p in block_def.output_specs],
        )
        self._diagram.instances[instance_id] = inst

        input_names = [p.name for p in block_def.input_specs]
        output_names = [p.name for p in block_def.output_specs]
        item = BlockItem(
            instance_id=instance_id,
            block_type=block_type,
            parameters=inst.parameters,
            input_ports=input_names,
            output_ports=output_names,
            position=(position.x(), position.y()),
        )
        self.addItem(item)
        self._block_items[instance_id] = item
        self.sync_to_diagram()
        return item

    def delete_block(self, instance_id: str) -> None:
        item = self._block_items.pop(instance_id, None)
        if item is None:
            return
        # Remove associated connections
        for port in list(item.input_ports.values()) + list(item.output_ports.values()):
            for conn in list(port.connections):
                self.delete_connection(conn)
        self.removeItem(item)
        del self._diagram.instances[instance_id]
        self.sync_to_diagram()
        self.selectionCleared.emit()

    def delete_connection(self, conn_item: ConnectionItem) -> None:
        conn_item.remove_from_ports()
        if conn_item in self._connection_items:
            self._connection_items.remove(conn_item)
        self.removeItem(conn_item)
        self.sync_to_diagram()

    def _generate_instance_id(self, block_type: str) -> str:
        base = block_type.lower().replace(" ", "_")
        n = 1
        while f"{base}_{n:03d}" in self._diagram.instances:
            n += 1
        return f"{base}_{n:03d}"

    # -- wiring interactions ------------------------------------------------

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        item = self.itemAt(event.scenePos(), QtGui.QTransform())
        if isinstance(item, PortItem):
            self._start_drag_connection(item, event.scenePos())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._drag_line is not None:
            self._update_drag_line(event.scenePos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._drag_line is not None:
            self._finish_drag_connection(event.scenePos())
            return
        super().mouseReleaseEvent(event)
        # Emit selection signal
        selected = [it for it in self.selectedItems() if isinstance(it, BlockItem)]
        if len(selected) == 1:
            self.blockSelected.emit(selected[0].instance_id)
        elif not selected:
            self.selectionCleared.emit()

    def _start_drag_connection(self, port: PortItem, pos: QtCore.QPointF) -> None:
        if port.is_input and port.connections:
            # Input ports allow only one connection: remove existing
            existing = list(port.connections)
            for conn in existing:
                self.delete_connection(conn)
        self._drag_src_port = port
        self._drag_line = QtWidgets.QGraphicsPathItem()
        self._drag_line.setPen(QtGui.QPen(QtGui.QColor("#31556f"), 2, QtCore.Qt.PenStyle.DashLine))
        self.addItem(self._drag_line)
        self._update_drag_line(pos)

    def _update_drag_line(self, pos: QtCore.QPointF) -> None:
        if self._drag_line is None or self._drag_src_port is None:
            return
        p1 = self._drag_src_port.scene_center()
        dx = abs(pos.x() - p1.x()) * 0.5
        path = QtGui.QPainterPath(p1)
        path.cubicTo(p1.x() + dx, p1.y(), pos.x() - dx, pos.y(), pos.x(), pos.y())
        self._drag_line.setPath(path)

    def _finish_drag_connection(self, pos: QtCore.QPointF) -> None:
        if self._drag_line is None or self._drag_src_port is None:
            return
        self.removeItem(self._drag_line)
        self._drag_line = None
        src = self._drag_src_port
        self._drag_src_port = None

        item = self.itemAt(pos, QtGui.QTransform())
        if not isinstance(item, PortItem):
            return
        dst = item

        # Validation
        if src.parent_block == dst.parent_block:
            return
        if src.is_input == dst.is_input:
            return
        # Determine direction: src must be output, dst input
        if src.is_input:
            src, dst = dst, src
        if dst.connections and dst.is_input:
            # Replace existing input connection
            for conn in list(dst.connections):
                self.delete_connection(conn)

        conn_item = ConnectionItem(src, dst)
        self.addItem(conn_item)
        self._connection_items.append(conn_item)
        self.sync_to_diagram()

    # -- keyboard -----------------------------------------------------------

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace):
            for item in list(self.selectedItems()):
                if isinstance(item, BlockItem):
                    self.delete_block(item.instance_id)
                elif isinstance(item, ConnectionItem):
                    self.delete_connection(item)
            return
        super().keyPressEvent(event)


class BlockEditorCanvas(QtWidgets.QGraphicsView):
    """View widget with zoom/pan support."""

    def __init__(self, scene: BlockDiagramScene, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
        self._dragging = False
        self._last_mouse_pos: QtCore.QPointF = QtCore.QPointF()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        self.scale(factor, factor)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self._dragging = True
            self._last_mouse_pos = event.pos()
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ClosedHandCursor))
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._dragging:
            delta = event.pos() - self._last_mouse_pos
            self._last_mouse_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self._dragging = False
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ArrowCursor))
            return
        super().mouseReleaseEvent(event)
