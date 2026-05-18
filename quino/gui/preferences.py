# quino/gui/preferences.py
"""Persistent user preferences via QtCore.QSettings.

The QSettings instance maps to:
- Windows: HKCU\\Software\\QUINO\\QUINO
- Linux:   ~/.config/QUINO/QUINO.conf
- macOS:   ~/Library/Preferences/com.QUINO.QUINO.plist
"""
from __future__ import annotations

from PySide6 import QtCore


_VALID_SKETCH_BACKENDS = ("solvespace", "legacy")


class Preferences:
    """Wrapper around QSettings exposing typed accessors with sensible defaults.

    Pass a custom QSettings instance to the constructor for testing (e.g. an
    IniFormat settings file in a tmp_path). When called with no arguments,
    persists to the platform's default user settings location under
    organization "QUINO", application "QUINO".
    """

    _SKETCH_SOLVER_KEY = "sketch/solver_backend"

    def __init__(self, settings: QtCore.QSettings | None = None) -> None:
        self._qs = settings if settings is not None else QtCore.QSettings("QUINO", "QUINO")

    @property
    def sketch_solver_backend(self) -> str:
        value = self._qs.value(self._SKETCH_SOLVER_KEY, "solvespace", type=str)
        if value not in _VALID_SKETCH_BACKENDS:
            # Corrupt or unknown values fall back silently to the default.
            return "solvespace"
        return value

    @sketch_solver_backend.setter
    def sketch_solver_backend(self, value: str) -> None:
        if value not in _VALID_SKETCH_BACKENDS:
            raise ValueError(f"Invalid sketch solver backend: {value!r}")
        self._qs.setValue(self._SKETCH_SOLVER_KEY, value)
