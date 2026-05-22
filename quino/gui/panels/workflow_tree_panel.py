from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.workspace import Analysis, Case as _Case
from quino.gui.icons import get_icon
from quino.gui.tree_branches import tree_branch_stylesheet
from quino.services.batch_runner import (
    enqueue_baseline_analyses,
    enqueue_case_analyses,
    enqueue_workspace_analyses,
)
from quino.services.plot_renderer import load_artifact
from quino.services.run_export import export_matplotlib_script, export_run_csv, export_run_json


_BASE_TREE_STYLESHEET = (
    "QTreeWidget { background: #fbfcfd; alternate-background-color: #f4f6f9;"
    " border: 1px solid #d0d7de; }"
    " QTreeView::item { padding: 1px 0; }"
    " QTreeView::item:selected { background: #cfe1f5; color: #112746; }"
)


def _tree_stylesheet() -> str:
    return _BASE_TREE_STYLESHEET + tree_branch_stylesheet()

_USER_ROLE = int(QtCore.Qt.ItemDataRole.UserRole)
_OWNER_ROLE = _USER_ROLE + 1

_STATUS_COLORS = {
    "not_run": "#aaaaaa",
    "queued": "#6a6f7a",
    "ok": "#2a8c3f",
    "partial": "#9a6a00",
    "stale": "#c07000",
    "running": "#1a6ec2",
    "failed": "#c02020",
}


_DELTA_LABELS = {
    "bodies": "bodies",
    "markers": "markers",
    "sliders": "sliders",
    "joints": "joints",
    "drivers": "drivers",
    "springs": "springs",
    "springs_meta": "springs",
    "loads": "loads",
    "parameters": "params",
    "model": "blocks",
    "block_diagram": "blocks",
}


def _build_delta_summary(case: _Case) -> str:
    """Return compact category summary, e.g. '2 bodies, 1 driver (+1 added, -1 removed)'."""
    counts: dict[str, int] = {}
    for path in case.invariant_values:
        domain = path.split("/")[0]
        label = _DELTA_LABELS.get(domain, domain)
        counts[label] = counts.get(label, 0) + 1
    parts = [f"{v} {k}" for k, v in counts.items()]
    added_total = sum(len(v) for v in case.added_entities.values())
    removed_total = len(case.removed_entity_ids) + len(case.removed_connections)
    if added_total:
        parts.append(f"+{added_total} added")
    if removed_total:
        parts.append(f"-{removed_total} removed")
    return ", ".join(parts)


def _badge_string(case: _Case) -> str:
    """Compact +N -M ~K  P:p A:a B:b badge tail used in node labels."""
    added = sum(len(v) for v in case.added_entities.values())
    removed = len(case.removed_entity_ids) + len(case.removed_connections)
    overrides = len(case.invariant_values) + sum(
        len(refs) for refs in case.reference_overrides.values()
    )
    parts: list[str] = []
    if added:
        parts.append(f"+{added}")
    if removed:
        parts.append(f"-{removed}")
    if overrides:
        parts.append(f"~{overrides}")
    return "  " + " ".join(parts) if parts else ""


