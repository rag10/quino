"""Pure decision rules for value-based cascading (no overlays).

A parent edit cascades to a child only when the child still held the value the
parent had *before* the edit — i.e. the child was tracking the parent. If the
child already diverged, it owns a local override and is left untouched.
"""
from __future__ import annotations


def should_cascade_value(*, old_parent: object, child: object) -> bool:
    """True if the child was tracking the parent (child == old parent value)."""
    try:
        return bool(child == old_parent)
    except Exception:
        return False
