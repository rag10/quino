"""Tests for subsystem expansion (Fase 5.5)."""

import numpy as np

from quino.blocks.compiler import _expand_subsystems, compile_diagram
from quino.blocks.engine import BlockEngine
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec


class TestSubsystemExpansion:
    def test_flatten_simple_subsystem(self) -> None:
        """A subsystem containing Gain(2) should flatten to the internal blocks."""
        inner = BlockDiagram(
            instances={
                "in1": BlockInstance("in1", "Inport", parameters={"port_name": "in"}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "g": BlockInstance("g", "Gain", parameters={"k": 2.0}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "out1": BlockInstance("out1", "Outport", parameters={"port_name": "out"}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[
                Connection("in1", "out", "g", "in"),
                Connection("g", "out", "out1", "in"),
            ],
        )
        outer = BlockDiagram(
            instances={
                "src": BlockInstance("src", "Constant", parameters={"value": 5.0}, output_ports=[PortSpec("out")]),
                "sub": BlockInstance("sub", "Subsystem", internal_diagram=inner, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[
                Connection("src", "out", "sub", "in"),
            ],
        )
        expanded = _expand_subsystems(outer)
        # The subsystem should be removed and replaced by inner blocks with prefix
        assert "sub" not in expanded.instances
        assert "sub/in1" in expanded.instances
        assert "sub/g" in expanded.instances
        assert "sub/out1" in expanded.instances
        # The external connection should be rewired
        assert any(c.dst_instance == "sub/in1" and c.dst_port == "in" for c in expanded.connections)

    def test_subsystem_execution(self) -> None:
        """A subsystem Gain(3) fed by Constant(4) should output 12."""
        inner = BlockDiagram(
            instances={
                "in1": BlockInstance("in1", "Inport", parameters={"port_name": "in"}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "g": BlockInstance("g", "Gain", parameters={"k": 3.0}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "out1": BlockInstance("out1", "Outport", parameters={"port_name": "out"}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[
                Connection("in1", "out", "g", "in"),
                Connection("g", "out", "out1", "in"),
            ],
        )
        outer = BlockDiagram(
            instances={
                "src": BlockInstance("src", "Constant", parameters={"value": 4.0}, output_ports=[PortSpec("out")]),
                "sub": BlockInstance("sub", "Subsystem", internal_diagram=inner, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[
                Connection("src", "out", "sub", "in"),
            ],
        )
        engine = BlockEngine.from_diagram(outer)
        engine.step(t=0.0, dt=0.01)
        # After expansion, the output should be from sub/out1
        assert np.isclose(engine.output("sub/out1", "out")[0], 12.0)

    def test_compile_with_subsystem(self) -> None:
        """compile_diagram should expand subsystems transparently."""
        inner = BlockDiagram(
            instances={
                "in1": BlockInstance("in1", "Inport", parameters={"port_name": "in"}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "g": BlockInstance("g", "Gain", parameters={"k": 2.0}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "out1": BlockInstance("out1", "Outport", parameters={"port_name": "out"}, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[
                Connection("in1", "out", "g", "in"),
                Connection("g", "out", "out1", "in"),
            ],
        )
        outer = BlockDiagram(
            instances={
                "src": BlockInstance("src", "Constant", parameters={"value": 3.0}, output_ports=[PortSpec("out")]),
                "sub": BlockInstance("sub", "Subsystem", internal_diagram=inner, input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[
                Connection("src", "out", "sub", "in"),
            ],
        )
        compiled = compile_diagram(outer)
        # sub should not appear in execution order
        assert "sub" not in compiled.execution_order
        assert "sub/in1" in compiled.execution_order
        assert "sub/g" in compiled.execution_order
        assert "sub/out1" in compiled.execution_order
