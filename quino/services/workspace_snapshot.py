"""workspace_snapshot — stub module (dead code).

The ApplicationService uses copy.deepcopy directly for undo/redo snapshots.
These functions are kept as no-ops to avoid breaking any lingering imports.
"""
from __future__ import annotations


def capture_project_snapshot(project) -> str:
    """No-op stub — undo is handled by ApplicationService via deepcopy."""
    return ""


def load_snapshot_project(snapshot_payload: str):
    """No-op stub."""
    return None


def apply_snapshot_to_project(project, snapshot_payload: str) -> None:
    """No-op stub."""
    pass
