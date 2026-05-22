from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class KinematicCache:
    axes: list[dict]
    shape: list[int]
    sensors: dict[str, dict]
    poses: list[dict | None]
    failed_mask: list[bool]

    @classmethod
    def load(cls, project_dir: Path | None, run) -> "KinematicCache | None":
        if project_dir is None or run.result_ref is None:
            return None
        path = project_dir / run.result_ref.artifact_path
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") != "kinematic":
            return None
        shape = list(data.get("shape", []))
        poses = list(data.get("poses", []))
        return cls(
            axes=list(data.get("sweep_axes", [])),
            shape=shape,
            sensors=dict(data.get("sensors", {})),
            poses=[pose or None for pose in poses] or [None] * _prod(shape),
            failed_mask=list(data.get("failed_mask", [])),
        )

    def cell_index(self, indices: list[int]) -> int:
        idx = 0
        stride = 1
        for axis in reversed(range(len(self.shape))):
            idx += indices[axis] * stride
            stride *= self.shape[axis]
        return idx

    def pose_at(self, indices: list[int]) -> dict | None:
        if not self.shape:
            return None
        idx = self.cell_index(indices)
        if idx >= len(self.poses):
            return None
        return self.poses[idx]

    def point_cloud(self) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for blob in self.sensors.values():
            channels = list(blob.get("channels", []))
            if "x" not in channels or "y" not in channels:
                continue
            ix = channels.index("x")
            iy = channels.index("y")
            stride = len(channels)
            values = list(blob.get("values", []))
            for cell in range(len(values) // stride):
                x = values[cell * stride + ix]
                y = values[cell * stride + iy]
                if not (math.isnan(x) or math.isnan(y)):
                    out.append((x, y))
        return out

    def inner_axis_line(self, indices: list[int]) -> list[tuple[float, float]]:
        if not self.shape:
            return []
        line: list[tuple[float, float]] = []
        for inner_idx in range(self.shape[-1]):
            pose = self.pose_at(indices[:-1] + [inner_idx])
            if not pose:
                continue
            for body_pose in pose.values():
                line.append((float(body_pose["x"]), float(body_pose["y"])))
                break
        return line


def _prod(values: list[int]) -> int:
    total = 1
    for value in values:
        total *= value
    return total
