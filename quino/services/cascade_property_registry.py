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
    Check if a property path is cascadable for the given type.

    Recognises nested paths the engine cascades dynamically:
      - ``parameters.<key>``         (block instance parameters)
      - ``metadata.values.<key>``    (per-entity metadata bag)
      - ``style.<key>``              (visual override)
    The root name is validated against the registry.
    """
    try:
        registry = cascadable_properties(cls)
    except ValueError:
        return False
    if prop in registry:
        return True
    root = prop.split(".", 1)[0]
    if root == "parameters" and root not in registry:
        # BlockInstance parameters live in a dict; treat any "parameters.<k>" as cascadable.
        from quino.domain.blocks import BlockInstance
        if cls is BlockInstance:
            return True
        return False
    if root in {"metadata", "style"}:
        # metadata.values.<k> and style.<k> are cascadable regardless of dataclass field
        # presence — both are bags addressed by nested key.
        return True
    return root in registry
