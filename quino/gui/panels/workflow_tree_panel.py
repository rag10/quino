from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from quino.application.service import ApplicationService
from quino.domain.workspace import Case

ROLE_NODE_KIND = QtCore.Qt.ItemDataRole.UserRole
ROLE_ID = QtCore.Qt.ItemDataRole.UserRole + 1


class WorkflowTreePanel(QtWidgets.QWidget):
    case_selected = QtCore.Signal(str)
    pose_selected = QtCore.Signal(str)
    analysis_selected = QtCore.Signal(str)
    run_selected = QtCore.Signal(str)

    def __init__(self, app_service: ApplicationService, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = app_service
        layout = QtWidgets.QVBoxLayout(self)
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels(["Workspace"])
        self._tree.itemClicked.connect(self._on_item_clicked)
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
                item = self._build_case_item(root_case)
                self._tree.addTopLevelItem(item)

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
    # Internal tree builders
    # ------------------------------------------------------------------

    def _build_case_item(self, case: Case) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([case.name])
        item.setData(0, ROLE_NODE_KIND, "case")
        item.setData(0, ROLE_ID, case.id)

        poses_node = QtWidgets.QTreeWidgetItem([f"Poses ({len(case.poses)})"])
        poses_node.setData(0, ROLE_NODE_KIND, "poses_group")
        for pose in case.poses:
            pose_item = QtWidgets.QTreeWidgetItem([pose.name])
            pose_item.setData(0, ROLE_NODE_KIND, "pose")
            pose_item.setData(0, ROLE_ID, pose.id)
            poses_node.addChild(pose_item)
        item.addChild(poses_node)

        analyses_node = QtWidgets.QTreeWidgetItem([f"Analyses ({len(case.analyses)})"])
        analyses_node.setData(0, ROLE_NODE_KIND, "analyses_group")
        for analysis in case.analyses:
            a_item = QtWidgets.QTreeWidgetItem([analysis.name])
            a_item.setData(0, ROLE_NODE_KIND, "analysis")
            a_item.setData(0, ROLE_ID, analysis.id)
            analyses_node.addChild(a_item)
        item.addChild(analyses_node)

        runs_node = QtWidgets.QTreeWidgetItem([f"Runs ({len(case.runs)})"])
        runs_node.setData(0, ROLE_NODE_KIND, "runs_group")
        for run in case.runs:
            label = f"{run.analysis_id} / {run.created_at[:10]} {run.status}"
            r_item = QtWidgets.QTreeWidgetItem([label])
            r_item.setData(0, ROLE_NODE_KIND, "run")
            r_item.setData(0, ROLE_ID, run.id)
            runs_node.addChild(r_item)
        item.addChild(runs_node)

        children_node = QtWidgets.QTreeWidgetItem(["Child cases"])
        children_node.setData(0, ROLE_NODE_KIND, "children_group")
        ws = self._service._workspace
        if ws is not None:
            for cid, child_case in ws.cases.items():
                if child_case.parent_case_id == case.id:
                    children_node.addChild(self._build_case_item(child_case))
        item.addChild(children_node)
        return item

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, ROLE_NODE_KIND)
        ent_id = item.data(0, ROLE_ID)
        if kind == "case" and ent_id:
            self.case_selected.emit(ent_id)
        elif kind == "pose" and ent_id:
            self.pose_selected.emit(ent_id)
        elif kind == "analysis" and ent_id:
            self.analysis_selected.emit(ent_id)
        elif kind == "run" and ent_id:
            self.run_selected.emit(ent_id)

    def contextMenuEvent(self, event) -> None:
        item = self._tree.itemAt(self._tree.viewport().mapFrom(self, event.pos()))
        if item is None:
            return
        kind = item.data(0, ROLE_NODE_KIND)
        case_id = item.data(0, ROLE_ID)
        if kind != "case" or not case_id:
            return
        menu = QtWidgets.QMenu(self)
        fork_action = menu.addAction("Fork case…")
        rename_action = menu.addAction("Rename…")
        delete_action = menu.addAction("Delete")
        action = menu.exec(event.globalPos())
        if action == fork_action:
            name, ok = QtWidgets.QInputDialog.getText(self, "Fork case", "New case name:")
            if ok and name.strip():
                self.fork_case(case_id, name.strip())
                self.refresh()
        elif action == rename_action:
            ws = self._service._workspace
            current_name = ws.cases[case_id].name if ws and case_id in ws.cases else ""
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Rename case", "New name:", text=current_name
            )
            if ok and name.strip():
                self.rename_case(case_id, name.strip())
                self.refresh()
        elif action == delete_action:
            self.delete_case(case_id)
            self.refresh()
