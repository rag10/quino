import copy

from quino.domain.model import Body, Model
from quino.domain.types import BodyType
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine


def _body() -> Body:
    return Body(
        id="b1",
        name="bar",
        type=BodyType.BAR,
        markers=[],
        edge_order=[],
        closed_shape=False,
    )


def _ws():
    parent = Case(id="p", name="parent", model=Model())
    child = Case(id="c", name="child", parent_case_id="p", model=Model())
    gchild = Case(id="g", name="g", parent_case_id="c", model=Model())
    return Workspace(id="w", name="w", schema_version="0.4.0",
                     root_case_ids=["p"], cases={"p": parent, "c": child, "g": gchild})


def test_add_entity_cascades_to_all_descendants():
    ws = _ws()
    CascadingEngine(ws).add_entity("p", _body(), "bodies")
    assert any(b.id == "b1" for b in ws.cases["c"].model.bodies)
    assert any(b.id == "b1" for b in ws.cases["g"].model.bodies)


def test_remove_entity_cascades_when_value_identical():
    ws = _ws()
    for cid in ("p", "c", "g"):
        ws.cases[cid].model.bodies.append(_body())
    CascadingEngine(ws).remove_entity("p", "b1")
    assert all(not c.model.bodies for c in ws.cases.values())


def test_remove_entity_keeps_diverged_child():
    ws = _ws()
    for cid in ("p", "c"):
        ws.cases[cid].model.bodies.append(_body())
    ws.cases["c"].model.bodies[0].name = "renamed"
    CascadingEngine(ws).remove_entity("p", "b1")
    assert not ws.cases["p"].model.bodies
    assert ws.cases["c"].model.bodies and ws.cases["c"].model.bodies[0].name == "renamed"
