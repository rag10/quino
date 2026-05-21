from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.workspace import Analysis, Case as _Case

_USER_ROLE = int(QtCore.Qt.ItemDataRole.UserRole)
_OWNER_ROLE = _USER_ROLE + 1

_STATUS_COLORS = {
    "not_run": "#aaaaaa",
    "ok": "#2a8c3f",
    "stale": "#c07000",
    "running": "#1a6ec2",
    "failed": "#c02020",
}


_DELTA_LABELS = {
    "bodies": "bodies",
    "drivers": "drivers",
    "springs": "springs",
    "loads": "loads",
    "parameters": "params",
    "model": "blocks",
}


def _build_delta_summary(case: _Case) -> str:
    """Return compact category summary like '2 bodies, 1 driver'."""
    if not case.invariant_values:
        return ""
    counts: dict[str, int] = {}
    for path in case.invariant_values:
        domain = path.split("/")[0]
        label = _DELTA_LABELS.get(domain, domain)
        counts[label] = counts.get(label, 0) + 1
    parts = [f"{v} {k}" for k, v in counts.items()]
    return ", ".join(parts)


class WorkflowTreePanel(QtWidgets.QWidget):
    working_context_changed = QtCore.Signal()
    run_analysis_requested = QtCore.Signal(str)  # analysis_id
    pose_selected = QtCore.Signal(str)           # pose_id
    analysis_selected = QtCore.Signal(str)       # analysis_id
    selection_changed = QtCore.Signal(str, str)  # (kind, id)

    def __init__(self, app_service: ApplicationService) -> None:
        super().__init__()
        self.app_service = app_service
        self._item_map: dict[str, QtWidgets.QTreeWidgetItem] = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._badge = QtWidgets.QLabel("Working: —")
        self._badge.setContentsMargins(6, 2, 6, 2)
        self._badge.setStyleSheet(
            "QLabel { background: #dceeff; color: #1a3a6e; border-radius: 3px;"
            " font-weight: bold; font-size: 11px; }"
        )
        layout.addWidget(self._badge)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(2)
        self._add_btn = QtWidgets.QToolButton()
        self._add_btn.setText("+")
        self._add_btn.setToolTip("Add item")
        self._add_btn.clicked.connect(self._on_add)
        self._del_btn = QtWidgets.QToolButton()
        self._del_btn.setText("−")
        self._del_btn.setToolTip("Delete selected")
        self._del_btn.clicked.connect(self._on_delete)
        self._run_btn = QtWidgets.QToolButton()
        self._run_btn.setText("▶")
        self._run_btn.setToolTip("Run selected analysis")
        self._run_btn.clicked.connect(self._on_run)
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(self._del_btn)
        toolbar.addWidget(self._run_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setIndentation(14)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self._tree, stretch=1)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._tree.clear()
        self._item_map.clear()
        project = self.app_service.project
        if project is None or project.workspace is None:
            item = QtWidgets.QTreeWidgetItem(self._tree)
            item.setText(0, "No workspace")
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            self._update_badge()
            return

        ws = project.workspace
        for baseline in ws.baselines:
            b_item = self._make_item(baseline.id, "baseline", baseline.name)
            self._item_map[baseline.id] = b_item
            self._tree.addTopLevelItem(b_item)
            self._populate_analyses(b_item, baseline_id=baseline.id)
            self._populate_poses(b_item, baseline_id=baseline.id)
            self._populate_child_cases(b_item, parent_case_id=None, baseline_id=baseline.id)

        if not ws.baselines:
            placeholder = QtWidgets.QTreeWidgetItem(self._tree)
            placeholder.setText(0, "No baseline — right-click to add")
            placeholder.setFlags(placeholder.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)

        self._tree.expandAll()
        self._apply_active_highlight()
        self._update_badge()
        self._update_toolbar_state()

    def _populate_child_cases(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        *,
        parent_case_id: str | None,
        baseline_id: str,
    ) -> None:
        ws = self.app_service.project.workspace
        children = [
            c for c in ws.cases
            if c.baseline_id == baseline_id and c.parent_case_id == parent_case_id
        ]
        for case in children:
            c_item = self._make_item(case.id, "case", case.name)
            summary = _build_delta_summary(case)
            if summary:
                c_item.setToolTip(0, summary)
            self._item_map[case.id] = c_item
            parent_item.addChild(c_item)
            self._populate_analyses(c_item, case_id=case.id)
            self._populate_poses(c_item, case_id=case.id)
            self._populate_child_cases(c_item, parent_case_id=case.id, baseline_id=baseline_id)

    def _populate_poses(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
    ) -> None:
        ws = self.app_service.project.workspace
        poses = [
            p for p in ws.poses
            if p.baseline_id == baseline_id and p.case_id == case_id
        ]
        for pose in poses:
            label = pose.name + (" [default]" if pose.is_default else "")
            p_item = self._make_item(pose.id, "pose", label)
            p_item.setData(0, _OWNER_ROLE, ("case" if case_id else "baseline", case_id or baseline_id))
            self._item_map[pose.id] = p_item
            parent_item.addChild(p_item)
            pose_analyses = [a for a in ws.analyses if a.workspace_pose_id == pose.id]
            for analysis in pose_analyses:
                self._add_analysis_item(p_item, analysis)

    def _populate_analyses(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
    ) -> None:
        ws = self.app_service.project.workspace
        analyses = [
            a for a in ws.analyses
            if a.baseline_id == baseline_id and a.case_id == case_id and a.workspace_pose_id is None
        ]
        for analysis in analyses:
            self._add_analysis_item(parent_item, analysis)

    def _add_analysis_item(self, parent_item: QtWidgets.QTreeWidgetItem, analysis: Analysis) -> None:
        label = f"{analysis.name} [{analysis.analysis_type}]"
        a_item = self._make_item(analysis.id, "analysis", label)
        self._item_map[analysis.id] = a_item
        parent_item.addChild(a_item)

        ws = self.app_service.project.workspace
        status = "not_run"
        runs_for_analysis = [r for r in ws.runs if r.analysis_id == analysis.id]
        if runs_for_analysis:
            status = runs_for_analysis[-1].status

        color = _STATUS_COLORS.get(status, "#aaaaaa")
        a_item.setForeground(0, QtGui.QBrush(QtGui.QColor(color)))
        a_item.setToolTip(0, f"Status: {status}")

    def _make_item(self, obj_id: str, kind: str, text: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([text])
        item.setData(0, _USER_ROLE, (kind, obj_id))
        return item

    # ------------------------------------------------------------------
    # Active highlight + badge
    # ------------------------------------------------------------------

    def _apply_active_highlight(self) -> None:
        ws = self.app_service.project.workspace if self.app_service.project else None
        if ws is None:
            return
        active_id = ws.active_case_id or ws.active_baseline_id
        bold_font = QtGui.QFont()
        bold_font.setBold(True)
        normal_font = QtGui.QFont()
        for obj_id, item in self._item_map.items():
            if obj_id == active_id:
                item.setBackground(0, QtGui.QBrush(QtGui.QColor("#dceeff")))
                item.setFont(0, bold_font)
            else:
                item.setBackground(0, QtGui.QBrush())
                item.setFont(0, normal_font)

    def _update_badge(self) -> None:
        ws = self.app_service.project.workspace if self.app_service.project else None
        if ws is None or (ws.active_case_id is None and ws.active_baseline_id is None):
            self._badge.setText("Working: —")
            return
        if ws.active_case_id:
            case = next((c for c in ws.cases if c.id == ws.active_case_id), None)
            if case:
                self._badge.setText(f"Working: {case.name}")
                return
        if ws.active_baseline_id:
            baseline = next((b for b in ws.baselines if b.id == ws.active_baseline_id), None)
            if baseline:
                self._badge.setText(f"Working: {baseline.name}")
                return
        self._badge.setText("Working: —")

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def _on_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        data = item.data(0, _USER_ROLE)
        if data is None:
            return
        kind, obj_id = data
        if kind == "baseline":
            self._action_set_working(baseline_id=obj_id)
        elif kind == "case":
            self._action_set_working(case_id=obj_id)
        elif kind == "pose":
            self.app_service.set_selected_pose(obj_id)
            self.pose_selected.emit(obj_id)
        elif kind == "analysis":
            self.app_service.set_selected_analysis(obj_id)
            self.analysis_selected.emit(obj_id)

    def _set_subtree_expanded(self, item: QtWidgets.QTreeWidgetItem, expanded: bool) -> None:
        item.setExpanded(expanded)
        for i in range(item.childCount()):
            self._set_subtree_expanded(item.child(i), expanded)

    def _on_current_changed(self) -> None:
        self._update_toolbar_state()

        item = self._selected_item()
        if not item:
            return
        data = item.data(0, _USER_ROLE)
        if not data:
            return
        kind, obj_id = data
        self.selection_changed.emit(kind, obj_id)

    def _update_toolbar_state(self) -> None:
        item = self._selected_item()
        kind = item.data(0, _USER_ROLE)[0] if item and item.data(0, _USER_ROLE) else ""
        self._del_btn.setEnabled(kind in ("baseline", "case", "pose", "analysis"))
        self._run_btn.setEnabled(kind == "analysis")

    def _selected_item(self) -> QtWidgets.QTreeWidgetItem | None:
        items = self._tree.selectedItems()
        return items[0] if items else None

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        item = self._selected_item()
        data = item.data(0, _USER_ROLE) if item else None
        kind = data[0] if data else ""
        obj_id = data[1] if data else ""
        if kind == "baseline":
            self._action_add_case(baseline_id=obj_id)
        elif kind == "case":
            self._action_add_case(parent_case_id=obj_id)
        elif kind == "pose":
            self._action_add_analysis_to_pose(obj_id)
        else:
            self._action_add_baseline()

    def _on_delete(self) -> None:
        item = self._selected_item()
        if not item:
            return
        kind, obj_id = item.data(0, _USER_ROLE)
        self._delete_item(kind, obj_id, item.text(0))

    def _on_run(self) -> None:
        item = self._selected_item()
        if not item:
            return
        kind, obj_id = item.data(0, _USER_ROLE)
        if kind == "analysis":
            self.run_analysis_requested.emit(obj_id)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self._tree.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        if item is None:
            menu.addAction("Add Baseline", self._action_add_baseline)
        else:
            data = item.data(0, _USER_ROLE)
            if data is None:
                return
            kind, obj_id = data
            if kind == "baseline":
                menu.addAction("Add Subcase", lambda: self._action_add_case(baseline_id=obj_id))
                menu.addAction("Add Pose", lambda: self._action_add_pose(baseline_id=obj_id))
                menu.addAction("Add Analysis", lambda: self._action_add_analysis(baseline_id=obj_id))
                menu.addSeparator()
                menu.addAction("Set As Working Context", lambda: self._action_set_working(baseline_id=obj_id))
                menu.addSeparator()
                menu.addAction("Rename", lambda: self._action_rename(kind, obj_id))
                menu.addAction("Delete", lambda: self._delete_item(kind, obj_id, item.text(0)))
            elif kind == "case":
                menu.addAction("Add Subcase", lambda: self._action_add_case(parent_case_id=obj_id))
                menu.addAction("Add Pose", lambda: self._action_add_pose(case_id=obj_id))
                menu.addAction("Add Analysis", lambda: self._action_add_analysis(case_id=obj_id))
                menu.addSeparator()
                menu.addAction("Set As Working Context", lambda: self._action_set_working(case_id=obj_id))
                menu.addSeparator()
                menu.addAction("Rename", lambda: self._action_rename(kind, obj_id))
                menu.addAction("Delete", lambda: self._delete_item(kind, obj_id, item.text(0)))
                menu.addSeparator()
                menu.addAction("Expand All Below", lambda: self._set_subtree_expanded(item, True))
                menu.addAction("Collapse All Below", lambda: self._set_subtree_expanded(item, False))
            elif kind == "pose":
                ws = self.app_service.project.workspace
                pose = next((p for p in ws.poses if p.id == obj_id), None)
                menu.addAction("Add Analysis", lambda: self._action_add_analysis(pose_id=obj_id))
                if pose and not pose.is_default:
                    menu.addAction("Use As Initial Pose", lambda: self._action_use_as_initial_pose(obj_id))
                menu.addSeparator()
                if pose and not pose.is_default:
                    menu.addAction("Rename", lambda: self._action_rename(kind, obj_id))
                act_del = menu.addAction("Delete", lambda: self._delete_item(kind, obj_id, item.text(0)))
                if pose and pose.is_default:
                    act_del.setEnabled(False)
            elif kind == "analysis":
                menu.addAction("Run", lambda: self.run_analysis_requested.emit(obj_id))
                menu.addSeparator()
                menu.addAction("Rename", lambda: self._action_rename(kind, obj_id))
                menu.addAction("Delete", lambda: self._delete_item(kind, obj_id, item.text(0)))
        if not menu.isEmpty():
            menu.exec(self._tree.mapToGlobal(pos))

    # ------------------------------------------------------------------
    # CRUD actions
    # ------------------------------------------------------------------

    def _action_add_baseline(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New Baseline", "Name:")
        if ok and name:
            self.app_service.workspace.create_baseline(name)
            self.refresh()

    def _action_set_working(self, *, case_id: str | None = None, baseline_id: str | None = None) -> None:
        self.app_service.set_working_context(case_id=case_id, baseline_id=baseline_id)
        self._apply_active_highlight()
        self._update_badge()
        self.working_context_changed.emit()

    def _action_add_case(self, *, baseline_id: str | None = None, parent_case_id: str | None = None) -> None:
        title = "New Case" if baseline_id else "New Subcase"
        name, ok = QtWidgets.QInputDialog.getText(self, title, "Name:")
        if ok and name:
            self.app_service.workspace.create_case(
                name, baseline_id=baseline_id, parent_case_id=parent_case_id
            )
            self.refresh()

    def _action_add_pose(self, *, baseline_id: str | None = None, case_id: str | None = None) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New Pose", "Name:")
        if ok and name:
            self.app_service.workspace.create_pose(name, baseline_id=baseline_id, case_id=case_id)
            self.refresh()

    def _action_add_analysis(
        self,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
        pose_id: str | None = None,
    ) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New Analysis", "Name:")
        if not ok or not name:
            return
        # Future types: static, kinematic, equilibrium
        analysis_type, ok2 = QtWidgets.QInputDialog.getItem(
            self, "Analysis Type", "Type:", ["dynamic"], 0, False
        )
        if not ok2:
            return
        self.app_service.workspace.create_analysis(
            name,
            analysis_type=analysis_type,
            baseline_id=baseline_id,
            case_id=case_id,
            workspace_pose_id=pose_id,
        )
        self.refresh()

    def _action_add_analysis_to_pose(self, pose_id: str) -> None:
        ws = self.app_service.project.workspace
        pose = next((p for p in ws.poses if p.id == pose_id), None)
        if pose is None:
            return
        self._action_add_analysis(
            baseline_id=pose.baseline_id,
            case_id=pose.case_id,
            pose_id=pose_id,
        )

    def _action_use_as_initial_pose(self, pose_id: str) -> None:
        self.app_service.set_selected_pose(pose_id)
        self.pose_selected.emit(pose_id)

    def _action_rename(self, kind: str, obj_id: str) -> None:
        item = self._item_map.get(obj_id)
        current = item.text(0) if item else ""
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=current)
        if not ok or not name:
            return
        if kind == "baseline":
            self.app_service.workspace.rename_baseline(obj_id, name)
        elif kind == "case":
            self.app_service.workspace.rename_case(obj_id, name)
        elif kind == "pose":
            self.app_service.workspace.rename_pose(obj_id, name)
        elif kind == "analysis":
            self.app_service.workspace.rename_analysis(obj_id, name)
        self.refresh()

    def _delete_item(self, kind: str, obj_id: str, label: str) -> None:
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete", f"Delete {kind} '{label}'?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        ws = self.app_service.project.workspace
        active_case_id = ws.active_case_id if ws else None
        if kind == "baseline":
            self.app_service.workspace.delete_baseline(obj_id)
        elif kind == "case":
            self.app_service.workspace.delete_case(obj_id)
            if active_case_id == obj_id:
                self.app_service.set_working_context()
                self.working_context_changed.emit()
        elif kind == "pose":
            self.app_service.workspace.delete_pose(obj_id)
        elif kind == "analysis":
            self.app_service.workspace.delete_analysis(obj_id)
        self.refresh()
