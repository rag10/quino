from __future__ import annotations

import math

from PySide6 import QtCore, QtWidgets

from quino.application.service import ApplicationService


class PoseConstraintsStrip(QtWidgets.QWidget):
    """Compact lateral widget for pose constraint management. Visible only in pose mode."""

    constraint_selected = QtCore.Signal(str)
    constraint_delete_requested = QtCore.Signal(str)

    def __init__(self, app_service: ApplicationService, parent=None) -> None:
        super().__init__(parent)
        self.app_service = app_service
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        title = QtWidgets.QLabel("<b>Pose constraints</b>")
        layout.addWidget(title)
        self._list = QtWidgets.QListWidget()
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, stretch=1)
        del_btn = QtWidgets.QPushButton("Delete selected")
        del_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(del_btn)
        self.setMaximumWidth(220)

    def set_constraints(self, constraints: list) -> None:
        self._list.clear()
        for c in constraints:
            label = f"{getattr(c, 'kind', '?')}: {getattr(c, 'target_id', '?')}"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, c.id)
            self._list.addItem(item)

    def refresh(self) -> None:
        """Reload constraints for the current pose from the app service."""
        self._list.clear()
        project = self.app_service.project
        if project is None:
            return
        current_pose = self.app_service.get_current_pose()
        if current_pose is None:
            return
        raw_items = current_pose.metadata.values.get("pose_constraints", [])
        if not isinstance(raw_items, list):
            return
        for item_data in raw_items:
            if not isinstance(item_data, dict):
                continue
            key = item_data.get("key")
            constraint = item_data.get("constraint")
            if not isinstance(key, str) or not isinstance(constraint, dict):
                continue
            label = self._constraint_label(constraint)
            list_item = QtWidgets.QListWidgetItem(label)
            list_item.setData(QtCore.Qt.ItemDataRole.UserRole, key)
            self._list.addItem(list_item)

    def _constraint_label(self, constraint: dict) -> str:
        kind = constraint.get("kind")
        metadata = constraint.get("metadata", {})
        if kind == "marker_projected_coordinate" and isinstance(metadata, dict):
            axis = "X" if float(metadata.get("axis_x", 0.0)) else "Y"
            return f"Prescribe {axis}: {float(metadata.get('value', 0.0)):.6g} mm"
        if kind == "body_angle" and isinstance(metadata, dict):
            return f"Prescribe angle: {math.degrees(float(metadata.get('angle', 0.0))):.6g} deg"
        if kind == "relative_body_angle" and isinstance(metadata, dict):
            return f"Prescribe relative angle: {math.degrees(float(metadata.get('angle', 0.0))):.6g} deg"
        return "Pose prescribe"

    def _on_item_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        cid = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if cid:
            self.constraint_selected.emit(cid)

    def _on_delete_clicked(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        cid = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if cid:
            self.constraint_delete_requested.emit(cid)
