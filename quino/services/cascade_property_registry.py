# quino/services/cascade_property_registry.py
from __future__ import annotations

from dataclasses import fields
from typing import Type

from quino.domain.blocks import BlockInstance
from quino.domain.model import (
    Body,
    Driver,
    Joint,
    Load,
    Marker,
    Sensor,
    Slider,
    Spring,
)

# Properties that are *never* cascadable, irrespective of type.
_GLOBAL_EXCLUSIONS: set[str] = {"id", "instance_id"}

# Per-class extra exclusions: fields that represent topology / contained
# entities, not values that should propagate to children.
_PER_CLASS_EXCLUSIONS: dict[type, set[str]] = {
    Body: {"markers", "edge_order"},
    Marker: set(),
    Joint: set(),
    Slider: set(),
    Driver: set(),
    Load: set(),
    Sensor: {"marker_ids"},
    Spring: set(),
    BlockInstance: {"position", "internal_diagram", "input_ports", "output_ports"},
}

_SUPPORTED: tuple[type, ...] = (Body, Joint, Marker, Slider, Driver, Load, Sensor, Spring, BlockInstance)


def cascadable_properties(cls: Type) -> frozenset[str]:
    """
    Return the set of property names that can be cascaded from parent to child cases for the given type.

    Excludes:
    - id (always)
    - structural/topological fields (per-class)

    Args:
        cls: The model class (Body, Joint, Marker, etc.)

    Returns:
        A frozenset of cascadable property names.

    Raises:
        ValueError: If the type is not supported.
    """
    if cls not in _SUPPORTED:
        raise ValueError(f"Type {cls.__name__} is not in the cascade registry")
    names = {f.name for f in fields(cls)}
    names -= _GLOBAL_EXCLUSIONS
    names -= _PER_CLASS_EXCLUSIONS.get(cls, set())
    return frozenset(names)


def is_cascadable_property(cls: Type, prop: str) -> bool:
    """
    Check if a property is cascadable for the given type.

    Args:
        cls: The model class.
        prop: The property name.

    Returns:
        True if the property is cascadable, False otherwise.
    """
    try:
        return prop in cascadable_properties(cls)
    except ValueError:
        return False