class WorkflowTreePanel(QtWidgets.QWidget):
    working_context_changed = QtCore.Signal()
    run_analysis_requested = QtCore.Signal(str)  # analysis_id
    pose_selected = QtCore.Signal(str)           # pose_id
    analysis_selected = QtCore.Signal(str)       # analysis_id
    run_selected = QtCore.Signal(str)            # run_id
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
        self._tree.setIndentation(18)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setIconSize(QtCore.QSize(16, 16))
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        # Inventor-style branch lines: the disclosure carets are replaced by
        # explicit guide-line glyphs so parent/child relationships read at a
        # glance. Vertical guides + L/T connectors are drawn by Qt via the
        # QTreeView::branch substyles.
        self._tree.setStyleSheet(_tree_stylesheet())
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
            item.setText(0, "No workspace loaded.\nOpen or create a project to begin.")
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(0, QtGui.QBrush(QtGui.QColor("#888888")))
            self._update_badge()
            return

        ws = project.workspace
        for baseline in ws.baselines:
            # Plain name only — the type icon already conveys what kind of
            # node this is (Inventor-style browser).
            b_item = self._make_item(baseline.id, "baseline", baseline.name)
            self._style_node(b_item, "baseline")
            self._item_map[baseline.id] = b_item
            self._tree.addTopLevelItem(b_item)
            # Subgroups under baseline (no diffs section: baseline holds no overrides)
            self._populate_scope_groups(b_item, baseline_id=baseline.id, case_id=None)
            self._populate_child_cases(b_item, parent_case_id=None, baseline_id=baseline.id)

        if not ws.baselines:
            placeholder = QtWidgets.QTreeWidgetItem(self._tree)
            placeholder.setText(
                0,
                "No baselines yet.\nRight-click here to add the first baseline.",
            )
            placeholder.setFlags(placeholder.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            placeholder.setForeground(0, QtGui.QBrush(QtGui.QColor("#888888")))

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
            # Plain name only: icon disambiguates case vs subcase.
            c_item = self._make_item(case.id, "case", case.name)
            # Subcases get a distinct glyph (hollow diamond) over top cases.
            if parent_case_id:
                c_item.setIcon(0, get_icon("workspace-subcase", size=16))
            self._style_node(c_item, "subcase" if parent_case_id else "case")
            summary = _build_delta_summary(case)
            if summary:
                c_item.setToolTip(0, summary)
            self._item_map[case.id] = c_item
            parent_item.addChild(c_item)
            self._populate_scope_groups(c_item, case_id=case.id, baseline_id=baseline_id, case=case)
            self._populate_child_cases(c_item, parent_case_id=case.id, baseline_id=baseline_id)

    def _populate_scope_groups(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
        case: _Case | None = None,
    ) -> None:
        """Insert non-selectable subgroup nodes under a baseline or case
        (Diffs / Poses / Analyses / Blocks). Empty groups are omitted to
        keep the tree compact."""
        ws = self.app_service.project.workspace
        # Diffs subgroup: only meaningful for cases.
        if case is not None:
            additions = sum(len(v) for v in case.added_entities.values())
            removals = len(case.removed_entity_ids) + len(case.removed_connections)
            overrides = len(case.invariant_values) + sum(
                len(refs) for refs in case.reference_overrides.values()
            )
            if additions or removals or overrides:
                diffs_node = QtWidgets.QTreeWidgetItem(
                    [f"Diffs  (+{additions}  -{removals}  ~{overrides})"]
                )
                diffs_node.setFlags(diffs_node.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
                font = diffs_node.font(0)
                font.setItalic(True)
                diffs_node.setFont(0, font)
                diffs_node.setForeground(0, QtGui.QBrush(QtGui.QColor("#888888")))
                diffs_node.setIcon(0, get_icon("workspace-diffs", size=16))
                parent_item.addChild(diffs_node)

        # Poses subgroup. For case scope, match by case_id only (baseline_id
        # on a case-scoped pose may be None, since the case owns the link).
        if case_id is not None:
            poses = [p for p in ws.poses if p.case_id == case_id]
        else:
            poses = [p for p in ws.poses if p.case_id is None and p.baseline_id == baseline_id]
        if poses:
            poses_node = QtWidgets.QTreeWidgetItem([f"Poses  ({len(poses)})"])
            poses_node.setFlags(poses_node.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            poses_node.setForeground(0, QtGui.QBrush(QtGui.QColor("#666666")))
            poses_node.setIcon(0, get_icon("workspace-poses", size=16))
            parent_item.addChild(poses_node)
            self._populate_poses(poses_node, baseline_id=baseline_id, case_id=case_id)

        # No standalone "Analyses" subgroup: every analysis hangs off the
        # pose it was created against and shows up under that pose via
        # _populate_poses. Dropping the duplicate listing keeps the tree
        # compact and unambiguous.

        # Blocks subgroup: only for cases that added blocks; for baseline,
        # blocks live in project.model and are handled in the model tree.
        if case is not None:
            block_adds = case.added_entities.get("blocks", [])
            if block_adds:
                blocks_node = QtWidgets.QTreeWidgetItem([f"Blocks  ({len(block_adds)})"])
                blocks_node.setFlags(blocks_node.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
                blocks_node.setForeground(0, QtGui.QBrush(QtGui.QColor("#666666")))
                blocks_node.setIcon(0, get_icon("workspace-blocks", size=16))
                parent_item.addChild(blocks_node)
                for ent in block_adds:
                    bid = ent.get("id") or ent.get("instance_id") or "?"
                    btype = ent.get("block_type", "block")
                    blk_item = self._make_item(bid, "block", f"{bid}  [{btype}]")
                    self._item_map[bid] = blk_item
                    blocks_node.addChild(blk_item)

    def _scope_counts(self, *, baseline_id: str | None, case_id: str | None) -> str:
        """Return a compact 'P:p A:a' badge tail for a baseline/case scope."""
        ws = self.app_service.project.workspace
        if case_id is not None:
            poses = sum(1 for p in ws.poses if p.case_id == case_id)
            analyses = sum(1 for a in ws.analyses if a.case_id == case_id)
        else:
            poses = sum(1 for p in ws.poses if p.case_id is None and p.baseline_id == baseline_id)
            analyses = sum(1 for a in ws.analyses if a.case_id is None and a.baseline_id == baseline_id)
        parts: list[str] = []
        if poses:
            parts.append(f"P:{poses}")
        if analyses:
            parts.append(f"A:{analyses}")
        return "  " + " ".join(parts) if parts else ""

    def _style_node(self, item: QtWidgets.QTreeWidgetItem, kind: str) -> None:
        """Apply a consistent foreground/font per node kind so baseline,
        case and subcase are visually distinguishable at a glance."""
        font = item.font(0)
        if kind == "baseline":
            font.setBold(True)
            item.setForeground(0, QtGui.QBrush(QtGui.QColor("#1a3a6e")))
        elif kind == "case":
            font.setBold(True)
            item.setForeground(0, QtGui.QBrush(QtGui.QColor("#214d8a")))
        elif kind == "subcase":
            font.setBold(False)
            item.setForeground(0, QtGui.QBrush(QtGui.QColor("#3a6aaa")))
        item.setFont(0, font)

    def _populate_poses(
        self,
        parent_item: QtWidgets.QTreeWidgetItem,
        *,
        baseline_id: str | None = None,
        case_id: str | None = None,
    ) -> None:
        ws = self.app_service.project.workspace
        if case_id is not None:
            poses = [p for p in ws.poses if p.case_id == case_id]
        else:
            poses = [p for p in ws.poses if p.case_id is None and p.baseline_id == baseline_id]
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

        runs = sorted(
            (r for r in ws.runs if r.analysis_id == analysis.id),
            key=lambda r: r.created_at,
            reverse=True,
        )
        for run in runs:
            prefix = ""
            if run.status == "running":
                prefix = "⏳ "
            elif run.status == "queued":
                prefix = "⋯ "
            label = f"{prefix}Run {run.created_at[:16].replace('T', ' ')}  {run.status}"
            if run.note:
                label += f"  · {run.note}"
            run_item = self._make_item(run.id, "run", label)
            run_item.setForeground(0, QtGui.QBrush(QtGui.QColor(_STATUS_COLORS.get(run.status, "#aaaaaa"))))
            a_item.addChild(run_item)

    _ITEM_ICONS = {
        "baseline": "workspace-baseline",
        "case": "workspace-case",
        "subcase": "workspace-subcase",
        "pose": "workspace-pose",
        "analysis": "workspace-analysis",
        "run": "workspace-analysis",
        "block": "block-instance",
    }

    def _make_item(self, obj_id: str, kind: str, text: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([text])
        item.setData(0, _USER_ROLE, (kind, obj_id))
        # Attach an Inventor-style type icon. Subcases get a distinct glyph
        # vs. top-level cases — caller passes "subcase" explicitly.
        icon_name = self._ITEM_ICONS.get(kind)
        if icon_name:
            item.setIcon(0, get_icon(icon_name, size=16))
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
        self._badge.setText("Working: " + self._build_breadcrumb(ws))

    def _build_breadcrumb(self, ws) -> str:
        parts: list[str] = []
        # Resolve baseline either from the active context or, when only a
        # case is active, from the case's baseline_id chain.
        baseline_id = ws.active_baseline_id
        if ws.active_case_id is not None and baseline_id is None:
            case = next((c for c in ws.cases if c.id == ws.active_case_id), None)
            if case is not None:
                baseline_id = case.baseline_id
        baseline = next((b for b in ws.baselines if b.id == baseline_id), None)
        if baseline is not None:
            parts.append(baseline.name)
        if ws.active_case_id is not None:
            chain = self._case_chain_names(ws, ws.active_case_id)
            parts.extend(chain)
        return " / ".join(parts) if parts else "—"

    def _case_chain_names(self, ws, case_id: str) -> list[str]:
        by_id = {c.id: c for c in ws.cases}
        chain: list[str] = []
        current = by_id.get(case_id)
        while current is not None:
            chain.append(current.name)
            current = by_id.get(current.parent_case_id) if current.parent_case_id else None
        chain.reverse()
        return chain

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
        if kind == "run":
            self.run_selected.emit(obj_id)
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
            menu.addSeparator()
            menu.addAction("Run All Analyses", self._action_run_workspace_analyses)
        else:
            data = item.data(0, _USER_ROLE)
            if data is None:
                return
            kind, obj_id = data
            if kind == "baseline":
                menu.addAction("Add Subcase", lambda: self._action_add_case(baseline_id=obj_id))
                menu.addAction("Add Pose", lambda: self._action_add_pose(baseline_id=obj_id))
                menu.addAction("Run All Analyses In Scope", lambda: self._action_run_baseline_analyses(obj_id))
                # Analyses hang off poses — added from the pose context menu.
                menu.addSeparator()
                menu.addAction("Set As Working Context", lambda: self._action_set_working(baseline_id=obj_id))
                menu.addSeparator()
                menu.addAction("Rename", lambda: self._action_rename(kind, obj_id))
                menu.addAction("Delete", lambda: self._delete_item(kind, obj_id, item.text(0)))
            elif kind == "case":
                menu.addAction("Add Subcase", lambda: self._action_add_case(parent_case_id=obj_id))
                menu.addAction("Add Pose", lambda: self._action_add_pose(case_id=obj_id))
                menu.addAction("Run All Analyses In Scope", lambda: self._action_run_case_analyses(obj_id))
                # Analyses hang off poses — added from the pose context menu.
                menu.addSeparator()
                menu.addAction("Set As Working Context", lambda: self._action_set_working(case_id=obj_id))
                menu.addSeparator()
                menu.addAction("Duplicate Case", lambda: self._action_duplicate_case(obj_id))
                menu.addAction("Rename", lambda: self._action_rename(kind, obj_id))
                menu.addAction("Delete", lambda: self._delete_item(kind, obj_id, item.text(0)))
                menu.addSeparator()
                menu.addAction("Expand All Below", lambda: self._set_subtree_expanded(item, True))
                menu.addAction("Collapse All Below", lambda: self._set_subtree_expanded(item, False))
            elif kind == "pose":
                ws = self.app_service.project.workspace
                pose = next((p for p in ws.poses if p.id == obj_id), None)
                # Add Analysis under this specific pose. We propagate the
                # pose's owning scope so the new analysis can be filtered by
                # case/baseline (it still hangs under the pose in the tree).
                menu.addAction(
                    "Add Analysis",
                    lambda: self._action_add_analysis_to_pose(obj_id),
                )
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
            elif kind == "run":
                for action in self._build_run_context_menu(obj_id):
                    menu.addAction(action)
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

    def _action_run_case_analyses(self, case_id: str) -> None:
        enqueue_case_analyses(self.app_service, case_id)
        self.refresh()

    def _action_run_baseline_analyses(self, baseline_id: str) -> None:
        enqueue_baseline_analyses(self.app_service, baseline_id)
        self.refresh()

    def _action_run_workspace_analyses(self) -> None:
        enqueue_workspace_analyses(self.app_service)
        self.refresh()

    def _action_duplicate_case(self, case_id: str) -> None:
        try:
            self.app_service.workspace.duplicate_case(case_id)
        except Exception as exc:  # pragma: no cover - UI feedback
            QtWidgets.QMessageBox.warning(self, "Duplicate failed", str(exc))
            return
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
        from quino.gui.dialogs.new_analysis_dialog import NewAnalysisDialog

        ws = self.app_service.project.workspace
        if ws is None:
            return
        # Build poses list for the dialog
        if pose_id is not None:
            poses = [(pose_id, next((p.name for p in ws.poses if p.id == pose_id), pose_id))]
        elif case_id is not None:
            poses = [(p.id, p.name) for p in ws.poses if p.case_id == case_id]
        else:
            poses = [(p.id, p.name) for p in ws.poses if p.baseline_id == baseline_id and p.case_id is None]
        if not poses:
            QtWidgets.QMessageBox.warning(
                self, "No poses", "Cannot create analysis: no poses exist for this scope."
            )
            return
        dialog = NewAnalysisDialog(poses=poses, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        self.app_service.workspace.create_analysis(
            dialog.selected_name(),
            analysis_type=dialog.selected_type(),
            baseline_id=baseline_id,
            case_id=case_id,
            workspace_pose_id=dialog.selected_pose_id(),
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
        # Read the logical name straight from the workspace object so the
        # prefilled value never contains tree decorations (glyphs, badges,
        # "P:1 A:2", etc.). Reusing item.text(0) would persist the whole
        # decorated label and add the prefix on every subsequent rename.
        current = self._logical_name(kind, obj_id)
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=current)
        if not ok or not name.strip():
            return
        name = name.strip()
        if kind == "baseline":
            self.app_service.workspace.rename_baseline(obj_id, name)
        elif kind == "case":
            self.app_service.workspace.rename_case(obj_id, name)
        elif kind == "pose":
            self.app_service.workspace.rename_pose(obj_id, name)
        elif kind == "analysis":
            self.app_service.workspace.rename_analysis(obj_id, name)
        self.refresh()

    def _logical_name(self, kind: str, obj_id: str) -> str:
        """Return the persisted (undecorated) name of a workspace object."""
        project = self.app_service.project
        if project is None or project.workspace is None:
            return ""
        ws = project.workspace
        if kind == "baseline":
            obj = next((b for b in ws.baselines if b.id == obj_id), None)
        elif kind == "case":
            obj = next((c for c in ws.cases if c.id == obj_id), None)
        elif kind == "pose":
            obj = next((p for p in ws.poses if p.id == obj_id), None)
        elif kind == "analysis":
            obj = next((a for a in ws.analyses if a.id == obj_id), None)
        else:
            obj = None
        return getattr(obj, "name", "") if obj is not None else ""

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
        elif kind == "run":
            from quino.services.run_invalidation import delete_run
            project_dir = getattr(self.app_service, "current_project_path", None)
            if project_dir is not None:
                from pathlib import Path
                project_dir = Path(project_dir).parent if Path(project_dir).is_file() else Path(project_dir)
            delete_run(self.app_service.project.workspace, project_dir, obj_id)
        self.refresh()

    def _build_run_context_menu(self, run_id: str) -> list[QtGui.QAction]:
        actions: list[QtGui.QAction] = []
        actions.append(QtGui.QAction("Run with same config", self, triggered=lambda: self._rerun_analysis_for_run(run_id)))
        actions.append(QtGui.QAction("Rename", self, triggered=lambda: self._rename_run(run_id)))
        actions.append(QtGui.QAction("Add note", self, triggered=lambda: self._edit_run_note(run_id)))
        actions.append(QtGui.QAction("Open artefact folder", self, triggered=lambda: self._open_run_artifact_folder(run_id)))
        actions.append(QtGui.QAction("Export CSV (wide)", self, triggered=lambda: self._export_run_action(run_id, "csv_wide")))
        actions.append(QtGui.QAction("Export CSV (per sensor)", self, triggered=lambda: self._export_run_action(run_id, "csv_per_sensor")))
        actions.append(QtGui.QAction("Export JSON", self, triggered=lambda: self._export_run_action(run_id, "json")))
        actions.append(QtGui.QAction("Export matplotlib script", self, triggered=lambda: self._export_run_action(run_id, "matplotlib")))
        actions.append(QtGui.QAction("Delete Run", self, triggered=lambda: self._delete_item("run", run_id, run_id)))
        return actions

    def _find_run(self, run_id: str):
        project = self.app_service.project
        if project is None or project.workspace is None:
            return None
        return next((run for run in project.workspace.runs if run.id == run_id), None)

    def _rerun_analysis_for_run(self, run_id: str) -> None:
        run = self._find_run(run_id)
        if run is None:
            return
        self.app_service.ensure_executor().enqueue(run.analysis_id)
        self.refresh()

    def _rename_run(self, run_id: str) -> None:
        run = self._find_run(run_id)
        if run is None:
            return
        text, ok = QtWidgets.QInputDialog.getText(self, "Rename Run", "Label / note:", text=run.note or run.id)
        if not ok:
            return
        run.note = text.strip()
        self.refresh()

    def _edit_run_note(self, run_id: str) -> None:
        run = self._find_run(run_id)
        if run is None:
            return
        text, ok = QtWidgets.QInputDialog.getText(self, "Run Note", "Note:", text=run.note)
        if not ok:
            return
        run.note = text.strip()
        self.refresh()

    def _open_run_artifact_folder(self, run_id: str) -> None:
        run = self._find_run(run_id)
        project_dir = self.app_service.current_project_dir
        if run is None or run.result_ref is None or project_dir is None:
            return
        folder = (project_dir / run.result_ref.artifact_path).parent
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    def _export_run_action(self, run_id: str, kind: str) -> None:
        run = self._find_run(run_id)
        project = self.app_service.project
        if run is None or project is None:
            return
        artifact = load_artifact(self.app_service.current_project_dir, run)
        if not artifact:
            QtWidgets.QMessageBox.information(self, "No artefact", "This run has no persisted artefact.")
            return
        if kind == "csv_wide":
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export CSV", f"{run.id}.csv", "CSV Files (*.csv)")
            if path:
                export_run_csv(run, artifact, Path(path), mode="wide")
            return
        if kind == "csv_per_sensor":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Export per-sensor CSV")
            if path:
                export_run_csv(run, artifact, Path(path), mode="per_sensor")
            return
        if kind == "json":
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export JSON", f"{run.id}.json", "JSON Files (*.json)")
            if path:
                export_run_json(run, artifact, Path(path))
            return
        if kind == "matplotlib":
            analysis = next((item for item in project.workspace.analyses if item.id == run.analysis_id), None)
            if analysis is None or not getattr(analysis.config, "plots", []):
                QtWidgets.QMessageBox.information(self, "No plots", "This analysis has no saved plot definitions.")
                return
            plot_def = analysis.config.plots[0]
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export matplotlib script", f"{run.id}_{plot_def.id}.py", "Python Files (*.py)")
            if path:
                export_matplotlib_script(plot_def, artifact, Path(path))
