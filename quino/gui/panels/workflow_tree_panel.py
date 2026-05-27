from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.workspace import Case
from quino.gui.icons import get_icon
from quino.gui.theme import (
    BLUE_DARK,
    BLUE_SOFT,
    INK_MUTED,
    INK_SUBTLE,
    apply_browser_tree_style,
)

ROLE_NODE_KIND = QtCore.Qt.ItemDataRole.UserRole
ROLE_ID = QtCore.Qt.ItemDataRole.UserRole + 1

# Status colours for run badges
_RUN_STATUS_COLORS = {
    "ok": "#25815f",
    "partial": "#a66a00",
    "failed": "#b43a2f",
    "stale": "#66727e",
    "running": "#2d74a7",
    "queued": "#2d74a7",
    "to_be_run": "#81909f",
}

_ANALYSIS_TYPE_LABELS = {
    "dynamic":     "Dyn",
    "kinematic":   "Kin",
    "static":      "Sta",
    "equilibrium": "Equ",
}


def _group_item(label: str, icon_name: str) -> QtWidgets.QTreeWidgetItem:
    """Non-selectable section header."""
    item = QtWidgets.QTreeWidgetItem([label])
    item.setIcon(0, get_icon(icon_name, INK_MUTED, size=16))
    item.setData(0, ROLE_NODE_KIND, "group")
    font = item.font(0)
    font.setBold(True)
    item.setFont(0, font)
    item.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_MUTED)))
    flags = item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable
    item.setFlags(flags)
    return item


