"""Tests for granular block diagram serialization."""

import pytest
from quino.domain.blocks import BlockInstance, Connection, PortSpec, BlockDiagram
from quino.serialization.json_io import JsonMapper


class TestBlockInstanceSerialization:
    """Tests for BlockInstance serialization."""

    def test_block_instance_roundtrip(self):
        """Test that a BlockInstance can be serialized and deserialized."""
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
        restored = mapper._block_instance_from_dict("b1", payload)

        assert restored.instance_id == "b1"
        assert restored.block_type == "constant"
        assert restored.parameters == {"value": 1.5}
        assert restored.position == (10.0, 20.0)
        assert len(restored.output_ports) == 1
        assert restored.output_ports[0].name == "out"

    def test_block_instance_with_empty_parameters(self):
        """Test BlockInstance with no parameters."""
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
        restored = mapper._block_instance_from_dict("b2", payload)

        assert restored.instance_id == "b2"
        assert restored.block_type == "gain"
        assert restored.parameters == {}
        assert restored.position == (0.0, 0.0)

    def test_block_instance_with_ports_roundtrip(self):
        """Test BlockInstance with multiple input/output ports."""
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
        restored = mapper._block_instance_from_dict("b3", payload)

        assert len(restored.input_ports) == 2
        assert restored.input_ports[0].name == "in1"
        assert restored.input_ports[0].shape == (1,)
        assert restored.input_ports[1].name == "in2"
        assert restored.input_ports[1].shape == (2,)
        assert len(restored.output_ports) == 1


class TestConnectionSerialization:
    """Tests for Connection serialization."""

    def test_connection_roundtrip(self):
        """Test that a Connection can be serialized and deserialized."""
        conn = Connection(
            src_instance="b1",
            src_port="out",
            dst_instance="b2",
            dst_port="in",
        )
        mapper = JsonMapper()
        payload = mapper._connection_to_dict(conn)
        restored = mapper._connection_from_dict(payload)

        assert restored.src_instance == "b1"
        assert restored.src_port == "out"
        assert restored.dst_instance == "b2"
        assert restored.dst_port == "in"

    def test_connection_various_ports(self):
        """Test Connection with various port names."""
        conn = Connection(
            src_instance="source_block",
            src_port="output_signal",
            dst_instance="sink_block",
            dst_port="input_signal",
        )
        mapper = JsonMapper()
        payload = mapper._connection_to_dict(conn)
        restored = mapper._connection_from_dict(payload)

        assert restored.src_instance == "source_block"
        assert restored.src_port == "output_signal"
        assert restored.dst_instance == "sink_block"
        assert restored.dst_port == "input_signal"


class TestBlockDiagramRefactoring:
    """Tests to verify that refactoring _block_diagram_to_dict and _block_diagram_from_dict produces identical output."""

    def test_block_diagram_roundtrip_unchanged(self):
        """Test that existing block diagram serialization behavior is unchanged."""
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
                Connection(
                    src_instance="b1",
                    src_port="out",
                    dst_instance="b2",
                    dst_port="in",
                )
            ],
        )

        mapper = JsonMapper()
        payload = mapper._block_diagram_to_dict(diagram)
        restored = mapper._block_diagram_from_dict(payload)

        assert len(restored.instances) == 2
        assert "b1" in restored.instances
        assert "b2" in restored.instances
        assert restored.instances["b1"].block_type == "constant"
        assert restored.instances["b2"].block_type == "gain"
        assert len(restored.connections) == 1
        assert restored.connections[0].src_instance == "b1"
        assert restored.connections[0].dst_instance == "b2"
