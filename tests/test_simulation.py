from __future__ import annotations

import importlib
import math
from pathlib import Path
import types

import pytest

from quino import (
    ApplicationService,
    DriverType,
    JointEndpointInput,
    JointEndpointKind,
    MarkerInput,
    PropertyValueInput,
    SliderInput,
)
from quino.application.examples import build_slider_crank_example
from quino.domain.model import Project
from quino.domain.types import Dimension
from quino.simulation.assembler import AssembledDriver, AssembledSpring, AssembledSpringEndpoint
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
    def MarkerBodyMass(**kwargs):
        return {"kind": "MarkerBodyMass", **kwargs}

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

    @staticmethod
    def LoadMassProportional(**kwargs):
        return {"kind": "LoadMassProportional", **kwargs}

    @staticmethod
    def LoadForceVector(**kwargs):
        return {"kind": "LoadForceVector", **kwargs}

    @staticmethod
    def SensorObject(**kwargs):
        return {"kind": "SensorObject", **kwargs}

    @staticmethod
    def SensorUserFunction(**kwargs):
        return {"kind": "SensorUserFunction", **kwargs}

    @staticmethod
    def NodePoint2D(**kwargs):
        return {"kind": "NodePoint2D", **kwargs}

    @staticmethod
    def ObjectMassPoint2D(**kwargs):
        return {"kind": "ObjectMassPoint2D", **kwargs}

    @staticmethod
    def MarkerNodePosition(**kwargs):
        return {"kind": "MarkerNodePosition", **kwargs}

    @staticmethod
    def Force(**kwargs):
        return {"kind": "Force", **kwargs}


class _FakeMbs:
    def __init__(self) -> None:
        self.nodes = []
        self.objects = []
        self.markers = []
        self.sensors = []
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

    def AddSensor(self, item):
        self.sensors.append(item)
        return len(self.sensors) - 1

    def CreateCoordinateConstraint(self, **kwargs):
        self.coordinate_constraints.append(kwargs)
        return len(self.coordinate_constraints) - 1

    def Assemble(self):
        self.assembled = True

    def AddLoad(self, item):
        self.loads = getattr(self, "loads", [])
        self.loads.append(item)
        return len(self.loads) - 1

    def SolveDynamic(self, simulationSettings=None):
        self.solved_dynamic = True

    def SolveStatic(self, simulationSettings=None):
        self.solved_static = True

    def GetNodeOutput(self, nodeNumber, variableType):
        return [0.0, 0.0, 0.0]

    def GetObjectOutput(self, objectNumber, variableType):
        return [0.0, 0.0]


class _FakeSystemContainer:
    def __init__(self):
        self.mbs = _FakeMbs()

    def AddSystem(self):
        return self.mbs


class _FakeBridge:
    def __init__(self, values: dict[str, float]):
        self.values = values

    def command_value(self, target_id: str) -> float | None:
        return self.values.get(target_id)


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


def test_driver_value_can_come_from_control_graph_command() -> None:
    app = ApplicationService()
    adapter = app.simulation_runner.adapter
    project = Project(id="p1", name="P1", schema_version="test")
    driver = AssembledDriver(
        driver_id="driver_001",
        name="Drive",
        driver_type=DriverType.TRANSLATION.value,
        target_joint_id="joint_001",
        law_expression="0 mm",
        unit="mm",
        expected_dimension=Dimension.LENGTH.value,
    )

    value = adapter._evaluate_driver_value(
        project,
        driver,
        Dimension.LENGTH,
        0.0,
        bridge=_FakeBridge({"driver_001": 25.0}),
    )

    assert value == pytest.approx(0.025)


def test_spring_law_can_come_from_control_graph_command() -> None:
    app = ApplicationService()
    adapter = app.simulation_runner.adapter
    project = Project(id="p1", name="P1", schema_version="test")
    spring = AssembledSpring(
        spring_id="spring_001",
        name="Actuator",
        spring_type="linear_actuator",
        endpoint_a=AssembledSpringEndpoint("ground", None, None, 0.0, 0.0, 0.0, 0.0),
        endpoint_b=AssembledSpringEndpoint("ground", None, None, 0.0, 0.0, 0.0, 0.0),
        stiffness=0.0,
        damping=0.0,
        rest_value=0.0,
        law_expression="0 N",
        law_unit="N",
        law_dimension=Dimension.FORCE.value,
    )

    law_fn = adapter._make_spring_law_fn(
        project,
        spring,
        "N",
        bridge=_FakeBridge({"spring_001": 12.5}),
    )

    assert law_fn(None, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0) == pytest.approx(12.5)


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
    assert any(
        obj["kind"] == "CoordinateConstraint" and obj.get("name") == "SliderDrive"
        for obj in fake_sc.mbs.objects
    )
    assert fake_sc.mbs.assembled is True
    assert getattr(fake_sc.mbs, "solved_dynamic", False) is True
    assert result.frames
    assert result.time


