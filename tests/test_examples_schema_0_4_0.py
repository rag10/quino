"""Guard that all shipped examples are genuine schema 0.4.0 (no overlay/runs residue)."""
from __future__ import annotations

from pathlib import Path

import pytest

from quino.serialization.json_io import JsonMapper

_EXAMPLES = sorted(Path("examples").glob("*.quino.json"))


@pytest.mark.parametrize("path", _EXAMPLES, ids=lambda p: p.name)
def test_example_loads_at_0_4_0(path: Path) -> None:
    ws = JsonMapper().load(path)
    assert ws.schema_version == "0.4.0"
    assert ws.cases


@pytest.mark.parametrize("path", _EXAMPLES, ids=lambda p: p.name)
def test_example_has_no_overlay_or_runs_residue(path: Path) -> None:
    blob = path.read_text(encoding="utf-8")
    for stale in ('"overlay"', '"runs"', '"baselines"', '"added_entities"', '"removed_entity_ids"'):
        assert stale not in blob, f"{path.name} still contains stale key {stale}"
