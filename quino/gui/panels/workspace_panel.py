from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.workspace import Run, Study
from quino.gui.icons import get_icon


class WorkspacePanel(QtWidgets.QWidget):
    """Tree widget showing the workspace hierarchy: baselines, cases, case groups,
    studies and runs."""

    run_study_requested = QtCore.Signal(str)  # study_id

    def __init__(self, app_service: ApplicationService) -> None:
        super().__init__()
        self.app_service = app_service

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(4)
        self._new_btn = QtWidgets.QToolButton()
        self._new_btn.setText("New")
        self._new_btn.setIcon(get_icon("add", "#3d3d3d"))
        self._new_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._new_btn.clicked.connect(self._on_new)
        self._rename_btn = QtWidgets.QToolButton()
        self._rename_btn.setText("Rename")
        self._rename_btn.clicked.connect(self._on_rename)
        self._delete_btn = QtWidgets.QToolButton()
        self._delete_btn.setText("Delete")
        self._delete_btn.setIcon(get_icon("remove", "#8b2500"))
        self._delete_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._delete_btn.clicked.connect(self._on_delete)
        self._run_btn = QtWidgets.QToolButton()
        self._run_btn.setText("Run")
        self._run_btn.setIcon(get_icon("run-simulation", "#006400"))
        self._run_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._run_btn.clicked.connect(self._on_run)
        toolbar.addWidget(self._new_btn)
        toolbar.addWidget(self._rename_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addWidget(self._run_btn)
        toolbar.addStretch(1)
        outer.addLayout(toolbar)

        # Tree
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        self._tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        outer.addWidget(self._tree, stretch=1)

        # State
        self._item_map: dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._next_parent: QtWidgets.QTreeWidgetItem | None = None

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._tree.clear()
        self._item_map.clear()
        project = self.app_service.project
        if project is None:
            item = QtWidgets.QTreeWidgetItem(self._tree)
            item.setText(0, "No project loaded")
            item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            self._update_toolbar_state()
            return

        # Ensure workspace exists so user can always create items
        if project.workspace is None:
            project.workspace = self.app_service.workspace._ensure_workspace()

        ws = project.workspace

        # Baselines root (always visible)
        baseline_root = QtWidgets.QTreeWidgetItem(self._tree, ["Baselines"])
        baseline_root.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("root", "baselines"))
        for baseline in ws.baselines:
            item = QtWidgets.QTreeWidgetItem(baseline_root, [baseline.name])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("baseline", baseline.id))
            self._item_map[baseline.id] = item

        # Cases root (always visible)
        case_root = QtWidgets.QTreeWidgetItem(self._tree, ["Cases"])
        case_root.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("root", "cases"))
        for case in ws.cases:
            item = QtWidgets.QTreeWidgetItem(case_root, [case.name])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("case", case.id))
            self._item_map[case.id] = item

        # Case Groups root (always visible)
        cg_root = QtWidgets.QTreeWidgetItem(self._tree, ["Case Groups"])
        cg_root.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("root", "case_groups"))
        for cg in ws.case_groups:
            item = QtWidgets.QTreeWidgetItem(cg_root, [cg.name])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("case_group", cg.id))
            self._item_map[cg.id] = item

        # Studies root (always visible)
        study_root = QtWidgets.QTreeWidgetItem(self._tree, ["Studies"])
        study_root.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("root", "studies"))
        for study in ws.studies:
            study_item = QtWidgets.QTreeWidgetItem(study_root, [study.name])
            study_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("study", study.id))
            self._item_map[study.id] = study_item

            # Runs under study
            study_runs = [r for r in ws.runs if r.study_id == study.id]
            for run in study_runs:
                run_item = QtWidgets.QTreeWidgetItem(study_item, [f"Run {run.id} ({run.status})"])
                run_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("run", run.id))
                self._item_map[run.id] = run_item
                for entry in run.entries:
                    label = f"{entry.scope}: {entry.status}"
                    if entry.case_id:
                        label = f"Case {entry.case_id}: {entry.status}"
                    entry_item = QtWidgets.QTreeWidgetItem(run_item, [label])
                    entry_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, ("entry", entry.id))

        self._tree.expandAll()
        self._update_toolbar_state()

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _on_new(self) -> None:
        selected = self._selected_item()
        kind = ""
        if selected is not None:
            kind, _ = selected.data(0, QtCore.Qt.ItemDataRole.UserRole)
        # If nothing selected or a root selected, show a generic new dialog
        if not kind or kind == "root":
            options = ["Baseline", "Case", "Study"]
            choice, ok = QtWidgets.QInputDialog.getItem(
                self, "New Workspace Item", "Type:", options, 0, False
            )
            if not ok:
                return
            kind_map = {"Baseline": "baselines", "Case": "cases", "Study": "studies"}
            kind = kind_map.get(choice, choice.lower())
        if kind in ("root", "baselines", "baseline"):
            name, ok = QtWidgets.QInputDialog.getText(self, "New Baseline", "Name:")
            if ok and name:
                self.app_service.workspace.create_baseline(name)
                self.refresh()
        elif kind in ("root", "cases", "case"):
            name, ok = QtWidgets.QInputDialog.getText(self, "New Case", "Name:")
            if ok and name:
                self.app_service.workspace.create_case(name)
                self.refresh()
        elif kind in ("root", "studies", "study"):
            name, ok = QtWidgets.QInputDialog.getText(self, "New Study", "Name:")
            if ok and name:
                self.app_service.workspace.create_study(name)
                self.refresh()

    def _on_rename(self) -> None:
        selected = self._selected_item()
        if selected is None:
            return
        kind, obj_id = selected.data(0, QtCore.Qt.ItemDataRole.UserRole)
        current = selected.text(0)
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=current)
        if not ok or not name:
            return
        if kind == "baseline":
            self.app_service.workspace.rename_baseline(obj_id, name)
        elif kind == "case":
            self.app_service.workspace.rename_case(obj_id, name)
        elif kind == "case_group":
            self.app_service.workspace.rename_case_group(obj_id, name)
        elif kind == "study":
            self.app_service.workspace.rename_study(obj_id, name)
        self.refresh()

    def _on_delete(self) -> None:
        selected = self._selected_item()
        if selected is None:
            return
        kind, obj_id = selected.data(0, QtCore.Qt.ItemDataRole.UserRole)
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete", f"Delete {kind} '{selected.text(0)}'?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if kind == "baseline":
            self.app_service.workspace.delete_baseline(obj_id)
        elif kind == "case":
            self.app_service.workspace.delete_case(obj_id)
        elif kind == "case_group":
            self.app_service.workspace.delete_case_group(obj_id)
        elif kind == "study":
            self.app_service.workspace.delete_study(obj_id)
        self.refresh()

    def _on_run(self) -> None:
        selected = self._selected_item()
        if selected is None:
            return
        kind, obj_id = selected.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if kind == "study":
            self.run_study_requested.emit(obj_id)

    def _on_current_item_changed(self) -> None:
        self._update_toolbar_state()

    def _update_toolbar_state(self) -> None:
        selected = self._selected_item()
        has_selection = selected is not None
        kind = ""
        if has_selection:
            kind, _ = selected.data(0, QtCore.Qt.ItemDataRole.UserRole)
        self._new_btn.setEnabled(has_selection)
        self._rename_btn.setEnabled(has_selection and kind not in ("root", "run", "entry"))
        self._delete_btn.setEnabled(has_selection and kind not in ("root", "run", "entry"))
        self._run_btn.setEnabled(kind == "study")

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        kind, obj_id = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        menu = QtWidgets.QMenu(self)
        if kind == "baseline":
            menu.addAction("Rename", lambda: self._rename_item(kind, obj_id))
            menu.addAction("Delete", lambda: self._delete_item(kind, obj_id))
        elif kind == "case":
            menu.addAction("Rename", lambda: self._rename_item(kind, obj_id))
            menu.addAction("Delete", lambda: self._delete_item(kind, obj_id))
        elif kind == "study":
            menu.addAction("Run Study", lambda: self.run_study_requested.emit(obj_id))
            menu.addAction("Rename", lambda: self._rename_item(kind, obj_id))
            menu.addAction("Delete", lambda: self._delete_item(kind, obj_id))
        elif kind == "run":
            menu.addAction("Delete", lambda: self._delete_item(kind, obj_id))
        if not menu.isEmpty():
            menu.exec(self._tree.mapToGlobal(pos))

    def _rename_item(self, kind: str, obj_id: str) -> None:
        # Triggered from context menu; reuse toolbar logic via selection
        item = self._item_map.get(obj_id)
        if item:
            self._tree.setCurrentItem(item)
            self._on_rename()

    def _delete_item(self, kind: str, obj_id: str) -> None:
        item = self._item_map.get(obj_id)
        if item:
            self._tree.setCurrentItem(item)
            self._on_delete()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _selected_item(self) -> QtWidgets.QTreeWidgetItem | None:
        items = self._tree.selectedItems()
        return items[0] if items else None
