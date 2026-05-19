# quino/gui/preferences.py
"""Persistent user preferences via QtCore.QSettings.

The QSettings instance maps to:
- Windows: HKCU\\Software\\QUINO\\QUINO
- Linux:   ~/.config/QUINO/QUINO.conf
- macOS:   ~/Library/Preferences/com.QUINO.QUINO.plist

Currently empty — previous keys (sketch_solver_backend) were removed when
the legacy iterative solver was eliminated. Kept as a scaffold for future
persisted preferences.
"""
from __future__ import annotations

from PySide6 import QtCore


class Preferences:
    def __init__(self, settings: QtCore.QSettings | None = None) -> None:
        self._qs = settings if settings is not None else QtCore.QSettings("QUINO", "QUINO")
