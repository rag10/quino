"""Classification of cascadable property paths.

Centralises the question "is this property model-affecting, purely visual, or
structural?" so the cascading engine and command layer can agree on a single
table instead of scattering string literals.
"""
from __future__ import annotations

from enum import Enum


class PropertyCategory(Enum):
    """Coarse classification for a cascadable property path."""

    MODEL = "model"
    """Changing this property changes simulation results. Runs must be marked stale."""

    VISUAL = "visual"
    """Purely cosmetic. Does not invalidate runs."""

    STRUCTURAL = "structural"
    """Topology / containment. Should not flow through edit_property."""


# Roots whose entire subtree is visual (sets the rule for "style.color", "style.*").
_VISUAL_ROOTS: frozenset[str] = frozenset({"style"})

# Exact paths that are visual even though their root would otherwise be MODEL.
_VISUAL_EXACT: frozenset[str] = frozenset({
    "name",
    "visible",
    "position",
})

# Roots whose subtree is structural and should never be reached by edit_property.
_STRUCTURAL_ROOTS: frozenset[str] = frozenset({
    "markers",
    "edge_order",
    "marker_ids",
    "input_ports",
    "output_ports",
    "internal_diagram",
})


def classify(prop_path: str) -> PropertyCategory:
    """Classify a property path.

    Args:
        prop_path: A property path of the form ``"mass"``, ``"style.color"``,
            ``"metadata.values.friction_coulomb"``, ``"parameters.kp"``, etc.
    """
    if prop_path in _VISUAL_EXACT:
        return PropertyCategory.VISUAL
    root = prop_path.split(".", 1)[0]
    if root in _VISUAL_ROOTS:
        return PropertyCategory.VISUAL
    if root in _STRUCTURAL_ROOTS:
        return PropertyCategory.STRUCTURAL
    return PropertyCategory.MODEL


def is_model_affecting(prop_path: str) -> bool:
    """True if editing this property should mark runs stale."""
    return classify(prop_path) is PropertyCategory.MODEL
