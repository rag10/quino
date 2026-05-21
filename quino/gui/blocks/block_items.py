"""QGraphicsItems for the block diagram editor."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCK_WIDTH = 120
BLOCK_HEIGHT = 60
PORT_RADIUS = 6
PORT_HIT_RADIUS = 10
CONNECTION_COLOR = QtGui.QColor("#31556f")
CONNECTION_SELECTED_COLOR = QtGui.QColor("#e67e22")
CONNECTION_WIDTH = 2
BLOCK_BG = QtGui.QColor("#f8f9fa")
BLOCK_BORDER = QtGui.QColor("#dee2e6")
BLOCK_SELECTED_BORDER = QtGui.QColor("#31556f")
BLOCK_ERROR_BORDER = QtGui.QColor("#dc3545")
BLOCK_ERROR_BG = QtGui.QColor("#f8d7da")
BLOCK_TEXT_COLOR = QtGui.QColor("#212529")
PORT_INPUT_COLOR = QtGui.QColor("#28a745")
PORT_OUTPUT_COLOR = QtGui.QColor("#dc3545")
PORT_ERROR_COLOR = QtGui.QColor("#dc3545")


# ---------------------------------------------------------------------------
# PortItem
# ---------------------------------------------------------------------------

class PortItem(QtWidgets.QGraphicsEllipseItem):
    """A small circular port on the edge of a block."""

    def __init__(
        self,
        name: str,
        is_input: bool,
        parent: BlockItem,
        shape: tuple[int, ...] | None = None,
    ) -> None:
        self._port_name = name
        self._is_input = is_input
        self._parent_block = parent
        self._shape: tuple[int, ...] | None = shape
        self._connections: list[ConnectionItem] = []
        super().__init__(
            -PORT_RADIUS, -PORT_RADIUS,
            PORT_RADIUS * 2, PORT_RADIUS * 2,
            parent,
        )
        self.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1))
        self.setBrush(PORT_INPUT_COLOR if is_input else PORT_OUTPUT_COLOR)
        self.setAcceptHoverEvents(True)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.CrossCursor))
        self._refresh_tooltip()

    def set_shape(self, shape: tuple[int, ...] | None) -> None:
        self._shape = shape
        self._refresh_tooltip()

    @property
    def shape(self) -> tuple[int, ...] | None:
        return self._shape

    def _refresh_tooltip(self) -> None:
        direction = "Input" if self._is_input else "Output"
        connected = "connected" if self._connections else "disconnected"
        shape_str = ""
        if self._shape:
            shape_str = f"\nShape: {'×'.join(str(d) for d in self._shape)}"
        self.setToolTip(
            f"{self._parent_block.instance_id}.{self._port_name}\n"
            f"{direction} · {connected}{shape_str}"
        )

    @property
    def port_name(self) -> str:
        return self._port_name

    @property
    def is_input(self) -> bool:
        return self._is_input

    @property
    def parent_block(self) -> BlockItem:
        return self._parent_block

    @property
    def connections(self) -> list[ConnectionItem]:
        return self._connections

    def add_connection(self, conn: ConnectionItem) -> None:
        if conn not in self._connections:
            self._connections.append(conn)
            self._refresh_tooltip()

    def remove_connection(self, conn: ConnectionItem) -> None:
        if conn in self._connections:
            self._connections.remove(conn)
            self._refresh_tooltip()

    def scene_center(self) -> QtCore.QPointF:
        return self.mapToScene(self.boundingRect().center())

    def set_error(self, error: bool) -> None:
        self.setBrush(PORT_ERROR_COLOR if error else (PORT_INPUT_COLOR if self._is_input else PORT_OUTPUT_COLOR))

    def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self.setScale(1.3)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self.setScale(1.0)
        super().hoverLeaveEvent(event)


# ---------------------------------------------------------------------------
# BlockItem
# ---------------------------------------------------------------------------

class BlockItem(QtWidgets.QGraphicsRectItem):
    """Visual representation of a block instance on the canvas."""

    def __init__(
        self,
        instance_id: str,
        block_type: str,
        parameters: dict[str, Any],
        input_ports: list[str],
        output_ports: list[str],
        position: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        super().__init__(
            0, 0, BLOCK_WIDTH,
            max(BLOCK_HEIGHT, 40 + max(len(input_ports), len(output_ports)) * 24),
        )
        self._instance_id = instance_id
        self._block_type = block_type
        self._parameters = dict(parameters)
        self._input_ports: dict[str, PortItem] = {}
        self._output_ports: dict[str, PortItem] = {}
        self._drag_offset: QtCore.QPointF = QtCore.QPointF()
        self.setPos(position[0], position[1])
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges,
        )
        self.setAcceptHoverEvents(True)
        self._build_ports(input_ports, output_ports)
        self._update_appearance()

    # -- accessors ----------------------------------------------------------

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def block_type(self) -> str:
        return self._block_type

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    def set_parameters(self, params: dict[str, Any]) -> None:
        self._parameters = dict(params)

    @property
    def input_ports(self) -> dict[str, PortItem]:
        return self._input_ports

    @property
    def output_ports(self) -> dict[str, PortItem]:
        return self._output_ports

    def port_by_name(self, name: str) -> PortItem | None:
        return self._input_ports.get(name) or self._output_ports.get(name)

    # -- construction -------------------------------------------------------

    def _build_ports(self, input_names: list[str], output_names: list[str]) -> None:
        h = self.rect().height()
        y_start = 24
        gap = 24

        for i, name in enumerate(input_names):
            port = PortItem(name, is_input=True, parent=self)
            port.setPos(0, y_start + i * gap)
            self._input_ports[name] = port

        for i, name in enumerate(output_names):
            port = PortItem(name, is_input=False, parent=self)
            port.setPos(BLOCK_WIDTH, y_start + i * gap)
            self._output_ports[name] = port

    def _update_appearance(self) -> None:
        if getattr(self, '_error_state', False):
            pen = QtGui.QPen(BLOCK_ERROR_BORDER, 2)
            self.setBrush(QtGui.QBrush(BLOCK_ERROR_BG))
        else:
            pen = QtGui.QPen(BLOCK_SELECTED_BORDER if self.isSelected() else BLOCK_BORDER, 2)
            self.setBrush(QtGui.QBrush(BLOCK_BG))
        self.setPen(pen)

    def set_error(self, error: bool) -> None:
        self._error_state = error
        self._update_appearance()

    # -- painting -----------------------------------------------------------

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        super().paint(painter, option, widget)
        painter.setPen(QtGui.QPen(BLOCK_TEXT_COLOR))
        painter.drawText(
            self.rect().adjusted(4, 4, -4, -4),
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignHCenter,
            self._block_type,
        )
        if self._parameters:
            param_text = ", ".join(f"{k}={v}" for k, v in list(self._parameters.items())[:2])
            painter.drawText(
                self.rect().adjusted(4, 20, -4, -4),
                QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignHCenter,
                param_text,
            )

    # -- events -------------------------------------------------------------

    def itemChange(self, change: QtWidgets.QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Notify connections to update geometry
            for port in list(self._input_ports.values()) + list(self._output_ports.values()):
                for conn in port.connections:
                    conn.update_path()
        elif change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            self._update_appearance()
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        self._drag_offset = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        super().mouseMoveEvent(event)
        for port in list(self._input_ports.values()) + list(self._output_ports.values()):
            for conn in port.connections:
                conn.update_path()

    def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self.setZValue(10)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self.setZValue(0)
        super().hoverLeaveEvent(event)


# ---------------------------------------------------------------------------
# ConnectionItem
# ---------------------------------------------------------------------------

class ConnectionItem(QtWidgets.QGraphicsPathItem):
    """Visual wire between two ports with a direction arrow at the destination."""

    def __init__(
        self,
        src_port: PortItem,
        dst_port: PortItem,
    ) -> None:
        super().__init__()
        self._src_port = src_port
        self._dst_port = dst_port
        self._hovered = False
        self.setPen(QtGui.QPen(CONNECTION_COLOR, CONNECTION_WIDTH))
        self.setZValue(-1)
        self.setFlags(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        src_port.add_connection(self)
        dst_port.add_connection(self)
        self.update_path()
        self._refresh_tooltip()

    def _refresh_tooltip(self) -> None:
        src = f"{self._src_port.parent_block.instance_id}.{self._src_port.port_name}"
        dst = f"{self._dst_port.parent_block.instance_id}.{self._dst_port.port_name}"
        self.setToolTip(f"{src} → {dst}")

    def hoverEnterEvent(self, event):  # pragma: no cover - visual
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):  # pragma: no cover - visual
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    @property
    def src_port(self) -> PortItem:
        return self._src_port

    @property
    def dst_port(self) -> PortItem:
        return self._dst_port

    def update_path(self) -> None:
        p1 = self._src_port.scene_center()
        p2 = self._dst_port.scene_center()
        dx = abs(p2.x() - p1.x()) * 0.5
        path = QtGui.QPainterPath(p1)
        path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
        self.setPath(path)

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        pen = self.pen()
        if self.isSelected():
            pen.setColor(CONNECTION_SELECTED_COLOR)
            pen.setWidth(CONNECTION_WIDTH + 1)
        elif self._hovered:
            pen.setColor(CONNECTION_SELECTED_COLOR)
            pen.setWidth(CONNECTION_WIDTH)
        else:
            pen.setColor(CONNECTION_COLOR)
            pen.setWidth(CONNECTION_WIDTH)
        self.setPen(pen)
        super().paint(painter, option, widget)
        # Direction arrow at the destination.
        self._draw_arrow(painter, pen.color())

    def _draw_arrow(self, painter: QtGui.QPainter, color: QtGui.QColor) -> None:
        path = self.path()
        if path.length() <= 0:
            return
        # Sample slightly before the end so the arrow tangent is meaningful.
        t_tip = 1.0
        t_back = max(0.0, 1.0 - 12.0 / max(path.length(), 1e-6))
        tip = path.pointAtPercent(t_tip)
        back = path.pointAtPercent(t_back)
        # Direction vector
        dx, dy = tip.x() - back.x(), tip.y() - back.y()
        import math
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            return
        ux, uy = dx / length, dy / length
        # Perpendicular for arrow wings
        px, py = -uy, ux
        size = 7.0
        wing = 4.5
        p_back = QtCore.QPointF(tip.x() - size * ux, tip.y() - size * uy)
        p_left = QtCore.QPointF(p_back.x() + wing * px, p_back.y() + wing * py)
        p_right = QtCore.QPointF(p_back.x() - wing * px, p_back.y() - wing * py)
        poly = QtGui.QPolygonF([tip, p_left, p_right])
        painter.save()
        painter.setBrush(QtGui.QBrush(color))
        painter.setPen(QtGui.QPen(color, 1))
        painter.drawPolygon(poly)
        painter.restore()

    def remove_from_ports(self) -> None:
        self._src_port.remove_connection(self)
        self._dst_port.remove_connection(self)
