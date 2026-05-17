from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.model import Pose
from quino.gui.icons import get_icon


class PosesPanel(QtWidgets.QWidget):
    """List + CRUD widget for the project's poses, with a star indicator for
    the simulation initial pose."""

    current_pose_changed = QtCore.Signal(str)        # pose_id selected for editing
    simulation_pose_changed = QtCore.Signal(object)  # pose_id or None
    poses_mutated = QtCore.Signal()                  # any add/remove/rename
    pose_constraint_selected = QtCore.Signal(str)
    pose_constraint_delete_requested = QtCore.Signal(str)

    _STAR_FILLED = "★"
    _STAR_EMPTY = "☆"

    def __init__(self, app_service: ApplicationService) -> None:
        super().__init__()
        self.app_service = app_service
        self._suspend = False

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(4)
        self._new_btn = QtWidgets.QToolButton()
        self._new_btn.setText("New")
        self._new_btn.setIcon(get_icon("add", "#3d3d3d"))
        self._new_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._new_btn.clicked.connect(self._on_new)
        self._duplicate_btn = QtWidgets.QToolButton()
        self._duplicate_btn.setText("Duplicate")
        self._duplicate_btn.setIcon(get_icon("content-save", "#3d3d3d"))
        self._duplicate_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._duplicate_btn.clicked.connect(self._on_duplicate)
        self._rename_btn = QtWidgets.QToolButton()
        self._rename_btn.setText("Rename")
        self._rename_btn.clicked.connect(self._on_rename)
        self._delete_btn = QtWidgets.QToolButton()
        self._delete_btn.setText("Delete")
        self._delete_btn.setIcon(get_icon("remove", "#8b2500"))
        self._delete_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._delete_btn.clicked.connect(self._on_delete)
        toolbar.addWidget(self._new_btn)
        toolbar.addWidget(self._duplicate_btn)
        toolbar.addWidget(self._rename_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addStretch(1)
        outer.addLayout(toolbar)

        self._list = QtWidgets.QTreeWidget()
        self._list.setHeaderHidden(True)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._list.currentItemChanged.connect(self._on_current_changed)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        outer.addWidget(self._list, stretch=1)

        hint = QtWidgets.QLabel(
            "Click the star to mark the pose used as the simulation initial state.\n"
            "Double-click to rename."
        )
        hint.setStyleSheet("color: #6a6a6a;")
        hint.setWordWrap(True)
        outer.addWidget(hint)

    def refresh(self) -> None:
        self._suspend = True
        try:
            self._list.clear()
            project = self.app_service.project
            if project is None:
                return
            sim_id = self.app_service.get_simulation_initial_pose_id()
            current_id = self.app_service.get_current_pose_id()
            current_item = None
            for pose in self.app_service.list_poses():
                star = self._STAR_FILLED if pose.id == sim_id else self._STAR_EMPTY
                item = QtWidgets.QTreeWidgetItem([f"{star}  {pose.name}"])
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, pose.id)
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole + 1, "pose")
                item.setToolTip(0,
                    "Active simulation initial pose" if pose.id == sim_id else "Click star to mark as simulation initial"
                )
                self._list.addTopLevelItem(item)
                for constraint_key, constraint_data in self._pose_constraint_items(pose):
                    child = QtWidgets.QTreeWidgetItem([self._pose_constraint_label(constraint_data)])
                    child.setData(0, QtCore.Qt.ItemDataRole.UserRole, constraint_key)
                    child.setData(0, QtCore.Qt.ItemDataRole.UserRole + 1, "constraint")
                    child.setToolTip(0, "Pose prescribe constraint. Select and Delete to remove.")
                    item.addChild(child)
                item.setExpanded(True)
                if pose.id == current_id:
                    current_item = item
            if current_item is not None:
                self._list.setCurrentItem(current_item)
            self._update_button_state()
        finally:
            self._suspend = False

    def _update_button_state(self) -> None:
        has_project = self.app_service.project is not None
        current = self._list.currentItem()
        selected_kind = current.data(0, QtCore.Qt.ItemDataRole.UserRole + 1) if current is not None else None
        has_pose_selection = selected_kind == "pose"
        has_constraint_selection = selected_kind == "constraint"
        self._new_btn.setEnabled(has_project)
        self._duplicate_btn.setEnabled(has_project and has_pose_selection)
        self._rename_btn.setEnabled(has_project and has_pose_selection)
        self._delete_btn.setEnabled(has_project and (has_pose_selection or has_constraint_selection))

    def _selected_pose_id(self) -> str | None:
        item = self._list.currentItem()
        if item is None:
            return None
        if item.data(0, QtCore.Qt.ItemDataRole.UserRole + 1) == "constraint":
            item = item.parent()
        return item.data(0, QtCore.Qt.ItemDataRole.UserRole) if item else None

    def _selected_constraint_key(self) -> str | None:
        item = self._list.currentItem()
        if item is None or item.data(0, QtCore.Qt.ItemDataRole.UserRole + 1) != "constraint":
            return None
        return item.data(0, QtCore.Qt.ItemDataRole.UserRole)

    def _on_current_changed(self, current, previous) -> None:
        if self._suspend or current is None:
            self._update_button_state()
            return
        kind = current.data(0, QtCore.Qt.ItemDataRole.UserRole + 1)
        if kind == "constraint":
            pose_item = current.parent()
            pose_id = pose_item.data(0, QtCore.Qt.ItemDataRole.UserRole) if pose_item is not None else None
            constraint_key = current.data(0, QtCore.Qt.ItemDataRole.UserRole)
            if pose_id:
                self.app_service.set_current_pose_id(pose_id)
                self.current_pose_changed.emit(pose_id)
            if constraint_key:
                self.pose_constraint_selected.emit(constraint_key)
            self._update_button_state()
            return
        pose_id = current.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if pose_id:
            self.app_service.set_current_pose_id(pose_id)
            self.current_pose_changed.emit(pose_id)
        self._update_button_state()

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem) -> None:
        if self._suspend or item is None:
            return
        if item.data(0, QtCore.Qt.ItemDataRole.UserRole + 1) != "pose":
            return
        # If user clicked on the star glyph area (first ~3 characters),
        # treat it as toggling the simulation initial flag.
        cursor_pos = self._list.viewport().mapFromGlobal(QtGui.QCursor.pos())
        rect = self._list.visualItemRect(item)
        # Hit-test the first ~22px (star + spacing).
        if rect.contains(cursor_pos) and cursor_pos.x() - rect.left() <= 22:
            pose_id = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
            current_sim = self.app_service.get_simulation_initial_pose_id()
            new_sim: str | None = None if current_sim == pose_id else pose_id
            self.app_service.set_simulation_initial_pose(new_sim)
            self.simulation_pose_changed.emit(new_sim)
            self.refresh()

    def _on_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem) -> None:
        if item is not None and item.data(0, QtCore.Qt.ItemDataRole.UserRole + 1) == "pose":
            self._on_rename()

    def _on_new(self) -> None:
        if self.app_service.project is None:
            return
        pose = self.app_service.create_pose()
        self.poses_mutated.emit()
        self.refresh()
        self.current_pose_changed.emit(pose.id)

    def _on_duplicate(self) -> None:
        pose_id = self._selected_pose_id()
        if pose_id is None:
            return
        pose = self.app_service.duplicate_pose(pose_id)
        self.poses_mutated.emit()
        self.refresh()
        self.current_pose_changed.emit(pose.id)

    def _on_rename(self) -> None:
        pose_id = self._selected_pose_id()
        if pose_id is None:
            return
        pose = self.app_service.get_pose(pose_id)
        if pose is None:
            return
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename pose", "Pose name:", QtWidgets.QLineEdit.EchoMode.Normal, pose.name
        )
        if not ok:
            return
        try:
            self.app_service.rename_pose(pose_id, new_name)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Rename pose", str(exc))
            return
        self.poses_mutated.emit()
        self.refresh()

    def _on_delete(self) -> None:
        constraint_key = self._selected_constraint_key()
        if constraint_key is not None:
            self.pose_constraint_delete_requested.emit(constraint_key)
            return
        pose_id = self._selected_pose_id()
        if pose_id is None:
            return
        pose = self.app_service.get_pose(pose_id)
        if pose is None:
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Delete pose",
            f"Delete pose '{pose.name}'?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.app_service.delete_pose(pose_id)
        self.poses_mutated.emit()
        self.refresh()
        new_current = self.app_service.get_current_pose_id()
        if new_current is not None:
            self.current_pose_changed.emit(new_current)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == QtCore.Qt.Key.Key_Delete and self._selected_constraint_key() is not None:
            self._on_delete()
            event.accept()
            return
        super().keyPressEvent(event)

    def _pose_constraint_items(self, pose: Pose) -> list[tuple[str, dict]]:
        raw_items = pose.metadata.values.get("pose_constraints", [])
        if not isinstance(raw_items, list):
            return []
        items: list[tuple[str, dict]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            constraint = item.get("constraint")
            if isinstance(key, str) and isinstance(constraint, dict):
                items.append((key, constraint))
        return items

    def _pose_constraint_label(self, constraint: dict) -> str:
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