def test_translation_driver_is_relative_to_initial_slider_coordinate(monkeypatch) -> None:
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
    app.new_project("TranslationDriveOffset")
    body_id = app.create_body("Mass", [MarkerInput("150 mm", "0 mm", "P")])
    slider_id = app.create_slider("Guide", SliderInput("100 mm", "0 mm", "0 deg", "-100 mm", "100 mm"))
    marker_id = next(marker.id for marker in app._find_body(body_id).markers if marker.name == "P")
    joint_id = app.connect_marker_to_slider(marker_id, slider_id, name="Slider_P", align="none")
    app.create_driver("SliderDrive", DriverType.TRANSLATION.value, joint_id, "10 mm * t / 1 s", "mm")

    result = app.run_kinematic_simulation()

    driver_constraint = next(
        obj for obj in fake_sc.mbs.objects
        if obj["kind"] == "CoordinateConstraint" and obj.get("name") == "SliderDrive"
    )
    assert result.success is True
    # With positions in metres: initial_coord = 50mm * 1e-3 = 0.05m, driver at t=1 adds 10mm = 0.01m
    assert driver_constraint["offsetUserFunction"](None, 0.0, 0, 0.0) == pytest.approx(-0.05)
    assert driver_constraint["offsetUserFunction"](None, 1.0, 0, 0.0) == pytest.approx(-0.06)


def test_time_dependent_load_creates_force_user_function(monkeypatch) -> None:
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
    app.new_project("LoadWithTime")
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "P")])
    marker_id = next(m.id for m in app._find_body(body_id).markers if m.name == "P")
    app.create_load("Wind", marker_id, "10 N * t / 1 s", "0 N")

    result = app.run_kinematic_simulation()

    assert result.success is True
    force_load = next(load for load in fake_sc.mbs.loads if load["kind"] == "LoadForceVector")
    assert "loadVectorUserFunction" in force_load
    assert force_load["loadVectorUserFunction"](fake_sc.mbs, 2.0, [0.0, 0.0, 0.0]) == pytest.approx([20.0, 0.0, 0.0])


def test_sensor_dependent_load_creates_force_user_function(monkeypatch) -> None:
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
    app.new_project("LoadWithSensor")
    body_id = app.create_body(
        "Block",
        [MarkerInput("0 mm", "0 mm", "A"), MarkerInput("30 mm", "40 mm", "B")],
    )
    marker_a = next(m.id for m in app._find_body(body_id).markers if m.name == "A")
    marker_b = next(m.id for m in app._find_body(body_id).markers if m.name == "B")
    app.create_sensor("Gap", "distance", [marker_a, marker_b])
    app.create_load("Springish", marker_b, "2 N/mm * Gap.d", "0 N")

    result = app.run_kinematic_simulation()

    assert result.success is True
    force_load = next(load for load in fake_sc.mbs.loads if load["kind"] == "LoadForceVector")
    assert "loadVectorUserFunction" in force_load
    assert force_load["loadVectorUserFunction"](fake_sc.mbs, 0.0, [0.0, 0.0, 0.0]) == pytest.approx([100.0, 0.0, 0.0])


def test_revolute_joint_friction_creates_coordinate_spring_damper(monkeypatch) -> None:
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
    app.new_project("JointFriction")
    body1 = app.create_bar("Crank", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    body2 = app.create_bar("Rod", MarkerInput("100 mm", "0 mm", "C"), MarkerInput("200 mm", "0 mm", "D"))
    joint_id = app.create_joint(
        "Joint1",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body1, marker_id=next(m.id for m in app._find_body(body1).markers if m.name == "B")),
        JointEndpointInput(JointEndpointKind.MARKER, body_id=body2, marker_id=next(m.id for m in app._find_body(body2).markers if m.name == "C")),
    )
    app.update_property(joint_id, "friction_coulomb", PropertyValueInput("expression", "2.0"))
    app.update_property(joint_id, "friction_viscous", PropertyValueInput("expression", "0.5"))

    result = app.run_kinematic_simulation()

    assert result.success is True
    friction_objects = [
        obj for obj in fake_sc.mbs.objects
        if obj["kind"] == "ObjectConnectorCoordinateSpringDamper" and obj.get("name") == "Joint1_friction"
    ]
    assert friction_objects


