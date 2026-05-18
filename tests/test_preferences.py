"""Tests for the Preferences QSettings wrapper.

These tests use an isolated INI-format QSettings file in a tmp_path so they
don't touch the developer's actual preferences.
"""
import pytest
from PySide6 import QtCore

from quino.gui.preferences import Preferences


@pytest.fixture
def isolated_settings(tmp_path):
    """A QSettings backed by an INI file inside tmp_path, isolated from the user's real config."""
    return QtCore.QSettings(str(tmp_path / "prefs.ini"), QtCore.QSettings.IniFormat)


def test_default_sketch_solver_backend_is_solvespace(isolated_settings):
    p = Preferences(isolated_settings)
    assert p.sketch_solver_backend == "solvespace"


def test_set_and_get_legacy(isolated_settings):
    p = Preferences(isolated_settings)
    p.sketch_solver_backend = "legacy"
    assert p.sketch_solver_backend == "legacy"


def test_set_invalid_raises(isolated_settings):
    p = Preferences(isolated_settings)
    with pytest.raises(ValueError, match="Invalid sketch solver backend"):
        p.sketch_solver_backend = "xyz"


def test_corrupt_value_falls_back_to_solvespace(isolated_settings):
    isolated_settings.setValue("sketch/solver_backend", "garbage")
    p = Preferences(isolated_settings)
    assert p.sketch_solver_backend == "solvespace"


def test_persists_across_instances(isolated_settings, tmp_path):
    p1 = Preferences(isolated_settings)
    p1.sketch_solver_backend = "legacy"
    isolated_settings.sync()
    # Re-open a fresh QSettings pointing at the same file
    fresh = QtCore.QSettings(str(tmp_path / "prefs.ini"), QtCore.QSettings.IniFormat)
    p2 = Preferences(fresh)
    assert p2.sketch_solver_backend == "legacy"
