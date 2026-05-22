from __future__ import annotations

from quino import ApplicationService, MarkerInput
from quino.serialization.json_io import JsonMapper


def test_end_to_end_new_project_always_has_workspace() -> None:
    app = ApplicationService()
    project = app.new_project("Legacy")
    app.create_bar("Bar", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))

    mapper = JsonMapper()
    data = mapper.dump(project)
    # new_project always creates a baseline, so workspace is always serialized
    assert "workspace" in data
    assert len(data["workspace"]["baselines"]) == 1

    restored = mapper.load(data)
    assert restored.workspace is not None
    assert len(restored.workspace.baselines) == 1
