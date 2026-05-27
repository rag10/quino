"""QGraphicsView/Scene for the block diagram editor."""

from __future__ import annotations

import copy
from typing import Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets

from quino.blocks.compiler import compile_diagram
from quino.blocks.library import BLOCK_REGISTRY, get_block_def
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec

from .block_items import BlockItem, ConnectionItem, PortItem, CONNECTION_COLOR, CONNECTION_SELECTED_COLOR


_BLOCK_DEFAULT_PARAMETERS: dict[str, dict[str, Any]] = {
    "Constant": {"value": 0.0},
    "Step": {"step_time": 0.0, "initial_value": 0.0, "final_value": 1.0},
    "Ramp": {"slope": 1.0, "start_time": 0.0},
    "Sine": {"amplitude": 1.0, "frequency": 1.0, "phase": 0.0, "bias": 0.0},
    "Gain": {"k": 1.0},
    "Adder": {"signs": [1.0, 1.0]},
    "Saturation": {"lower": -1.0, "upper": 1.0},
    "DeadZone": {"deadband": 0.5},
    "Integrator": {"initial_condition": 0.0},
    "IntegratorLimited": {"initial_condition": 0.0, "lower": -1e30, "upper": 1e30},
    "UnitDelay": {"initial_condition": 0.0},
    "PID": {"kp": 1.0, "ki": 0.0, "kd": 0.0, "lower": -1e30, "upper": 1e30, "anti_windup": False},
    "DerivativeFiltered": {"time_constant": 0.01},
    "Resistor": {"r": 1.0},
    "Inductor": {"l": 1.0, "initial_current": 0.0},
    "Capacitor": {"c": 1.0, "initial_voltage": 0.0},
    "DCMotor": {"kt": 1.0, "r": 1.0},
    "HydraulicPump": {"q": 1.0},
    "HydraulicOrifice": {"gain": 1.0},
    "HydraulicChamber": {"bulk_modulus": 1.6e9, "volume": 1.0, "initial_pressure": 0.0},
    "MBSSensor": {"body_id": "", "variable": "Position", "component": "y"},
    "MBSActuator": {"body_id": "", "direction": [0.0, 1.0, 0.0]},
    "ModelSensor": {"sensor_id": "", "channel": "y"},
    "LoadCommand": {"load_id": "", "component": "fx"},
    "SpringCommand": {"spring_id": ""},
    "DriverCommand": {"driver_id": ""},
}


def default_block_parameters(block_type: str) -> dict[str, Any]:
    return copy.deepcopy(_BLOCK_DEFAULT_PARAMETERS.get(block_type, {}))


