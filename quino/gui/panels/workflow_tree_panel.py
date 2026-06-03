from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.workspace import Case
from quino.gui.icons import get_icon
from quino.gui.theme import (
    BLUE_DARK,
    BLUE_SOFT,
    INK,
    INK_MUTED,
    INK_SUBTLE,
    apply_browser_tree_style,
)

ROLE_NODE_KIND = QtCore.Qt.ItemDataRole.UserRole
ROLE_ID = QtCore.Qt.ItemDataRole.UserRole + 1
# Custom paint flags. The tree QSS forces ``QTreeWidget::item`` background to
# transparent, which overrides any ``setBackground`` brush — so row tinting is
# done in the delegate instead, driven by these roles.
ROLE_ACTIVE_TINT = QtCore.Qt.ItemDataRole.UserRole + 2  # bool: active-case scope
ROLE_SELECTED_FILL = QtCore.Qt.ItemDataRole.UserRole + 3  # bool: selected pose/analysis

# Status icons + colours for run badges (icon_name, color)
_RUN_STATUS_ICONS = {
    "ok":        ("check-circle",   "#25815f"),
    "partial":   ("check-circle",   "#a66a00"),
    "failed":    ("remove",         "#b43a2f"),
    "stale":     ("refresh",        "#66727e"),
    "running":   ("refresh",        "#2d74a7"),
    "queued":    ("pause",          "#2d74a7"),
    "to_be_run": ("run-simulation", "#81909f"),
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


# Colours for the case/subcase pill background drawn by _CaseFrameDelegate.
_CASE_PILL_BG_INACTIVE = "#eaf3fb"
_CASE_PILL_BORDER_INACTIVE = "#bcd6ec"
_CASE_PILL_BG_ACTIVE = "#1e6fb0"
_CASE_PILL_BORDER_ACTIVE = "#174462"
_CASE_PILL_RADIUS = 6

# Row backgrounds painted by the delegate for poses/analyses (QSS forces the
# item background transparent, so these are painted, not set as brushes).
_ACTIVE_SCOPE_FILL = "#eef6fc"   # light: everything under the active case
_SELECTED_FILL = "#cfe4f6"       # stronger: the explicitly-selected pose/analysis


class _CaseFrameDelegate(QtWidgets.QStyledItemDelegate):
    """Draws a rounded "pill" frame behind case/subcase nodes.

    For non-case rows the default delegate behaviour is used unchanged.
    """

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        kind = index.data(ROLE_NODE_KIND)
        if kind != "case":
            # Paint the row fill ourselves (the QSS forces item bg transparent).
            # Selected fill wins over the lighter active-scope tint. The Qt
            # selection highlight still draws on top via super().paint().
            fill = None
            if index.data(ROLE_SELECTED_FILL):
                fill = QtGui.QColor(_SELECTED_FILL)
            elif index.data(ROLE_ACTIVE_TINT):
                fill = QtGui.QColor(_ACTIVE_SCOPE_FILL)
            if fill is not None and not (option.state & QtWidgets.QStyle.StateFlag.State_Selected):
                painter.save()
                painter.fillRect(option.rect, fill)
                painter.restore()
            super().paint(painter, option, index)
            return

        # Detect "active case" by checking whether the foreground brush is
        # pure white — this is the marker the panel sets when is_active.
        fg = index.data(QtCore.Qt.ItemDataRole.ForegroundRole)
        is_active = False
        if fg is not None:
            try:
                col = QtGui.QColor(fg) if not isinstance(fg, QtGui.QBrush) else fg.color()
                is_active = col.name().lower() == "#ffffff"
            except Exception:
                is_active = False

        bg = QtGui.QColor(_CASE_PILL_BG_ACTIVE if is_active else _CASE_PILL_BG_INACTIVE)
        border = QtGui.QColor(_CASE_PILL_BORDER_ACTIVE if is_active else _CASE_PILL_BORDER_INACTIVE)

        # Draw the rounded pill behind the row content.
        pill_rect = QtCore.QRectF(option.rect).adjusted(2.0, 2.0, -3.0, -2.0)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QtGui.QBrush(bg))
        painter.setPen(QtGui.QPen(border, 1.0))
        painter.drawRoundedRect(pill_rect, _CASE_PILL_RADIUS, _CASE_PILL_RADIUS)
        painter.restore()

        # Now overlay icon + text manually so we don't fight with the style's
        # default selection painting.
        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        text = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        font = index.data(QtCore.Qt.ItemDataRole.FontRole)

        row_rect = QtCore.QRect(option.rect)
        left = row_rect.left() + 8
        icon_size = 20
        if isinstance(icon, QtGui.QIcon) and not icon.isNull():
            icon_rect = QtCore.QRect(left, row_rect.center().y() - icon_size // 2, icon_size, icon_size)
            icon.paint(painter, icon_rect, QtCore.Qt.AlignmentFlag.AlignCenter)
            left = icon_rect.right() + 8

        text_rect = QtCore.QRect(left, row_rect.top(), row_rect.right() - left - 6, row_rect.height())
        painter.save()
        if isinstance(font, QtGui.QFont):
            painter.setFont(font)
        text_color = QtGui.QColor("#ffffff" if is_active else BLUE_DARK)
        painter.setPen(QtGui.QPen(text_color))
        painter.drawText(
            text_rect,
            int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
            str(text),
        )
        painter.restore()


class WorkflowTreePanel(QtWidgets.QWidget):
    case_selected = QtCore.Signal(str)      # single-click on case: set active, inspect
    case_activated = QtCore.Signal(str)     # double-click on case: enter model mode
    pose_selected = QtCore.Signal(str)
    analysis_selected = QtCore.Signal(str)
    run_selected = QtCore.Signal(str)
    run_now_requested = QtCore.Signal(str)  # analysis_id — execute the analysis
    rerun_requested = QtCore.Signal(str)    # run_id — re-execute its analysis

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
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.customContextMenuRequested.connect(self._on_context_menu_requested)
        self._case_delegate = _CaseFrameDelegate(self._tree)
        self._tree.setItemDelegate(self._case_delegate)
        layout.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        ws = self._service._workspace
        if ws is None:
            self._tree.clear()
            return
        # Preserve expansion state across rebuilds. We key by (kind, id) for
        # selectable nodes and by (kind, parent_id, position) for group nodes
        # whose identity comes from their parent.
        previous_expansion = self._snapshot_expansion()
        self._tree.clear()
        for root_id in ws.root_case_ids:
            root_case = ws.cases.get(root_id)
            if root_case is not None:
                item = self._build_case_item(root_case, ws)
                self._tree.addTopLevelItem(item)
                self._restore_expansion(item, previous_expansion, first_time=not previous_expansion)

    def _snapshot_expansion(self) -> dict[tuple, bool]:
        """Walk the current tree and collect the expansion state of every item."""
        state: dict[tuple, bool] = {}
        def walk(item: QtWidgets.QTreeWidgetItem) -> None:
            key = self._expansion_key(item)
            if key is not None:
                state[key] = item.isExpanded()
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i))
        return state

    def _expansion_key(self, item: QtWidgets.QTreeWidgetItem) -> tuple | None:
        kind = item.data(0, ROLE_NODE_KIND)
        ent_id = item.data(0, ROLE_ID)
        if not kind:
            return None
        return (kind, ent_id)

    def _restore_expansion(
        self,
        item: QtWidgets.QTreeWidgetItem,
        previous: dict[tuple, bool],
        *,
        first_time: bool,
    ) -> None:
        """Recursively restore expansion from snapshot; default to expanded
        when this is the very first build (previous snapshot empty)."""
        key = self._expansion_key(item)
        if key is not None and key in previous:
            item.setExpanded(previous[key])
        elif first_time:
            # Initial population: keep the expanded-by-default look.
            item.setExpanded(True)
        # For genuinely new nodes after the first build, leave whatever
        # _build_case_item / _build_analysis_item already set (which expands
        # groups that contain children).
        for i in range(item.childCount()):
            self._restore_expansion(item.child(i), previous, first_time=first_time)

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
        ws.selected_pose_id = None
        ws.selected_analysis_id = None
        self.case_selected.emit(new_id)
        return new_id

    def delete_case(self, case_id: str) -> None:
        """Backward-compat helper used by tests; delegates to backend."""
        try:
            self._service.workspace.delete_case(case_id)
        except ValueError:
            return

    def rename_case(self, case_id: str, new_name: str) -> None:
        """Backward-compat helper used by tests; delegates to backend."""
        self._service.workspace.rename_case(case_id, new_name)

    # ------------------------------------------------------------------
    # Tree builders
    # ------------------------------------------------------------------

    def _build_case_item(self, case: Case, ws) -> QtWidgets.QTreeWidgetItem:
        is_active = ws.selected_case_id == case.id
        is_root = case.parent_case_id is None
        icon_name = "workspace-case" if is_root else "workspace-subcase"
        # Cases (root) and subcases get a rounded coloured frame painted by
        # _CaseFrameDelegate. Text is dark blue when inactive, white when the
        # case is the one currently being worked on.
        label_prefix = "" if is_root else "▸ "
        item = QtWidgets.QTreeWidgetItem([f"{label_prefix}{case.name}"])
        icon_size = 20 if is_root else 18
        icon_color = "#ffffff" if is_active else BLUE_DARK
        item.setIcon(0, get_icon(icon_name, icon_color, size=icon_size))
        item.setData(0, ROLE_NODE_KIND, "case")
        item.setData(0, ROLE_ID, case.id)

        font = item.font(0)
        font.setBold(True)
        if is_root:
            font.setPointSizeF(font.pointSizeF() + 1.5)
        else:
            font.setPointSizeF(font.pointSizeF() + 0.5)
        item.setFont(0, font)
        # The delegate inspects the foreground colour: pure white => active.
        text_color = "#ffffff" if is_active else BLUE_DARK
        item.setForeground(0, QtGui.QBrush(QtGui.QColor(text_color)))

        tooltip = f"{'Case' if is_root else 'Subcase'}: {case.name}"
        if is_active:
            tooltip += " (active)"
        item.setToolTip(0, tooltip)

        analyses_by_pose: dict[str | None, list] = {}
        for analysis in case.analyses:
            analyses_by_pose.setdefault(analysis.pose_id, []).append(analysis)
        known_pose_ids = {p.id for p in case.poses}

        # --- Poses hang DIRECTLY off the case (default first, then user poses) ---
        default_pose = next((p for p in case.poses if p.is_default), None)
        if default_pose is None:
            # Auto-create the reference pose if missing (workspaces saved before
            # the load-time migration was added).
            from quino.domain.workspace import create_default_pose
            pose_id = self._service.id_service.new("pose")
            default_pose = create_default_pose(pose_id)
            case.poses.insert(0, default_pose)
        non_default_poses = [p for p in case.poses if not p.is_default]

        dp_pose_id = default_pose.id if default_pose else None
        dp_label = f"{default_pose.name}  [reference]" if default_pose else "Reference  [reference]"
        dp_item = QtWidgets.QTreeWidgetItem([dp_label])
        dp_item.setIcon(0, get_icon("workspace-pose", INK_SUBTLE, size=16))
        dp_item.setData(0, ROLE_NODE_KIND, "default_pose")
        if dp_pose_id:
            dp_item.setData(0, ROLE_ID, dp_pose_id)
        dp_item.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_SUBTLE)))
        dp_item.setToolTip(0, "Reference pose — model in its reference configuration (read-only)")
        self._apply_row_style(dp_item, selected=False, active=is_active)
        # Analyses hang directly off their parent pose (no intermediate
        # "Analyses" group node).
        dp_analyses = analyses_by_pose.get(dp_pose_id, []) if dp_pose_id else []
        for analysis in dp_analyses:
            a_child = self._build_analysis_item(analysis, ws)
            self._apply_row_style(
                a_child,
                selected=ws.selected_analysis_id == analysis.id,
                active=is_active,
            )
            dp_item.addChild(a_child)
        dp_item.setExpanded(True)
        item.addChild(dp_item)

        for pose in non_default_poses:
            pose_analyses = analyses_by_pose.get(pose.id, [])
            is_selected_pose = ws.selected_pose_id == pose.id
            pose_item = QtWidgets.QTreeWidgetItem([pose.name])
            pose_item.setIcon(
                0,
                get_icon("workspace-pose", BLUE_DARK if is_selected_pose else INK_MUTED, size=16),
            )
            pose_item.setData(0, ROLE_NODE_KIND, "pose")
            pose_item.setData(0, ROLE_ID, pose.id)
            pose_item.setForeground(0, QtGui.QBrush(QtGui.QColor(INK)))
            # Surface a re-solve warning if the pose failed to re-solve after a
            # model change (it is preserved, not deleted).
            warn = None
            if pose.metadata is not None:
                warn = pose.metadata.values.get("solve_warning")
            if pose.solve_failed or warn:
                pose_item.setText(0, f"{pose.name}  ⚠")
                pose_item.setToolTip(0, f"Pose: {pose.name}\n⚠ {warn or 'needs re-solving'}")
            else:
                pose_item.setToolTip(0, f"Pose: {pose.name}")
            self._apply_row_style(pose_item, selected=is_selected_pose, active=is_active)
            for analysis in pose_analyses:
                a_child = self._build_analysis_item(analysis, ws)
                self._apply_row_style(
                    a_child,
                    selected=ws.selected_analysis_id == analysis.id,
                    active=is_active,
                )
                pose_item.addChild(a_child)
            pose_item.setExpanded(True)
            item.addChild(pose_item)

        # --- Orphaned analyses (no pose / pose missing) ---
        orphan_analyses = [
            a for a in case.analyses
            if a.pose_id is None or a.pose_id not in known_pose_ids
        ]
        if orphan_analyses:
            orphan_group = _group_item(f"Analyses  ({len(orphan_analyses)})", "workspace-analyses")
            for analysis in orphan_analyses:
                orphan_group.addChild(self._build_analysis_item(analysis, ws))
            orphan_group.setExpanded(True)
            item.addChild(orphan_group)

        # --- Subcases group (always shown) ---
        child_cases = [c for c in ws.cases.values() if c.parent_case_id == case.id]
        sub_group = _group_item(
            f"Subcases  ({len(child_cases)})" if child_cases else "Subcases",
            "folder-open",
        )
        sub_group.setData(0, ROLE_NODE_KIND, "subcases_group")
        sub_group.setData(0, ROLE_ID, case.id)
        for child_case in child_cases:
            sub_group.addChild(self._build_case_item(child_case, ws))
        sub_group.setExpanded(bool(child_cases))
        item.addChild(sub_group)

        # When this is the active case, auto-expand it so its poses/analyses are
        # visible. The subcases group is intentionally NOT tinted (only the
        # active case's own poses/analyses are highlighted).
        if is_active:
            item.setExpanded(True)

        return item

    def _apply_row_style(
        self,
        item: QtWidgets.QTreeWidgetItem,
        *,
        selected: bool,
        active: bool,
    ) -> None:
        """Unified styling for pose/analysis rows.

        Visual language:
        - **bold** marks the explicitly-selected pose/analysis (cases are bold
          via their own builder). Non-selected rows use normal weight.
        - the selected row gets the stronger fill; rows under the active case
          get a lighter active-scope tint. Fills are painted by the delegate
          (driven by ROLE_SELECTED_FILL / ROLE_ACTIVE_TINT) because the tree QSS
          forces item backgrounds transparent.
        """
        font = item.font(0)
        font.setBold(bool(selected))
        item.setFont(0, font)
        item.setData(0, ROLE_SELECTED_FILL, bool(selected))
        item.setData(0, ROLE_ACTIVE_TINT, bool(active) and not selected)

    def _build_analysis_item(self, analysis, ws) -> QtWidgets.QTreeWidgetItem:
        type_badge = _ANALYSIS_TYPE_LABELS.get(analysis.analysis_type, analysis.analysis_type[:3].capitalize())
        is_selected = ws.selected_analysis_id == analysis.id
        status = getattr(analysis, "status", "to_be_run")
        _icon_name, status_color = _RUN_STATUS_ICONS.get(status, ("run-simulation", "#888888"))

        # Run state is rendered ON the analysis node (no separate run rows).
        # A status suffix is appended for non-default states.
        status_suffix = "" if status == "to_be_run" else f"  · {status}"
        label = f"[{type_badge}] {analysis.name}{status_suffix}"
        a_item = QtWidgets.QTreeWidgetItem([label])

        # Tint the analysis icon by run status so different statuses produce
        # visibly different pixmaps. Selection takes precedence for colour.
        if is_selected:
            icon_color = BLUE_DARK
        elif status == "to_be_run":
            icon_color = INK_MUTED
        else:
            icon_color = status_color
        a_item.setIcon(0, get_icon("workspace-analysis", icon_color, size=16))
        a_item.setData(0, ROLE_NODE_KIND, "analysis")
        a_item.setData(0, ROLE_ID, analysis.id)
        # Bold/selection fill/active tint are applied by the caller via
        # _apply_row_style so all rows share one consistent visual language.

        tooltip = f"{analysis.analysis_type.capitalize()} analysis: {analysis.name}\nStatus: {status}"
        error_message = getattr(analysis, "error_message", "")
        if error_message:
            tooltip += f"\n{error_message}"
        a_item.setToolTip(0, tooltip)
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

    def _on_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, ROLE_NODE_KIND)
        ent_id = item.data(0, ROLE_ID)
        if not ent_id:
            return
        if kind == "case":
            self.case_activated.emit(ent_id)
        elif kind in ("pose", "default_pose"):
            self.pose_selected.emit(ent_id)
        elif kind == "analysis":
            self.analysis_selected.emit(ent_id)

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
        elif kind == "subcases_group":
            self._show_subcases_group_menu(global_pos, ent_id)
        elif kind == "default_pose":
            self._show_default_pose_menu(global_pos, ent_id)
        elif kind == "pose":
            self._show_pose_menu(global_pos, ent_id)
        elif kind == "analysis":
            self._show_analysis_menu(global_pos, ent_id)

    # ------------------------------------------------------------------
    # Confirmation helper
    # ------------------------------------------------------------------

    def _confirm_delete(self, what: str, name: str, extra: str = "") -> bool:
        text = f"Delete {what} '{name}'?"
        if extra:
            text += f"\n\n{extra}"
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle(f"Delete {what}")
        box.setText(text)
        box.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        return box.exec() == QtWidgets.QMessageBox.StandardButton.Yes

    def _show_error(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, title, message)

    # ------------------------------------------------------------------
    # Context menu implementations
    # ------------------------------------------------------------------

    def _show_case_menu(self, global_pos: QtCore.QPoint, case_id: str) -> None:
        ws = self._service._workspace
        case = ws.cases.get(case_id) if ws else None
        if case is None:
            return
        n_descendants = len([c for c in ws.cases.values() if c.parent_case_id == case_id])
        is_only_root = case_id in ws.root_case_ids and len(ws.root_case_ids) == 1

        menu = QtWidgets.QMenu(self)
        edit_action = menu.addAction("Edit model (enter case)")
        set_active_action = menu.addAction("Set active")
        menu.addSeparator()
        add_pose_action = menu.addAction("Add pose…")
        add_subcase_action = menu.addAction("Add subcase…")
        menu.addSeparator()
        rename_action = menu.addAction("Rename…")
        duplicate_action = menu.addAction("Duplicate…")
        delete_action = menu.addAction("Delete")
        delete_action.setEnabled(not is_only_root)
        action = menu.exec(global_pos)

        if action == edit_action:
            self.case_activated.emit(case_id)
        elif action == set_active_action:
            self.case_selected.emit(case_id)
        elif action == add_pose_action:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add pose", "Pose name:")
            if ok and name.strip():
                pose = self._service.workspace.create_pose(name.strip(), case_id=case_id)
                self.refresh()
                self.pose_selected.emit(pose.id)
        elif action == add_subcase_action:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add subcase", "Subcase name:")
            if ok and name.strip():
                self.fork_case(case_id, name.strip())
                self.refresh()
        elif action == rename_action:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Rename case", "New name:", text=case.name
            )
            if ok and name.strip():
                self._service.workspace.rename_case(case_id, name.strip())
                self.refresh()
        elif action == duplicate_action:
            default_name = f"{case.name} copy"
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Duplicate case", "New name:", text=default_name
            )
            if ok and name.strip():
                self._service.workspace.duplicate_case(case_id, new_name=name.strip())
                self.refresh()
        elif action == delete_action:
            extra = (f"This will also delete {n_descendants} subcase(s)."
                     if n_descendants else "")
            if self._confirm_delete("case", case.name, extra):
                try:
                    self._service.workspace.delete_case(case_id)
                except ValueError as exc:
                    self._show_error("Cannot delete case", str(exc))
                self.refresh()

    def _show_subcases_group_menu(self, global_pos: QtCore.QPoint, parent_case_id: str) -> None:
        menu = QtWidgets.QMenu(self)
        add_action = menu.addAction("Add subcase…")
        action = menu.exec(global_pos)
        if action == add_action:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add subcase", "Subcase name:")
            if ok and name.strip():
                self.fork_case(parent_case_id, name.strip())
                self.refresh()

    def _show_default_pose_menu(self, global_pos: QtCore.QPoint, pose_id: str) -> None:
        menu = QtWidgets.QMenu(self)
        enter_action = menu.addAction("Enter pose (read-only)")
        menu.addSeparator()
        add_analysis_action = menu.addAction("Add analysis…")
        action = menu.exec(global_pos)
        if action == enter_action:
            self.pose_selected.emit(pose_id)
        elif action == add_analysis_action:
            self._open_add_analysis_dialog(pose_id)

    def _show_pose_menu(self, global_pos: QtCore.QPoint, pose_id: str) -> None:
        ws = self._service._workspace
        pose = next(
            (p for case in (ws.cases.values() if ws else []) for p in case.poses if p.id == pose_id),
            None,
        )
        if pose is None:
            return
        owner_case = next(
            (c for c in ws.cases.values() if any(p.id == pose_id for p in c.poses)),
            None,
        )
        n_analyses = len([a for a in (owner_case.analyses if owner_case else [])
                          if a.pose_id == pose_id])

        menu = QtWidgets.QMenu(self)
        enter_action = menu.addAction("Enter pose")
        menu.addSeparator()
        add_analysis_action = menu.addAction("Add analysis…")
        menu.addSeparator()
        rename_action = menu.addAction("Rename…")
        duplicate_action = menu.addAction("Duplicate…")
        delete_action = menu.addAction("Delete")
        action = menu.exec(global_pos)

        if action == enter_action:
            self.pose_selected.emit(pose_id)
        elif action == add_analysis_action:
            self._open_add_analysis_dialog(pose_id)
        elif action == rename_action:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Rename pose", "New name:", text=pose.name
            )
            if ok and name.strip():
                try:
                    self._service.workspace.rename_pose(pose_id, name.strip())
                except ValueError as exc:
                    self._show_error("Cannot rename pose", str(exc))
                self.refresh()
        elif action == duplicate_action:
            default_name = f"{pose.name} copy"
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Duplicate pose", "New name:", text=default_name
            )
            if ok and name.strip():
                pose = self._service.duplicate_pose_in_case(pose_id, new_name=name.strip())
                self.refresh()
                self.pose_selected.emit(pose.id)
        elif action == delete_action:
            extra = (f"This will also delete {n_analyses} analysis(es) and their runs."
                     if n_analyses else "")
            if self._confirm_delete("pose", pose.name, extra):
                try:
                    self._service.workspace.delete_pose(pose_id, cascade=bool(n_analyses))
                except ValueError as exc:
                    self._show_error("Cannot delete pose", str(exc))
                self.refresh()

    def _show_analysis_menu(self, global_pos: QtCore.QPoint, analysis_id: str) -> None:
        ws = self._service._workspace
        analysis = next(
            (a for case in (ws.cases.values() if ws else []) for a in case.analyses if a.id == analysis_id),
            None,
        )
        if analysis is None:
            return
        menu = QtWidgets.QMenu(self)
        open_action = menu.addAction("Open")
        run_action = menu.addAction("▶  Run now")
        clear_action = menu.addAction("Clear results")
        clear_action.setEnabled(getattr(analysis, "status", "to_be_run") not in
                                {"to_be_run", "queued", "running"})
        menu.addSeparator()
        rename_action = menu.addAction("Rename…")
        duplicate_action = menu.addAction("Duplicate…")
        delete_action = menu.addAction("Delete")
        action = menu.exec(global_pos)

        if action == open_action:
            self.analysis_selected.emit(analysis_id)
        elif action == run_action:
            self.run_now_requested.emit(analysis_id)
        elif action == clear_action:
            # Reset the analysis' run state back to to_be_run (one run/analysis).
            self._service.delete_run(analysis_id)
            self.refresh()
        elif action == rename_action:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Rename analysis", "New name:", text=analysis.name
            )
            if ok and name.strip():
                self._service.workspace.rename_analysis(analysis_id, name.strip())
                self.refresh()
        elif action == duplicate_action:
            default_name = f"{analysis.name} copy"
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Duplicate analysis", "New name:", text=default_name
            )
            if ok and name.strip():
                self._service.duplicate_analysis(analysis_id, new_name=name.strip())
                self.refresh()
        elif action == delete_action:
            if self._confirm_delete("analysis", analysis.name):
                self._service.workspace.delete_analysis(analysis_id)
                self.refresh()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _open_add_analysis_dialog(self, pose_id: str | None) -> None:
        if not pose_id:
            return
        analysis_types = ["dynamic", "kinematic", "static", "equilibrium"]
        atype, ok1 = QtWidgets.QInputDialog.getItem(
            self, "Add analysis", "Analysis type:", analysis_types, 0, False
        )
        if not ok1:
            return
        name, ok2 = QtWidgets.QInputDialog.getText(
            self, "Add analysis", "Analysis name:", text=f"{atype.capitalize()} analysis"
        )
        if not (ok2 and name.strip()):
            return
        case_id = self._case_id_for_pose(pose_id)
        if not case_id:
            return
        analysis = self._service.workspace.create_analysis(
            name.strip(),
            analysis_type=atype,
            case_id=case_id,
            workspace_pose_id=pose_id,
        )
        self.refresh()
        self.analysis_selected.emit(analysis.id)

    def _case_id_for_pose(self, pose_id: str) -> str | None:
        ws = self._service._workspace
        if ws is None:
            return None
        # Prefer the active case when the same pose id exists in multiple
        # cases (defence-in-depth: ids should be unique, but legacy data
        # forked before the id-regeneration fix may still collide).
        active = ws.cases.get(ws.selected_case_id) if ws.selected_case_id else None
        if active is not None and any(p.id == pose_id for p in active.poses):
            return active.id
        for case in ws.cases.values():
            if any(p.id == pose_id for p in case.poses):
                return case.id
        return None
