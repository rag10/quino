from __future__ import annotations

import copy
import json

from quino.serialization.json_io import JsonMapper


def capture_project_snapshot(project) -> str:
    payload = JsonMapper().dump(copy.deepcopy(project))
    payload.pop("workspace", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def load_snapshot_project(snapshot_payload: str):
    return JsonMapper().load(json.loads(snapshot_payload))


def apply_snapshot_to_project(project, snapshot_payload: str) -> None:
    loaded = load_snapshot_project(snapshot_payload)
    project.parameters = loaded.parameters
    project.sketch = loaded.sketch
    project.model = loaded.model
    project.poses = loaded.poses
    project.simulation_initial_pose_id = loaded.simulation_initial_pose_id
    project.sensor_outputs.clear()
    project.reaction_outputs.clear()