def _port_names_for_instance(inst: BlockInstance) -> tuple[list[str], list[str]]:
    if inst.block_type in BLOCK_REGISTRY:
        block_def = get_block_def(inst.block_type)
        return (
            [p.name for p in block_def.input_specs],
            [p.name for p in block_def.output_specs],
        )
    return (
        [p.name for p in inst.input_ports],
        [p.name for p in inst.output_ports],
    )


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
        self._app_service = None
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self._build_from_diagram()

    def set_app_service(self, app_service) -> None:
        """When set, all mutating operations route through ApplicationService
        (snapshot + case overlay). When None, the scene mutates its own diagram."""
        self._app_service = app_service

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
        self.validate_and_highlight()

    # -- build from domain --------------------------------------------------

    def _build_from_diagram(self) -> None:
        for inst_id, inst in self._diagram.instances.items():
            input_names, output_names = _port_names_for_instance(inst)
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
            # Attach shape metadata when known (from registry or instance).
            shape_by_name: dict[str, tuple[int, ...]] = {}
            if inst.block_type in BLOCK_REGISTRY:
                block_def = get_block_def(inst.block_type)
                for p in block_def.input_specs:
                    shape_by_name[p.name] = p.shape
                for p in block_def.output_specs:
                    shape_by_name[p.name] = p.shape
            else:
                for p in inst.input_ports:
                    shape_by_name[p.name] = p.shape
                for p in inst.output_ports:
                    shape_by_name[p.name] = p.shape
            for port_name, port_item in {**item.input_ports, **item.output_ports}.items():
                if port_name in shape_by_name:
                    port_item.set_shape(shape_by_name[port_name])

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
        object.__setattr__(self._diagram, "connections", conns)

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

        # Route through ApplicationService when wired (snapshot + case overlay).
        if self._app_service is not None:
            default_params = default_block_parameters(block_type)
            default_params["_position"] = [position.x(), position.y()]
            new_id = self._app_service.add_block(
                block_type=block_type,
                name=block_type,
                position=(position.x(), position.y()),
                parameters=default_params,
            )
            self._sync_from_app_service()
            item = self._block_items.get(new_id)
            if item is not None:
                self.clearSelection()
                item.setSelected(True)
                self.blockSelected.emit(new_id)
            return item

        if instance_id is None:
            instance_id = self._generate_instance_id(block_type)
        if instance_id in self._diagram.instances:
            instance_id = self._generate_instance_id(block_type)

        inst = BlockInstance(
            instance_id=instance_id,
            block_type=block_type,
            parameters={
                **default_block_parameters(block_type),
                "_position": [position.x(), position.y()],
            },
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
        # Annotate ports with their shape for tooltip display.
        for p in block_def.input_specs:
            port_item = item.input_ports.get(p.name)
            if port_item is not None:
                port_item.set_shape(p.shape)
        for p in block_def.output_specs:
            port_item = item.output_ports.get(p.name)
            if port_item is not None:
                port_item.set_shape(p.shape)
        self.clearSelection()
        item.setSelected(True)
        self.sync_to_diagram()
        self.blockSelected.emit(instance_id)
        return item

    def clear_diagram(self) -> None:
        """Remove every block (and dependent connections) from the diagram."""
        ids = list(self._block_items.keys())
        if not ids:
            return
        for instance_id in ids:
            self.delete_block(instance_id)

    def auto_layout(self) -> None:
        """Topologically place blocks left-to-right by dependency depth.

        Sources (no input connections) sit in the leftmost column, sinks
        in the rightmost. Disconnected components are stacked vertically
        below the main flow. Positions are persisted via set_block_position
        when an app_service is wired; otherwise updated locally.
        """
        instances = self._diagram.instances
        if not instances:
            return
        # Adjacency: for each block, the set of input source blocks.
        in_edges: dict[str, set[str]] = {iid: set() for iid in instances}
        out_edges: dict[str, set[str]] = {iid: set() for iid in instances}
        for conn in self._diagram.connections:
            if conn.src_instance in in_edges and conn.dst_instance in in_edges:
                in_edges[conn.dst_instance].add(conn.src_instance)
                out_edges[conn.src_instance].add(conn.dst_instance)
        # Longest-path depth (Kahn-like)
        depth: dict[str, int] = {iid: 0 for iid in instances}
        remaining = dict(in_edges)
        ready = [iid for iid, deps in remaining.items() if not deps]
        while ready:
            current = ready.pop(0)
            for successor in out_edges[current]:
                depth[successor] = max(depth[successor], depth[current] + 1)
                remaining[successor].discard(current)
                if not remaining[successor]:
                    ready.append(successor)
        # Group by depth and assign positions
        col_width = 200.0
        row_height = 120.0
        by_depth: dict[int, list[str]] = {}
        for iid, d in depth.items():
            by_depth.setdefault(d, []).append(iid)
        for d, ids in by_depth.items():
            ids.sort()
            for row, iid in enumerate(ids):
                x = d * col_width
                y = row * row_height
                if self._app_service is not None:
                    try:
                        self._app_service.set_block_position(iid, (x, y))
                    except Exception:
                        pass
                item = self._block_items.get(iid)
                if item is not None:
                    item.setPos(x, y)
                self._diagram.instances[iid].parameters["_position"] = [x, y]
        if self._app_service is None:
            self.sync_to_diagram()
        else:
            self._sync_from_app_service()

    def _sync_from_app_service(self) -> None:
        """Rebuild scene from app_service.display_project's control_graph."""
        if self._app_service is None:
            return
        dp = self._app_service.display_project
        cg = dp.model.control_graph if dp is not None else None
        if cg is None:
            from quino.domain.blocks import BlockDiagram as _BD
            cg = _BD()
        self.clear()
        self._block_items.clear()
        self._connection_items.clear()
        self._diagram = cg
        self._build_from_diagram()
        self.diagramChanged.emit()
        self.validate_and_highlight()

    def delete_block(self, instance_id: str) -> None:
        if self._app_service is not None:
            self._app_service.remove_block(instance_id)
            self._sync_from_app_service()
            self.selectionCleared.emit()
            return
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
        if self._app_service is not None:
            self._app_service.remove_connection(
                src_instance=conn_item.src_port.parent_block.instance_id,
                src_port=conn_item.src_port.port_name,
                dst_instance=conn_item.dst_port.parent_block.instance_id,
                dst_port=conn_item.dst_port.port_name,
            )
            self._sync_from_app_service()
            return
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

    def create_subsystem_from_selection(self) -> BlockItem | None:
        """Group selected blocks into a Subsystem instance."""
        selected = [it for it in self.selectedItems() if isinstance(it, BlockItem)]
        if len(selected) < 2:
            return None

        selected_ids = {it.instance_id for it in selected}

        # Collect boundary connections
        boundary_inputs: list[tuple[str, str, str, str]] = []  # (ext_src, ext_src_port, dst_inst, dst_port)
        boundary_outputs: list[tuple[str, str, str, str]] = []  # (src_inst, src_port, ext_dst, ext_dst_port)
        internal_connections: list[Connection] = []

        for conn in self._diagram.connections:
            src_in = conn.src_instance in selected_ids
            dst_in = conn.dst_instance in selected_ids
            if src_in and dst_in:
                internal_connections.append(conn)
            elif not src_in and dst_in:
                boundary_inputs.append((conn.src_instance, conn.src_port, conn.dst_instance, conn.dst_port))
            elif src_in and not dst_in:
                boundary_outputs.append((conn.src_instance, conn.src_port, conn.dst_instance, conn.dst_port))

        # Build internal diagram
        internal_instances: dict[str, BlockInstance] = {}
        internal_connections_list: list[Connection] = list(internal_connections)

        for item in selected:
            inst = self._diagram.instances[item.instance_id]
            internal_instances[inst.instance_id] = BlockInstance(
                instance_id=inst.instance_id,
                block_type=inst.block_type,
                parameters=dict(inst.parameters),
                input_ports=list(inst.input_ports),
                output_ports=list(inst.output_ports),
                position=inst.position,
            )

        # Add Inport blocks for each boundary input
        inport_mappings: dict[tuple[str, str], str] = {}
        for idx, (ext_src, ext_src_port, dst_inst, dst_port) in enumerate(boundary_inputs):
            inport_id = f"inport_{idx}"
            internal_instances[inport_id] = BlockInstance(
                instance_id=inport_id,
                block_type="Inport",
                parameters={"port_name": dst_port},
                input_ports=[PortSpec("in")],
                output_ports=[PortSpec("out")],
            )
            internal_connections_list.append(Connection(inport_id, "out", dst_inst, dst_port))
            inport_mappings[(dst_inst, dst_port)] = inport_id

        # Add Outport blocks for each boundary output
        outport_mappings: dict[tuple[str, str], str] = {}
        for idx, (src_inst, src_port, ext_dst, ext_dst_port) in enumerate(boundary_outputs):
            outport_id = f"outport_{idx}"
            internal_instances[outport_id] = BlockInstance(
                instance_id=outport_id,
                block_type="Outport",
                parameters={"port_name": src_port},
                input_ports=[PortSpec("in")],
                output_ports=[PortSpec("out")],
            )
            internal_connections_list.append(Connection(src_inst, src_port, outport_id, "in"))
            outport_mappings[(src_inst, src_port)] = outport_id

        internal_diagram = BlockDiagram(
            instances=internal_instances,
            connections=internal_connections_list,
        )

        # Create Subsystem instance
        sub_id = self._generate_instance_id("Subsystem")
        input_ports = [PortSpec(f"in_{i}") for i in range(len(boundary_inputs))]
        output_ports = [PortSpec(f"out_{i}") for i in range(len(boundary_outputs))]
        sub_inst = BlockInstance(
            instance_id=sub_id,
            block_type="Subsystem",
            parameters={},
            input_ports=input_ports,
            output_ports=output_ports,
            internal_diagram=internal_diagram,
        )
        self._diagram.instances[sub_id] = sub_inst

        # Remove old blocks and their connections
        for item in selected:
            self.delete_block(item.instance_id)

        # Add visual item
        sub_item = BlockItem(
            instance_id=sub_id,
            block_type="Subsystem",
            parameters={},
            input_ports=[p.name for p in input_ports],
            output_ports=[p.name for p in output_ports],
            position=(0.0, 0.0),
        )
        self.addItem(sub_item)
        self._block_items[sub_id] = sub_item

        # Rewire external connections
        for idx, (ext_src, ext_src_port, _dst_inst, _dst_port) in enumerate(boundary_inputs):
            self._diagram.connections.append(Connection(ext_src, ext_src_port, sub_id, f"in_{idx}"))
        for idx, (_src_inst, _src_port, ext_dst, ext_dst_port) in enumerate(boundary_outputs):
            self._diagram.connections.append(Connection(sub_id, f"out_{idx}", ext_dst, ext_dst_port))

        self._build_from_diagram()  # rebuild scene to show new wiring
        self.sync_to_diagram()
        return sub_item

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
        # Persist any positional changes for selected blocks (drag-end).
        if self._app_service is not None:
            for item in selected:
                pos = item.pos()
                try:
                    self._app_service.set_block_position(item.instance_id, (pos.x(), pos.y()))
                except Exception:
                    pass

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
        # Color the rubber line green when hovering over a compatible target
        # port, red when over an incompatible one, default blue otherwise.
        item = self.itemAt(pos, QtGui.QTransform())
        pen = self._drag_line.pen()
        if isinstance(item, PortItem):
            if item.parent_block == self._drag_src_port.parent_block:
                pen.setColor(QtGui.QColor("#dc3545"))  # red: same block
            elif item.is_input == self._drag_src_port.is_input:
                pen.setColor(QtGui.QColor("#dc3545"))  # red: same direction
            else:
                pen.setColor(QtGui.QColor("#28a745"))  # green: compatible
        else:
            pen.setColor(QtGui.QColor("#31556f"))  # default blue
        self._drag_line.setPen(pen)

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

        # Validation with user feedback.
        if src.parent_block == dst.parent_block:
            self.validationError.emit("Cannot connect a block to itself")
            return
        if src.is_input == dst.is_input:
            direction = "input" if src.is_input else "output"
            self.validationError.emit(
                f"Cannot connect two {direction} ports; connect output → input"
            )
            return
        # Determine direction: src must be output, dst input
        if src.is_input:
            src, dst = dst, src
        if dst.connections and dst.is_input:
            # Replace existing input connection
            for conn in list(dst.connections):
                self.delete_connection(conn)

        if self._app_service is not None:
            self._app_service.add_connection(
                src_instance=src.parent_block.instance_id,
                src_port=src.port_name,
                dst_instance=dst.parent_block.instance_id,
                dst_port=dst.port_name,
            )
            self._sync_from_app_service()
            return
        conn_item = ConnectionItem(src, dst)
        self.addItem(conn_item)
        self._connection_items.append(conn_item)
        self.sync_to_diagram()

    # -- selection ----------------------------------------------------------

    def set_selected(self, instance_id: str | None) -> None:
        """Programmatically select a block by instance_id (None clears selection)."""
        self.blockSignals(True)
        self.clearSelection()
        if instance_id is not None:
            item = self._block_items.get(instance_id)
            if item is not None:
                item.setSelected(True)
        self.blockSignals(False)

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
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#f8fbfd")))
        self._dragging = False
        self._last_mouse_pos: QtCore.QPointF = QtCore.QPointF()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        self.scale(factor, factor)

    def fit_blocks(self) -> None:
        """Fit the view to the bounding box of all blocks, with margin.

        Falls back to identity transform when the scene is empty.
        """
        scene = self.scene()
        if not isinstance(scene, BlockDiagramScene):
            return
        items = list(scene._block_items.values())
        if not items:
            self.resetTransform()
            self.centerOn(0.0, 0.0)
            return
        rect = items[0].sceneBoundingRect()
        for item in items[1:]:
            rect = rect.united(item.sceneBoundingRect())
        rect.adjust(-30, -30, 30, 30)
        self.fitInView(rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def center_block(self, instance_id: str) -> None:
        """Center the view on the named block. No-op when unknown."""
        scene = self.scene()
        if not isinstance(scene, BlockDiagramScene):
            return
        item = scene._block_items.get(instance_id)
        if item is None:
            return
        self.centerOn(item.sceneBoundingRect().center())

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        super().drawBackground(painter, rect)
        scene = self.scene()
        if not isinstance(scene, BlockDiagramScene):
            return
        # Light dot grid for visual orientation (only when there are blocks
        # or while the user is wiring; with no content we show the hint).
        viewport_rect = self.viewport().rect()
        scene_rect = self.mapToScene(viewport_rect).boundingRect()
        if scene._block_items:
            painter.save()
            painter.setPen(QtGui.QPen(QtGui.QColor("#dfe8f1"), 1))
            step = 40.0
            x = int(scene_rect.left() / step) * step
            while x < scene_rect.right():
                y = int(scene_rect.top() / step) * step
                while y < scene_rect.bottom():
                    painter.drawPoint(QtCore.QPointF(x, y))
                    y += step
                x += step
            painter.restore()
            return
        # Empty state hint when there are no blocks yet.
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#66727e")))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(
            scene_rect,
            QtCore.Qt.AlignmentFlag.AlignCenter,
            "Drag a block here from the palette  ·  or double-click a palette entry\n"
            "Drag between ports to wire blocks together",
        )
        painter.restore()

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

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasText() and event.mimeData().text() in BLOCK_REGISTRY:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasText() and event.mimeData().text() in BLOCK_REGISTRY:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        block_type = event.mimeData().text()
        if block_type not in BLOCK_REGISTRY:
            super().dropEvent(event)
            return
        scene = self.scene()
        if isinstance(scene, BlockDiagramScene):
            scene.add_block(block_type, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        scene = self.scene()
        if not isinstance(scene, BlockDiagramScene):
            return
        selected = [it for it in scene.selectedItems() if isinstance(it, BlockItem)]
        menu = QtWidgets.QMenu(self)
        if len(selected) >= 2:
            action = menu.addAction("Create Subsystem")
            action.triggered.connect(lambda: scene.create_subsystem_from_selection())
            menu.addSeparator()
        action_delete = menu.addAction("Delete")
        action_delete.triggered.connect(self._delete_selected)
        menu.exec(event.globalPos())

    def _delete_selected(self) -> None:
        scene = self.scene()
        if not isinstance(scene, BlockDiagramScene):
            return
        for item in list(scene.selectedItems()):
            if isinstance(item, BlockItem):
                scene.delete_block(item.instance_id)
            elif isinstance(item, ConnectionItem):
                scene.delete_connection(item)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        scene = self.scene()
        if not isinstance(scene, BlockDiagramScene):
            return
        item = scene.itemAt(self.mapToScene(event.pos()), QtGui.QTransform())
        if isinstance(item, BlockItem) and item.block_type == "Subsystem":
            self._open_subsystem_editor(item)
            return
        super().mouseDoubleClickEvent(event)

    def _open_subsystem_editor(self, item: BlockItem) -> None:
        scene = self.scene()
        if not isinstance(scene, BlockDiagramScene):
            return
        inst = scene.diagram.instances.get(item.instance_id)
        if inst is None or inst.internal_diagram is None:
            return
        from quino.gui.blocks.editor_widget import BlockEditorWidget
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Subsystem: {item.instance_id}")
        dialog.resize(800, 600)
        layout = QtWidgets.QVBoxLayout(dialog)
        editor = BlockEditorWidget(dialog)
        editor.set_diagram(inst.internal_diagram)
        layout.addWidget(editor)
        btn = QtWidgets.QPushButton("Close")
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn)
        dialog.exec()
