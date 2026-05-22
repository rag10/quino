from __future__ import annotations

from PySide6 import QtWidgets

from quino.domain.workspace import SweepDef
from quino.gui.dialogs.add_sweep_dialog import SweepDefEditor


class SweepEditorDialog(QtWidgets.QDialog):
    def __init__(self, project, sweep: SweepDef, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Sweep")
        self.result_sweep: SweepDef | None = None
        self._original = sweep
        layout = QtWidgets.QVBoxLayout(self)
        self.editor = SweepDefEditor(project, self)
        self.editor.from_sweep_def(sweep)
        layout.addWidget(self.editor)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        self.result_sweep = self.editor.to_sweep_def(self._original.id)
        self.accept()
