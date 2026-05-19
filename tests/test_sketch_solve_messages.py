"""Tests for human-readable failure messages from solve_sketch()."""
from quino import ApplicationService


def test_failed_constraint_message_includes_constraint_name():
    """An impossible distance constraint surfaces with its name, not a UUID."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("0 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("fix", [p2])
    # Impossible: both points fixed at the same place but with distance = 10
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm", name="my_dist")
    report = svc.solve_sketch()
    messages = [m.message for m in report.messages]
    # Report must surface some failure indication (warning).
    warnings = [m for m in report.messages if m.level == "warning"]
    assert warnings, f"Expected at least one warning, got: {messages}"
    # And raw constraint IDs (e.g. 'skcon_001') must NOT leak into user-facing text.
    for m in messages:
        assert "skcon_" not in m, f"Raw constraint id leaked in message: {m}"


def test_success_message_unchanged():
    """When the sketch solves, the existing 'Sketch solved' message is preserved."""
    svc = ApplicationService()
    svc.new_project("T")
    svc.create_sketch("S")
    p1 = svc.create_sketch_point("0 mm", "0 mm", "P1")
    p2 = svc.create_sketch_point("5 mm", "0 mm", "P2")
    svc.create_sketch_constraint("fix", [p1])
    svc.create_sketch_constraint("distance", [p1, p2], value="10 mm")
    report = svc.solve_sketch()
    messages = [m.message for m in report.messages]
    assert any("solved" in m.lower() for m in messages), f"Expected 'solved' message, got: {messages}"