def test_slider_joint_friction_creates_coordinate_spring_damper(monkeypatch) -> None:
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
    app.new_project("SliderFriction")
    body = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "P")])
    slider_id = app.create_slider("Guide", SliderInput("0 mm", "0 mm", "0 deg"))
    marker_id = next(m.id for m in app._find_body(body).markers if m.name == "P")
    joint_id = app.connect_marker_to_slider(marker_id, slider_id, name="SliderJoint")
    app.update_property(joint_id, "friction_coulomb", PropertyValueInput("expression", "4.0"))
    app.update_property(joint_id, "friction_viscous", PropertyValueInput("expression", "0.2"))

    result = app.run_kinematic_simulation()

    assert result.success is True
    friction_objects = [
        obj for obj in fake_sc.mbs.objects
        if obj["kind"] == "ObjectConnectorCoordinateSpringDamper" and obj.get("name") == "SliderJoint_friction"
    ]
    assert friction_objects


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


def test_umbrella_mechanism_slider_driver_runs_without_erratic_jump_if_available() -> None:
    import importlib.util

    if importlib.util.find_spec("exudyn") is None:
        return
    example_path = Path("examples/Umbrella_Mechanism.quino.json")
    if not example_path.exists():
        return

    app = ApplicationService()
    app.load_project(str(example_path))

    result = app.run_kinematic_simulation(duration=1.0, steps=100)

    assert result.success is True
    assert len(result.frames) == len(result.time)
    assert result.time[-1] == pytest.approx(1.0)
    assembled = app.simulation_runner.adapter.assembler.assemble(app.project)
    slider = next(iter(assembled.sliders.values()))
    slider_joint = next(
        joint
        for joint in app.project.model.joints
        if any(endpoint.kind is JointEndpointKind.SLIDER for endpoint in (joint.endpoint_a, joint.endpoint_b))
    )
    marker_endpoint = next(
        endpoint
        for endpoint in (slider_joint.endpoint_a, slider_joint.endpoint_b)
        if endpoint.kind is JointEndpointKind.MARKER
    )
    driver = next(driver for driver in app.project.model.drivers if driver.target_joint_id == slider_joint.id)
    marker = assembled.bodies[marker_endpoint.body_id].markers[marker_endpoint.marker_id]
    initial_coordinate = (
        (marker.global_x - slider.origin_x) * slider.axis_x
        + (marker.global_y - slider.origin_y) * slider.axis_y
    )
    max_coordinate_error = 0.0
    max_angle = 0.0
    for t, frame in zip(result.time, result.frames):
        px, py = _marker_world(assembled, frame, marker_endpoint.body_id, marker_endpoint.marker_id)
        coordinate = (px - slider.origin_x) * slider.axis_x + (py - slider.origin_y) * slider.axis_y
        target = initial_coordinate + app.unit_service.convert(
            app.expression_service.evaluate_expression(
                driver.law.expression,
                app.project.parameters,
                variables={"t": app.unit_service.quantity(t, "s")},
            ),
            "mm",
        )
        max_coordinate_error = max(max_coordinate_error, abs(coordinate - target))
        for body in assembled.bodies:
            max_angle = max(max_angle, abs(frame[f"{body}.angle"]))
    assert max_coordinate_error < 1e-4
    assert max_angle < 10.0


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


def test_exudyn_adapter_export_script_generates_valid_python(monkeypatch) -> None:
    app = ApplicationService()
    build_slider_crank_example(app)
    adapter = ExudynAdapter(app.expression_service)
    script = adapter.export_script(app.project, duration=1.0, steps=10)

    assert "import exudyn" in script
    assert "mbs.SolveDynamic" in script
    assert "_driver_" in script
    assert "_interp" in script

    # Verify it is valid Python syntax
    import ast
    ast.parse(script)


def test_application_service_export_exudyn_script_raises_for_non_exudyn() -> None:
    app = ApplicationService()
    app.new_project("Test")
    # swap adapter to a fake one
    from quino.simulation.runner import SimulationRunner
    from quino.solver_adapters.base import SolverAdapter

    class FakeAdapter(SolverAdapter):
        name = "fake"

        def run(self, project, duration=1.0, steps=100):
            return project

    app.simulation_runner = SimulationRunner(FakeAdapter())
    with pytest.raises(RuntimeError, match="only supported for the Exudyn"):
        app.export_exudyn_script()


