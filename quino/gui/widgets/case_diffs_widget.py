"""Side panel showing a short, human-readable diff vs. the parent case.

Pure presentation: the heavy lifting (label resolution, value formatting,
composite-field decomposition) lives in :mod:`quino.services.case_diff`.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.gui.icons import get_icon
from quino.gui.theme import (
    BLUE_DARK,
    GREEN,
    INK_MUTED,
    INK_SUBTLE,
    ORANGE,
    RED,
)
from quino.services.case_diff import DiffEntry, diff_case_against


_KIND_COLORS = {
    "added": GREEN,
    "removed": RED,
    "changed": ORANGE,
}

_KIND_BADGE = {
    "added": "+",
    "removed": "−",
    "changed": "Δ",
}

_ENTITY_ICONS = {
    "Body": "body",
    "Joint": "revolute",
    "Marker": "marker",
    "Slider": "slider",
    "Driver": "rotate-driver",
    "Spring": "spring",
    "Load": "load-gravity",
    "Sensor": "sensor-distance",
    "BlockInstance": "block-instance",
}


def _ancestor_chain(ws, case_id: str) -> list:
    """Return [root, ..., parent] chain (excluding the case itself)."""
    chain: list = []
    current_id = ws.cases[case_id].parent_case_id if case_id in ws.cases else None
    while current_id is not None:
        case = ws.cases.get(current_id)
        if case is None:
            break
        chain.append(case)
        current_id = case.parent_case_id
    chain.reverse()
    return chain


class CaseDiffsWidget(QtWidgets.QWidget):
    """Compact, readable diff of the active case vs. its parent (or all ancestors)."""

    entity_selected = QtCore.Signal(str)

    def __init__(self, app_service: ApplicationService, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = app_service

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header = QtWidgets.QLabel("No active case")
        self._header.setContentsMargins(8, 6, 8, 4)
        self._header.setWordWrap(True)
        font = self._header.font()
        font.setPointSize(font.pointSize() + 1)
        self._header.setFont(font)
        layout.addWidget(self._header)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(8)
        self._scope_combo = QtWidgets.QComboBox()
        self._scope_combo.addItem("Direct parent", userData="parent")
        self._scope_combo.addItem("All ancestors", userData="ancestors")
        self._scope_combo.setToolTip("Choose what to compare against.")
        self._scope_combo.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(QtWidgets.QLabel("Compare with:"))
        toolbar.addWidget(self._scope_combo)
        self._visual_toggle = QtWidgets.QCheckBox("Show visual changes")
        self._visual_toggle.setToolTip(
            "Include purely visual changes (colour, line width, position, name)."
        )
        self._visual_toggle.toggled.connect(self.refresh)
        toolbar.addWidget(self._visual_toggle)
        toolbar.addStretch(1)
        self._refresh_btn = QtWidgets.QPushButton(get_icon("refresh", BLUE_DARK, size=16), "Refresh")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(self._refresh_btn)
        layout.addLayout(toolbar)

        # Empty-state placeholder, swapped with the tree as needed.
        self._stack = QtWidgets.QStackedWidget()
        layout.addWidget(self._stack, stretch=1)

        self._placeholder = QtWidgets.QLabel("No differences with parent")
        self._placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(f"color: {INK_SUBTLE}; font-size: 11pt;")
        self._stack.addWidget(self._placeholder)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels(["Property", "Parent", "This case"])
        self._tree.setColumnCount(3)
        header = self._tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._stack.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._tree.clear()
        ws = self._service._workspace
        if ws is None or not ws.selected_case_id:
            self._header.setText("No active case")
            self._show_placeholder("No active case")
            return
        case = ws.cases.get(ws.selected_case_id)
        if case is None:
            self._header.setText("No active case")
            self._show_placeholder("No active case")
            return
        if case.parent_case_id is None:
            self._header.setText(f"<b>{case.name}</b> — root case")
            self._show_placeholder("This is a root case — nothing to compare against.")
            return

        include_visual = self._visual_toggle.isChecked()
        scope = self._scope_combo.currentData()

        if scope == "ancestors":
            self._populate_ancestor_chain(ws, case, include_visual)
        else:
            parent = ws.cases.get(case.parent_case_id)
            if parent is None:
                self._show_placeholder("Parent case not found")
                return
            self._header.setText(f"<b>{case.name}</b> vs <b>{parent.name}</b>")
            diffs = diff_case_against(parent, case, include_visual=include_visual)
            if not diffs:
                self._show_placeholder("No differences with parent")
                return
            self._populate_section(self._tree.invisibleRootItem(), diffs)
            self._show_tree()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _show_placeholder(self, message: str) -> None:
        self._placeholder.setText(message)
        self._stack.setCurrentWidget(self._placeholder)

    def _show_tree(self) -> None:
        self._stack.setCurrentWidget(self._tree)

    def _populate_ancestor_chain(self, ws, case, include_visual: bool) -> None:
        chain = _ancestor_chain(ws, case.id) + [case]
        if len(chain) < 2:
            self._show_placeholder("No ancestors")
            return
        any_diff = False
        self._header.setText(f"<b>{case.name}</b> — diffs along {len(chain) - 1} ancestor step(s)")
        for parent_case, child_case in zip(chain, chain[1:]):
            diffs = diff_case_against(parent_case, child_case, include_visual=include_visual)
            section = QtWidgets.QTreeWidgetItem(
                [f"{parent_case.name}  →  {child_case.name}", "", ""]
            )
            section_font = section.font(0)
            section_font.setBold(True)
            section.setFont(0, section_font)
            section.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_MUTED)))
            self._tree.addTopLevelItem(section)
            if diffs:
                any_diff = True
                self._populate_section(section, diffs)
            else:
                empty = QtWidgets.QTreeWidgetItem(["No differences", "", ""])
                empty.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_SUBTLE)))
                section.addChild(empty)
            section.setExpanded(True)
        if not any_diff:
            self._tree.clear()
            self._show_placeholder("No differences in the ancestor chain")
        else:
            self._show_tree()

    def _populate_section(self, parent_item: QtWidgets.QTreeWidgetItem, diffs: list[DiffEntry]) -> None:
        # Group by entity.
        by_entity: dict[str, list[DiffEntry]] = {}
        order: list[str] = []
        for d in diffs:
            if d.entity_id not in by_entity:
                by_entity[d.entity_id] = []
                order.append(d.entity_id)
            by_entity[d.entity_id].append(d)

        for entity_id in order:
            entries = by_entity[entity_id]
            head = entries[0]
            # Top-level entity row.
            summary = self._summarise_entity(entries)
            entity_item = QtWidgets.QTreeWidgetItem([
                f"{head.entity_kind}: {head.entity_label}",
                summary,
                "",
            ])
            entity_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, entity_id)
            entity_font = entity_item.font(0)
            entity_font.setBold(True)
            entity_item.setFont(0, entity_font)
            icon_name = _ENTITY_ICONS.get(head.entity_kind)
            if icon_name is not None:
                entity_item.setIcon(0, get_icon(icon_name, INK_MUTED, size=14))
            entity_item.setForeground(1, QtGui.QBrush(QtGui.QColor(INK_MUTED)))
            parent_item.addChild(entity_item)

            for d in entries:
                if d.property_label is None:
                    # added / removed whole entity — already conveyed by the
                    # summary on the parent row; no extra child needed.
                    continue
                row = QtWidgets.QTreeWidgetItem([
                    f"{_KIND_BADGE['changed']}  {d.property_label}",
                    d.parent_text,
                    d.child_text,
                ])
                row.setData(0, QtCore.Qt.ItemDataRole.UserRole, entity_id)
                colour = QtGui.QColor(_KIND_COLORS.get(d.kind, INK_MUTED))
                row.setForeground(0, QtGui.QBrush(colour))
                row.setToolTip(0, f"{d.entity_kind} · {d.property_path}")
                entity_item.addChild(row)

            entity_item.setExpanded(True)

    def _summarise_entity(self, entries: list[DiffEntry]) -> str:
        head = entries[0]
        if any(e.kind == "added" and e.property_label is None for e in entries):
            return "added in this case"
        if any(e.kind == "removed" and e.property_label is None for e in entries):
            return "removed in this case"
        changed = [e for e in entries if e.kind == "changed"]
        if not changed:
            return ""
        if len(changed) == 1:
            return "1 change"
        return f"{len(changed)} changes"

    def _on_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        entity_id = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if isinstance(entity_id, str) and entity_id:
            self.entity_selected.emit(entity_id)
