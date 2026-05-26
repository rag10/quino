from __future__ import annotations

import importlib
import math

from quino.pose.geometry import state_overlay_to_pose
from quino.simulation.assembler import MechanismAssembler
from quino.solver_adapters.exudyn_adapter import ExudynAdapter
from quino.services.expressions import ExpressionService
from quino.services.units import UnitService


def solve_static(project, config) -> dict:
    expression_service = ExpressionService(UnitService())
    adapter = ExudynAdapter(expression_service)
    assembled = adapter.assembler.assemble(project)
    exu = importlib.import_module("exudyn")
    project.sensor_outputs.clear()
    project.reaction_outputs.clear()
    result = adapter._run_with_exudyn(
        project,
        assembled,
        exu,
        solve_mode="static",
        duration=0.0,
        steps=1,
    )
    if not result.success or not result.frames:
        raise RuntimeError(result.error or "Static solve failed")

    frame = result.frames[-1]
    pose = state_overlay_to_pose(project, frame, pose_id="static_result", name="Static Result")
    applied_loads = _applied_load_rows(project, assembled)
    spring_rows, total_energy = _spring_rows(project, assembled, pose)
    reaction_rows = _reaction_rows(project)

    return {
        "pose": {
            body_id: {"x": body_pose.x, "y": body_pose.y, "theta": body_pose.angle}
            for body_id, body_pose in pose.body_poses.items()
        },
        "applied_loads": applied_loads,
        "spring_forces": spring_rows,
        "actuator_forces": [row for row in spring_rows if "actuator" in row["kind"]],
        "reactions": reaction_rows,
        "total_energy_in_springs": total_energy,
    }


def _applied_load_rows(project, assembled) -> list[dict]:
    rows: list[dict] = []
    for load in assembled.loads:
        rows.append(
            {
                "name": load.name,
                "source": "load",
                "marker_id": load.target_marker_id,
                "fx": load.fx,
                "fy": load.fy,
            }
        )
    gravity = project.model.gravity
    if gravity is not None:
        for body in assembled.bodies.values():
            if body.mass <= 0:
                continue
            rows.append(
                {
                    "name": f"gravity:{body.name}",
                    "source": "gravity",
                    "marker_id": None,
                    "fx": body.mass * gravity.magnitude * gravity.direction_x,
                    "fy": body.mass * gravity.magnitude * gravity.direction_y,
                }
            )
    return rows


def _spring_rows(project, assembled, pose) -> tuple[list[dict], float]:
    rows: list[dict] = []
    total_energy = 0.0
    for spring in assembled.springs:
        if spring.spring_type.startswith("rotational"):
            angle = 0.0
            delta = angle - spring.rest_value
            force = spring.stiffness * delta
            energy = 0.5 * spring.stiffness * (delta ** 2)
            rows.append(
                {
                    "name": spring.name,
                    "kind": spring.spring_type,
                    "F": force,
                    "length": angle,
                    "energy": energy,
                }
            )
            total_energy += energy
            continue
        x1, y1 = _spring_endpoint_xy(project, spring.endpoint_a, pose)
        x2, y2 = _spring_endpoint_xy(project, spring.endpoint_b, pose)
        length = math.hypot(x2 - x1, y2 - y1)
        delta = length - spring.rest_value
        force = spring.stiffness * delta
        energy = 0.5 * spring.stiffness * (delta ** 2)
        rows.append(
            {
                "name": spring.name,
                "kind": spring.spring_type,
                "F": force,
                "length": length,
                "energy": energy,
            }
        )
        total_energy += energy
    return rows, total_energy


def _spring_endpoint_xy(project, endpoint, pose) -> tuple[float, float]:
    if endpoint.kind == "ground":
        return endpoint.global_x, endpoint.global_y
    from quino.pose.geometry import marker_world_position

    return marker_world_position(project, endpoint.marker_id, pose)


def _reaction_rows(project) -> list[dict]:
    rows: list[dict] = []
    for output in project.reaction_outputs.values():
        if not output.data:
            continue
        fx, fy, _f, mz = output.data[-1]
        position = output.positions[-1] if output.positions else (0.0, 0.0)
        rows.append(
            {
                "joint_id": output.joint_id,
                "joint_name": output.joint_name,
                "endpoint_type": output.endpoint_type,
                "fx": fx,
                "fy": fy,
                "moment": mz,
                "position_x": position[0],
                "position_y": position[1],
            }
        )
    return rows