def test_assembler_defaults_mass_to_zero() -> None:
    app = ApplicationService()
    app.new_project("Massless")
    body_id = app.create_bar("Link", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    app.connect_marker_to_ground(next(m.id for m in app._find_body(body_id).markers if m.name == "A"))

    assembled = app.simulation_runner.adapter.assembler.assemble(app.project)
    body = assembled.bodies[body_id]
    assert body.mass == pytest.approx(0.0)


def test_dynamic_simulation_runs_without_drivers_when_bodies_have_mass(monkeypatch) -> None:
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
    app.new_project("Pendulum")
    arm = app.create_bar("Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B"))
    app.update_property(arm, "mass", PropertyValueInput("expression", "1 kg"))
    app.connect_marker_to_ground(next(m.id for m in app._find_body(arm).markers if m.name == "A"))
    app.add_gravity()

    result = app.run_kinematic_simulation()

    assert result.success is True
    assert getattr(fake_sc.mbs, "solved_dynamic", False) is True
    assert any(
        load.get("loadVector") == [0.0, -9.81, 0.0]
        for load in getattr(fake_sc.mbs, "loads", [])
    )


def test_exudyn_script_includes_gravity() -> None:
    app = ApplicationService()
    build_slider_crank_example(app)
    # Add mass to one body so gravity loads are generated
    for body in app.project.model.bodies:
        app.update_property(body.id, "mass", PropertyValueInput("expression", "1 kg"))
    app.add_gravity()
    adapter = ExudynAdapter(app.expression_service)
    script = adapter.export_script(app.project, duration=1.0, steps=10)

    assert "LoadMassProportional" in script
    assert "[0.0, -9.81, 0.0]" in script


# Gravity simulation tests


def test_gravity_disabled_produces_no_load() -> None:
    """When gravity is disabled, no LoadMassProportional is added."""
    app = ApplicationService()
    app.new_project("GravityTest")
    body_id = app.create_body("Body1", [MarkerInput("0 mm", "0 mm", "P")])
    app.update_property(body_id, "mass", PropertyValueInput("expression", "1 kg"))

    # Disable gravity
    app.delete_gravity()

    # Generate script
    adapter = ExudynAdapter(app.expression_service)
    script = adapter.export_script(app.project, duration=1.0, steps=10)

    # Verify: LoadMassProportional should not appear in script
    assert "LoadMassProportional" not in script

    # Verify: SetGravity should be [0, 0, 0]
    assert "mbs.SetGravity([0, 0, 0])" in script


def test_gravity_enabled_produces_loads() -> None:
    """When gravity is enabled with mass, LoadMassProportional is added."""
    app = ApplicationService()
    app.new_project("GravityTest")
    body_id = app.create_body("Body1", [MarkerInput("0 mm", "0 mm", "P")])
    app.update_property(body_id, "mass", PropertyValueInput("expression", "1 kg"))

    app.add_gravity()
    assert app.project.model.gravity is not None

    # Generate script
    adapter = ExudynAdapter(app.expression_service)
    script = adapter.export_script(app.project, duration=1.0, steps=10)

    # Verify: LoadMassProportional should appear in script
    assert "LoadMassProportional" in script

    # Verify: SetGravity should use default values
    assert "[0.0, -9.81, 0.0]" in script or "[0, -9.81, 0]" in script


def test_custom_gravity_parameters_applied() -> None:
    """Custom gravity magnitude and direction are applied correctly."""
    app = ApplicationService()
    app.new_project("CustomGravityTest")
    body_id = app.create_body("Body1", [MarkerInput("0 mm", "0 mm", "P")])
    app.update_property(body_id, "mass", PropertyValueInput("expression", "1 kg"))
    app.add_gravity()

    # Set custom gravity
    app.update_property(
        "__gravity__",
        "magnitude",
        PropertyValueInput("expression", "5.0")
    )
    app.update_property(
        "__gravity__",
        "direction_x",
        PropertyValueInput("expression", "1.0")
    )
    app.update_property(
        "__gravity__",
        "direction_y",
        PropertyValueInput("expression", "0.0")
    )

    # Generate script
    adapter = ExudynAdapter(app.expression_service)
    script = adapter.export_script(app.project, duration=1.0, steps=10)

    # Verify: SetGravity should contain custom values
    # The script should have SetGravity([5.0, 0.0, 0])
    assert "mbs.SetGravity([5" in script and "0.0, 0])" in script


