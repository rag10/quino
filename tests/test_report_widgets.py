import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.gui.widgets.report_panel import ReportPanelWidget
from quino.gui.widgets.validation_banner import ValidationBanner


def test_banner_severities_set_colors(qtbot) -> None:
    banner = ValidationBanner()
    qtbot.addWidget(banner)
    banner.set_status("error", "DoF=2")
    assert "#aa2222" in banner.styleSheet().lower()
    banner.set_status("warning", "no loads")
    assert "#c75b12" in banner.styleSheet().lower()
    banner.set_status("ok", "ready")
    assert "#228822" in banner.styleSheet().lower()
    banner.set_status("idle", "")
    assert not banner.isVisible()


def test_report_panel_adds_tabs(qtbot) -> None:
    panel = ReportPanelWidget()
    qtbot.addWidget(panel)
    panel.add_table_tab("Loads", ["name", "fx", "fy"], [["A", "1", "2"]])
    assert panel.count() == 1
