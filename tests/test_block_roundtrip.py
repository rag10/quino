"""Round-trip tests for BlockDiagram JSON serialization (Paso 2.7)."""

from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec
from quino.serialization.json_io import JsonMapper


class TestBlockDiagramRoundTrip:
    def test_roundtrip(self) -> None:
        original = BlockDiagram(
            instances={
                "src": BlockInstance(
                    "src", "Constant",
                    parameters={"value": 3.0},
                    output_ports=[PortSpec("out")],
                    position=(10.0, 20.0),
                ),
                "dst": BlockInstance(
                    "dst", "Gain",
                    parameters={"k": 2.0},
                    input_ports=[PortSpec("in")],
                    output_ports=[PortSpec("out")],
                    position=(30.0, 40.0),
                ),
            },
            connections=[
                Connection("src", "out", "dst", "in"),
            ],
        )

        mapper = JsonMapper()
        data = mapper._block_diagram_to_dict(original)
        restored = mapper._block_diagram_from_dict(data)

        assert restored is not None
        assert list(restored.instances.keys()) == ["src", "dst"]
        assert restored.instances["src"].block_type == "Constant"
        assert restored.instances["src"].parameters["value"] == 3.0
        assert restored.instances["src"].position == (10.0, 20.0)
        assert restored.instances["dst"].input_ports[0].name == "in"
        assert len(restored.connections) == 1
        assert restored.connections[0].src_instance == "src"
        assert restored.connections[0].dst_port == "in"

    def test_none_roundtrip(self) -> None:
        mapper = JsonMapper()
        restored = mapper._block_diagram_from_dict(None)
        assert restored is None
