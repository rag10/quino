"""BlockEngine: step-by-step execution of a compiled block diagram."""

from __future__ import annotations

import numpy as np

from quino.blocks.compiler import compile_diagram
from quino.blocks.library import get_block_def
from quino.domain.blocks import BlockDiagram, CompiledDiagram


class BlockEngine:
    """Runtime engine for block diagrams.

    Evaluates blocks in topological order, propagates signals, and manages
    state for memoryful blocks (integrators, delays, PID, etc.).
    """

    def __init__(self, compiled: CompiledDiagram, context: Any = None) -> None:
        self._compiled = compiled
        self._context = context
        self._states: dict[str, dict[str, np.ndarray]] = {}
        self._buffers: dict[str, dict[str, np.ndarray]] = {}
        self._init_states()

    @classmethod
    def from_diagram(cls, diagram: BlockDiagram, context: Any = None) -> "BlockEngine":
        compiled = compile_diagram(diagram)
        return cls(compiled, context)

    def _init_states(self) -> None:
        for instance_id, instance in self._compiled.source.instances.items():
            block_def = get_block_def(instance.block_type)
            if block_def.init_state is not None:
                self._states[instance_id] = block_def.init_state(instance.parameters)
            else:
                self._states[instance_id] = {}
            self._buffers[instance_id] = {
                port.name: np.zeros(port.shape)
                for port in instance.output_ports
            }

    def step(self, t: float, dt: float) -> None:
        """Execute one simulation step at time *t* with step *dt*.

        The wiring is resolved in topological order so that every block
        sees the up-to-date outputs of its predecessors.
        """
        for instance_id in self._compiled.execution_order:
            instance = self._compiled.source.instances[instance_id]
            block_def = get_block_def(instance.block_type)

            # Gather inputs from wiring
            inputs: dict[str, np.ndarray] = {}
            for conn in self._compiled.source.connections:
                if conn.dst_instance == instance_id:
                    src_buf = self._buffers[conn.src_instance]
                    inputs[conn.dst_port] = src_buf[conn.src_port].copy()

            # Execute
            if block_def.compute is not None:
                outputs = block_def.compute(inputs, instance.parameters, t, context=self._context)
            elif block_def.update is not None:
                state = self._states[instance_id]
                outputs = block_def.update(inputs, instance.parameters, t, dt, state, context=self._context)
                # Update persistent state (keys that are not output ports)
                out_keys = {p.name for p in block_def.output_specs}
                for key, val in outputs.items():
                    if key not in out_keys:
                        self._states[instance_id][key] = val
                # Keep only output-port keys for wiring
                outputs = {k: v for k, v in outputs.items() if k in out_keys}
            else:
                raise RuntimeError(f"Block {instance_id} has no compute or update function")

            # Write outputs to buffer
            for port_name, value in outputs.items():
                self._buffers[instance_id][port_name] = value

    def output(self, instance_id: str, port: str) -> np.ndarray:
        return self._buffers[instance_id][port].copy()

    def reset(self) -> None:
        """Re-initialize all states to their initial conditions."""
        self._init_states()
