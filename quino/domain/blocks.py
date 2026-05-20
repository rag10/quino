"""Domain model for block diagrams (Simulink-like control and signal blocks).

These dataclasses are pure, immutable and have no external dependencies.
They follow the same style as quino/domain/model.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PortSpec:
    """Specification of a block port."""

    name: str
    shape: tuple[int, ...] = (1,)


@dataclass(slots=True)
class BlockInstance:
    """A single instance of a block inside a diagram."""

    instance_id: str
    block_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    input_ports: list[PortSpec] = field(default_factory=list)
    output_ports: list[PortSpec] = field(default_factory=list)
    # Position hint for the visual editor (Fase 4)
    position: tuple[float, float] = (0.0, 0.0)
    # Internal diagram for subsystems (Fase 5.5)
    internal_diagram: "BlockDiagram | None" = None

    def parameter(self, key: str, default: Any = None) -> Any:
        return self.parameters.get(key, default)


@dataclass(frozen=True, slots=True)
class Connection:
    """A directed connection from an output port to an input port."""

    src_instance: str
    src_port: str
    dst_instance: str
    dst_port: str


@dataclass(frozen=True, slots=True)
class BlockDiagram:
    """A directed acyclic graph of block instances and signal connections."""

    instances: dict[str, BlockInstance] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)

    def validate(self) -> None:
        """Raise ValueError if the diagram has structural problems."""
        # Validate that all referenced instances exist
        for conn in self.connections:
            if conn.src_instance not in self.instances:
                raise ValueError(
                    f"Connection references unknown source instance: {conn.src_instance}"
                )
            if conn.dst_instance not in self.instances:
                raise ValueError(
                    f"Connection references unknown destination instance: {conn.dst_instance}"
                )
            if conn.src_instance == conn.dst_instance:
                raise ValueError(
                    f"Self-connection not allowed: {conn.src_instance} -> {conn.dst_instance}"
                )

        # Validate that no two connections target the same input port
        seen_inputs: set[tuple[str, str]] = set()
        for conn in self.connections:
            key = (conn.dst_instance, conn.dst_port)
            if key in seen_inputs:
                raise ValueError(
                    f"Input port {conn.dst_port!r} on instance {conn.dst_instance!r} "
                    "has multiple connections"
                )
            seen_inputs.add(key)


@dataclass(frozen=True, slots=True)
class CompiledDiagram:
    """Result of compiling a BlockDiagram: execution order and wiring tables."""

    source: BlockDiagram
    execution_order: list[str] = field(default_factory=list)
    # Mapping: (instance_id, port_name) -> list of (dst_instance, dst_port)
    wiring: dict[tuple[str, str], list[tuple[str, str]]] = field(default_factory=dict)
