from quino.services.run_artifacts import good_dir


def test_good_dir_matches_runner_prefix(tmp_path):
    base = tmp_path / "artifacts"
    assert good_dir(base, "an1").name == "run_an1"
    assert good_dir(base, "an1").parent == base
