from __future__ import annotations

import importlib.util

from quino import ApplicationService, build_four_bar_example, build_slider_crank_example


def test_four_bar_example_builds_expected_topology() -> None:
    app = ApplicationService()
    result = build_four_bar_example(app)

    assert result.project_name == "Four Bar"
    assert len(result.body_ids) == 3
    assert len(result.joint_ids) == 4
    assert len(result.driver_ids) == 1
    assert app.project is not None
    assert len(app.project.model.bodies) == 3
    assert len(app.project.model.joints) == 4
    assert len(app.project.model.drivers) == 1


def test_slider_crank_example_builds_expected_topology() -> None:
    app = ApplicationService()
    result = build_slider_crank_example(app)

    assert result.project_name == "Slider Crank"
    assert len(result.body_ids) == 2
    assert len(result.slider_ids) == 1
    assert len(result.joint_ids) == 3
    assert len(result.driver_ids) == 1
    assert app.project is not None
    assert len(app.project.model.sliders) == 1


def test_four_bar_example_runs_if_exudyn_is_available() -> None:
    if importlib.util.find_spec("exudyn") is None:
        return

    app = ApplicationService()
    build_four_bar_example(app)
    result = app.run_kinematic_simulation()

    assert result.success is True
    assert result.frames
    assert result.time


def test_slider_crank_example_runs_if_exudyn_is_available() -> None:
    if importlib.util.find_spec("exudyn") is None:
        return

    app = ApplicationService()
    build_slider_crank_example(app)
    result = app.run_kinematic_simulation()

    assert result.success is True
    assert result.frames
    assert result.time



def test_pantograph_json_loads_and_roundtrips() -> None:
    from pathlib import Path
    import tempfile, os
    app = ApplicationService()
    path = Path("examples/Pantograph.quino.json")
    if not path.exists():
        pytest.skip("Pantograph example not found")
    app.load_project(str(path))
    assert app.project.name == "Pantograph"
    assert len(app.project.model.bodies) == 4
    assert len(app.project.model.joints) == 5

    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "roundtrip.quino.json")
        app.save_project(out)
        app2 = ApplicationService()
        app2.load_project(out)
        assert app2.project.name == "Pantograph"
        assert len(app2.project.model.bodies) == 4


def test_umbrella_mechanism_json_loads_and_roundtrips() -> None:
    from pathlib import Path
    import tempfile, os
    app = ApplicationService()
    path = Path("examples/Umbrella_Mechanism.quino.json")
    if not path.exists():
        pytest.skip("Umbrella example not found")
    app.load_project(str(path))
    assert app.project.name == "Umbrella Mechanism"
    assert len(app.project.model.bodies) == 2
    assert len(app.project.model.joints) == 3

    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "roundtrip.quino.json")
        app.save_project(out)
        app2 = ApplicationService()
        app2.load_project(out)
        assert app2.project.name == "Umbrella Mechanism"
        assert len(app2.project.model.bodies) == 2
