"""Human-readable diff between two cases.

Returns a flat list of ``DiffEntry`` describing what changed between a parent
case and a child case. The widget never sees raw dataclass dumps; values are
formatted into short strings (``"2 kg"``, ``"revolute"``, ``"(unset)"``) and
labels are looked up in a human table.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Iterable, Literal

from quino.domain.model import (
    Body,
    Driver,
    JointEndpoint,
    Load,
    Marker,
    ScalarProperty,
    Sensor,
    Spring,
    SpringEndpoint,
    Style,
)
from quino.domain.workspace import Case
from quino.services.case_overlay_validator import _entity_lookup
from quino.services.cascade_property_category import PropertyCategory, classify


DiffKind = Literal["added", "removed", "changed"]


@dataclass(slots=True)
class DiffEntry:
    kind: DiffKind
    entity_kind: str
    entity_label: str
    entity_id: str
    property_label: str | None
    property_path: str | None
    parent_text: str
    child_text: str
    category: PropertyCategory


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------

_UNSET = "(unset)"
_DASH = "—"


def format_value(value: object, *, name_lookup: dict[str, str] | None = None) -> str:
    """Format a value into a short, human-readable string.

    ``name_lookup`` maps entity ids → ``name`` so that endpoint references can
    be shown as ``"thigh"`` instead of an opaque id.
    """
    if value is None:
        return _UNSET
    if isinstance(value, ScalarProperty):
        return value.expression
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Enum):
        return value.name.lower()
    if isinstance(value, str):
        if name_lookup is not None and value in name_lookup:
            return name_lookup[value]
        return _shorten(value, 40)
    if isinstance(value, (list, tuple)):
        items = list(value)
        if not items:
            return "[]"
        head = items[:4]
        formatted = [format_value(it, name_lookup=name_lookup) for it in head]
        if len(items) > 4:
            formatted.append(f"… (+{len(items) - 4})")
        return "[" + ", ".join(formatted) + "]"
    if isinstance(value, dict):
        return "{…}"
    # Objects with a name attribute (Body, Joint, ...) → reference by name.
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name
    return _shorten(repr(value), 40)


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Property labels
# ---------------------------------------------------------------------------

_PROPERTY_LABELS: dict[tuple[type, str], str] = {
    (Body, "mass"): "Mass",
    (Body, "type"): "Body type",
    (Body, "closed_shape"): "Closed shape",
    (Body, "com"): "Centre of mass",
    (Marker, "type"): "Marker type",
    (Marker, "x"): "X",
    (Marker, "y"): "Y",
    (Marker, "visible"): "Visible",
    (Driver, "type"): "Driver type",
    (Driver, "target_joint_id"): "Target joint",
    (Driver, "law"): "Law",
    (Load, "target_marker_id"): "Target marker",
    (Load, "fx"): "Force X",
    (Load, "fy"): "Force Y",
    (Spring, "rest_value"): "Rest value",
    (Spring, "law"): "Law",
    (Spring, "spring_type"): "Spring type",
    (Sensor, "type"): "Sensor type",
    (Sensor, "marker_ids"): "Markers",
}

# Subkey labels under metadata.values. Keys are the dict keys, values the
# user-facing label. These are domain conventions, not all entries are present
# in every entity.
_METADATA_VALUE_LABELS: dict[str, str] = {
    "friction_coulomb": "Friction (Coulomb)",
    "friction_viscous": "Friction (viscous)",
    "friction_pin_radius": "Pin radius",
    "angle_limit_positive_deg": "Angle limit +",
    "angle_limit_negative_deg": "Angle limit −",
    "stiffness": "Stiffness",
    "damping": "Damping",
}


def _humanise(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def label_for(cls: type, prop_path: str) -> str:
    if (cls, prop_path) in _PROPERTY_LABELS:
        return _PROPERTY_LABELS[(cls, prop_path)]
    if prop_path.startswith("metadata.values."):
        key = prop_path[len("metadata.values."):]
        return _METADATA_VALUE_LABELS.get(key, _humanise(key))
    if prop_path.startswith("parameters."):
        return _humanise(prop_path[len("parameters."):])
    if prop_path.startswith("style."):
        return f"Style — {_humanise(prop_path[len('style.'):])}"
    return _humanise(prop_path)


def entity_label_for(entity: object, kind: str) -> str:
    name = getattr(entity, "name", None)
    if isinstance(name, str) and name:
        return name
    return f"<unnamed {kind}>"


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

# Fields that are decomposed instead of compared as objects.
_COMPOSITE_FIELDS = {"metadata", "style", "parameters", "endpoint_a", "endpoint_b", "com"}

# Per-class fields that are pure topology / containment and never produce
# property diffs (they participate via add/remove of contained entities).
_SKIP_FIELDS: dict[type, set[str]] = {
    Body: {"markers", "edge_order"},
}


def diff_case_against(
    parent_case: Case,
    child_case: Case,
    *,
    include_visual: bool = False,
) -> list[DiffEntry]:
    """Compute a flat list of ``DiffEntry`` between ``parent_case`` and ``child_case``.

    ``include_visual`` toggles whether purely visual changes (``style.*``,
    ``name``, ``position``, ``visible``) are reported. They are off by default
    to keep the user-visible feed focused on semantic differences.
    """
    parent_index = _entity_lookup(parent_case)
    child_index = _entity_lookup(child_case)
    parent_names = {eid: getattr(ent, "name", eid) or eid for eid, (ent, _) in parent_index.items()}
    child_names = {eid: getattr(ent, "name", eid) or eid for eid, (ent, _) in child_index.items()}

    out: list[DiffEntry] = []

    # Removed entities (in parent, missing in child).
    for ent_id, (parent_ent, cls) in parent_index.items():
        if ent_id in child_index:
            continue
        out.append(
            DiffEntry(
                kind="removed",
                entity_kind=cls.__name__,
                entity_label=entity_label_for(parent_ent, cls.__name__),
                entity_id=ent_id,
                property_label=None,
                property_path=None,
                parent_text=_DASH,
                child_text=_DASH,
                category=PropertyCategory.STRUCTURAL,
            )
        )

    # Added entities (only in child).
    for ent_id, (child_ent, cls) in child_index.items():
        if ent_id in parent_index:
            continue
        out.append(
            DiffEntry(
                kind="added",
                entity_kind=cls.__name__,
                entity_label=entity_label_for(child_ent, cls.__name__),
                entity_id=ent_id,
                property_label=None,
                property_path=None,
                parent_text=_DASH,
                child_text=_DASH,
                category=PropertyCategory.STRUCTURAL,
            )
        )

    # Changed properties of common entities.
    for ent_id, (parent_ent, cls) in parent_index.items():
        if ent_id not in child_index:
            continue
        child_ent, _ = child_index[ent_id]
        for entry in _diff_entity(
            parent_ent,
            child_ent,
            cls,
            parent_names=parent_names,
            child_names=child_names,
            include_visual=include_visual,
        ):
            out.append(entry)

    return out


def _diff_entity(
    parent_ent: object,
    child_ent: object,
    cls: type,
    *,
    parent_names: dict[str, str],
    child_names: dict[str, str],
    include_visual: bool,
) -> Iterable[DiffEntry]:
    if not is_dataclass(parent_ent):
        return
    skip = _SKIP_FIELDS.get(cls, set())
    entity_label = entity_label_for(child_ent, cls.__name__)

    for field in fields(cls):
        name = field.name
        if name == "id" or name in skip:
            continue
        try:
            pv = getattr(parent_ent, name)
            cv = getattr(child_ent, name)
        except AttributeError:
            continue

        if name in _COMPOSITE_FIELDS:
            yield from _diff_composite(
                cls=cls,
                entity_id=getattr(child_ent, "id"),
                entity_label=entity_label,
                root=name,
                parent_value=pv,
                child_value=cv,
                parent_names=parent_names,
                child_names=child_names,
                include_visual=include_visual,
            )
            continue

        if pv == cv:
            continue
        category = classify(name)
        if category is PropertyCategory.VISUAL and not include_visual:
            continue
        yield DiffEntry(
            kind="changed",
            entity_kind=cls.__name__,
            entity_label=entity_label,
            entity_id=getattr(child_ent, "id"),
            property_label=label_for(cls, name),
            property_path=name,
            parent_text=format_value(pv, name_lookup=parent_names),
            child_text=format_value(cv, name_lookup=child_names),
            category=category,
        )


def _diff_composite(
    *,
    cls: type,
    entity_id: str,
    entity_label: str,
    root: str,
    parent_value: Any,
    child_value: Any,
    parent_names: dict[str, str],
    child_names: dict[str, str],
    include_visual: bool,
) -> Iterable[DiffEntry]:
    # metadata.values is a dict; compare key by key.
    if root == "metadata":
        p = parent_value.values if parent_value is not None else {}
        c = child_value.values if child_value is not None else {}
        for key in sorted(set(p) | set(c)):
            if p.get(key) == c.get(key):
                continue
            path = f"metadata.values.{key}"
            yield DiffEntry(
                kind="changed",
                entity_kind=cls.__name__,
                entity_label=entity_label,
                entity_id=entity_id,
                property_label=label_for(cls, path),
                property_path=path,
                parent_text=format_value(p.get(key)),
                child_text=format_value(c.get(key)),
                category=PropertyCategory.MODEL,
            )
        return

    if root == "style":
        if not include_visual:
            return
        if isinstance(parent_value, Style) and isinstance(child_value, Style):
            for field in fields(Style):
                pv = getattr(parent_value, field.name)
                cv = getattr(child_value, field.name)
                if pv == cv:
                    continue
                path = f"style.{field.name}"
                yield DiffEntry(
                    kind="changed",
                    entity_kind=cls.__name__,
                    entity_label=entity_label,
                    entity_id=entity_id,
                    property_label=label_for(cls, path),
                    property_path=path,
                    parent_text=format_value(pv),
                    child_text=format_value(cv),
                    category=PropertyCategory.VISUAL,
                )
        return

    if root == "parameters":
        # BlockInstance.parameters is a dict.
        p = parent_value or {}
        c = child_value or {}
        if not isinstance(p, dict) or not isinstance(c, dict):
            return
        for key in sorted(set(p) | set(c)):
            if p.get(key) == c.get(key):
                continue
            path = f"parameters.{key}"
            yield DiffEntry(
                kind="changed",
                entity_kind=cls.__name__,
                entity_label=entity_label,
                entity_id=entity_id,
                property_label=label_for(cls, path),
                property_path=path,
                parent_text=format_value(p.get(key)),
                child_text=format_value(c.get(key)),
                category=PropertyCategory.MODEL,
            )
        return

    if root in ("endpoint_a", "endpoint_b"):
        yield from _diff_endpoint(
            cls=cls,
            entity_id=entity_id,
            entity_label=entity_label,
            root=root,
            parent_value=parent_value,
            child_value=child_value,
            parent_names=parent_names,
            child_names=child_names,
        )
        return

    if root == "com":
        # CoMAnchor: (kind, data dict). Surface both as one line each.
        if parent_value is None or child_value is None or parent_value == child_value:
            return
        p_kind = getattr(parent_value, "kind", None)
        c_kind = getattr(child_value, "kind", None)
        if p_kind != c_kind:
            yield DiffEntry(
                kind="changed",
                entity_kind=cls.__name__,
                entity_label=entity_label,
                entity_id=entity_id,
                property_label="CoM anchor type",
                property_path="com.kind",
                parent_text=format_value(p_kind),
                child_text=format_value(c_kind),
                category=PropertyCategory.MODEL,
            )
        p_data = getattr(parent_value, "data", {}) or {}
        c_data = getattr(child_value, "data", {}) or {}
        for key in sorted(set(p_data) | set(c_data)):
            if p_data.get(key) == c_data.get(key):
                continue
            yield DiffEntry(
                kind="changed",
                entity_kind=cls.__name__,
                entity_label=entity_label,
                entity_id=entity_id,
                property_label=f"CoM — {_humanise(key)}",
                property_path=f"com.data.{key}",
                parent_text=format_value(p_data.get(key)),
                child_text=format_value(c_data.get(key)),
                category=PropertyCategory.MODEL,
            )


def _diff_endpoint(
    *,
    cls: type,
    entity_id: str,
    entity_label: str,
    root: str,
    parent_value: Any,
    child_value: Any,
    parent_names: dict[str, str],
    child_names: dict[str, str],
) -> Iterable[DiffEntry]:
    if parent_value is None or child_value is None:
        return
    label_root = "Endpoint A" if root == "endpoint_a" else "Endpoint B"
    fields_to_check = ("kind", "body_id", "marker_id", "slider_id", "ground_x", "ground_y")
    sub_labels = {
        "kind": "kind",
        "body_id": "body",
        "marker_id": "marker",
        "slider_id": "slider",
        "ground_x": "ground X",
        "ground_y": "ground Y",
    }
    for sub in fields_to_check:
        if not hasattr(parent_value, sub) or not hasattr(child_value, sub):
            continue
        pv = getattr(parent_value, sub)
        cv = getattr(child_value, sub)
        if pv == cv:
            continue
        yield DiffEntry(
            kind="changed",
            entity_kind=cls.__name__,
            entity_label=entity_label,
            entity_id=entity_id,
            property_label=f"{label_root} — {sub_labels[sub]}",
            property_path=f"{root}.{sub}",
            parent_text=format_value(pv, name_lookup=parent_names),
            child_text=format_value(cv, name_lookup=child_names),
            category=PropertyCategory.MODEL,
        )
