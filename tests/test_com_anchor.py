import math
import pytest
from quino.application.service import ApplicationService
from quino.domain.inputs import MarkerInput
from quino.domain.model import BodyPose, CoMAnchor, Pose
from quino.services.com_geometry import com_global_position, com_local_position


def test_com_anchor_holds_kind_and_data():
    anchor = CoMAnchor(kind="bar_percent", data={"percent": 50.0})
    assert anchor.kind == "bar_percent"
    assert anchor.data["percent"] == 50.0


def test_com_anchor_roundtrip_dict():
    anchor = CoMAnchor(kind="barycentric", data={"weights": {"m1": 0.4, "m2": 0.6}})
    payload = {"kind": anchor.kind, "data": dict(anchor.data)}
    restored = CoMAnchor(kind=payload["kind"], data=dict(payload["data"]))
    assert restored == anchor


def _make_bar(percent: float | None = None) -> tuple[ApplicationService, str]:
    app = ApplicationService()
    app.new_project("t")
    body_id = app.create_bar(
        "Bar",
        MarkerInput("0 mm", "0 mm", "A"),
        MarkerInput("100 mm", "0 mm", "B"),
    )
    if percent is not None:
        body = app.get_body(body_id)
        body.com = CoMAnchor(kind="bar_percent", data={"percent": percent})
    return app, body_id


def test_bar_percent_midpoint() -> None:
    app, body_id = _make_bar()
    body = app.get_body(body_id)
    lx, ly = com_local_position(app.project, body)
    assert lx == pytest.approx(50.0)
    assert ly == pytest.approx(0.0)


def test_bar_percent_at_30() -> None:
    app, body_id = _make_bar(percent=30.0)
    body = app.get_body(body_id)
    lx, ly = com_local_position(app.project, body)
    assert lx == pytest.approx(30.0)
    assert ly == pytest.approx(0.0)


def test_local_offset_ignores_markers() -> None:
    app, body_id = _make_bar()
    body = app.get_body(body_id)
    body.com = CoMAnchor(kind="local_offset", data={"lx": 12.5, "ly": -3.0})
    lx, ly = com_local_position(app.project, body)
    assert lx == pytest.approx(12.5)
    assert ly == pytest.approx(-3.0)


def test_marker_kind_returns_marker_position() -> None:
    app = ApplicationService()
    app.new_project("t")
    body_id = app.create_punctual_mass("M", x="42 mm", y="7 mm")
    body = app.get_body(body_id)
    lx, ly = com_local_position(app.project, body)
    assert lx == pytest.approx(42.0)
    assert ly == pytest.approx(7.0)


def test_barycentric_equal_weights_centroid() -> None:
    app = ApplicationService()
    app.new_project("t")
    body_id = app.create_body(
        "Tri",
        [
            MarkerInput("0 mm", "0 mm", "A"),
            MarkerInput("100 mm", "0 mm", "B"),
            MarkerInput("0 mm", "60 mm", "C"),
        ],
        body_type="body",
    )
    body = app.get_body(body_id)
    structural_ids = [m.id for m in body.structural_markers()]
    body.com = CoMAnchor(
        kind="barycentric",
        data={"weights": {mid: 1.0 for mid in structural_ids}},
    )
    lx, ly = com_local_position(app.project, body)
    assert lx == pytest.approx(100.0 / 3.0)
    assert ly == pytest.approx(60.0 / 3.0)


def test_global_position_applies_body_pose() -> None:
    app, body_id = _make_bar()  # CoM at (50, 0)
    body = app.get_body(body_id)
    pose = Pose(
        id="p1",
        name="p1",
        body_poses={body_id: BodyPose(body_id=body_id, x=10.0, y=20.0, angle=math.pi / 2)},
    )
    gx, gy = com_global_position(app.project, body, pose)
    # 90 deg rotation maps (50, 0) -> (0, 50), then +translate (10, 20).
    assert gx == pytest.approx(10.0)
    assert gy == pytest.approx(70.0)