def test_gravity_with_zero_direction_components() -> None:
    """Gravity with direction components set to zero works correctly."""
    app = ApplicationService()
    app.new_project("ZeroGravityTest")
    body_id = app.create_body("Body1", [MarkerInput("0 mm", "0 mm", "P")])
    app.update_property(body_id, "mass", PropertyValueInput("expression", "1 kg"))
    app.add_gravity()

    # Set gravity to all zeros (effectively disables it)
    app.update_property(
        "__gravity__",
        "magnitude",
        PropertyValueInput("expression", "0.0")
    )
    app.update_property(
        "__gravity__",
        "direction_x",
        PropertyValueInput("expression", "0.0")
    )
    app.update_property(
        "__gravity__",
        "direction_y",
        PropertyValueInput("expression", "0.0")
    )

    # Generate script
    adapter = ExudynAdapter(app.expression_service)
    script = adapter.export_script(app.project, duration=1.0, steps=10)

    # Verify: SetGravity should be [0.0, 0.0, 0]
    assert "mbs.SetGravity([0.0, 0.0, 0])" in script


def test_gravity_direction_normalization() -> None:
    """Gravity direction with custom magnitude is applied correctly."""
    app = ApplicationService()
    app.new_project("DirectionNormTest")
    body_id = app.create_body("Body1", [MarkerInput("0 mm", "0 mm", "P")])
    app.update_property(body_id, "mass", PropertyValueInput("expression", "2 kg"))
    app.add_gravity()

    # Set custom gravity with non-unit direction vector
    app.update_property(
        "__gravity__",
        "magnitude",
        PropertyValueInput("expression", "10.0")
    )
    app.update_property(
        "__gravity__",
        "direction_x",
        PropertyValueInput("expression", "0.6")
    )
    app.update_property(
        "__gravity__",
        "direction_y",
        PropertyValueInput("expression", "0.8")
    )

    # Generate script
    adapter = ExudynAdapter(app.expression_service)
    script = adapter.export_script(app.project, duration=1.0, steps=10)

    # Verify: SetGravity should have magnitude*direction components
    # magnitude * direction_x = 10 * 0.6 = 6.0
    # magnitude * direction_y = 10 * 0.8 = 8.0
    assert "mbs.SetGravity([6" in script or "6.0" in script
    assert "8" in script or "8.0" in script


# ---------------------------------------------------------------------------
# Reaction force tests
# ---------------------------------------------------------------------------

def test_reaction_output_dataclass_fields() -> None:
    from quino.domain.model import ReactionOutput
    r = ReactionOutput(
        joint_id="j1",
        joint_name="Ground_A",
        endpoint_type="ground",
        time=[0.0, 0.1],
        columns=["Fx [N]", "Fy [N]", "F [N]"],
        data=[[1.0, 2.0, 2.236], [3.0, 4.0, 5.0]],
        positions=[(10.0, 20.0), (10.1, 20.1)],
    )
    assert r.joint_id == "j1"
    assert r.columns == ["Fx [N]", "Fy [N]", "F [N]"]
    assert len(r.data) == 2
    assert len(r.positions) == 2


def test_project_has_reaction_outputs_field() -> None:
    app = ApplicationService()
    app.new_project("Test")
    assert hasattr(app.project, "reaction_outputs")
    assert isinstance(app.project.reaction_outputs, dict)
    assert len(app.project.reaction_outputs) == 0


def test_get_entity_returns_reaction_output_for_reaction_prefix() -> None:
    from quino.domain.model import ReactionOutput
    app = ApplicationService()
    app.new_project("Test")
    rxn = ReactionOutput(
        joint_id="j1", joint_name="Ground_A", endpoint_type="ground",
        time=[0.0], columns=["Fx [N]", "Fy [N]", "F [N]"],
        data=[[1.0, 2.0, 2.236]], positions=[(10.0, 20.0)],
    )
    app.project.reaction_outputs["j1"] = rxn
    result = app.get_entity("__reaction__j1")
    assert result is rxn
    assert app.get_entity("__reaction__nonexistent") is None


def test_run_simulation_clears_reaction_outputs() -> None:
    from quino.domain.model import ReactionOutput
    app = ApplicationService()
    app.new_project("Test")
    app.project.reaction_outputs["j1"] = ReactionOutput(
        joint_id="j1", joint_name="Ground_A", endpoint_type="ground",
    )
    app.run_kinematic_simulation()
    assert len(app.project.reaction_outputs) == 0


