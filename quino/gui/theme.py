from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

INK = "#17212b"
INK_MUTED = "#66727e"
INK_SUBTLE = "#81909f"
SURFACE = "#f4f7fa"
SURFACE_PANEL = "#ffffff"
SURFACE_PANEL_ALT = "#fbfdff"
SURFACE_RAISED = "#eef4f8"
BORDER = "#cbd6e2"
BORDER_STRONG = "#aebdcb"
BLUE = "#2d74a7"
BLUE_DARK = "#174462"
BLUE_SOFT = "#d9ebf7"
ORANGE = "#c76f1f"
ORANGE_SOFT = "#fff1e2"
GREEN = "#25815f"
GREEN_SOFT = "#e7f4ee"
VIOLET = "#7059a6"
RED = "#b43a2f"
RED_SOFT = "#fdecea"


APP_QSS = f"""
QMainWindow {{
    background: {SURFACE};
}}

QWidget {{
    color: {INK};
    font-size: 12px;
}}

QMenuBar {{
    background: #ffffff;
    border-bottom: 1px solid {BORDER};
    padding: 1px 6px;
}}

QMenuBar::item {{
    background: transparent;
    padding: 4px 9px;
    border-radius: 3px;
}}

QMenuBar::item:selected {{
    background: {BLUE_SOFT};
    color: {BLUE_DARK};
}}

QMenu {{
    background: #ffffff;
    border: 1px solid {BORDER_STRONG};
    padding: 4px;
}}

QMenu::item {{
    padding: 5px 28px 5px 24px;
    border-radius: 3px;
}}

QMenu::item:selected {{
    background: {BLUE_SOFT};
    color: {BLUE_DARK};
}}

QToolBar {{
    background: #ffffff;
    border: none;
    border-bottom: 1px solid {BORDER};
    spacing: 4px;
    padding: 3px 6px 2px 6px;
}}

QToolBar::separator {{
    background: {BORDER};
    width: 1px;
    margin: 6px 5px;
}}

QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 2px 4px;
    color: {INK};
}}

QToolButton:hover {{
    background: #edf5fb;
    border-color: #c5dced;
}}

QToolButton:pressed {{
    background: #cfe4f3;
    border-color: #92bedc;
}}

QToolButton:checked {{
    background: {BLUE_SOFT};
    border-color: #92bedc;
    color: {BLUE_DARK};
}}

QToolButton:disabled {{
    color: #98a6b3;
    background: transparent;
}}

QPushButton {{
    background: #ffffff;
    border: 1px solid {BORDER_STRONG};
    border-radius: 3px;
    padding: 4px 10px;
    min-height: 20px;
}}

QPushButton:hover {{
    background: #edf5fb;
    border-color: #9fc4dc;
}}

QPushButton:pressed {{
    background: {BLUE_SOFT};
}}

QPushButton:disabled {{
    color: #98a6b3;
    background: #f1f5f8;
}}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #ffffff;
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 3px 5px;
    selection-background-color: {BLUE_SOFT};
    selection-color: {BLUE_DARK};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: #7fb4d8;
}}

QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: #f1f5f8;
    color: {INK_MUTED};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: #ffffff;
}}

QTabBar::tab {{
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 5px 10px;
    min-height: 18px;
    color: {INK_MUTED};
}}

QTabBar::tab:selected {{
    background: #ffffff;
    color: {BLUE_DARK};
    border-top: 2px solid {BLUE};
}}

QHeaderView::section {{
    background: {SURFACE_RAISED};
    color: {INK_MUTED};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 4px 6px;
    font-weight: 600;
}}

QTreeWidget, QTableWidget, QListWidget {{
    background: {SURFACE_PANEL_ALT};
    alternate-background-color: #f4f7fa;
    border: 1px solid {BORDER};
    outline: none;
}}

QTreeWidget::item, QListWidget::item {{
    min-height: 22px;
    padding: 2px 4px;
    border-radius: 3px;
}}

QTreeWidget::item:hover, QListWidget::item:hover {{
    background: #edf5fb;
}}

QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {BLUE_SOFT};
    color: {BLUE_DARK};
}}

QTableWidget::item {{
    padding: 3px 5px;
}}

QTableWidget::item:selected {{
    background: {BLUE_SOFT};
    color: {BLUE_DARK};
}}

QSplitter::handle {{
    background: {BORDER};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background: #edf2f7;
    border: none;
    margin: 0;
}}

QScrollBar:vertical {{
    width: 10px;
}}

QScrollBar:horizontal {{
    height: 10px;
}}

QScrollBar::handle {{
    background: #b9c8d7;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}}

QScrollBar::handle:hover {{
    background: #9fb2c5;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 14px;
    background: #ffffff;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {INK_MUTED};
}}

QStatusBar {{
    background: #253447;
    color: #dce6ef;
    border-top: 1px solid #172434;
}}

QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}

QDockWidget::title {{
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    padding: 5px 8px;
    color: {INK};
    font-weight: 600;
}}

QLabel#inspectorTitle {{
    background: {SURFACE_PANEL_ALT};
    border-bottom: 1px solid {BORDER};
    color: {INK};
    font-weight: 650;
}}

QWidget#inspectorProperties {{
    background: {SURFACE_PANEL_ALT};
}}

QWidget#propertyRow {{
    background: #ffffff;
    border: 1px solid transparent;
    border-bottom: 1px solid #edf2f6;
    min-height: 28px;
}}

QWidget#propertyRow:hover {{
    background: #f7fbfe;
}}

QLabel#propertyLabel {{
    color: {INK_MUTED};
}}

QLabel#propertyReadonly {{
    color: {INK_MUTED};
}}

QLabel#propertyEval {{
    color: {INK_MUTED};
}}

QLabel#propertySection {{
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 3px 6px;
}}

QPlainTextEdit#validationView, QPlainTextEdit#messagesView, QPlainTextEdit#infoView {{
    background: {SURFACE_PANEL_ALT};
    border: none;
    font-family: Consolas, "Courier New", monospace;
    font-size: 11px;
}}

QWidget#runStatusWidget {{
    background: #f8fbfd;
    border: 1px solid {BORDER};
}}

QLabel#runStatusLabel {{
    color: {INK_MUTED};
    font-weight: 600;
}}
"""


