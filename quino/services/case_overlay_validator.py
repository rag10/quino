# quino/services/case_overlay_validator.py
from __future__ import annotations

from typing import Iterable

from quino.domain.model import Body, Driver, Joint, Load, Model, Sensor, Slider, Spring
from quino.domain.workspace import Case, CaseOverlay, EntityOverlay


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
