# quino/services/case_overlay_validator.py
from __future__ import annotations

from dataclasses import fields as _fields
from typing import Iterable

from quino.domain.model import Body, Driver, Joint, Load, Model, Sensor, Slider, Spring
from quino.domain.workspace import Case, CaseOverlay, EntityOverlay
from quino.services.cascade_property_registry import cascadable_properties


class OverlayInvariantError(ValueError):
    """Raised when a Case.overlay violates the cascading invariants."""


def _iter_model_entity_ids(case: Case) -> Iterable[str]:
    m = case.model
    for body in m.bodies:
        yield body.id
        for marker in body.markers:
            yield marker.id
    for joint in m.joints:
        yield joint.id
    for slider in m.sliders:
        yield slider.id
    for driver in m.drivers:
        yield driver.id
    for load in m.loads:
        yield load.id
    for sensor in m.sensors:
        yield sensor.id
    for spring in m.springs:
        yield spring.id
    if m.control_graph is not None:
        for instance_id in m.control_graph.instances.keys():
            yield instance_id


def _parent_entity_ids(parent: Case) -> set[str]:
    return set(_iter_model_entity_ids(parent))


def validate_overlay(case: Case, parent: Case | None) -> None:
    """Raise OverlayInvariantError if any overlay invariant is violated."""
    if parent is None:
        if case.overlay is not None and (
            case.overlay.entities
            or case.overlay.deleted_inherited_entity_ids
            or case.overlay.inherited_connections
            or case.overlay.deleted_inherited_connections
            or case.overlay.poses
            or case.overlay.deleted_inherited_pose_ids
        ):
            raise OverlayInvariantError("Root case must have overlay=None or an empty overlay")
        return

    if case.overlay is None:
        raise OverlayInvariantError(f"Case {case.id!r} has a parent but overlay is None")

    overlay = case.overlay
    model_ids = set(_iter_model_entity_ids(case))
    parent_ids = _parent_entity_ids(parent)

    # 1. Bijection: every model entity must have an overlay entry and vice versa
    missing = model_ids - set(overlay.entities.keys())
    extra = set(overlay.entities.keys()) - model_ids
    if missing or extra:
        raise OverlayInvariantError(
            f"Case {case.id!r}: overlay/model entity mismatch. "
            f"Missing overlay entries: {missing}. Extra overlay entries: {extra}."
        )

    # 2. origin coherence + 3. inherited entities must exist in parent
    for ent_id, entry in overlay.entities.items():
        if entry.origin == "local" and entry.linked_properties:
            raise OverlayInvariantError(
                f"Case {case.id!r}: entity {ent_id!r} has origin='local' "
                f"but non-empty linked_properties {entry.linked_properties!r}"
            )
        if entry.origin == "inherited" and ent_id not in parent_ids:
            raise OverlayInvariantError(
                f"Case {case.id!r}: entity {ent_id!r} is origin='inherited' "
                f"but does not exist in parent {parent.id!r}"
            )

    # 4. deleted_inherited_entity_ids must reference entities that exist in parent
    for did in overlay.deleted_inherited_entity_ids:
        if did not in parent_ids:
            raise OverlayInvariantError(
                f"Case {case.id!r}: deleted_inherited_entity {did!r} "
                f"does not exist in parent {parent.id!r}"
            )

    # 5. Pose overlay bijection and inherited poses must exist in parent
    pose_ids = {p.id for p in case.poses}
    parent_pose_ids = {p.id for p in parent.poses}
    p_missing = pose_ids - set(overlay.poses.keys())
    p_extra = set(overlay.poses.keys()) - pose_ids
    if p_missing or p_extra:
        raise OverlayInvariantError(
            f"Case {case.id!r}: overlay/poses mismatch. "
            f"Missing overlay entries: {p_missing}. Extra overlay entries: {p_extra}."
        )
    for pid, entry in overlay.poses.items():
        if entry.origin == "inherited" and pid not in parent_pose_ids:
            raise OverlayInvariantError(
                f"Case {case.id!r}: pose {pid!r} is origin='inherited' "
                f"but does not exist in parent {parent.id!r}"
            )


def _entity_lookup(case: Case) -> dict[str, tuple[object, type]]:
    """Map id -> (entity, cls) for everything in the case's model."""
    out: dict[str, tuple[object, type]] = {}
    m = case.model
    for body in m.bodies:
        out[body.id] = (body, type(body))
        for marker in body.markers:
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
    if hasattr(m, 'control_graph') and m.control_graph is not None:
        for inst in m.control_graph.instances.values():
            out[inst.instance_id] = (inst, type(inst))
    return out


def _linked_properties_for_match(parent_ent: object, child_ent: object, cls: type) -> set[str]:
    """Return the subset of cascadable properties whose value matches between parent and child."""
    out: set[str] = set()
    try:
        cascadable = cascadable_properties(cls)
    except ValueError:
        return out
    for f in _fields(cls):
        if f.name not in cascadable:
            continue
        try:
            if getattr(parent_ent, f.name) == getattr(child_ent, f.name):
                out.add(f.name)
        except Exception:
            pass
    return out


def rebuild_overlay(case: Case, parent: Case | None) -> None:
    """Recompute case.overlay by comparing case.model against parent.model.

    Lossy: cannot distinguish 'intentional override at same value' from
    'linked, value coincidentally matches'. Used only for migration and recovery.
    """
    if parent is None:
        case.overlay = None
        return

    parent_index = _entity_lookup(parent)
    child_index = _entity_lookup(case)

    overlay = CaseOverlay()
    for ent_id, (child_ent, cls) in child_index.items():
        if ent_id in parent_index:
            parent_ent, parent_cls = parent_index[ent_id]
            if parent_cls is cls:
                linked = _linked_properties_for_match(parent_ent, child_ent, cls)
                overlay.entities[ent_id] = EntityOverlay(origin="inherited", linked_properties=linked)
            else:
                overlay.entities[ent_id] = EntityOverlay(origin="local")
        else:
            overlay.entities[ent_id] = EntityOverlay(origin="local")

    for parent_id in parent_index.keys():
        if parent_id not in child_index:
            overlay.deleted_inherited_entity_ids.add(parent_id)

    # Poses
    parent_pose_ids = {p.id for p in parent.poses}
    for pose in case.poses:
        if pose.id in parent_pose_ids:
            overlay.poses[pose.id] = EntityOverlay(origin="inherited")
        else:
            overlay.poses[pose.id] = EntityOverlay(origin="local")
    for ppose in parent.poses:
        if ppose.id not in {p.id for p in case.poses}:
            overlay.deleted_inherited_pose_ids.add(ppose.id)

    case.overlay = overlay
