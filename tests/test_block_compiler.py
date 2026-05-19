"""Tests for quino.blocks.compiler (Paso 2.2)."""

import pytest

from quino.blocks.compiler import compile_diagram
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec


class TestCompileDiagram:
    def test_linear_chain(self) -> None:
        d = BlockDiagram(
            instances={
                "a": BlockInstance("a", "Constant", output_ports=[PortSpec("out")]),
                "b": BlockInstance("b", "Gain", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "c": BlockInstance("c", "Scope", input_ports=[PortSpec("in")]),
            },
            connections=[
                Connection("a", "out", "b", "in"),
                Connection("b", "out", "c", "in"),
            ],
        )
        compiled = compile_diagram(d)
        assert compiled.execution_order == ["a", "b", "c"]
        assert compiled.wiring[("a", "out")] == [("b", "in")]
        assert compiled.wiring[("b", "out")] == [("c", "in")]

    def test_fan_out(self) -> None:
        d = BlockDiagram(
            instances={
                "src": BlockInstance("src", "Constant", output_ports=[PortSpec("out")]),
                "dst1": BlockInstance("dst1", "Gain", input_ports=[PortSpec("in")]),
                "dst2": BlockInstance("dst2", "Gain", input_ports=[PortSpec("in")]),
            },
            connections=[
                Connection("src", "out", "dst1", "in"),
                Connection("src", "out", "dst2", "in"),
            ],
        )
        compiled = compile_diagram(d)
        assert compiled.execution_order[0] == "src"
        assert compiled.wiring[("src", "out")] == [("dst1", "in"), ("dst2", "in")]

    def test_cycle_detection(self) -> None:
        d = BlockDiagram(
            instances={
                "a": BlockInstance("a", "Gain", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "b": BlockInstance("b", "Gain", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[
                Connection("a", "out", "b", "in"),
                Connection("b", "out", "a", "in"),
            ],
        )
        with pytest.raises(ValueError, match="Algebraic cycle detected"):
            compile_diagram(d)

    def test_unconnected_input_raises(self) -> None:
        d = BlockDiagram(
            instances={
                "a": BlockInstance("a", "Gain", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[],
        )
        with pytest.raises(ValueError, match="not connected"):
            compile_diagram(d)

    def test_self_loop_raises(self) -> None:
        d = BlockDiagram(
            instances={
                "a": BlockInstance("a", "Gain", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
            },
            connections=[
                Connection("a", "out", "a", "in"),
            ],
        )
        with pytest.raises(ValueError, match="Self-connection not allowed"):
            compile_diagram(d)
