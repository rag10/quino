from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from quino import ApplicationService, DriverType, MarkerInput
from quino.blocks.exudyn_bridge import ExudynBlockBridge
from quino.blocks.library import BLOCK_REGISTRY
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec
from quino.gui.blocks.block_canvas import BlockDiagramScene
from quino.gui.blocks.inspector import BlockInspector
from quino.gui.blocks.palette import BlockPalette, palette_categories


def test_semantic_block_types_are_registered() -> None:
    for block_type in ("ModelSensor", "LoadCommand", "SpringCommand", "DriverCommand"):
        assert block_type in BLOCK_REGISTRY


def test_palette_exposes_semantic_model_interface_blocks() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    palette = BlockPalette()

    names_by_category: dict[str, list[str]] = {}
    for index in range(palette.topLevelItemCount()):
        category_item = palette.topLevelItem(index)
        names_by_category[category_item.text(0)] = [
            category_item.child(child_index).text(0)
            for child_index in range(category_item.childCount())
        ]

    assert "Model Interface" in names_by_category
    assert names_by_category["Model Interface"] == palette_categories()["Model Interface"]
    assert "Legacy MBS Interface" in names_by_category
    assert qt_app is not None


def test_exudyn_bridge_recognizes_semantic_sensor_and_command_blocks() -> None:
    diagram = BlockDiagram(
        instances={
            "sensor": BlockInstance(
                "sensor", "ModelSensor",
                parameters={"sensor_id": "sensor_001", "channel": "y"},
                output_ports=[PortSpec("out")],
            ),
            "src": BlockInstance(
                "src", "Constant",
                parameters={"value": 4.0},
                output_ports=[PortSpec("out")],
            ),
            "driver": BlockInstance(
                "driver", "DriverCommand",
                parameters={"driver_id": "driver_001"},
                input_ports=[PortSpec("in")],
                output_ports=[PortSpec("out")],
            ),
        },
        connections=[Connection("src", "out", "driver", "in")],
    )

    bridge = ExudynBlockBridge(
        diagram,
        mbs=None,
        item_interface=None,
        exu=None,
        node_numbers={},
        body_objects={},
    )

    assert "sensor" in bridge._sensor_instances
    assert "driver" in bridge._actuator_instances


def test_semantic_blocks_get_default_parameters_on_creation() -> None:
    scene = BlockDiagramScene()
    item = scene.add_block("ModelSensor", QtCore.QPointF(10.0, 20.0))

    assert item is not None
    inst = scene.diagram.instances[item.instance_id]
    assert inst.parameters["sensor_id"] == ""
    assert inst.parameters["channel"] == "y"


def test_block_inspector_uses_model_aware_combos_for_semantic_blocks() -> None:
    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app = ApplicationService()
    app.new_project("Inspector")
    body_id = app.create_body("Body", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(marker.id for marker in app.get_body(body_id).markers if marker.name == "P")
    sensor_id = app.create_sensor("Probe", "point", [marker_id])
    joint_id = app.connect_marker_to_ground(marker_id, name="Ground_P")
    driver_id = app.create_driver("Drive", DriverType.ROTATION.value, joint_id, "0 deg", "deg")

    inspector = BlockInspector()
    inspector.set_project(app.project)
    inspector.set_block(
        "sensor_block",
        "ModelSensor",
        {"sensor_id": sensor_id, "channel": "y"},
    )

    sensor_widget = inspector._fields["sensor_id"]
    channel_widget = inspector._fields["channel"]
    assert isinstance(sensor_widget, QtWidgets.QComboBox)
    assert isinstance(channel_widget, QtWidgets.QComboBox)
    assert sensor_widget.currentData() == sensor_id
    assert channel_widget.currentData() == "y"

    inspector.set_block(
        "driver_block",
        "DriverCommand",
        {"driver_id": driver_id},
    )
    driver_widget = inspector._fields["driver_id"]
    assert isinstance(driver_widget, QtWidgets.QComboBox)
    assert driver_widget.currentData() == driver_id
    assert qt_app is not None