BROWSER_TREE_QSS = f"""
QTreeWidget {{
    background-color: {SURFACE_PANEL_ALT};
    alternate-background-color: #f4f7fa;
    border: 1px solid {BORDER};
    outline: none;
}}
QTreeWidget::item {{
    background-color: transparent;
    color: {INK};
    padding: 2px 4px;
    min-height: 22px;
    border-radius: 3px;
}}
QTreeWidget::item:hover {{
    background: #edf5fb;
}}
QTreeWidget::item:selected {{
    background-color: {BLUE_SOFT};
    color: {BLUE_DARK};
    outline: none;
    border: none;
}}
QTreeWidget::item:disabled {{
    color: {INK_SUBTLE};
}}
"""


MODE_INDICATOR_QSS = f"""
QWidget#modeIndicatorOverlay {{
    background: transparent;
    border: none;
}}
QToolButton {{
    border: 1px solid {BORDER_STRONG};
    border-left: none;
    background: rgba(255, 255, 255, 230);
    color: {INK_MUTED};
    font-weight: 650;
    font-size: 11px;
}}
QToolButton:hover {{
    background: #edf5fb;
    color: {INK};
}}
QToolButton:checked {{
    background: {BLUE};
    color: white;
    border-color: {BLUE};
}}
QToolButton:disabled {{
    background: rgba(255, 255, 255, 215);
    color: #96a4b2;
}}
QToolButton:checked:disabled {{
    background: {BLUE};
    color: white;
    border-color: {BLUE};
}}
"""


def apply_modern_engineering_theme(app: QtWidgets.QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    font = QtGui.QFont("Segoe UI", 9)
    app.setFont(font)


def apply_browser_tree_style(
    tree: QtWidgets.QTreeWidget,
    *,
    icon_size: int = 16,
    indentation: int = 18,
    show_header: bool | None = None,
) -> None:
    from quino.gui.tree_branches import tree_branch_stylesheet

    tree.setAlternatingRowColors(True)
    tree.setUniformRowHeights(True)
    tree.setIconSize(QtCore.QSize(icon_size, icon_size))
    tree.setIndentation(indentation)
    tree.setRootIsDecorated(True)
    if show_header is not None:
        tree.setHeaderHidden(not show_header)
    tree.setStyleSheet(BROWSER_TREE_QSS + tree_branch_stylesheet())
