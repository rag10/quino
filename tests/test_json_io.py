"""Tests for granular block diagram serialization."""

import pytest
from quino.domain.blocks import BlockInstance, Connection, PortSpec, BlockDiagram
from quino.serialization.json_io import JsonMapper


def test_block_instance_roundtrip():
    from quino.domain.blocks import BlockInstance
    from quino.serialization.json_io import JsonMapper
    inst = BlockInstance(
        instance_id="b1",
        block_type="constant",
        parameters={"value": 1.5},
        output_ports=[PortSpec("out", (1,))],
        position=(10.0, 20.0),
    )
    payload = JsonMapper()._block_instance_to_dict(inst)
    restored = JsonMapper()._block_instance_from_dict(payload)
    assert restored.instance_id == "b1"
    assert restored.block_type == "constant"
    assert restored.position == (10.0, 20.0)
    assert restored.parameters == {"value": 1.5}


def test_block_connection_roundtrip():
    from quino.domain.blocks import Connection
    from quino.serialization.json_io import JsonMapper
    conn = Connection(
        src_instance="b1", src_port="out",
        dst_instance="b2", dst_port="in",
    )
    payload = JsonMapper()._block_connection_to_dict(conn)
    restored = JsonMapper()._block_connection_from_dict(payload)
    assert restored.src_instance == "b1"
    assert restored.dst_instance == "b2"


class TestBlockInstanceSerialization:
    """Tests for BlockInstance serialization."""

    def test_block_instance_roundtrip_with_ports(self):
        inst = BlockInstance(
            instance_id="b1",
            block_type="constant",
            parameters={"value": 1.5},
            input_ports=[],
            output_ports=[PortSpec("out", (1,))],
            position=(10.0, 20.0),
        )
        mapper = JsonMapper()
        payload = mapper._block_instance_to_dict(inst)
        restored = mapper._block_instance_from_dict(payload)

        assert restored.instance_id == "b1"
        assert restored.block_type == "constant"
        assert restored.parameters == {"value": 1.5}
        assert restored.position == (10.0, 20.0)
        assert len(restored.output_ports) == 1
        assert restored.output_ports[0].name == "out"

    def test_block_instance_with_empty_parameters(self):
        inst = BlockInstance(
            instance_id="b2",
            block_type="gain",
            parameters={},
            input_ports=[PortSpec("in", (1,))],
            output_ports=[PortSpec("out", (1,))],
            position=(0.0, 0.0),
        )
        mapper = JsonMapper()
        payload = mapper._block_instance_to_dict(inst)
        restored = mapper._block_instance_from_dict(payload)

        assert restored.instance_id == "b2"
        assert restored.block_type == "gain"
        assert restored.parameters == {}

    def test_block_instance_with_multiple_ports(self):
        inst = BlockInstance(
            instance_id="b3",
            block_type="sum",
            parameters={},
            input_ports=[PortSpec("in1", (1,)), PortSpec("in2", (2,))],
            output_ports=[PortSpec("out", (1,))],
            position=(5.5, 10.5),
        )
        mapper = JsonMapper()
        payload = mapper._block_instance_to_dict(inst)
        restored = mapper._block_instance_from_dict(payload)

        assert len(restored.input_ports) == 2
        assert restored.input_ports[0].name == "in1"
        assert restored.input_ports[1].shape == (2,)


class TestConnectionSerialization:
    """Tests for Connection serialization."""

    def test_connection_roundtrip(self):
        conn = Connection(
            src_instance="b1", src_port="out",
            dst_instance="b2", dst_port="in",
        )
        mapper = JsonMapper()
        payload = mapper._block_connection_to_dict(conn)
        restored = mapper._block_connection_from_dict(payload)

        assert restored.src_instance == "b1"
        assert restored.src_port == "out"
        assert restored.dst_instance == "b2"
        assert restored.dst_port == "in"

    def test_connection_various_ports(self):
        conn = Connection(
            src_instance="source_block",
            src_port="output_signal",
            dst_instance="sink_block",
            dst_port="input_signal",
        )
        mapper = JsonMapper()
        payload = mapper._block_connection_to_dict(conn)
        restored = mapper._block_connection_from_dict(payload)

        assert restored.src_instance == "source_block"
        assert restored.src_port == "output_signal"


class TestBlockDiagramRefactoring:
    """Verify that diagram roundtrip uses granular helpers and is backward compatible."""

    def test_block_diagram_roundtrip_unchanged(self):
        diagram = BlockDiagram(
            instances={
                "b1": BlockInstance(
                    instance_id="b1",
                    block_type="constant",
                    parameters={"value": 1.5},
                    input_ports=[],
                    output_ports=[PortSpec("out", (1,))],
                    position=(10.0, 20.0),
                ),
                "b2": BlockInstance(
                    instance_id="b2",
                    block_type="gain",
                    parameters={"gain": 2.0},
                    input_ports=[PortSpec("in", (1,))],
                    output_ports=[PortSpec("out", (1,))],
                    position=(30.0, 20.0),
                ),
            },
            connections=[
                Connection(src_instance="b1", src_port="out",
                           dst_instance="b2", dst_port="in")
            ],
        )

        mapper = JsonMapper()
        payload = mapper._block_diagram_to_dict(diagram)
        restored = mapper._block_diagram_from_dict(payload)

        assert len(restored.instances) == 2
        assert "b1" in restored.instances
        assert restored.instances["b1"].block_type == "constant"
        assert len(restored.connections) == 1
        assert restored.connections[0].src_instance == "b1"
