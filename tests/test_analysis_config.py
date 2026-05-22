from quino.domain.workspace import (
    DynamicConfig,
    KinematicConfig,
    StaticConfig,
    EquilibriumConfig,
    SweepDef,
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
