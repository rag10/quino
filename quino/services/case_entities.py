"""Single source of truth for enumerating the entities of a case's model.

Maps entity id -> (entity, class) for bodies, structural markers, joints,
sliders, drivers, loads, sensors, springs and block instances. Replaces the
copy that used to live in case_overlay_validator (now deleted).
"""
from __future__ import annotations

from quino.domain.types import MarkerType
from quino.domain.workspace import Case


def entity_lookup(case: Case) -> dict[str, tuple[object, type]]:
    """Map id -> (entity, cls) for everything in the case's model."""
    out: dict[str, tuple[object, type]] = {}
    m = case.model
    for body in m.bodies:
        out[body.id] = (body, type(body))
        for marker in body.markers:
            if marker.type is MarkerType.STRUCTURAL:
                out[marker.id] = (marker, type(marker))
    for joint in m.joints:
        out[joint.id] = (joint, type(joint))
    for slider in m.sliders:
        out[slider.id] = (slider, type(slider))
    for driver in m.drivers:
        out[driver.id] = (driver, type(driver))
    for load in m.loads:
        out[load.id] = (load, type(load))
    for sensor in m.sensors:
        out[sensor.id] = (sensor, type(sensor))
    for spring in m.springs:
        out[spring.id] = (spring, type(spring))
    if getattr(m, "control_graph", None) is not None:
        for inst in m.control_graph.instances.values():
            out[inst.instance_id] = (inst, type(inst))
    return out
