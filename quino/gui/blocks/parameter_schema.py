"""Per-block-type parameter metadata for inspector rendering.

The schema declares, for each known block type, how each parameter should
be rendered in the inspector. The MainWindow asks ``schema_for(block_type)``
for a dict of ``{param_name: ParamSchema}`` and uses it to pick widgets,
labels, validation hints and choice lists.

Parameters not listed fall back to a plain ``expression``-style line edit
with float/int coercion in the main window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ParamSchema:
    name: str
    type: str  # one of: float, int, bool, str, list_float, enum, entity_ref
    label: str | None = None
    choices: list[str] = field(default_factory=list)
    # When type == "entity_ref", domain identifies which project collection
    # to pull from: sensors / loads / springs / drivers / bodies.
    domain: str = ""
    # Names of other parameters this one depends on. Used by the inspector
    # to recompute choices when any of those changes (e.g. ModelSensor.channel
    # depends on ModelSensor.sensor_id).
    depends_on: list[str] = field(default_factory=list)
    # Optional callable to compute choices dynamically given
    # (display_project, current_block_parameters). Returns list of (label,
    # value) tuples; the GUI shows the label and stores the value.
    dynamic_choices: Callable[..., list[tuple[str, str]]] | None = None


# --- dynamic choice helpers --------------------------------------------------

def _sensor_choices(display_project, _params) -> list[tuple[str, str]]:
    project = display_project
    if project is None:
        return []
    items: list[tuple[str, str]] = []
    seen_names: dict[str, int] = {}
    for sensor in project.model.sensors:
        name = sensor.name or sensor.id
        kind = getattr(sensor, "type", None)
        kind_label = kind.value if hasattr(kind, "value") else (str(kind) if kind else "")
        seen_names[name] = seen_names.get(name, 0) + 1
        # Build a display label that includes kind to disambiguate where useful.
        if kind_label:
            display = f"{name} ({kind_label})"
        else:
            display = name
        items.append((display, sensor.id))
    # If duplicate display labels remain, suffix with a short id slice.
    counts: dict[str, int] = {}
    for label, _ in items:
        counts[label] = counts.get(label, 0) + 1
    if any(v > 1 for v in counts.values()):
        items = [
            (f"{label} [{sid[:6]}]" if counts[label] > 1 else label, sid)
            for label, sid in items
        ]
    return items


_SENSOR_CHANNELS_BY_KIND: dict[str, list[str]] = {
    "point": ["x", "y", "vx", "vy", "ax", "ay"],
    "distance": ["d"],
    "angle_horizontal": ["theta"],
    "angle_vertical": ["theta"],
    "angle_vector": ["theta"],
}


def _sensor_channel_choices(display_project, params) -> list[tuple[str, str]]:
    if display_project is None:
        return []
    sensor_id = (params or {}).get("sensor_id", "")
    if not sensor_id:
        return []
    sensor = next((s for s in display_project.model.sensors if s.id == sensor_id), None)
    if sensor is None:
        return []
    kind = getattr(sensor.type, "value", str(sensor.type))
    channels = _SENSOR_CHANNELS_BY_KIND.get(kind, ["y"])
    return [(c, c) for c in channels]


def _load_choices(display_project, _params) -> list[tuple[str, str]]:
    if display_project is None:
        return []
    return [(load.name or load.id, load.id) for load in display_project.model.loads]


def _spring_choices(display_project, _params) -> list[tuple[str, str]]:
    if display_project is None:
        return []
    return [(spring.name or spring.id, spring.id) for spring in display_project.model.springs]


def _driver_choices(display_project, _params) -> list[tuple[str, str]]:
    if display_project is None:
        return []
    return [(driver.name or driver.id, driver.id) for driver in display_project.model.drivers]


def _body_choices(display_project, _params) -> list[tuple[str, str]]:
    if display_project is None:
        return []
    return [(body.name or body.id, body.id) for body in display_project.model.bodies]


# --- schemas -----------------------------------------------------------------

_SCHEMAS: dict[str, dict[str, ParamSchema]] = {
    "Constant": {
        "value": ParamSchema("value", "float", label="Value"),
    },
    "Step": {
        "step_time": ParamSchema("step_time", "float", label="Step time"),
        "initial_value": ParamSchema("initial_value", "float", label="Initial value"),
        "final_value": ParamSchema("final_value", "float", label="Final value"),
    },
    "Ramp": {
        "slope": ParamSchema("slope", "float", label="Slope"),
        "start_time": ParamSchema("start_time", "float", label="Start time"),
    },
    "Sine": {
        "amplitude": ParamSchema("amplitude", "float", label="Amplitude"),
        "frequency": ParamSchema("frequency", "float", label="Frequency (Hz)"),
        "phase": ParamSchema("phase", "float", label="Phase (rad)"),
        "bias": ParamSchema("bias", "float", label="Bias"),
    },
    "Gain": {
        "k": ParamSchema("k", "float", label="Gain"),
    },
    "Adder": {
        "signs": ParamSchema("signs", "list_float", label="Signs"),
    },
    "Saturation": {
        "lower": ParamSchema("lower", "float", label="Lower bound"),
        "upper": ParamSchema("upper", "float", label="Upper bound"),
    },
    "DeadZone": {
        "deadband": ParamSchema("deadband", "float", label="Deadband"),
    },
    "Integrator": {
        "initial_condition": ParamSchema("initial_condition", "float", label="Initial condition"),
    },
    "IntegratorLimited": {
        "initial_condition": ParamSchema("initial_condition", "float", label="Initial condition"),
        "lower": ParamSchema("lower", "float", label="Lower bound"),
        "upper": ParamSchema("upper", "float", label="Upper bound"),
    },
    "UnitDelay": {
        "initial_condition": ParamSchema("initial_condition", "float", label="Initial condition"),
    },
    "PID": {
        "kp": ParamSchema("kp", "float", label="Kp"),
        "ki": ParamSchema("ki", "float", label="Ki"),
        "kd": ParamSchema("kd", "float", label="Kd"),
        "lower": ParamSchema("lower", "float", label="Lower bound"),
        "upper": ParamSchema("upper", "float", label="Upper bound"),
        "anti_windup": ParamSchema("anti_windup", "bool", label="Anti-windup"),
    },
    "DerivativeFiltered": {
        "time_constant": ParamSchema("time_constant", "float", label="Time constant"),
    },
    "ModelSensor": {
        "sensor_id": ParamSchema(
            "sensor_id", "entity_ref", label="Sensor",
            domain="sensors", dynamic_choices=_sensor_choices,
        ),
        "channel": ParamSchema(
            "channel", "enum", label="Channel",
            depends_on=["sensor_id"], dynamic_choices=_sensor_channel_choices,
        ),
    },
    "LoadCommand": {
        "load_id": ParamSchema(
            "load_id", "entity_ref", label="Load",
            domain="loads", dynamic_choices=_load_choices,
        ),
        "component": ParamSchema(
            "component", "enum", label="Component",
            choices=["fx", "fy", "fz", "mx", "my", "mz"],
        ),
    },
    "SpringCommand": {
        "spring_id": ParamSchema(
            "spring_id", "entity_ref", label="Spring",
            domain="springs", dynamic_choices=_spring_choices,
        ),
    },
    "DriverCommand": {
        "driver_id": ParamSchema(
            "driver_id", "entity_ref", label="Driver",
            domain="drivers", dynamic_choices=_driver_choices,
        ),
    },
    "MBSSensor": {
        "body_id": ParamSchema(
            "body_id", "entity_ref", label="Body",
            domain="bodies", dynamic_choices=_body_choices,
        ),
        "variable": ParamSchema(
            "variable", "enum", label="Variable",
            choices=["Position", "Velocity", "Acceleration"],
        ),
        "component": ParamSchema(
            "component", "enum", label="Component", choices=["x", "y", "z"],
        ),
    },
    "MBSActuator": {
        "body_id": ParamSchema(
            "body_id", "entity_ref", label="Body",
            domain="bodies", dynamic_choices=_body_choices,
        ),
        "direction": ParamSchema("direction", "list_float", label="Direction"),
    },
}


def schema_for(block_type: str) -> dict[str, ParamSchema]:
    """Return the parameter schema for a block type, or {} when unknown."""
    return _SCHEMAS.get(block_type, {})


def is_hidden_param(name: str) -> bool:
    """Parameters starting with underscore (e.g. _position) are internal."""
    return name.startswith("_") or name == "__name__"
