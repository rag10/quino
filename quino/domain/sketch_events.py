from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityCreated:
    entity_id: str
    entity_type: str


@dataclass(frozen=True, slots=True)
class EntityModified:
    entity_id: str
    property_path: str


@dataclass(frozen=True, slots=True)
class ConstraintAdded:
    constraint_id: str
    constraint_type: str


@dataclass(frozen=True, slots=True)
class ConstraintRemoved:
    constraint_id: str
    constraint_type: str
