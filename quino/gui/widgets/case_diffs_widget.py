from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.gui.icons import get_icon
from quino.gui.theme import BLUE_DARK, INK_MUTED, INK_SUBTLE


_ENTITY_TYPE_LABELS = {
    "Body": "Body",
    "Marker": "Marker",
    "Joint": "Joint",
    "Slider": "Slider",
    "Driver": "Driver",
    "Load": "Load",
    "Sensor": "Sensor",
    "Spring": "Spring",
}

_KIND_COLORS = {
    "added":   "#25815f",
    "removed": "#b43a2f",
    "changed": "#2d74a7",
}

_KIND_LABELS = {
    "added":   "ADDED",
    "removed": "REMOVED",
    "changed": "CHANGED",
}


def _compute_diffs_for_pair(parent_case, child_case) -> list[dict]:
    """Return a flat list of diff records between parent_case and child_case."""
    from quino.services.case_overlay_validator import _entity_lookup

    diffs: list[dict] = []
    parent_index = _entity_lookup(parent_case)
    child_index = _entity_lookup(child_case)

    # Entities present in parent but missing in child
    for ent_id, (parent_ent, cls) in parent_index.items():
        if ent_id not in child_index:
            diffs.append({
                "kind": "removed",
                "entity_type": cls.__name__,
                "entity_id": ent_id,
                "entity_name": getattr(parent_ent, "name", ent_id),
                "field": None,
                "parent_value": None,
                "child_value": None,
            })
            continue
        child_ent, _ = child_index[ent_id]
        # Field-level diffs
        for field in cls.__dataclass_fields__:  # type: ignore[attr-defined]
            if field in ("id",):
                continue
            try:
                pv = getattr(parent_ent, field)
                cv = getattr(child_ent, field)
                if pv != cv:
                    diffs.append({
                        "kind": "changed",
                        "entity_type": cls.__name__,
                        "entity_id": ent_id,
                        "entity_name": getattr(parent_ent, "name", ent_id),
                        "field": field,
                        "parent_value": pv,
                        "child_value": cv,
                    })
            except Exception:
                pass

    # Entities only in child (added)
    for ent_id in child_index:
        if ent_id not in parent_index:
            child_ent, cls = child_index[ent_id]
            diffs.append({
                "kind": "added",
                "entity_type": cls.__name__,
                "entity_id": ent_id,
                "entity_name": getattr(child_ent, "name", ent_id),
                "field": None,
                "parent_value": None,
                "child_value": None,
            })

    return diffs


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
    """Shows entity-level diffs of the active case versus each ancestor up to the root case."""

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

        # Refresh button
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 0)
        self._refresh_btn = QtWidgets.QPushButton(get_icon("refresh", BLUE_DARK, size=16), "Refresh")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(self._refresh_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # Tree showing diffs
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels(["Entity / Field", "Parent value", "Case value"])
        self._tree.setColumnCount(3)
        self._tree.header().setStretchLastSection(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setExpandsOnDoubleClick(False)
        layout.addWidget(self._tree, stretch=1)

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._tree.clear()
        ws = self._service._workspace
        if ws is None or not ws.selected_case_id:
            self._header.setText("No active case")
            return

        case = ws.cases.get(ws.selected_case_id)
        if case is None:
            self._header.setText("No active case")
            return

        if case.parent_case_id is None:
            self._header.setText(f"<b>{case.name}</b> — root case (no parent)")
            self._tree.addTopLevelItem(
                QtWidgets.QTreeWidgetItem(["This is a root case", "", ""])
            )
            return

        self._header.setText(f"<b>{case.name}</b> — diffs vs ancestors")

        ancestors = _ancestor_chain(ws, case.id)
        # We compare each consecutive pair: root→…→parent→active
        pairs: list[tuple] = []
        chain_with_active = ancestors + [case]
        for i in range(len(chain_with_active) - 1):
            pairs.append((chain_with_active[i], chain_with_active[i + 1]))

        if not pairs:
            self._tree.addTopLevelItem(QtWidgets.QTreeWidgetItem(["No ancestor found", "", ""]))
            return

        for parent_case, child_case in pairs:
            section_label = f"{parent_case.name}  →  {child_case.name}"
            section_item = QtWidgets.QTreeWidgetItem([section_label, "", ""])
            section_font = section_item.font(0)
            section_font.setBold(True)
            section_item.setFont(0, section_font)
            section_item.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_MUTED)))

            try:
                diffs = _compute_diffs_for_pair(parent_case, child_case)
            except Exception as exc:
                err = QtWidgets.QTreeWidgetItem([f"Error computing diffs: {exc}", "", ""])
                err.setForeground(0, QtGui.QBrush(QtGui.QColor("#b43a2f")))
                section_item.addChild(err)
                self._tree.addTopLevelItem(section_item)
                section_item.setExpanded(True)
                continue

            if not diffs:
                no_diff = QtWidgets.QTreeWidgetItem(["No differences", "", ""])
                no_diff.setForeground(0, QtGui.QBrush(QtGui.QColor(INK_SUBTLE)))
                section_item.addChild(no_diff)
            else:
                # Group by entity
                by_entity: dict[str, list[dict]] = {}
                for diff in diffs:
                    key = f"{diff['entity_type']}:{diff['entity_id']}"
                    by_entity.setdefault(key, []).append(diff)

                for key, entity_diffs in by_entity.items():
                    first = entity_diffs[0]
                    entity_label = f"{first['entity_type']}: {first['entity_name']}"
                    entity_item = QtWidgets.QTreeWidgetItem([entity_label, "", ""])
                    entity_font = entity_item.font(0)
                    entity_font.setBold(True)
                    entity_item.setFont(0, entity_font)

                    for diff in entity_diffs:
                        kind = diff["kind"]
                        color = _KIND_COLORS.get(kind, "#888888")
                        badge = _KIND_LABELS.get(kind, kind.upper())
                        if diff["field"] is None:
                            # Added / removed whole entity
                            row = QtWidgets.QTreeWidgetItem([f"[{badge}]", "", ""])
                        else:
                            pv = str(diff["parent_value"]) if diff["parent_value"] is not None else "—"
                            cv = str(diff["child_value"]) if diff["child_value"] is not None else "—"
                            row = QtWidgets.QTreeWidgetItem([diff["field"], pv, cv])
                        row.setForeground(0, QtGui.QBrush(QtGui.QColor(color)))
                        row.setToolTip(0, f"[{badge}] {diff.get('field', '')}")
                        entity_item.addChild(row)

                    entity_item.setExpanded(True)
                    section_item.addChild(entity_item)

            section_item.setExpanded(True)
            self._tree.addTopLevelItem(section_item)

        self._tree.resizeColumnToContents(0)
        self._tree.resizeColumnToContents(1)
