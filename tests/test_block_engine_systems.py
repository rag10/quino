"""Integration tests for BlockEngine with complete control systems (Paso 2.6)."""

import numpy as np

from quino.blocks.engine import BlockEngine
from quino.domain.blocks import BlockDiagram, BlockInstance, Connection, PortSpec


class TestFirstOrderResponse:
    """Simulate a first-order low-pass filter using an integrator with feedback.

    Diagram: Step -> Adder -> Integrator -> Output
                    ^- Gain(-1) <-----------+
    ODE: dx/dt = (u - x)  ->  tau=1 first-order response.
    """

    def test_step_response(self) -> None:
        diagram = BlockDiagram(
            instances={
                "step": BlockInstance("step", "Step", output_ports=[PortSpec("out")]),
                "sum": BlockInstance("sum", "Adder", input_ports=[PortSpec("in0"), PortSpec("in1")], output_ports=[PortSpec("out")]),
                "integ": BlockInstance("integ", "Integrator", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "fb": BlockInstance("fb", "Gain", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")], parameters={"k": -1.0}),
            },
            connections=[
                Connection("step", "out", "sum", "in0"),
                Connection("fb", "out", "sum", "in1"),
                Connection("sum", "out", "integ", "in"),
                Connection("integ", "out", "fb", "in"),
            ],
        )
        engine = BlockEngine.from_diagram(diagram)

        # Step final value = 1.0 (default), step_time = 0.0
        # The first-order response x(t) = 1 * (1 - exp(-t))
        dt = 0.01
        t_final = 3.0
        steps = int(t_final / dt)
        for i in range(steps):
            t = (i + 1) * dt
            engine.step(t, dt)

        final_output = engine.output("integ", "out")[0]
        expected = 1.0 * (1.0 - np.exp(-t_final))
        assert np.isclose(final_output, expected, rtol=0.05)


class TestPIDPositionControl:
    """PID controlling a double-integrator plant (1/s^2).

    Diagram: Step -> Adder(error=ref-pos) -> PID -> Plant(Integrator->Integrator)
    """

    def test_convergence(self) -> None:
        diagram = BlockDiagram(
            instances={
                "ref": BlockInstance("ref", "Step", output_ports=[PortSpec("out")], parameters={"final_value": 1.0}),
                "err": BlockInstance("err", "Adder", input_ports=[PortSpec("in0"), PortSpec("in1")], output_ports=[PortSpec("out")]),
                "pid": BlockInstance("pid", "PID", input_ports=[PortSpec("error")], output_ports=[PortSpec("out")], parameters={"kp": 10.0, "ki": 2.0, "kd": 1.0}),
                "plant_v": BlockInstance("plant_v", "Integrator", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "plant_x": BlockInstance("plant_x", "Integrator", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")]),
                "neg": BlockInstance("neg", "Gain", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")], parameters={"k": -1.0}),
            },
            connections=[
                Connection("ref", "out", "err", "in0"),
                Connection("plant_x", "out", "neg", "in"),
                Connection("neg", "out", "err", "in1"),
                Connection("err", "out", "pid", "error"),
                Connection("pid", "out", "plant_v", "in"),
                Connection("plant_v", "out", "plant_x", "in"),
            ],
        )
        engine = BlockEngine.from_diagram(diagram)

        dt = 0.01
        t_final = 8.0
        steps = int(t_final / dt)
        for i in range(steps):
            t = (i + 1) * dt
            engine.step(t, dt)

        final_pos = engine.output("plant_x", "out")[0]
        # Should converge close to reference = 1.0
        assert np.isclose(final_pos, 1.0, atol=0.1)


class TestIntegratorSaturation:
    """Integrator with output saturation should clip at the limit."""

    def test_saturation(self) -> None:
        diagram = BlockDiagram(
            instances={
                "src": BlockInstance("src", "Constant", output_ports=[PortSpec("out")], parameters={"value": 10.0}),
                "integ": BlockInstance("integ", "IntegratorLimited", input_ports=[PortSpec("in")], output_ports=[PortSpec("out")], parameters={"lower": -2.0, "upper": 2.0}),
            },
            connections=[
                Connection("src", "out", "integ", "in"),
            ],
        )
        engine = BlockEngine.from_diagram(diagram)

        dt = 0.1
        for i in range(100):
            t = (i + 1) * dt
            engine.step(t, dt)

        final = engine.output("integ", "out")[0]
        assert np.isclose(final, 2.0)
