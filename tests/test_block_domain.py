"""Tests for quino.domain.blocks (Paso 2.1)."""

import pytest

from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec


class TestPortSpec:
    def test_default_shape(self) -> None:
        p = PortSpec(name="in")
        assert p.shape == (1,)

    def test_custom_shape(self) -> None:
        p = PortSpec(name="vec", shape=(3,))
        assert p.shape == (3,)


class TestBlockInstance:
    def test_parameter_access(self) -> None:
        b = BlockInstance(
            instance_id="g1",
            block_type="Gain",
            parameters={"k": 2.5},
        )
        assert b.parameter("k") == 2.5
        assert b.parameter("missing", 0.0) == 0.0


class TestConnection:
    def test_creation(self) -> None:
        c = Connection(
            src_instance="src",
            src_port="out",
            dst_instance="dst",
            dst_port="in",
        )
        assert c.src_instance == "src"
        assert c.dst_port == "in"


class TestBlockDiagramValidation:
    def test_empty_diagram_is_valid(self) -> None:
        d = BlockDiagram()
        d.validate()  # no raise

    def test_unknown_src_instance_raises(self) -> None:
        d = BlockDiagram(
            instances={"dst": BlockInstance("dst", "Gain")},
            connections=[
                Connection("missing", "out", "dst", "in"),
            ],
        )
        with pytest.raises(ValueError, match="unknown source instance"):
            d.validate()

    def test_unknown_dst_instance_raises(self) -> None:
        d = BlockDiagram(
            instances={"src": BlockInstance("src", "Gain")},
            connections=[
                Connection("src", "out", "missing", "in"),
            ],
        )
        with pytest.raises(ValueError, match="unknown destination instance"):
            d.validate()

    def test_self_connection_raises(self) -> None:
        d = BlockDiagram(
            instances={"b": BlockInstance("b", "Gain")},
            connections=[
                Connection("b", "out", "b", "in"),
            ],
        )
        with pytest.raises(ValueError, match="Self-connection not allowed"):
            d.validate()

    def test_duplicate_input_connection_raises(self) -> None:
        d = BlockDiagram(
            instances={
                "src1": BlockInstance("src1", "Constant"),
                "src2": BlockInstance("src2", "Constant"),
                "dst": BlockInstance("dst", "Gain"),
            },
            connections=[
                Connection("src1", "out", "dst", "in"),
                Connection("src2", "out", "dst", "in"),
            ],
        )
        with pytest.raises(ValueError, match="multiple connections"):
            d.validate()

    def test_valid_linear_chain(self) -> None:
        d = BlockDiagram(
            instances={
                "a": BlockInstance("a", "Constant"),
                "b": BlockInstance("b", "Gain"),
                "c": BlockInstance("c", "Scope"),
            },
            connections=[
                Connection("a", "out", "b", "in"),
                Connection("b", "out", "c", "in"),
            ],
        )
        d.validate()  # no raise
