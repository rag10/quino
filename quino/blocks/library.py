"""Block library: pure functions for sources, math and routing blocks.

Signals are 1-D numpy arrays. Scalars are shape (1,).
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from quino.domain.blocks import PortSpec


class BlockDef:
    """Definition of a block type: ports and compute/update functions.

    Stateless blocks only provide ``compute``.
    Stateful blocks provide ``init_state`` and ``update`` instead.
    All callables receive an optional ``context`` argument (e.g. the Exudyn bridge).
    """

    def __init__(
        self,
        input_specs: list[PortSpec],
        output_specs: list[PortSpec],
        compute: Callable[..., dict[str, np.ndarray]] | None = None,
        init_state: Callable[..., dict[str, np.ndarray]] | None = None,
        update: Callable[..., dict[str, np.ndarray]] | None = None,
    ) -> None:
        self.input_specs = input_specs
        self.output_specs = output_specs
        self.compute = compute
        self.init_state = init_state
        self.update = update
        if (compute is None) == (update is None):
            raise ValueError("BlockDef must provide exactly one of compute or update")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _constant(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    value = float(parameters.get("value", 0.0))
    return {"out": np.array([value])}


def _step(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    step_time = float(parameters.get("step_time", 0.0))
    initial = float(parameters.get("initial_value", 0.0))
    final = float(parameters.get("final_value", 1.0))
    return {"out": np.array([final if t >= step_time else initial])}


def _ramp(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    slope = float(parameters.get("slope", 1.0))
    start_time = float(parameters.get("start_time", 0.0))
    return {"out": np.array([slope * max(t - start_time, 0.0)])}


def _sine(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    amplitude = float(parameters.get("amplitude", 1.0))
    frequency = float(parameters.get("frequency", 1.0))
    phase = float(parameters.get("phase", 0.0))
    bias = float(parameters.get("bias", 0.0))
    return {"out": np.array([bias + amplitude * np.sin(2.0 * np.pi * frequency * t + phase)])}


# ---------------------------------------------------------------------------
# Math / Operations
# ---------------------------------------------------------------------------

def _gain(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    k = float(parameters.get("k", 1.0))
    return {"out": k * inputs["in"]}


def _adder(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    result = np.zeros_like(next(iter(inputs.values())))
    signs = parameters.get("signs")
    if signs is not None:
        for key, arr in inputs.items():
            # Try to extract numeric index from port name (e.g. 'in0' -> 0, 'a' -> 0)
            idx = None
            if key.startswith("in"):
                try:
                    idx = int(key[2:])
                except ValueError:
                    pass
            if idx is None:
                idx = list(inputs.keys()).index(key)
            sign = float(signs[idx]) if idx < len(signs) else 1.0
            result = result + sign * arr
    else:
        for arr in inputs.values():
            result = result + arr
    return {"out": result}


def _product(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    result = np.ones_like(next(iter(inputs.values())))
    for arr in inputs.values():
        result = result * arr
    return {"out": result}


def _saturation(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    lower = float(parameters.get("lower", -1.0))
    upper = float(parameters.get("upper", 1.0))
    return {"out": np.clip(inputs["in"], lower, upper)}


def _dead_zone(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    deadband = float(parameters.get("deadband", 0.5))
    x = inputs["in"]
    out = np.where(
        np.abs(x) <= deadband,
        0.0,
        x - deadband * np.sign(x),
    )
    return {"out": out}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _mux(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    # Concatenate all scalar inputs into a vector
    parts = [inputs[f"in{i}"] for i in range(len(inputs))]
    return {"out": np.concatenate(parts)}


def _demux(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    vec = inputs["in"]
    n = vec.shape[0]
    return {f"out{i}": vec[i : i + 1] for i in range(n)}


# ---------------------------------------------------------------------------
# Stateful blocks
# ---------------------------------------------------------------------------

def _integrator_init(parameters: dict[str, Any]) -> dict[str, np.ndarray]:
    x0 = float(parameters.get("initial_condition", 0.0))
    return {"x": np.array([x0])}


def _integrator_update(
    inputs: dict[str, np.ndarray],
    parameters: dict[str, Any],
    t: float,
    dt: float,
    state: dict[str, np.ndarray],
    **kwargs,
) -> dict[str, np.ndarray]:
    x = state["x"] + inputs["in"] * dt
    return {"out": x.copy(), "x": x}


def _integrator_limited_init(parameters: dict[str, Any]) -> dict[str, np.ndarray]:
    x0 = float(parameters.get("initial_condition", 0.0))
    return {"x": np.array([x0])}


def _integrator_limited_update(
    inputs: dict[str, np.ndarray],
    parameters: dict[str, Any],
    t: float,
    dt: float,
    state: dict[str, np.ndarray],
    **kwargs,
) -> dict[str, np.ndarray]:
    lower = float(parameters.get("lower", -1e30))
    upper = float(parameters.get("upper", 1e30))
    x = state["x"] + inputs["in"] * dt
    x = np.clip(x, lower, upper)
    return {"out": x.copy(), "x": x}


def _unit_delay_init(parameters: dict[str, Any]) -> dict[str, np.ndarray]:
    x0 = float(parameters.get("initial_condition", 0.0))
    return {"x": np.array([x0])}


def _unit_delay_update(
    inputs: dict[str, np.ndarray],
    parameters: dict[str, Any],
    t: float,
    dt: float,
    state: dict[str, np.ndarray],
    **kwargs,
) -> dict[str, np.ndarray]:
    out = state["x"].copy()
    x = inputs["in"].copy()
    return {"out": out, "x": x}


# ---------------------------------------------------------------------------
# Control
# ---------------------------------------------------------------------------

def _pid_init(parameters: dict[str, Any]) -> dict[str, np.ndarray]:
    return {
        "integral": np.array([0.0]),
        "last_error": np.array([0.0]),
        "last_t": np.array([-1.0]),  # -1 signals first call
    }


def _pid_update(
    inputs: dict[str, np.ndarray],
    parameters: dict[str, Any],
    t: float,
    dt: float,
    state: dict[str, np.ndarray],
    **kwargs,
) -> dict[str, np.ndarray]:
    kp = float(parameters.get("kp", 1.0))
    ki = float(parameters.get("ki", 0.0))
    kd = float(parameters.get("kd", 0.0))
    lower = float(parameters.get("lower", -1e30))
    upper = float(parameters.get("upper", 1e30))
    anti_windup = bool(parameters.get("anti_windup", False))

    error = inputs["error"][0]
    integral = state["integral"][0]
    last_error = state["last_error"][0]
    last_t = state["last_t"][0]

    if last_t < 0:
        effective_dt = dt
        derivative = 0.0
    else:
        effective_dt = t - last_t
        if effective_dt > 0:
            derivative = (error - last_error) / effective_dt
        else:
            derivative = 0.0
    integral += error * effective_dt

    output = kp * error + ki * integral + kd * derivative

    # Output saturation + anti-windup (clamping)
    saturated = np.clip(output, lower, upper)
    if anti_windup and ki != 0.0 and output != saturated:
        integral -= (output - saturated) / ki

    return {
        "out": np.array([saturated]),
        "integral": np.array([integral]),
        "last_error": np.array([error]),
        "last_t": np.array([t]),
    }


def _derivative_filtered_init(parameters: dict[str, Any]) -> dict[str, np.ndarray]:
    return {
        "last_input": np.array([0.0]),
        "last_output": np.array([0.0]),
        "last_t": np.array([-1.0]),
    }


def _derivative_filtered_update(
    inputs: dict[str, np.ndarray],
    parameters: dict[str, Any],
    t: float,
    dt: float,
    state: dict[str, np.ndarray],
    **kwargs,
) -> dict[str, np.ndarray]:
    time_constant = float(parameters.get("time_constant", 0.01))
    last_input = state["last_input"][0]
    last_output = state["last_output"][0]
    last_t = state["last_t"][0]

    if last_t < 0:
        output = 0.0
    else:
        effective_dt = t - last_t
        if effective_dt > 0 and time_constant > 0:
            # Backward Euler discretization of tau*dy/dt + y = dx/dt
            dx = inputs["in"][0] - last_input
            alpha = time_constant / (time_constant + effective_dt)
            output = alpha * last_output + (1.0 - alpha) * dx / effective_dt
        else:
            output = last_output

    return {
        "out": np.array([output]),
        "last_input": inputs["in"].copy(),
        "last_output": np.array([output]),
        "last_t": np.array([t]),
    }


# ---------------------------------------------------------------------------
# Electrical domain
# ---------------------------------------------------------------------------

def _resistor(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    r = float(parameters.get("r", 1.0))
    v = float(inputs["v"][0])
    return {"i": np.array([v / r])}


def _inductor_init(parameters: dict[str, Any]) -> dict[str, np.ndarray]:
    return {"i_state": np.array([float(parameters.get("initial_current", 0.0))])}


def _inductor_update(
    inputs: dict[str, np.ndarray],
    parameters: dict[str, Any],
    t: float,
    dt: float,
    state: dict[str, np.ndarray],
    **kwargs,
) -> dict[str, np.ndarray]:
    l = float(parameters.get("l", 1.0))
    v = float(inputs["v"][0])
    i = state["i_state"][0] + (v / l) * dt
    return {"i": np.array([i]), "i_state": np.array([i])}


def _capacitor_init(parameters: dict[str, Any]) -> dict[str, np.ndarray]:
    return {"v_state": np.array([float(parameters.get("initial_voltage", 0.0))])}


def _capacitor_update(
    inputs: dict[str, np.ndarray],
    parameters: dict[str, Any],
    t: float,
    dt: float,
    state: dict[str, np.ndarray],
    **kwargs,
) -> dict[str, np.ndarray]:
    c = float(parameters.get("c", 1.0))
    i = float(inputs["i"][0])
    v = state["v_state"][0] + (i / c) * dt
    return {"v": np.array([v]), "v_state": np.array([v])}


def _dc_motor(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    """Simplified DC motor: torque = Kt * V / R (steady-state electrical)."""
    kt = float(parameters.get("kt", 1.0))
    r = float(parameters.get("r", 1.0))
    v = float(inputs["v"][0])
    torque = kt * v / r
    return {"torque": np.array([torque])}


# ---------------------------------------------------------------------------
# Hydraulic domain
# ---------------------------------------------------------------------------

def _hydraulic_pump(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    q = float(parameters.get("q", 1.0))
    return {"out": np.array([q])}


def _hydraulic_orifice(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    gain = float(parameters.get("gain", 1.0))
    dp = float(inputs["dp"][0])
    q = gain * np.sign(dp) * np.sqrt(abs(dp))
    return {"out": np.array([q])}


def _hydraulic_chamber_init(parameters: dict[str, Any]) -> dict[str, np.ndarray]:
    return {"p_state": np.array([float(parameters.get("initial_pressure", 0.0))])}


def _hydraulic_chamber_update(
    inputs: dict[str, np.ndarray],
    parameters: dict[str, Any],
    t: float,
    dt: float,
    state: dict[str, np.ndarray],
    **kwargs,
) -> dict[str, np.ndarray]:
    beta = float(parameters.get("bulk_modulus", 1.6e9))
    volume = float(parameters.get("volume", 1.0))
    q = float(inputs["q"][0])
    p = state["p_state"][0] + (beta / volume) * q * dt
    return {"p": np.array([p]), "p_state": np.array([p])}


# ---------------------------------------------------------------------------
# Subsystem ports
# ---------------------------------------------------------------------------

def _inport(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    return {"out": inputs["in"].copy()}


def _outport(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    return {"out": inputs["in"].copy()}


# ---------------------------------------------------------------------------
# MBS Interface (Exudyn bridge)
# ---------------------------------------------------------------------------

def _mbs_sensor(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    value = float(parameters.get("_value", 0.0))
    return {"out": np.array([value])}


def _mbs_actuator(inputs: dict[str, np.ndarray], parameters: dict[str, Any], t: float, **kwargs) -> dict[str, np.ndarray]:
    # Pass-through so the bridge can read the output
    return {"out": inputs["in"].copy()}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BLOCK_REGISTRY: dict[str, BlockDef] = {
    # Sources
    "Constant": BlockDef([], [PortSpec("out")], compute=_constant),
    "Step": BlockDef([], [PortSpec("out")], compute=_step),
    "Ramp": BlockDef([], [PortSpec("out")], compute=_ramp),
    "Sine": BlockDef([], [PortSpec("out")], compute=_sine),
    # Math
    "Gain": BlockDef([PortSpec("in")], [PortSpec("out")], compute=_gain),
    "Adder": BlockDef([PortSpec("in0"), PortSpec("in1")], [PortSpec("out")], compute=_adder),
    "Product": BlockDef([PortSpec("in0"), PortSpec("in1")], [PortSpec("out")], compute=_product),
    "Saturation": BlockDef([PortSpec("in")], [PortSpec("out")], compute=_saturation),
    "DeadZone": BlockDef([PortSpec("in")], [PortSpec("out")], compute=_dead_zone),
    # Routing
    "Mux": BlockDef([PortSpec("in0"), PortSpec("in1")], [PortSpec("out")], compute=_mux),
    "Demux": BlockDef([PortSpec("in")], [PortSpec("out0"), PortSpec("out1")], compute=_demux),
    # Stateful
    "Integrator": BlockDef(
        [PortSpec("in")], [PortSpec("out")],
        init_state=_integrator_init, update=_integrator_update,
    ),
    "IntegratorLimited": BlockDef(
        [PortSpec("in")], [PortSpec("out")],
        init_state=_integrator_limited_init, update=_integrator_limited_update,
    ),
    "UnitDelay": BlockDef(
        [PortSpec("in")], [PortSpec("out")],
        init_state=_unit_delay_init, update=_unit_delay_update,
    ),
    "PID": BlockDef(
        [PortSpec("error")], [PortSpec("out")],
        init_state=_pid_init, update=_pid_update,
    ),
    "DerivativeFiltered": BlockDef(
        [PortSpec("in")], [PortSpec("out")],
        init_state=_derivative_filtered_init, update=_derivative_filtered_update,
    ),
    # Electrical
    "Resistor": BlockDef([PortSpec("v")], [PortSpec("i")], compute=_resistor),
    "Inductor": BlockDef(
        [PortSpec("v")], [PortSpec("i")],
        init_state=_inductor_init, update=_inductor_update,
    ),
    "Capacitor": BlockDef(
        [PortSpec("i")], [PortSpec("v")],
        init_state=_capacitor_init, update=_capacitor_update,
    ),
    "DCMotor": BlockDef([PortSpec("v")], [PortSpec("torque")], compute=_dc_motor),
    # Hydraulic
    "HydraulicPump": BlockDef([], [PortSpec("out")], compute=_hydraulic_pump),
    "HydraulicOrifice": BlockDef([PortSpec("dp")], [PortSpec("out")], compute=_hydraulic_orifice),
    "HydraulicChamber": BlockDef(
        [PortSpec("q")], [PortSpec("p")],
        init_state=_hydraulic_chamber_init, update=_hydraulic_chamber_update,
    ),
    # Subsystem ports
    "Inport": BlockDef([PortSpec("in")], [PortSpec("out")], compute=_inport),
    "Outport": BlockDef([PortSpec("in")], [PortSpec("out")], compute=_outport),
    # MBS Interface
    "MBSSensor": BlockDef(
        [], [PortSpec("out")],
        compute=_mbs_sensor,
    ),
    "MBSActuator": BlockDef(
        [PortSpec("in")], [PortSpec("out")],
        compute=_mbs_actuator,
    ),
    # Model semantic interface
    "ModelSensor": BlockDef(
        [], [PortSpec("out")],
        compute=_mbs_sensor,
    ),
    "LoadCommand": BlockDef(
        [PortSpec("in")], [PortSpec("out")],
        compute=_mbs_actuator,
    ),
    "SpringCommand": BlockDef(
        [PortSpec("in")], [PortSpec("out")],
        compute=_mbs_actuator,
    ),
    "DriverCommand": BlockDef(
        [PortSpec("in")], [PortSpec("out")],
        compute=_mbs_actuator,
    ),
}


def get_block_def(block_type: str) -> BlockDef:
    if block_type not in BLOCK_REGISTRY:
        raise ValueError(f"Unknown block type: {block_type!r}")
    return BLOCK_REGISTRY[block_type]
