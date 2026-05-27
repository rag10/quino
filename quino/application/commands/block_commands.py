from __future__ import annotations

from quino.application._context import ServiceContext
from quino.blocks.library import BLOCK_REGISTRY, get_block_def
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection
from typing import Any

class BlockCommands:
    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    def _ensure_diagram(self) -> BlockDiagram:
        project = self._ctx.project_provider()
        if project.model.control_graph is None:
            project.model.control_graph = BlockDiagram()
        return project.model.control_graph

    def add_block(
        self,
        *,
        block_type: str,
        name: str,
        position: tuple[float, float],
        parameters: dict | None = None,
    ) -> str:
        self._ctx.discard_runs_for_active_case()
        with self._ctx.operation():
            block_id = self._ctx.ids.new("blk")
            input_ports = []
            output_ports = []
            if block_type in BLOCK_REGISTRY:
                block_def = get_block_def(block_type)
                input_ports = list(block_def.input_specs)
                output_ports = list(block_def.output_specs)
            inst = BlockInstance(
                instance_id=block_id,
                block_type=block_type,
                parameters=dict(parameters or {}),
                input_ports=input_ports,
                output_ports=output_ports,
                position=position,
            )
            diagram = self._ensure_diagram()
            diagram.instances[block_id] = inst
        return block_id

    def add_connection(
        self,
        *,
        src_instance: str,
        src_port: str,
        dst_instance: str,
        dst_port: str,
    ) -> None:
        self._ctx.discard_runs_for_active_case()
        with self._ctx.operation():
            conn = Connection(
                src_instance=src_instance,
                src_port=src_port,
                dst_instance=dst_instance,
                dst_port=dst_port,
            )
            diagram = self._ensure_diagram()
            diagram.connections.append(conn)

    def set_block_parameter(self, instance_id: str, key: str, value: Any) -> None:
        # Block parameter edits change simulation results — confirm first.
        if not self._ctx.confirm_invalidation_if_runs_exist():
            return
        self._ctx.discard_runs_for_active_case()
        with self._ctx.operation():
            diagram = self._ensure_diagram()
            inst = diagram.instances.get(instance_id)
            if inst is None:
                raise KeyError(f"Block instance {instance_id!r} not found")
            inst.parameters[key] = value

    def remove_block(self, instance_id: str) -> None:
        """Remove a block instance and any connections that reference it."""
        self._ctx.discard_runs_for_active_case()
        with self._ctx.operation():
            diagram = self._ensure_diagram()
            diagram.instances.pop(instance_id, None)
            object.__setattr__(
                diagram,
                "connections",
                [
                    c for c in diagram.connections
                    if c.src_instance != instance_id and c.dst_instance != instance_id
                ],
            )

    def remove_connection(
        self,
        *,
        src_instance: str,
        src_port: str,
        dst_instance: str,
        dst_port: str,
    ) -> None:
        self._ctx.discard_runs_for_active_case()
        with self._ctx.operation():
            key = (src_instance, src_port, dst_instance, dst_port)
            diagram = self._ensure_diagram()
            object.__setattr__(
                diagram,
                "connections",
                [
                    c for c in diagram.connections
                    if (c.src_instance, c.src_port, c.dst_instance, c.dst_port) != key
                ],
            )

    def set_block_position(self, instance_id: str, position: tuple[float, float]) -> None:
        """Update a block's visual position."""
        with self._ctx.operation():
            diagram = self._ensure_diagram()
            inst = diagram.instances.get(instance_id)
            if inst is None:
                raise KeyError(f"Block instance {instance_id!r} not found")
            inst.parameters["_position"] = [float(position[0]), float(position[1])]

    def set_block_name(self, instance_id: str, new_name: str) -> None:
        """Rename a block instance (stored as parameters["__name__"])."""
        with self._ctx.operation():
            diagram = self._ensure_diagram()
            inst = diagram.instances.get(instance_id)
            if inst is None:
                raise KeyError(f"Block instance {instance_id!r} not found")
            inst.parameters["__name__"] = new_name
