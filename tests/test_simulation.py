from __future__ import annotations

import importlib
import math
from pathlib import Path
import types

from quino import (
    ApplicationService,
    DriverType,
    JointEndpointInput,
    JointEndpointKind,
    MarkerInput,
    SliderInput,
)
from quino.application.examples import build_slider_crank_example
from quino.solver_adapters.exudyn_adapter import ExudynAdapter


def _marker_world(assembled, frame: dict[str, float], body_id: str, marker_id: str) -> tuple[float, float]:
    body = assembled.bodies[body_id]
    marker = body.markers[marker_id]
    x = frame.get(f"{body_id}.x", body.origin_x)
    y = frame.get(f"{body_id}.y", body.origin_y)
    angle = frame.get(f"{body_id}.angle", body.angle)
    return (
        x + math.cos(angle) * marker.local_x - math.sin(angle) * marker.local_y,
        y + math.sin(angle) * marker.local_x + math.cos(angle) * marker.local_y,
    )


class _FakeItemInterface:
    @staticmethod
    def ObjectGround(**kwargs):
        return {"kind": "ObjectGround", **kwargs}

    @staticmethod
    def NodeRigidBody2D(**kwargs):
        return {"kind": "NodeRigidBody2D", **kwargs}

    @staticmethod
    def ObjectRigidBody2D(**kwargs):
        return {"kind": "ObjectRigidBody2D", **kwargs}

    @staticmethod
    def MarkerBodyRigid(**kwargs):
        return {"kind": "MarkerBodyRigid", **kwargs}

    @staticmethod
    def ObjectJointRevolute2D(**kwargs):
        return {"kind": "ObjectJointRevolute2D", **kwargs}

    @staticmethod
    def ObjectJointPrismatic2D(**kwargs):
        return {"kind": "ObjectJointPrismatic2D", **kwargs}

    @staticmethod
    def CoordinateConstraint(**kwargs):
        return {"kind": "CoordinateConstraint", **kwargs}

    @staticmethod
    def MarkerBodiesRelativeTranslationCoordinate(**kwargs):
        return {"kind": "MarkerBodiesRelativeTranslationCoordinate", **kwargs}

    @staticmethod
    def NodePointGround(**kwargs):
        return {"kind": "NodePointGround", **kwargs}

    @staticmethod
    def MarkerNodeCoordinate(**kwargs):
        return {"kind": "MarkerNodeCoordinate", **kwargs}

    @staticmethod
    def NodeGenericData(**kwargs):
        return {"kind": "NodeGenericData", **kwargs}

    @staticmethod
    def ObjectConnectorCoordinateSpringDamperExt(**kwargs):
        return {"kind": "ObjectConnectorCoordinateSpringDamperExt", **kwargs}

    @staticmethod
    def ObjectConnectorCoordinateSpringDamper(**kwargs):
        return {"kind": "ObjectConnectorCoordinateSpringDamper", **kwargs}


class _FakeMbs:
    def __init__(self) -> None:
        self.nodes = []
        self.objects = []
        self.markers = []
        self.coordinate_constraints = []
        self.assembled = False

    def AddNode(self, item):
        self.nodes.append(item)
        return len(self.nodes) - 1

    def AddObject(self, item):
        self.objects.append(item)
        return len(self.objects) - 1

    def AddMarker(self, item):
        self.markers.append(item)
        return len(self.markers) - 1

    def CreateCoordinateConstraint(self, **kwargs):
        self.coordinate_constraints.append(kwargs)
        return len(self.coordinate_constraints) - 1

    def Assemble(self):
        self.assembled = True

    def SolveDynamic(self, simulationSettings=None):
        self.solved_dynamic = True

    def SolveStatic(self, simulationSettings=None):
        self.solved_static = True

    def GetNodeOutput(self, nodeNumber, variableType):
        return [0.0, 0.0, 0.0]


class _FakeSystemContainer:
    def __init__(self):
        self.mbs = _FakeMbs()

    def AddSystem(self):
        return self.mbs


def test_simulation_returns_structured_result_even_without_exudyn() -> None:
    app = ApplicationService()
    app.new_project("Demo")
    app.create_parameter("L1", "100 mm", "mm")
    body_id = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L1", "0 mm", "B"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "A")
    app.connect_marker_to_ground(marker_id, name="Ground_A")
    slider_id = app.create_slider("Slider1", SliderInput("100 mm", "0 mm", "0 deg"))
    marker_b = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "B")
    app.connect_marker_to_slider(marker_b, slider_id, name="Joint_B")

    result = app.run_kinematic_simulation()

    assert result.backend == "exudyn"
    assert isinstance(result.success, bool)
    assert result.messages
    assert result.frames
    assert result.time


