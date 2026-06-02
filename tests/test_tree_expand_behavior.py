import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from quino.gui.theme import apply_browser_tree_style


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_double_click_does_not_expand():
    _app()
    tree = QtWidgets.QTreeWidget()
    parent = QtWidgets.QTreeWidgetItem(["p"])
    parent.addChild(QtWidgets.QTreeWidgetItem(["c"]))
    tree.addTopLevelItem(parent)
    apply_browser_tree_style(tree)
    assert tree.expandsOnDoubleClick() is False
    # items remain expandable via the branch triangle
    assert tree.itemsExpandable() is True
    assert tree.rootIsDecorated() is True
