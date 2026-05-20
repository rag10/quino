"""Tests for electrical and hydraulic blocks (Fase 5.3)."""

import numpy as np
import pytest

from quino.blocks.engine import BlockEngine
from quino.blocks.library import get_block_def
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec


class TestElectricalBlocks:
    def test_resistor(self) -> None:
        diagram = BlockDiagram(
            instances={
                "v": BlockInstance("v", "Constant", parameters={"value": 10.0}, output_ports=[PortSpec("out")]),
                "r": BlockInstance("r", "Resistor", parameters={"r": 5.0}, input_ports=[PortSpec("v")], output_ports=[PortSpec("i")]),
            },
            connections=[Connection("v", "out", "r", "v")],
        )
        engine = BlockEngine.from_diagram(diagram)
        engine.step(t=0.0, dt=0.01)
        assert np.isclose(engine.output("r", "i")[0], 2.0)

    def test_inductor_integration(self) -> None:
        diagram = BlockDiagram(
            instances={
                "v": BlockInstance("v", "Constant", parameters={"value": 5.0}, output_ports=[PortSpec("out")]),
                "l": BlockInstance("l", "Inductor", parameters={"l": 1.0, "initial_current": 0.0}, input_ports=[PortSpec("v")], output_ports=[PortSpec("i")]),
            },
            connections=[Connection("v", "out", "l", "v")],
        )
        engine = BlockEngine.from_diagram(diagram)
        engine.step(t=0.0, dt=0.1)
        # i = i0 + V/L * dt = 0 + 5 * 0.1 = 0.5
        assert np.isclose(engine.output("l", "i")[0], 0.5)
        engine.step(t=0.1, dt=0.1)
        # i = 0.5 + 5 * 0.1 = 1.0
        assert np.isclose(engine.output("l", "i")[0], 1.0)

    def test_capacitor_integration(self) -> None:
        diagram = BlockDiagram(
            instances={
                "i": BlockInstance("i", "Constant", parameters={"value": 2.0}, output_ports=[PortSpec("out")]),
                "c": BlockInstance("c", "Capacitor", parameters={"c": 1.0, "initial_voltage": 0.0}, input_ports=[PortSpec("i")], output_ports=[PortSpec("v")]),
            },
            connections=[Connection("i", "out", "c", "i")],
        )
        engine = BlockEngine.from_diagram(diagram)
        engine.step(t=0.0, dt=0.1)
        # v = v0 + I/C * dt = 0 + 2 * 0.1 = 0.2
        assert np.isclose(engine.output("c", "v")[0], 0.2)

    def test_dc_motor(self) -> None:
        diagram = BlockDiagram(
            instances={
                "v": BlockInstance("v", "Constant", parameters={"value": 12.0}, output_ports=[PortSpec("out")]),
                "motor": BlockInstance("motor", "DCMotor", parameters={"kt": 0.5, "r": 2.0}, input_ports=[PortSpec("v")], output_ports=[PortSpec("torque")]),
            },
            connections=[Connection("v", "out", "motor", "v")],
        )
        engine = BlockEngine.from_diagram(diagram)
        engine.step(t=0.0, dt=0.01)
        # T = Kt * V / R = 0.5 * 12 / 2 = 3.0
        assert np.isclose(engine.output("motor", "torque")[0], 3.0)


class TestHydraulicBlocks:
    def test_hydraulic_pump(self) -> None:
        diagram = BlockDiagram(
            instances={
                "pump": BlockInstance("pump", "HydraulicPump", parameters={"q": 5.0}, output_ports=[PortSpec("out")]),
            },
            connections=[],
        )
        engine = BlockEngine.from_diagram(diagram)
        engine.step(t=0.0, dt=0.01)
        assert np.isclose(engine.output("pump", "out")[0], 5.0)

    def test_hydraulic_orifice(self) -> None:
        diagram = BlockDiagram(
            instances={
                "dp": BlockInstance("dp", "Constant", parameters={"value": 4.0}, output_ports=[PortSpec("out")]),
                "orif": BlockInstance("orif", "HydraulicOrifice", parameters={"gain": 1.0}, input_ports=[PortSpec("dp")], output_ports=[PortSpec("out")]),
            },
            connections=[Connection("dp", "out", "orif", "dp")],
        )
        engine = BlockEngine.from_diagram(diagram)
        engine.step(t=0.0, dt=0.01)
        # Q = gain * sqrt(|dp|) * sign(dp) = 1 * 2 * 1 = 2
        assert np.isclose(engine.output("orif", "out")[0], 2.0)

    def test_hydraulic_chamber(self) -> None:
        diagram = BlockDiagram(
            instances={
                "q": BlockInstance("q", "Constant", parameters={"value": 0.01}, output_ports=[PortSpec("out")]),
                "ch": BlockInstance("ch", "HydraulicChamber", parameters={"bulk_modulus": 1000.0, "volume": 1.0, "initial_pressure": 0.0}, input_ports=[PortSpec("q")], output_ports=[PortSpec("p")]),
            },
            connections=[Connection("q", "out", "ch", "q")],
        )
        engine = BlockEngine.from_diagram(diagram)
        engine.step(t=0.0, dt=0.1)
        # p = p0 + beta/V * q * dt = 0 + 1000 * 0.01 * 0.1 = 1.0
        assert np.isclose(engine.output("ch", "p")[0], 1.0)
