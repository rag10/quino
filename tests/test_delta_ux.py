import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.application.service import ApplicationService
from quino.domain.workspace import ScalarValue, Case


@pytest.fixture
def svc_with_overlay():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    svc = ApplicationService()
    svc.new_project("test")
    body_id = svc.create_punctual_mass("Bar1", x="0 mm", y="0 mm")
    baseline = svc.workspace.create_baseline("B1")
    case = svc.workspace.create_case("C1", baseline_id=baseline.id)
    case.invariant_values[f"bodies/{body_id}/mass"] = ScalarValue(value=3.0, unit="kg")
    svc.set_working_context(case_id=case.id)
    return svc, body_id, case


def test_build_delta_summary_counts_bodies(svc_with_overlay):
    from quino.gui.panels.workflow_tree_panel import _build_delta_summary

    svc, body_id, case = svc_with_overlay
    summary = _build_delta_summary(case)
    assert "bod" in summary.lower()


def test_build_delta_summary_empty_case():
    from quino.gui.panels.workflow_tree_panel import _build_delta_summary

    empty_case = Case(id="c1", name="Empty")
    assert _build_delta_summary(empty_case) == ""


def test_changed_entity_ids_from_case(svc_with_overlay):
    from quino.gui.main_window import _changed_entity_ids_for_case

    svc, body_id, case = svc_with_overlay
    ids = _changed_entity_ids_for_case(case)
    assert body_id in ids
