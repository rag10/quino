import copy

from quino.domain.model import Body, Model, ScalarProperty
from quino.domain.types import BodyType, Dimension
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine


def _mass(expr: str) -> ScalarProperty:
    return ScalarProperty(expression=expr, unit="kg", expected_dimension=Dimension.MASS)


def _body(mass: ScalarProperty) -> Body:
    return Body(
        id="b1",
        name="bar",
        type=BodyType.BAR,
        markers=[],
        edge_order=[],
        closed_shape=False,
        mass=mass,
    )


def _ws_with_parent_child():
    body = _body(_mass("5 kg"))
    parent = Case(id="p", name="parent", model=Model(bodies=[copy.deepcopy(body)]))
    child = Case(id="c", name="child", parent_case_id="p",
                 model=Model(bodies=[copy.deepcopy(body)]))
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent, "c": child})
    return ws


def test_edit_cascades_to_tracking_child():
    ws = _ws_with_parent_child()
    CascadingEngine(ws).edit_property("p", "b1", "mass", _mass("8 kg"))
    assert ws.cases["c"].model.bodies[0].mass == _mass("8 kg")


def test_edit_does_not_cascade_to_diverged_child():
    ws = _ws_with_parent_child()
    ws.cases["c"].model.bodies[0].mass = _mass("2 kg")
    CascadingEngine(ws).edit_property("p", "b1", "mass", _mass("8 kg"))
    assert ws.cases["c"].model.bodies[0].mass == _mass("2 kg")
