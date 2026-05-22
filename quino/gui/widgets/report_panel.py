from __future__ import annotations

from PySide6 import QtWidgets


class ReportPanelWidget(QtWidgets.QTabWidget):
    def add_table_tab(self, name: str, headers: list[str], rows: list[list[str]]) -> None:
        table = QtWidgets.QTableWidget(len(rows), len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row):
                table.setItem(row_index, column_index, QtWidgets.QTableWidgetItem(str(cell)))
        table.resizeColumnsToContents()
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.addTab(table, name)

    def add_kv_tab(self, name: str, items: list[tuple[str, str]]) -> None:
        self.add_table_tab(name, ["Quantity", "Value"], [[key, value] for key, value in items])

    def clear_tabs(self) -> None:
        while self.count() > 0:
            self.removeTab(0)

    def replace_table_tab(self, name: str, headers: list[str], rows: list[list[str]]) -> None:
        for index in range(self.count()):
            if self.tabText(index) == name:
                self.removeTab(index)
                break
        self.add_table_tab(name, headers, rows)

    def replace_kv_tab(self, name: str, items: list[tuple[str, str]]) -> None:
        self.replace_table_tab(name, ["Quantity", "Value"], [[key, value] for key, value in items])