def test_four_bar_assembles_as_rigid_bodies_and_revolute_joints() -> None:
    app = ApplicationService()
    app.new_project("FourBar")
    app.create_parameter("L", "100 mm", "mm")
    ground = app.create_bar("GroundLink", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("200 mm", "0 mm", "D"))
    crank = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("L", "0 mm", "B"))
    coupler = app.create_bar("Coupler", MarkerInput("100 mm", "0 mm", "B"), MarkerInput("200 mm", "0 mm", "C"))
    rocker = app.create_bar("Rocker", MarkerInput("200 mm", "0 mm", "D"), MarkerInput("200 mm", "100 mm", "C"))

    def mid(body_id: str, marker_name: str) -> str:
        return next(marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name)

    app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=coupler, marker_id=mid(coupler, "B")),
    )
    app.create_joint(
        "Joint_C",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=coupler, marker_id=mid(coupler, "C")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rocker, marker_id=mid(rocker, "C")),
    )
    app.connect_marker_to_ground(mid(rocker, "D"), name="Ground_D")

    assembled = app.simulation_runner.adapter.assembler.assemble(app.project)

    assert len(assembled.bodies) == 4
    assert len(assembled.joints) == 4
    assert assembled.bodies[crank].body_type == "bar"
    assert assembled.bodies[coupler].markers[mid(coupler, "B")].local_x == 0.0


def test_slider_crank_uses_prismatic_joint_in_fake_exudyn(monkeypatch) -> None:
    fake_sc = _FakeSystemContainer()
    fake_exu = types.SimpleNamespace(
        SystemContainer=lambda: fake_sc,
        OutputVariableType=types.SimpleNamespace(Coordinates="Coordinates"),
    )
    fake_exu.SimulationSettings = lambda: types.SimpleNamespace(
        timeIntegration=types.SimpleNamespace(numberOfSteps=0, endTime=0.0),
        staticSolver=types.SimpleNamespace(numberOfLoadSteps=0),
        solutionSettings=types.SimpleNamespace(writeSolutionToFile=True),
    )
    fake_item_interface = _FakeItemInterface()

    def fake_import_module(name: str):
        if name == "exudyn":
            return fake_exu
        if name == "exudyn.itemInterface":
            return fake_item_interface
        raise ImportError(name)

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "exudyn" else None)
    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    app = ApplicationService()
    app.new_project("SliderCrank")
    crank = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("50 mm", "0 mm", "B"))
    rod = app.create_bar("Rod", MarkerInput("50 mm", "0 mm", "B"), MarkerInput("150 mm", "0 mm", "P"))
    slider = app.create_slider("Guide", SliderInput("150 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))

    def mid(body_id: str, marker_name: str) -> str:
        return next(marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name)

    app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rod, marker_id=mid(rod, "B")),
    )
    slider_joint_id = app.connect_marker_to_slider(mid(rod, "P"), slider, name="Slider_P")
    app.create_driver("SliderDrive", DriverType.TRANSLATION.value, slider_joint_id, "10 mm * t / 1 s", "mm")

    result = app.run_kinematic_simulation()

    assert result.success is True
    assert any(obj["kind"] == "CoordinateConstraint" for obj in fake_sc.mbs.objects)
    assert any(obj["kind"] == "ObjectConnectorCoordinateSpringDamperExt" for obj in fake_sc.mbs.objects)
    assert any(obj["kind"] == "ObjectConnectorCoordinateSpringDamper" for obj in fake_sc.mbs.objects)
    assert fake_sc.mbs.assembled is True
    assert getattr(fake_sc.mbs, "solved_dynamic", False) is True
    assert result.frames
    assert result.time


