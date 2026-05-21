from __future__ import annotations

from quino.application._context import ServiceContext
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection
from quino.domain.workspace import ScalarValue


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
        with self._ctx.operation():
            block_id = self._ctx.ids.new("blk")
            inst = BlockInstance(
                instance_id=block_id,
                block_type=block_type,
                parameters=dict(parameters or {}),
                position=position,
            )
            if not self._ctx.add_entity_to_case(inst, "blocks"):
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
        with self._ctx.operation():
            conn = Connection(
                src_instance=src_instance,
                src_port=src_port,
                dst_instance=dst_instance,
                dst_port=dst_port,
            )
            if not self._ctx.add_entity_to_case(conn, "connections"):
                diagram = self._ensure_diagram()
                diagram.connections.append(conn)

    def set_block_parameter(self, instance_id: str, key: str, value: float) -> None:
        with self._ctx.operation():
            case = self._ctx.get_active_case()
            path = f"model/control_graph/instances/{instance_id}/parameters/{key}"
            if case is not None:
                case.invariant_values[path] = ScalarValue(value=float(value), unit="")
                return
            diagram = self._ensure_diagram()
            inst = diagram.instances.get(instance_id)
            if inst is None:
                raise KeyError(f"Block instance {instance_id!r} not found")
            inst.parameters[key] = float(value)

    def set_block_name(self, instance_id: str, new_name: str) -> None:
        """Rename a block instance.

        BlockInstance has no 'name' field, so the name is stored as a
        reference_override keyed by instance_id in both the case and
        baseline paths.
        """
        with self._ctx.operation():
            case = self._ctx.get_active_case()
            if case is not None:
                case.reference_overrides.setdefault(instance_id, {})["name"] = new_name
                return
            # No active case: store the name override in the diagram-level metadata
            # (reference_overrides lives on Case, not on Model, so we store in
            # the instance's parameters under a reserved key for now)
            diagram = self._ensure_diagram()
            inst = diagram.instances.get(instance_id)
            if inst is None:
                raise KeyError(f"Block instance {instance_id!r} not found")
            inst.parameters["__name__"] = new_name
