import pytest

from quino.application.service import ApplicationService
from quino.domain.workspace import (
    DynamicConfig,
    KinematicConfig,
    StaticConfig,
    EquilibriumConfig,
    SweepDef,
    Analysis,
)


def test_dynamic_config_defaults():
    cfg = DynamicConfig()
    assert cfg.duration == 1.0
    assert cfg.steps == 100
    assert cfg.dt == 0.01
    assert cfg.integrator == "implicit"


def test_kinematic_config_defaults():
    cfg = KinematicConfig()
    assert cfg.sweeps == []
    assert cfg.allow_failed_steps is True


def test_static_config_defaults():
    cfg = StaticConfig()
    assert cfg.gravity_enabled is True
    assert cfg.tolerance == 1e-6
    assert cfg.report_reactions is True
    assert cfg.report_spring_energy is True


def test_equilibrium_config_defaults():
    cfg = EquilibriumConfig()
    assert cfg.gravity_enabled is True
    assert cfg.initial_perturbations == [0.0, 0.05, -0.05]
    assert cfg.stability_check is True


def test_sweepdef_linear_resolves_values():
    s = SweepDef(
        id="sw_1",
        variable_kind="marker_x",
        target_ids=["m1"],
        mode="linear",
        start=0.0,
        end=10.0,
        steps=11,
    )
    assert s.resolved_values() == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]


def test_sweepdef_list_passes_through():
    s = SweepDef(
        id="sw_1",
        variable_kind="marker_x",
        target_ids=["m1"],
        mode="list",
        values=[0.0, 3.0, 5.5],
    )
    assert s.resolved_values() == [0.0, 3.0, 5.5]


def test_analysis_default_config_matches_type():
    a = Analysis(id="a1", name="run1", analysis_type="dynamic")
    assert isinstance(a.config, DynamicConfig)

    a = Analysis(id="a2", name="run2", analysis_type="kinematic")
    assert isinstance(a.config, KinematicConfig)

    a = Analysis(id="a3", name="run3", analysis_type="static")
    assert isinstance(a.config, StaticConfig)

    a = Analysis(id="a4", name="run4", analysis_type="equilibrium")
    assert isinstance(a.config, EquilibriumConfig)


def test_analysis_explicit_config_wins():
    cfg = DynamicConfig(duration=5.0, steps=500)
    a = Analysis(id="a", name="x", analysis_type="dynamic", config=cfg)
    assert a.config is cfg


def test_analysis_config_roundtrip(tmp_path):
    from quino.application.service import ApplicationService

    svc = ApplicationService()
    svc.new_project("test")
    case = svc.workspace.create_case("C")
    pose = svc.workspace.create_pose("P", case_id=case.id)
    a = svc.workspace.create_analysis(
        "kin", analysis_type="kinematic", case_id=case.id, workspace_pose_id=pose.id,
    )
    a.config.sweeps.append(SweepDef(id="sw_1", variable_kind="marker_x",
                                    target_ids=["m1"], mode="linear",
                                    start=0, end=10, steps=11))
    path = tmp_path / "p.quino.json"
    svc.save_project(str(path))

    svc2 = ApplicationService()
    svc2.load_project(str(path))
    loaded = next(x for x in svc2.project.workspace.analyses if x.id == a.id)
    assert isinstance(loaded.config, KinematicConfig)
    assert len(loaded.config.sweeps) == 1
    assert loaded.config.sweeps[0].variable_kind == "marker_x"
    assert loaded.config.sweeps[0].steps == 11


def test_loading_old_schema_version_raises(tmp_path):
    import json
    path = tmp_path / "old.quino.json"
    path.write_text(json.dumps({"schema_version": "0.1.0", "project": {"id": "p", "name": "x"},
                                "parameters": [], "model": {}, "view_state": {}}))
    svc = ApplicationService()
    with pytest.raises(ValueError, match="schema"):
        svc.load_project(str(path))
