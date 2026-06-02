"""Artifact directory layout for analysis runs.

`save_result_artifact` (workspace_runner) writes to ``artifacts/run_<id>/``.
`good_dir` returns that same path so the executor can back up / restore the
previous results around a re-run.
"""
from __future__ import annotations

from pathlib import Path


def good_dir(base: Path, analysis_id: str) -> Path:
    """Directory holding the last persisted artifacts for an analysis."""
    return Path(base) / f"run_{analysis_id}"
