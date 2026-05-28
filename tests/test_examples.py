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


def test_all_json_examples_load_and_validate_overlays() -> None:
    from pathlib import Path
    from quino.services.case_overlay_validator import validate_overlay

    for path in sorted(Path("examples").glob("*.quino.json")):
        app = ApplicationService()
        app.load_workspace(path)
        ws = app._workspace
        assert ws is not None
        for case in ws.cases.values():
            parent = ws.cases.get(case.parent_case_id) if case.parent_case_id else None
            validate_overlay(case, parent)


def test_example_registry_skips_json_with_duplicate_name(tmp_path) -> None:
    from quino.application.example_registry import ExampleRegistry

    # Create a JSON file with the same name as a builtin example
    json_file = tmp_path / "Four Bar.quino.json"
    json_file.write_text("{}")

    registry = ExampleRegistry(examples_dir=tmp_path)
    names = [e.name for e in registry.list_examples()]
    assert names.count("Four Bar") == 1


def test_all_example_files_load_and_overlays_validate() -> None:
    """Every examples/*.quino.json must load as a Workspace at schema 0.3.0
    and every child case must satisfy validate_overlay against its parent.

    Acceptance criterion from docs/PLAN-02.md §5.
    """
    from pathlib import Path

    from quino.serialization.json_io import JsonMapper
    from quino.services.case_overlay_validator import validate_overlay

    repo_root = Path(__file__).resolve().parents[1]
    examples_dir = repo_root / "examples"
    example_files = sorted(examples_dir.glob("*.quino.json"))
    assert example_files, "No example files found under examples/"

    failures: list[str] = []
    for path in example_files:
        try:
            ws = JsonMapper().load(str(path))
        except Exception as exc:
            failures.append(f"{path.name}: load failed — {exc}")
            continue
        assert ws.schema_version == "0.3.0", f"{path.name}: not 0.3.0"
        for case in ws.cases.values():
            parent = ws.cases.get(case.parent_case_id) if case.parent_case_id else None
            try:
                validate_overlay(case, parent)
            except Exception as exc:
                failures.append(f"{path.name} :: case {case.id}: {exc}")
    assert not failures, "Example/overlay validation failed:\n" + "\n".join(failures)