def test_exudyn_adapter_returns_partial_frames_when_dynamic_solve_fails(monkeypatch) -> None:
    class _FailingPartialMbs(_FakeMbs):
        def SolveDynamic(self, simulationSettings=None):
            Path(simulationSettings.solutionSettings.coordinatesSolutionFileName).write_text("partial")
            raise ValueError("dynamic boom")

    class _FailingPartialSystemContainer:
        def __init__(self):
            self.mbs = _FailingPartialMbs()

        def AddSystem(self):
            return self.mbs

    class _Rows(list):
        ndim = 2

    fake_sc = _FailingPartialSystemContainer()
    fake_exu = types.SimpleNamespace(
        SystemContainer=lambda: fake_sc,
        OutputVariableType=types.SimpleNamespace(Coordinates="Coordinates"),
    )
    fake_exu.SimulationSettings = lambda: types.SimpleNamespace(
        timeIntegration=types.SimpleNamespace(numberOfSteps=0, endTime=0.0),
        staticSolver=types.SimpleNamespace(numberOfLoadSteps=0),
        solutionSettings=types.SimpleNamespace(writeSolutionToFile=True),
    )
    fake_item_interface = _FakeItemInterface()
    fake_utilities = types.SimpleNamespace(
        LoadSolutionFile=lambda *args, **kwargs: {
            "data": _Rows(
                [
                    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    [0.1, 1.0, 2.0, 0.1, 3.0, 4.0, 0.2],
                ]
            ),
            "columnsExported": [6],
        }
    )

    def fake_import_module(name: str):
        if name == "exudyn":
            return fake_exu
        if name == "exudyn.itemInterface":
            return fake_item_interface
        if name == "exudyn.utilities":
            return fake_utilities
        raise ImportError(name)

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "exudyn" else None)
    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    app = ApplicationService()
    build_slider_crank_example(app)

    result = app.simulation_runner.adapter.run(app.project, duration=1.0, steps=10)

    assert result.success is False
    assert result.frames
    assert result.time == [0.0, 0.1]
    assert "partial trajectory" in result.error
    assert any("partial frames" in message for message in result.messages)


def test_slider_crank_runs_with_real_exudyn_if_available() -> None:
    import importlib.util

    if importlib.util.find_spec("exudyn") is None:
        return

    app = ApplicationService()
    app.new_project("SliderCrankReal")
    crank = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("50 mm", "0 mm", "B"))
    rod = app.create_bar("Rod", MarkerInput("50 mm", "0 mm", "B"), MarkerInput("150 mm", "0 mm", "P"))
    slider = app.create_slider("Guide", SliderInput("150 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))

    def mid(body_id: str, marker_name: str) -> str:
        return next(marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name)

    app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rod, marker_id=mid(rod, "B")),
    )
    slider_joint_id = app.connect_marker_to_slider(mid(rod, "P"), slider, name="Slider_P")
    app.create_driver("SliderDrive", DriverType.TRANSLATION.value, slider_joint_id, "10 mm * t / 1 s", "mm")

    result = app.run_kinematic_simulation()

    assert result.success is True
    assert result.backend == "exudyn"
    assert any("assembled" in message.lower() for message in result.messages)
    assert any("dynamic solve completed" in message.lower() for message in result.messages)
    assert result.frames
    assert result.time
    assert len(result.time) == len(result.frames)


def test_four_bar_with_rotation_driver_runs_with_real_exudyn_if_available() -> None:
    import importlib.util

    if importlib.util.find_spec("exudyn") is None:
        return

    app = ApplicationService()
    app.new_project("FourBarDriven")
    crank = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("30 mm", "10 mm", "B"))
    coupler = app.create_bar("Coupler", MarkerInput("30 mm", "10 mm", "B"), MarkerInput("90 mm", "70 mm", "C"))
    rocker = app.create_bar("Rocker", MarkerInput("120 mm", "0 mm", "D"), MarkerInput("90 mm", "70 mm", "C"))

    def mid(body_id: str, marker_name: str) -> str:
        return next(marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name)

    ground_joint_id = app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=coupler, marker_id=mid(coupler, "B")),
    )
    app.create_joint(
        "Joint_C",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=coupler, marker_id=mid(coupler, "C")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rocker, marker_id=mid(rocker, "C")),
    )
    app.connect_marker_to_ground(mid(rocker, "D"), name="Ground_D")
    app.create_driver("CrankDrive", DriverType.ROTATION.value, ground_joint_id, "20 deg * t / 1 s", "deg")

    result = app.run_kinematic_simulation()

    assert result.success is True
    assert result.frames
    assert result.time
    assembled = app.simulation_runner.adapter.assembler.assemble(app.project)
    first_frame = result.frames[0]
    assert abs(first_frame[f"{crank}.x"] - assembled.bodies[crank].origin_x) < 1e-9
    assert abs(first_frame[f"{crank}.y"] - assembled.bodies[crank].origin_y) < 1e-9
    assert abs(first_frame[f"{crank}.angle"] - assembled.bodies[crank].angle) < 1e-9
    for frame in result.frames:
        max_gap = 0.0
        for joint in app.project.model.joints:
            marker_points = []
            for endpoint in (joint.endpoint_a, joint.endpoint_b):
                if endpoint.kind is JointEndpointKind.MARKER:
                    marker_points.append(_marker_world(assembled, frame, endpoint.body_id, endpoint.marker_id))
            if len(marker_points) == 2:
                max_gap = max(
                    max_gap,
                    math.hypot(
                        marker_points[0][0] - marker_points[1][0],
                        marker_points[0][1] - marker_points[1][1],
                    ),
                )
        assert max_gap < 1e-4


