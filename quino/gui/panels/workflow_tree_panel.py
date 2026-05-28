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

    def _overlay_has_unlinked_props(self, case: Case) -> bool:
        """True if any inherited entity has at least one unlinked cascadable property."""
        overlay = case.overlay
        if overlay is None:
            return False
        from quino.services.cascade_property_registry import cascadable_properties
        from quino.services.case_overlay_validator import _entity_lookup
        lookup = _entity_lookup(case)
        for ent_id, entry in overlay.entities.items():
            if entry.origin != "inherited":
                continue
            ent_info = lookup.get(ent_id)
            if ent_info is None:
                continue
            _ent, cls = ent_info
            try:
                full = set(cascadable_properties(cls))
            except ValueError:
                continue
            base_linked = {p.split(".", 1)[0] for p in entry.linked_properties}
            if not full.issubset(base_linked):
                return True
        return False

    def _case_badges(self, case: Case) -> tuple[str, str]:
        """Return (label_suffix, tooltip_extension) describing overlay state.

        ``★`` flags any local edit vs. parent (local entities, deleted-inherited,
        or unlinked properties). ``⚠ N`` shows divergence warnings count.
        """
        suffix_parts: list[str] = []
        tooltip_parts: list[str] = []
        overlay = getattr(case, "overlay", None)
        if overlay is not None:
            has_local_entity = any(e.origin == "local" for e in overlay.entities.values())
            has_deleted = bool(overlay.deleted_inherited_entity_ids)
            has_unlinked = self._overlay_has_unlinked_props(case)
            if has_local_entity or has_deleted or has_unlinked:
                suffix_parts.append("★")
                local_pieces = []
                if has_local_entity:
                    local_pieces.append("local entities")
                if has_deleted:
                    local_pieces.append("deleted inherited entities")
                if has_unlinked:
                    local_pieces.append("property overrides")
                tooltip_parts.append(f"Diverges from parent: {', '.join(local_pieces)}")
        warnings = case.metadata.get("divergence_warnings") if case.metadata else None
        if isinstance(warnings, list) and warnings:
            suffix_parts.append(f"⚠ {len(warnings)}")
            tooltip_parts.append(f"{len(warnings)} unresolved divergence warning(s)")
        suffix = ("  " + " ".join(suffix_parts)) if suffix_parts else ""
        tooltip = " · ".join(tooltip_parts)
        return suffix, tooltip

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

        # Compose overlay/divergence badges as a label suffix and tooltip extension.
        badge_suffix, badge_tooltip = self._case_badges(case)
        if badge_suffix:
            item.setText(0, f"{label_prefix}{case.name}{badge_suffix}")
        tooltip = f"{'Case' if is_root else 'Subcase'}: {case.name}"
        if is_active:
            tooltip += " (active)"
        if badge_tooltip:
            tooltip += f"\n{badge_tooltip}"
        item.setToolTip(0, tooltip)

        analyses_by_pose: dict[str | None, list] = {}
        for analysis in case.analyses:
            analyses_by_pose.setdefault(analysis.pose_id, []).append(analysis)
        runs_by_analysis: dict[str, list] = {}
        for run in case.runs:
            runs_by_analysis.setdefault(run.analysis_id, []).append(run)
        known_pose_ids = {p.id for p in case.poses}

        # --- Poses group (default first, then user poses) ---
        default_pose = next((p for p in case.poses if p.is_default), None)
        if default_pose is None:
            # Auto-create the reference pose if missing (workspaces saved before
            # the load-time migration was added).
            from quino.domain.workspace import create_default_pose
            pose_id = self._service.id_service.new("pose")
            default_pose = create_default_pose(pose_id)
            case.poses.insert(0, default_pose)
        non_default_poses = [p for p in case.poses if not p.is_default]
        total_poses = 1 + len(non_default_poses)
        poses_group = _group_item(
            f"Poses  ({total_poses})",
            "workspace-poses",
        )
        poses_group.setData(0, ROLE_NODE_KIND, "poses_group")
        poses_group.setData(0, ROLE_ID, case.id)

        dp_pose_id = default_pose.id if default_pose else None
        dp_label = f"{default_pose.name}  [reference]" if default_pose else "Reference  [reference]"
        dp_item = QtWidgets.QTreeWidgetItem([dp_label])
        dp_item.setIcon(0, get_icon("workspace-pose", INK_SUBTLE, size=16))
        dp_item.setData(0, ROLE_NODE_KIND, "default_pose")
        if dp_pose_id:
            dp_item.setData(0, ROLE_ID, dp_pose_id)
        dp_item.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_SUBTLE)))
        dp_item.setToolTip(0, "Reference pose — model in its reference configuration (read-only)")
        # Analyses hang directly off their parent pose (no intermediate
        # "Analyses" group node).
        dp_analyses = analyses_by_pose.get(dp_pose_id, []) if dp_pose_id else []
        for analysis in dp_analyses:
            dp_item.addChild(self._build_analysis_item(analysis, runs_by_analysis, ws))
        dp_item.setExpanded(True)
        poses_group.addChild(dp_item)

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
            if is_selected_pose:
                font = pose_item.font(0)
                font.setBold(True)
                pose_item.setFont(0, font)
                pose_item.setBackground(0, QtGui.QBrush(QtGui.QColor(BLUE_SOFT)))
            pose_item.setToolTip(0, f"Pose: {pose.name}")
            for analysis in pose_analyses:
                pose_item.addChild(self._build_analysis_item(analysis, runs_by_analysis, ws))
            pose_item.setExpanded(True)
            poses_group.addChild(pose_item)
        poses_group.setExpanded(True)
        item.addChild(poses_group)

        # --- Orphaned analyses (no pose / pose missing) ---
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

        # --- Subcases group (always shown) ---
        child_cases = [c for c in ws.cases.values() if c.parent_case_id == case.id]
        sub_group = _group_item(
            f"Subcases  ({len(child_cases)})" if child_cases else "Subcases",
            "workspace-subcase",
        )
        sub_group.setData(0, ROLE_NODE_KIND, "subcases_group")
        sub_group.setData(0, ROLE_ID, case.id)
        for child_case in child_cases:
            sub_group.addChild(self._build_case_item(child_case, ws))
        sub_group.setExpanded(bool(child_cases))
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
            icon_name, status_color = _RUN_STATUS_ICONS.get(status, ("run-simulation", "#888888"))
            label = f"{date_part}  [{status}]"
            if run.note:
                label += f"  {run.note}"
            r_item = QtWidgets.QTreeWidgetItem([label])
            r_item.setIcon(0, get_icon(icon_name, status_color, size=16))
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
        elif kind == "run":
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
        elif kind == "poses_group":
            self._show_poses_group_menu(global_pos, ent_id)
        elif kind == "subcases_group":
            self._show_subcases_group_menu(global_pos, ent_id)
        elif kind == "default_pose":
            self._show_default_pose_menu(global_pos, ent_id)
        elif kind == "pose":
            self._show_pose_menu(global_pos, ent_id)
        elif kind == "analysis":
            self._show_analysis_menu(global_pos, ent_id)
        elif kind == "run":
            self._show_run_menu(global_pos, ent_id)

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

    def _show_poses_group_menu(self, global_pos: QtCore.QPoint, case_id: str) -> None:
        menu = QtWidgets.QMenu(self)
        add_action = menu.addAction("Add pose…")
        action = menu.exec(global_pos)
        if action == add_action:
            name, ok = QtWidgets.QInputDialog.getText(self, "Add pose", "Pose name:")
            if ok and name.strip():
                pose = self._service.workspace.create_pose(name.strip(), case_id=case_id)
                self.refresh()
                self.pose_selected.emit(pose.id)

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
        menu.addSeparator()
        rename_action = menu.addAction("Rename…")
        duplicate_action = menu.addAction("Duplicate…")
        delete_action = menu.addAction("Delete")
        action = menu.exec(global_pos)

        if action == open_action:
            self.analysis_selected.emit(analysis_id)
        elif action == run_action:
            self.run_now_requested.emit(analysis_id)
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

    def _show_run_menu(self, global_pos: QtCore.QPoint, run_id: str) -> None:
        menu = QtWidgets.QMenu(self)
        open_action = menu.addAction("Open (view results)")
        rerun_action = menu.addAction("Re-run")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        action = menu.exec(global_pos)

        if action == open_action:
            self.run_selected.emit(run_id)
        elif action == rerun_action:
            self.rerun_requested.emit(run_id)
        elif action == delete_action:
            if self._confirm_delete("run", run_id):
                self._service.delete_run(run_id)
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
