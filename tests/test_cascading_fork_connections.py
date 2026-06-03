from quino.domain.model import Body, Model
from quino.domain.types import BodyType
from quino.domain.workspace import Analysis, Case, Workspace, create_default_pose
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


def _ws_single_root():
    root = Case(id="p", name="root", model=Model(bodies=[_body()]),
                poses=[create_default_pose("pose-def")],
                analyses=[Analysis(id="an1", name="Dyn", pose_id="pose-def")])
    return Workspace(id="w", name="w", schema_version="0.4.0",
                     root_case_ids=["p"], cases={"p": root})


def test_fork_copies_only_model_and_fresh_reference_pose():
    """A fork inherits the parent MODEL but NOT its poses/analyses.

    The child starts with a single fresh reference (default) pose and no
    analyses; poses and analyses are local working artifacts per case.
    """
    ws = _ws_single_root()
    ws.cases["p"].analyses[0].status = "ok"
    new_id = CascadingEngine(ws).fork_case("p", "child")
    child = ws.cases[new_id]
    assert child.parent_case_id == "p"
    # model inherited (ids preserved for cascading)
    assert [b.id for b in child.model.bodies] == ["b1"]
    # poses/analyses NOT copied
    assert child.analyses == []
    assert len(child.poses) == 1
    assert child.poses[0].is_default is True
    # fresh pose id, not the parent's "pose-def"
    assert child.poses[0].id != "pose-def"