def test_slider_crank_slider_constraint_stays_close_with_real_exudyn_if_available() -> None:
    import importlib.util

    if importlib.util.find_spec("exudyn") is None:
        return

    app = ApplicationService()
    app.new_project("SliderCrankConstraint")
    crank = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("50 mm", "0 mm", "B"))
    rod = app.create_bar("Rod", MarkerInput("50 mm", "0 mm", "B"), MarkerInput("150 mm", "0 mm", "P"))
    slider_id = app.create_slider("Guide", SliderInput("150 mm", "0 mm", "0 deg", "-20 mm", "20 mm"))

    def mid(body_id: str, marker_name: str) -> str:
        return next(marker.id for marker in app._find_body(body_id).markers if marker.name == marker_name)

    app.connect_marker_to_ground(mid(crank, "A"), name="Ground_A")
    app.create_joint(
        "Joint_B",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=crank, marker_id=mid(crank, "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=rod, marker_id=mid(rod, "B")),
    )
    app.connect_marker_to_slider(mid(rod, "P"), slider_id, name="Slider_P")
    ground_joint_id = next(joint.id for joint in app.project.model.joints if joint.name == "Ground_A")
    app.create_driver("CrankDrive", DriverType.ROTATION.value, ground_joint_id, "20 deg * t / 1 s", "deg")

    result = app.run_kinematic_simulation()

    assert result.success is True
    assembled = app.simulation_runner.adapter.assembler.assemble(app.project)
    slider = assembled.sliders[slider_id]
    marker_id = mid(rod, "P")
    max_perp = 0.0
    for frame in result.frames:
        px, py = _marker_world(assembled, frame, rod, marker_id)
        dx = px - slider.origin_x
        dy = py - slider.origin_y
        max_perp = max(max_perp, abs(dx * slider.normal_x + dy * slider.normal_y))
    assert max_perp < 1.0


def test_convenience_api_supports_slider_from_points_and_rigid_joints() -> None:
    app = ApplicationService()
    app.new_project("Convenience")
    body1 = app.create_body("Mass1", [MarkerInput("0 mm", "0 mm", "P1")])
    body2 = app.create_body("Mass2", [MarkerInput("50 mm", "0 mm", "P2")])
    slider_id = app.create_slider_from_points("Guide", "100 mm", "0 mm", "200 mm", "0 mm")
    marker1 = next(marker.id for marker in app._find_body(body1).markers if marker.name == "P1")
    marker2 = next(marker.id for marker in app._find_body(body2).markers if marker.name == "P2")
    app.add_marker_to_body_at(body1, "10 mm", "10 mm", "P3")

    joint_id = app.create_rigid_joint(
        "Rigid1",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=marker1),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=marker2),
    )

    slider = next(slider for slider in app.project.model.sliders if slider.id == slider_id)
    body = app._find_body(body1)

    assert slider.name == "Guide"
    assert joint_id in {joint.id for joint in app.project.model.joints}
    assert any(marker.name == "P3" for marker in body.markers)
    assert body.type.value == "body"


def test_exudyn_adapter_reports_diagnostics_on_execution_failure(monkeypatch) -> None:
    app = ApplicationService()
    build_slider_crank_example(app)
    adapter = ExudynAdapter(app.expression_service)
    monkeypatch.setattr(adapter, "is_available", lambda: True)
    monkeypatch.setattr(
        adapter,
        "_run_with_exudyn",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = adapter.run(app.project)

    assert result.success is False
    assert "boom" in result.error
    assert any("Solver phase:" in message for message in result.messages)
    assert any("Model summary:" in message for message in result.messages)
    assert any("RuntimeError: boom" in message for message in result.messages)
