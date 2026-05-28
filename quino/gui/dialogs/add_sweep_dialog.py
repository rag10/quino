from __future__ import annotations

from uuid import uuid4

from PySide6 import QtWidgets

from quino.analysis.kinematic_sweeps import compute_sweep_base_value
from quino.domain.workspace import SweepDef

_KINDS = {
    "marker_x": ("Marker X", 1, "Marker"),
    "marker_y": ("Marker Y", 1, "Marker"),
    "slider_stroke": ("Slider stroke", 2, "Slider, Marker"),
    "angle_horizontal": ("Angle horizontal", 2, "Marker, Marker"),
    "angle_vertical": ("Angle vertical", 2, "Marker, Marker"),
    "angle_between_segments": ("Angle between segments", 4, "Marker, Marker, Marker, Marker"),
}


class SweepDefEditor(QtWidgets.QWidget):
    def __init__(self, project, initial_pose=None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._initial_pose = initial_pose
        self._target_combos: list[QtWidgets.QComboBox] = []

        layout = QtWidgets.QFormLayout(self)
        self.kind_combo = QtWidgets.QComboBox(self)
        for kind, (label, _arity, _help) in _KINDS.items():
            self.kind_combo.addItem(label, kind)
        self.kind_combo.currentIndexChanged.connect(self._rebuild_targets)
        layout.addRow("Variable", self.kind_combo)

        self.targets_widget = QtWidgets.QWidget(self)
        self.targets_layout = QtWidgets.QFormLayout(self.targets_widget)
        layout.addRow("Targets", self.targets_widget)

        self.ref_mode_combo = QtWidgets.QComboBox(self)
        self.ref_mode_combo.addItem("Absolute", "absolute")
        self.ref_mode_combo.addItem("Relative to initial pose", "relative")
        self.ref_mode_combo.currentIndexChanged.connect(self._update_info_label)
        layout.addRow("Reference mode", self.ref_mode_combo)

        self.mode_combo = QtWidgets.QComboBox(self)
        self.mode_combo.addItem("Linear", "linear")
        self.mode_combo.addItem("List", "list")
        self.mode_combo.currentIndexChanged.connect(self._sync_mode_visibility)
        layout.addRow("Mode", self.mode_combo)

        self.start_spin = QtWidgets.QDoubleSpinBox(self)
        self.start_spin.setRange(-1e9, 1e9)
        self.start_spin.setDecimals(6)
        self.end_spin = QtWidgets.QDoubleSpinBox(self)
        self.end_spin.setRange(-1e9, 1e9)
        self.end_spin.setDecimals(6)
        self.steps_spin = QtWidgets.QSpinBox(self)
        self.steps_spin.setRange(1, 100000)
        self.steps_spin.setValue(11)
        self.values_edit = QtWidgets.QLineEdit(self)
        self.label_edit = QtWidgets.QLineEdit(self)

        layout.addRow("Start", self.start_spin)
        layout.addRow("End", self.end_spin)
        layout.addRow("Steps", self.steps_spin)
        layout.addRow("Values", self.values_edit)
        layout.addRow("Label", self.label_edit)

        self.info_label = QtWidgets.QLabel("", self)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addRow(self.info_label)

        # Connect value changes to update info label
        self.start_spin.valueChanged.connect(self._update_info_label)
        self.end_spin.valueChanged.connect(self._update_info_label)
        self.steps_spin.valueChanged.connect(self._update_info_label)
        self.values_edit.textChanged.connect(self._update_info_label)

        self._rebuild_targets()
        self._sync_mode_visibility()
        self._update_info_label()

    def from_sweep_def(self, sweep: SweepDef) -> None:
        idx = self.kind_combo.findData(sweep.variable_kind)
        if idx >= 0:
            self.kind_combo.setCurrentIndex(idx)
        ref_idx = self.ref_mode_combo.findData(sweep.reference_mode)
        if ref_idx >= 0:
            self.ref_mode_combo.setCurrentIndex(ref_idx)
        self.mode_combo.setCurrentIndex(0 if sweep.mode == "linear" else 1)
        self.start_spin.setValue(float(sweep.start))
        self.end_spin.setValue(float(sweep.end))
        self.steps_spin.setValue(int(sweep.steps))
        self.values_edit.setText(", ".join(str(v) for v in sweep.values))
        self.label_edit.setText(sweep.label)
        self._rebuild_targets()
        for combo, target in zip(self._target_combos, sweep.target_ids):
            target_idx = combo.findData(target)
            if target_idx >= 0:
                combo.setCurrentIndex(target_idx)
        self._update_info_label()

    def to_sweep_def(self, sweep_id: str | None = None) -> SweepDef:
        mode = self.mode_combo.currentData()
        values: list[float] = []
        if mode == "list":
            raw = self.values_edit.text().strip()
            values = [float(item.strip()) for item in raw.split(",") if item.strip()]
        return SweepDef(
            id=sweep_id or f"sw_{uuid4().hex[:8]}",
            variable_kind=str(self.kind_combo.currentData()),
            target_ids=[str(combo.currentData()) for combo in self._target_combos if combo.currentData() is not None],
            mode=str(mode),
            start=float(self.start_spin.value()),
            end=float(self.end_spin.value()),
            steps=int(self.steps_spin.value()),
            values=values,
            label=self.label_edit.text().strip(),
            reference_mode=str(self.ref_mode_combo.currentData()),
        )

    def _sync_mode_visibility(self) -> None:
        is_linear = self.mode_combo.currentData() == "linear"
        self.start_spin.setVisible(is_linear)
        self.end_spin.setVisible(is_linear)
        self.steps_spin.setVisible(is_linear)
        self.values_edit.setVisible(not is_linear)
        self._update_info_label()

    def _rebuild_targets(self) -> None:
        while self.targets_layout.rowCount():
            self.targets_layout.removeRow(0)
        self._target_combos.clear()
        kind = str(self.kind_combo.currentData())
        _label, arity, _help = _KINDS[kind]
        marker_ids = [
            (f"{body.name}.{marker.name}", marker.id)
            for body in self._project.model.bodies
            for marker in body.markers
        ]
        slider_ids = [(slider.name, slider.id) for slider in self._project.model.sliders]
        for index in range(arity):
            combo = QtWidgets.QComboBox(self.targets_widget)
            use_slider = kind == "slider_stroke" and index == 0
            source = slider_ids if use_slider else marker_ids
            for name, entity_id in source:
                combo.addItem(name, entity_id)
            self.targets_layout.addRow(f"Target {index + 1}", combo)
            self._target_combos.append(combo)
            combo.currentIndexChanged.connect(self._update_info_label)
        self._update_info_label()

    def _current_sweep_values(self) -> list[float] | None:
        try:
            sweep = self.to_sweep_def("tmp")
            return sweep.resolved_values()
        except Exception:
            return None

    def _update_info_label(self) -> None:
        if self._initial_pose is None:
            self.info_label.setText("No initial pose available.")
            return

        mode = str(self.ref_mode_combo.currentData())
        kind = str(self.kind_combo.currentData())

        # Build a temporary sweep to compute base value
        try:
            sweep = self.to_sweep_def("tmp")
        except Exception:
            self.info_label.setText("Invalid sweep configuration.")
            return

        try:
            base = compute_sweep_base_value(self._project, sweep, self._initial_pose)
        except Exception as exc:
            self.info_label.setText(f"Cannot compute base value: {exc}")
            return

        values = sweep.resolved_values()
        if not values:
            self.info_label.setText("No sweep values configured.")
            return

        unit = "°" if kind.startswith("angle_") else " mm"

        if mode == "relative":
            abs_values = [v + base for v in values]
            self.info_label.setText(
                f"Initial: {base:.4g}{unit}  |  "
                f"Absolute range: [{min(abs_values):.4g}, {max(abs_values):.4g}]{unit}"
            )
        else:
            rel_start = values[0] - base
            rel_end = values[-1] - base
            self.info_label.setText(
                f"Relative range: [{rel_start:.4g}, {rel_end:.4g}]{unit}  |  "
                f"Initial: {base:.4g}{unit}"
            )


class AddSweepDialog(QtWidgets.QDialog):
    def __init__(self, project, initial_pose=None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Sweep")
        self.result_sweep: SweepDef | None = None
        layout = QtWidgets.QVBoxLayout(self)
        self.editor = SweepDefEditor(project, initial_pose, self)
        layout.addWidget(self.editor)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        self.result_sweep = self.editor.to_sweep_def()
        self.accept()
