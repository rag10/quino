"""Centralised semantic palette for the QUINO GUI.

Colors are grouped by meaning to keep model tree, workflow tree,
inspector and canvas visually coherent. Refer to constants here instead
of inlining hex codes in widgets.

Semantics (matches docs/superpowers/plans/.../2026-05-21-workspace-and-blocks-ux):

* ACTIVE_BLUE        : active or currently-selected context
* ADDED_GREEN        : entity / block / connection added by the active case
* OVERRIDE_ORANGE    : property override (local to active case)
* REMOVED_RED        : entity removed by the active case, stale analyses, errors
* INHERITED_GRAY     : something coming from a parent case (read-only here)

The *_SOFT variants are lighter / desaturated and reserved for inherited
counterparts of the same semantics (drawn italic in tree views).
"""

from __future__ import annotations

# Active / selected
ACTIVE_BLUE = "#2255aa"
ACTIVE_BLUE_BG = "#cfe1f5"

# Added by case
ADDED_GREEN = "#228822"
ADDED_GREEN_SOFT = "#80c280"

# Overrides (local property edits in case mode)
OVERRIDE_ORANGE = "#c75b12"
OVERRIDE_ORANGE_SOFT = "#e2a472"

# Removals, stale results, errors
REMOVED_RED = "#aa2222"
REMOVED_RED_SOFT = "#d68585"
ERROR_RED = "#dc3545"

# Inherited / read-only auxiliary text
INHERITED_GRAY = "#888888"
INHERITED_GRAY_SOFT = "#aaaaaa"

# Headings and ambient ink
HEADING_INK = "#1a3a6e"
SUBHEADING_INK = "#214d8a"
SOFT_INK = "#3a6aaa"