class WorkflowTreePanel(QtWidgets.QWidget):
    case_selected = QtCore.Signal(str)
    pose_selected = QtCore.Signal(str)
    analysis_selected = QtCore.Signal(str)
    run_selected = QtCore.Signal(str)

    def __init__(self, app_service: ApplicationService, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = app_service
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setObjectName("workflowTree")
        self._tree.setHeaderLabels(["Workspace"])
        apply_browser_tree_style(self._tree, icon_size=16, indentation=18, show_header=True)
        self._tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.customContextMenuRequested.connect(self._on_context_menu_requested)
        layout.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._tree.clear()
        ws = self._service._workspace
        if ws is None:
            return
        for root_id in ws.root_case_ids:
            root_case = ws.cases.get(root_id)
            if root_case is not None:
                item = self._build_case_item(root_case, ws)
                self._tree.addTopLevelItem(item)
                item.setExpanded(True)

    def top_level_items(self) -> list[QtWidgets.QTreeWidgetItem]:
        return [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]

    def fork_case(self, parent_case_id: str, name: str) -> str:
        from quino.services.case_cascading import CascadingEngine
        ws = self._service._workspace
        if ws is None:
            raise ValueError("No active workspace")
        engine = CascadingEngine(ws)
        new_id = engine.fork_case(parent_case_id, name)
        ws.selected_case_id = new_id
        self.case_selected.emit(new_id)
        return new_id

    def delete_case(self, case_id: str) -> None:
        ws = self._service._workspace
        if ws is None:
            return
        to_delete: set[str] = {case_id}
        changed = True
        while changed:
            changed = False
            for cid, c in ws.cases.items():
                if c.parent_case_id in to_delete and cid not in to_delete:
                    to_delete.add(cid)
                    changed = True
        for cid in to_delete:
            ws.cases.pop(cid, None)
        ws.root_case_ids = [r for r in ws.root_case_ids if r in ws.cases]
        if ws.selected_case_id in to_delete:
            ws.selected_case_id = ws.root_case_ids[0] if ws.root_case_ids else None

    def rename_case(self, case_id: str, new_name: str) -> None:
        ws = self._service._workspace
        if ws is not None and case_id in ws.cases:
            ws.cases[case_id].name = new_name

    # ------------------------------------------------------------------
    # Tree builders
    # ------------------------------------------------------------------

    def _build_case_item(self, case: Case, ws) -> QtWidgets.QTreeWidgetItem:
        is_active = ws.selected_case_id == case.id
        icon_name = "workspace-subcase" if case.parent_case_id else "workspace-case"
        item = QtWidgets.QTreeWidgetItem([case.name])
        item.setIcon(
            0,
            get_icon(icon_name, BLUE_DARK if is_active else INK_MUTED, size=16),
        )
        item.setData(0, ROLE_NODE_KIND, "case")
        item.setData(0, ROLE_ID, case.id)
        if is_active:
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setBackground(0, QtGui.QBrush(QtGui.QColor(BLUE_SOFT)))
        item.setToolTip(0, f"Case: {case.name}" + (" (active)" if is_active else ""))

        # Build lookup tables
        analyses_by_pose: dict[str | None, list] = {}
        for analysis in case.analyses:
            analyses_by_pose.setdefault(analysis.pose_id, []).append(analysis)
        runs_by_analysis: dict[str, list] = {}
        for run in case.runs:
            runs_by_analysis.setdefault(run.analysis_id, []).append(run)
        known_pose_ids = {p.id for p in case.poses}

        # --- Default pose (reference, read-only) ---
        default_pose = next((p for p in case.poses if p.is_default), None)
        if default_pose is not None:
            dp_item = QtWidgets.QTreeWidgetItem([f"{default_pose.name}  [reference]"])
            dp_item.setIcon(0, get_icon("workspace-pose", INK_SUBTLE, size=16))
            dp_item.setData(0, ROLE_NODE_KIND, "default_pose")
            dp_item.setData(0, ROLE_ID, default_pose.id)
            dp_item.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_SUBTLE)))
            dp_item.setToolTip(0, "Reference pose - shows model in its reference configuration (read-only)")
            # Analyses under default pose
            for analysis in analyses_by_pose.get(default_pose.id, []):
                dp_item.addChild(self._build_analysis_item(analysis, runs_by_analysis, ws))
            item.addChild(dp_item)

        # --- Non-default poses ---
        non_default_poses = [p for p in case.poses if not p.is_default]
        if non_default_poses:
            poses_group = _group_item(f"Poses  ({len(non_default_poses)})", "workspace-poses")
            for pose in non_default_poses:
                pose_analyses = analyses_by_pose.get(pose.id, [])
                is_selected_pose = ws.selected_pose_id == pose.id
                suffix = f"  ({len(pose_analyses)} analysis)" if len(pose_analyses) == 1 else (f"  ({len(pose_analyses)} analyses)" if pose_analyses else "")
                pose_label = f"{pose.name}{suffix}"
                pose_item = QtWidgets.QTreeWidgetItem([pose_label])
                pose_item.setIcon(
                    0,
                    get_icon("workspace-pose", BLUE_DARK if is_selected_pose else INK_MUTED, size=16),
                )
                pose_item.setData(0, ROLE_NODE_KIND, "pose")
                pose_item.setData(0, ROLE_ID, pose.id)
                if is_selected_pose:
                    font = pose_item.font(0)
                    font.setBold(True)
                    pose_item.setFont(0, font)
                    pose_item.setBackground(0, QtGui.QBrush(QtGui.QColor(BLUE_SOFT)))
                pose_item.setToolTip(0, f"Pose: {pose.name}")
                for analysis in pose_analyses:
                    pose_item.addChild(self._build_analysis_item(analysis, runs_by_analysis, ws))
                if pose_analyses:
                    pose_item.setExpanded(True)
                poses_group.addChild(pose_item)
            poses_group.setExpanded(True)
            item.addChild(poses_group)

        # --- Orphaned analyses (no pose or pose missing) ---
        orphan_analyses = [
            a for a in case.analyses
            if a.pose_id is None or a.pose_id not in known_pose_ids
        ]
        if orphan_analyses:
            orphan_group = _group_item(f"Analyses  ({len(orphan_analyses)})", "workspace-analyses")
            for analysis in orphan_analyses:
                orphan_group.addChild(self._build_analysis_item(analysis, runs_by_analysis, ws))
            orphan_group.setExpanded(True)
            item.addChild(orphan_group)

        # --- Child (sub)cases ---
        child_cases = [c for c in ws.cases.values() if c.parent_case_id == case.id]
        if child_cases:
            sub_group = _group_item(f"Subcases  ({len(child_cases)})", "workspace-subcase")
            for child_case in child_cases:
                sub_group.addChild(self._build_case_item(child_case, ws))
            sub_group.setExpanded(True)
            item.addChild(sub_group)

        return item

    def _build_analysis_item(self, analysis, runs_by_analysis: dict[str, list], ws) -> QtWidgets.QTreeWidgetItem:
        type_badge = _ANALYSIS_TYPE_LABELS.get(analysis.analysis_type, analysis.analysis_type[:3].capitalize())
        runs = runs_by_analysis.get(analysis.id, [])
        run_summary = f"  ({len(runs)} run)" if len(runs) == 1 else (f"  ({len(runs)} runs)" if runs else "")
        is_selected = ws.selected_analysis_id == analysis.id
        label = f"[{type_badge}] {analysis.name}{run_summary}"
        a_item = QtWidgets.QTreeWidgetItem([label])
        a_item.setIcon(
            0,
            get_icon("workspace-analysis", BLUE_DARK if is_selected else INK_MUTED, size=16),
        )
        a_item.setData(0, ROLE_NODE_KIND, "analysis")
        a_item.setData(0, ROLE_ID, analysis.id)
        if is_selected:
            font = a_item.font(0)
            font.setBold(True)
            a_item.setFont(0, font)
            a_item.setBackground(0, QtGui.QBrush(QtGui.QColor(BLUE_SOFT)))
        a_item.setToolTip(0, f"{analysis.analysis_type.capitalize()} analysis: {analysis.name}")

        for run in runs:
            date_part = run.created_at[:10] if run.created_at else "-"
            status = run.status
            status_color = _RUN_STATUS_COLORS.get(status, "#888888")
            label = f"{date_part}  [{status}]"
            if run.note:
                label += f"  {run.note}"
            r_item = QtWidgets.QTreeWidgetItem([label])
            r_item.setIcon(0, get_icon("run-simulation", status_color, size=16))
            r_item.setData(0, ROLE_NODE_KIND, "run")
            r_item.setData(0, ROLE_ID, run.id)
            r_item.setForeground(0, QtGui.QBrush(QtGui.QColor(status_color)))
            r_item.setToolTip(0, f"Run {date_part} - {status}" + (f": {run.error_message}" if run.error_message else ""))
            a_item.addChild(r_item)

        if runs:
            a_item.setExpanded(True)
        return a_item

    # ------------------------------------------------------------------
    # Click / context menu routing
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, ROLE_NODE_KIND)
        ent_id = item.data(0, ROLE_ID)
        if kind == "case" and ent_id:
            self.case_selected.emit(ent_id)
        elif kind in ("pose", "default_pose") and ent_id:
            self.pose_selected.emit(ent_id)
        elif kind == "analysis" and ent_id:
            self.analysis_selected.emit(ent_id)
        elif kind == "run" and ent_id:
            self.run_selected.emit(ent_id)

    def _on_context_menu_requested(self, pos: QtCore.QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        kind = item.data(0, ROLE_NODE_KIND)
        ent_id = item.data(0, ROLE_ID)
        if not ent_id:
            return
        global_pos = self._tree.viewport().mapToGlobal(pos)
        if kind == "case":
            self._show_case_menu(global_pos, ent_id)
        elif kind == "default_pose":
            self._show_default_pose_menu(global_pos, ent_id)
        elif kind == "pose":
            self._show_pose_menu(global_pos, ent_id)
        elif kind == "analysis":
            self._show_analysis_menu(global_pos, ent_id)
        elif kind == "run":
            self._show_run_menu(global_pos, ent_id)

    # ------------------------------------------------------------------
    # Context menu implementations
    # ------------------------------------------------------------------

    def _show_case_menu(self, global_pos: QtCore.QPoint, case_id: str) -> None:
        ws = self._service._workspace
        case = ws.cases.get(case_id) if ws else None
        menu = QtWidgets.QMenu(self)
        add_pose_action = menu.addAction("Add pose…")
        menu.addSeparator()
        fork_action = menu.addAction("Fork case…")
        rename_action = menu.addAction("Rename…")
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        compare_action = menu.addAction("Compare with parent")
        compare_action.setEnabled(case is not None and case.parent_case_id is not None)
        action = menu.exec(global_pos)
        if action == add_pose_action:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add pose", "Pose name:")
            if ok and name.strip():
                self._service.workspace.create_pose(name.strip(), case_id=case_id)
                self.refresh()
        elif action == fork_action:
            name, ok = QtWidgets.QInputDialog.getText(self, "Fork case", "New case name:")
            if ok and name.strip():
                self.fork_case(case_id, name.strip())
                self.refresh()
        elif action == rename_action:
            current_name = case.name if case else ""
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Rename case", "New name:", text=current_name
            )
            if ok and name.strip():
                self.rename_case(case_id, name.strip())
                self.refresh()
        elif action == delete_action:
            self.delete_case(case_id)
            self.refresh()
        elif action == compare_action:
            self._compute_and_record_compare_warnings(case_id)
            self.case_selected.emit(case_id)

    def _show_default_pose_menu(self, global_pos: QtCore.QPoint, pose_id: str) -> None:
        menu = QtWidgets.QMenu(self)
        enter_action = menu.addAction("Enter pose (read-only)")
        menu.exec(global_pos)
        # Always enter regardless of which action (only one)
        self.pose_selected.emit(pose_id)

    def _show_pose_menu(self, global_pos: QtCore.QPoint, pose_id: str) -> None:
        ws = self._service._workspace
        pose = next(
            (p for case in (ws.cases.values() if ws else []) for p in case.poses if p.id == pose_id),
            None,
        )
        menu = QtWidgets.QMenu(self)
        add_analysis_action = menu.addAction("Add analysis…")
        menu.addSeparator()
        rename_action = menu.addAction("Rename…")
        delete_action = menu.addAction("Delete")
        action = menu.exec(global_pos)
        if action == add_analysis_action:
            analysis_types = ["dynamic", "kinematic", "static", "equilibrium"]
            atype, ok1 = QtWidgets.QInputDialog.getItem(
                self, "Add analysis", "Analysis type:", analysis_types, 0, False
            )
            if ok1:
                name, ok2 = QtWidgets.QInputDialog.getText(
                    self, "Add analysis", "Analysis name:", text=f"{atype.capitalize()} analysis"
                )
                if ok2 and name.strip():
                    case_id = self._case_id_for_pose(pose_id)
                    if case_id:
                        self._service.workspace.create_analysis(
                            name.strip(),
                            analysis_type=atype,
                            case_id=case_id,
                            workspace_pose_id=pose_id,
                        )
                        self.refresh()
        elif action == rename_action:
            current_name = pose.name if pose else ""
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Rename pose", "New name:", text=current_name
            )
            if ok and name.strip():
                self._service.workspace.rename_pose(pose_id, name.strip())
                self.refresh()
        elif action == delete_action:
            self._service.workspace.delete_pose(pose_id)
            self.refresh()

    def _show_analysis_menu(self, global_pos: QtCore.QPoint, analysis_id: str) -> None:
        ws = self._service._workspace
        analysis = next(
            (a for case in (ws.cases.values() if ws else []) for a in case.analyses if a.id == analysis_id),
            None,
        )
        menu = QtWidgets.QMenu(self)
        run_action = menu.addAction("▶  Run")
        menu.addSeparator()
        rename_action = menu.addAction("Rename…")
        delete_action = menu.addAction("Delete")
        action = menu.exec(global_pos)
        if action == run_action:
            self.analysis_selected.emit(analysis_id)
        elif action == rename_action:
            current_name = analysis.name if analysis else ""
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Rename analysis", "New name:", text=current_name
            )
            if ok and name.strip() and analysis:
                analysis.name = name.strip()
                self.refresh()
        elif action == delete_action:
            if ws:
                for case in ws.cases.values():
                    if any(a.id == analysis_id for a in case.analyses):
                        case.analyses = [a for a in case.analyses if a.id != analysis_id]
                        case.runs = [r for r in case.runs if r.analysis_id != analysis_id]
                        break
            self.refresh()

    def _show_run_menu(self, global_pos: QtCore.QPoint, run_id: str) -> None:
        menu = QtWidgets.QMenu(self)
        view_action = menu.addAction("View results")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        action = menu.exec(global_pos)
        if action == view_action:
            self.run_selected.emit(run_id)
        elif action == delete_action:
            ws = self._service._workspace
            if ws:
                for case in ws.cases.values():
                    if any(r.id == run_id for r in case.runs):
                        case.runs = [r for r in case.runs if r.id != run_id]
                        break
            self.refresh()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _case_id_for_pose(self, pose_id: str) -> str | None:
        ws = self._service._workspace
        if ws is None:
            return None
        for case in ws.cases.values():
            if any(p.id == pose_id for p in case.poses):
                return case.id
        return None

    def _compute_and_record_compare_warnings(self, case_id: str) -> None:
        from quino.services.case_overlay_validator import _entity_lookup
        ws = self._service._workspace
        if ws is None:
            return
        case = ws.cases.get(case_id)
        if case is None or case.parent_case_id is None:
            return
        parent = ws.cases.get(case.parent_case_id)
        if parent is None:
            return
        diffs = []
        parent_index = _entity_lookup(parent)
        child_index = _entity_lookup(case)
        for ent_id, (parent_ent, cls) in parent_index.items():
            child_ent_tuple = child_index.get(ent_id)
            if child_ent_tuple is None:
                diffs.append({"kind": "missing_in_child", "path": f"entities/{ent_id}"})
                continue
            for f in cls.__dataclass_fields__:  # type: ignore[attr-defined]
                try:
                    if getattr(parent_ent, f) != getattr(child_ent_tuple[0], f):
                        diffs.append({
                            "kind": "value_diff",
                            "path": f"entities/{ent_id}/{f}",
                            "parent_value": repr(getattr(parent_ent, f)),
                            "child_value": repr(getattr(child_ent_tuple[0], f)),
                        })
                except Exception:
                    pass
        case.metadata["divergence_warnings"] = diffs
