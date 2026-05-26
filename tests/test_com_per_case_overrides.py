import pytest
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput, PropertyValueInput
from quino.services.com_geometry import com_local_position
from quino.services.workspace_composition import compose_project


def _bar_with_case() -> tuple[ApplicationService, str, object]:
    app = ApplicationService()
    app.new_project("t")
    body_id = app.create_bar(
        "Bar",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
    )
    ws = app.project.workspace
    baseline = ws.baselines[0]
    case = app.workspace.create_case("C", baseline_id=baseline.id)
    app.workspace.set_working_context(case_id=case.id, baseline_id=baseline.id)
    return app, body_id, case


def test_marker_move_in_case_keeps_com_at_percent():
    """When a structural marker moves in a case, the composed CoM must
    follow the bar_percent anchor — not stay at the stale absolute
    coordinates."""
    app, body_id, case = _bar_with_case()
    body = app.get_body(body_id)
    structural = body.structural_markers()
    marker_b = structural[1]
    app.update_property(marker_b.id, "x", PropertyValueInput("expression", "200 mm"))

    composed = compose_project(app.project, case=case)
    cb = next(b for b in composed.model.bodies if b.id == body_id)
    lx, ly = com_local_position(composed, cb)
    assert lx == pytest.approx(100.0)
    assert ly == pytest.approx(0.0)
    # Baseline anchor must remain untouched.
    assert app.get_body(body_id).com.data["percent"] == pytest.approx(50.0)


def test_set_com_percent_in_case_writes_invariant_diff():
    """`set_com_percent` while a case is active must NOT mutate the
    baseline's anchor; the diff lives on the case."""
    app, body_id, case = _bar_with_case()
    app.bodies.set_com_percent(body_id, 75.0)

    assert app.get_body(body_id).com.data["percent"] == pytest.approx(50.0)
    overrides = case.reference_overrides.get(body_id, {})
    anchor = overrides.get("com_anchor")
    assert anchor is not None
    assert anchor["kind"] == "bar_percent"
    assert anchor["data"]["percent"] == pytest.approx(75.0)

    composed = compose_project(app.project, case=case)
    cb = next(b for b in composed.model.bodies if b.id == body_id)
    assert cb.com.kind == "bar_percent"
    assert cb.com.data["percent"] == pytest.approx(75.0)


def test_drag_com_outside_segment_in_case_swaps_anchor_kind():
    """Dragging the CoM off-axis in a case emits a `com_anchor` reference
    override with kind=local_offset."""
    app, body_id, case = _bar_with_case()
    app.bodies.drag_com_to_world(body_id, 50.0, 25.0)

    overrides = case.reference_overrides[body_id]
    assert overrides["com_anchor"]["kind"] == "local_offset"
    composed = compose_project(app.project, case=case)
    cb = next(b for b in composed.model.bodies if b.id == body_id)
    assert cb.com.kind == "local_offset"
    assert cb.com.data["lx"] == pytest.approx(50.0)
    assert cb.com.data["ly"] == pytest.approx(25.0)


def test_point_mass_set_com_rejects_in_case():
    app = ApplicationService()
    app.new_project("t")
    body_id = app.create_punctual_mass("M", x="0 mm", y="0 mm")
    ws = app.project.workspace
    baseline = ws.baselines[0]
    case = app.workspace.create_case("C", baseline_id=baseline.id)
    app.workspace.set_working_context(case_id=case.id, baseline_id=baseline.id)
    with pytest.raises(ValueError, match="locked"):
        app.bodies.set_com_offset(body_id, 5.0, 0.0)