def test_body_inertia_derived_from_structural_markers() -> None:
    """A bar's polar inertia about the CoM is m·L²/12 — sum of two point
    masses at L/2 from the CoM. Regression guard against the old
    `physicsInertia=1e-10` hard-coded value that crashed the dynamic
    integrator on any mechanism with a free rotational DoF (e.g. a passive
    double pendulum)."""
    from quino.solver_adapters.exudyn_adapter import _body_inertia_kg_m2

    app = ApplicationService()
    app.new_project("InertiaTest")
    bar_id = app.create_bar(
        "Bar",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
    )
    app.update_property(
        bar_id, "mass", PropertyValueInput(kind="expression", value="2 kg"),
    )
    adapter = ExudynAdapter(app.expression_service)
    assembled = adapter.assembler.assemble(app.project)
    body = assembled.bodies[bar_id]
    # Two structural markers ±50 mm from the CoM, mass split evenly:
    # Iz = 2 × (1 kg × (0.05 m)²) = 5e-3 kg·m².
    assert _body_inertia_kg_m2(body) == pytest.approx(5e-3, rel=1e-3)


def test_unsaved_project_persists_artifacts_to_scratch_dir() -> None:
    """An Untitled project (never saved → `current_project_path is None`)
    must still surface its run artefacts on disk, otherwise the dynamic
    controller can't re-hydrate the SimulationResult and the play / stop
    buttons stay disabled even after a successful run."""
    app = ApplicationService()
    app.new_project("Unsaved")
    assert app.current_project_path is None
    scratch = app.current_project_dir
    # Falls back to a real, existing scratch directory.
    assert scratch is not None
    assert scratch.exists()
    # Stable across calls (same scratch reused).
    assert app.current_project_dir == scratch


@pytest.mark.skip(reason="compose_project removed in redesign/case-as-model — needs rewrite")
def test_dynamic_run_succeeds_with_cancel_event_attached(tmp_path) -> None:
    """Regression: the cancel sensor used to declare `(mbs, t)` and return a
    bare float; Exudyn calls SensorUserFunction with 5 args and expects a
    `list[float]`. The mismatch aborted SolveDynamic before any frame was
    written and surfaced as a cryptic WinError 267 from the partial-frame
    loader trying to read a solution file that never existed."""
    import threading
    from quino.analysis.registry import get_runner_for_type
    from quino.domain.workspace import Run

    app = ApplicationService()
    app.load_project("examples/Double_Pendulum.quino.json")
    app.current_project_path = tmp_path / "p.quino.json"
    ws = app.project.workspace
    pose = ws.poses[0]
    analysis = app.workspace.create_analysis(
        "DynRun",
        analysis_type="dynamic",
        baseline_id=pose.baseline_id,
        case_id=pose.case_id,
        workspace_pose_id=pose.id,
    )
    composed = compose_project(app.project, case=None)
    run = Run(id="r1", analysis_id=analysis.id, created_at="now", status="queued")
    app.project.workspace.runs.append(run)
    cancel = threading.Event()  # never set, but must trip the cancel-sensor path
    result = get_runner_for_type("dynamic").run(
        composed, analysis,
        initial_pose=None, run=run,
        project_dir=app.current_project_dir,
        cancel_event=cancel,
    )
    assert result.status == "ok", result.error_message
    assert len(result.frames) == 101


def test_body_inertia_floor_for_point_mass() -> None:
    """A degenerate body (all markers at the CoM) gets `mass × ε²` rather
    than zero, so Exudyn's NodeRigidBody2D still has positive inertia."""
    from quino.solver_adapters.exudyn_adapter import (
        _MIN_INERTIA_RADIUS_M2,
        _body_inertia_kg_m2,
    )

    app = ApplicationService()
    app.new_project("PointMass")
    body_id = app.create_punctual_mass("M", x="0 mm", y="0 mm")
    app.update_property(
        body_id, "mass", PropertyValueInput(kind="expression", value="3 kg"),
    )
    adapter = ExudynAdapter(app.expression_service)
    assembled = adapter.assembler.assemble(app.project)
    body = assembled.bodies[body_id]
    # Single structural marker at the CoM → geometric Iz is 0; the floor
    # kicks in.
    assert _body_inertia_kg_m2(body) == pytest.approx(
        3.0 * _MIN_INERTIA_RADIUS_M2, rel=1e-6,
    )
