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


def test_delta_summary_counts_added_and_removed():
    from quino.domain.workspace import Case
    from quino.gui.panels.workflow_tree_panel import _build_delta_summary

    case = Case(
        id="c1", name="C",
        invariant_values={"bodies/b1/mass": ScalarValue(2.0, "kg")},
        added_entities={"bodies": [{"id": "new_body"}]},
        removed_entity_ids=["old_body"],
        removed_connections=[("a", "out", "b", "in")],
    )
    summary = _build_delta_summary(case)
    assert "1 bodies" in summary
    assert "+1 added" in summary
    assert "-2 removed" in summary


def test_baseline_hint_reads_baseline_not_override(svc_with_overlay):
    """When a case overrides mass=3kg and baseline has mass=1kg, the hint
    must show '1 kg', not '3 kg'."""
    from quino.gui.main_window import MainWindow
    from quino.domain.inputs import PropertyValueInput

    svc, body_id, case = svc_with_overlay
    # Set baseline mass to 1kg first (with no active case)
    svc.set_working_context()
    svc.update_property(body_id, "mass", PropertyValueInput(kind="expression", value="1 kg"))
    svc.set_working_context(case_id=case.id)
    # Verify the baseline value is reported, not the override (3kg in fixture).
    win = MainWindow(svc)
    hint = win._baseline_value_for_path(svc.project, f"bodies/{body_id}/mass")
    assert hint is not None
    assert "1" in hint
    assert "3" not in hint
    win.close()


def test_delta_summary_supports_new_path_domains():
    from quino.domain.workspace import Case
    from quino.gui.panels.workflow_tree_panel import _build_delta_summary

    case = Case(
        id="c1", name="C",
        invariant_values={
            "markers/m1/x": ScalarValue(10.0, "mm"),
            "sliders/s1/angle": ScalarValue(0.5, "rad"),
            "joints/j1/friction_coulomb": ScalarValue(0.1, ""),
            "springs_meta/sp1/stiffness": ScalarValue(50.0, ""),
        },
    )
    summary = _build_delta_summary(case)
    assert "markers" in summary
    assert "sliders" in summary
    assert "joints" in summary
    assert "springs" in summary
