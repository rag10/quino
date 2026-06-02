"""Extra branch-coverage tests for CascadingEngine.

Covers:
1. edit_property raises ValueError for skip-props (id, markers, edge_order)
2. add_entity skips cascade to child when dependencies are missing in child
3. add_connection + remove_connection propagate to children (and check in-place mutation)
4. add_connection skipped in child when a referenced block instance is absent
5. reparent_case raises ValueError on cycle
6. remove_entity shields grandchild when intermediate child has diverged
"""
import copy

import pytest

from quino.domain.blocks import BlockDiagram, BlockInstance, Connection
from quino.domain.model import Body, Driver, Model, ScalarProperty, Sensor
from quino.domain.types import Dimension, DriverType, SensorType, BodyType
from quino.domain.workspace import Case, Workspace
from quino.services.case_cascading import CascadingEngine, _connection_key


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _law() -> ScalarProperty:
    return ScalarProperty(expression="1 rad", unit="rad",
                          expected_dimension=Dimension.ANGLE)


def _body(bid: str = "b1", name: str = "bar") -> Body:
    return Body(
        id=bid,
        name=name,
        type=BodyType.BAR,
        markers=[],
        edge_order=[],
        closed_shape=False,
    )


def _driver(did: str = "drv1", joint_id: str = "j1") -> Driver:
    return Driver(
        id=did,
        name="drv",
        type=DriverType.ROTATION,
        target_joint_id=joint_id,
        law=_law(),
    )


def _sensor(sid: str = "sen1", marker_ids: list[str] | None = None) -> Sensor:
    return Sensor(id=sid, name="sen", type=SensorType.POINT,
                  marker_ids=marker_ids or [])


def _block(iid: str) -> BlockInstance:
    return BlockInstance(instance_id=iid, block_type="gain")


def _diagram(*instance_ids: str) -> BlockDiagram:
    return BlockDiagram(instances={iid: _block(iid) for iid in instance_ids})


# ---------------------------------------------------------------------------
# 1. skip-props raises ValueError
# ---------------------------------------------------------------------------

def test_edit_property_skip_prop_markers_raises():
    parent = Case(id="p", name="parent", model=Model(bodies=[_body()]))
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent})
    with pytest.raises(ValueError, match="structural"):
        CascadingEngine(ws).edit_property("p", "b1", "markers", [])


def test_edit_property_skip_prop_id_raises():
    parent = Case(id="p", name="parent", model=Model(bodies=[_body()]))
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent})
    with pytest.raises(ValueError, match="structural"):
        CascadingEngine(ws).edit_property("p", "b1", "id", "new-id")


def test_edit_property_skip_prop_edge_order_raises():
    parent = Case(id="p", name="parent", model=Model(bodies=[_body()]))
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent})
    with pytest.raises(ValueError, match="structural"):
        CascadingEngine(ws).edit_property("p", "b1", "edge_order", [])


# ---------------------------------------------------------------------------
# 2. add_entity skips child when dependency is missing in child
# ---------------------------------------------------------------------------

def test_add_entity_skips_child_with_missing_dependency():
    """Parent has joint "j1". Child does NOT have joint "j1".
    Adding a driver that targets "j1" should cascade to parent only."""
    parent = Case(id="p", name="parent", model=Model())
    # Child is empty — it doesn't have joint j1
    child = Case(id="c", name="child", parent_case_id="p", model=Model())
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent, "c": child})

    # The driver references joint "j1" which exists in parent but not child.
    # We add the driver to parent after noting the dependency situation.
    # Since parent model is also initially empty, we need j1 in parent for the
    # _missing_dependencies check on parent to succeed (parent already has the
    # driver added before _propagate_add is called to child).
    # We simulate this by: adding j1 only to parent first, then adding driver.
    from quino.domain.model import Joint, JointEndpoint
    from quino.domain.types import JointType, JointEndpointKind

    j1 = Joint(
        id="j1", name="j1", type=JointType.REVOLUTE,
        endpoint_a=JointEndpoint(kind=JointEndpointKind.GROUND),
        endpoint_b=JointEndpoint(kind=JointEndpointKind.GROUND),
    )
    parent.model.joints.append(j1)
    # child intentionally left without j1

    drv = _driver(did="drv1", joint_id="j1")
    CascadingEngine(ws).add_entity("p", drv, "drivers")

    # Driver must be in parent
    assert any(d.id == "drv1" for d in parent.model.drivers)
    # Driver must NOT be in child (missing dependency: j1)
    assert not any(d.id == "drv1" for d in child.model.drivers)


# ---------------------------------------------------------------------------
# 3. add_connection + remove_connection propagate to child
# ---------------------------------------------------------------------------

def _ws_with_diagram(*instance_ids: str) -> tuple[Workspace, Case, Case]:
    """Parent and child both have a BlockDiagram with the given block instance ids."""
    parent = Case(id="p", name="parent",
                  model=Model(control_graph=_diagram(*instance_ids)))
    child = Case(id="c", name="child", parent_case_id="p",
                 model=Model(control_graph=_diagram(*instance_ids)))
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent, "c": child})
    return ws, parent, child


def test_add_connection_propagates_to_child():
    ws, parent, child = _ws_with_diagram("A", "B")
    conn = Connection(src_instance="A", src_port="out", dst_instance="B", dst_port="in")

    CascadingEngine(ws).add_connection("p", conn)

    assert _connection_key(conn) in {_connection_key(c) for c in parent.model.control_graph.connections}
    assert _connection_key(conn) in {_connection_key(c) for c in child.model.control_graph.connections}


def test_remove_connection_propagates_to_child():
    ws, parent, child = _ws_with_diagram("A", "B")
    conn = Connection(src_instance="A", src_port="out", dst_instance="B", dst_port="in")
    engine = CascadingEngine(ws)
    engine.add_connection("p", conn)

    key = _connection_key(conn)
    engine.remove_connection("p", key)

    assert key not in {_connection_key(c) for c in parent.model.control_graph.connections}
    assert key not in {_connection_key(c) for c in child.model.control_graph.connections}


def test_connections_are_mutated_in_place():
    """Verify the list objects are the same (in-place mutation, not rebind)."""
    ws, parent, child = _ws_with_diagram("A", "B")
    parent_list_id = id(parent.model.control_graph.connections)
    child_list_id = id(child.model.control_graph.connections)

    conn = Connection(src_instance="A", src_port="out", dst_instance="B", dst_port="in")
    engine = CascadingEngine(ws)
    engine.add_connection("p", conn)
    engine.remove_connection("p", _connection_key(conn))

    # The list objects must be the same (mutated in-place)
    assert id(parent.model.control_graph.connections) == parent_list_id
    assert id(child.model.control_graph.connections) == child_list_id


# ---------------------------------------------------------------------------
# 4. add_connection skipped when block instance missing in child
# ---------------------------------------------------------------------------

def test_add_connection_skipped_when_block_missing_in_child():
    """Parent has A+B; child only has A. Adding A->B should appear in parent only."""
    parent = Case(id="p", name="parent",
                  model=Model(control_graph=_diagram("A", "B")))
    child = Case(id="c", name="child", parent_case_id="p",
                 model=Model(control_graph=_diagram("A")))   # B absent
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent, "c": child})

    conn = Connection(src_instance="A", src_port="out", dst_instance="B", dst_port="in")
    CascadingEngine(ws).add_connection("p", conn)

    key = _connection_key(conn)
    assert key in {_connection_key(c) for c in parent.model.control_graph.connections}
    assert key not in {_connection_key(c) for c in child.model.control_graph.connections}


# ---------------------------------------------------------------------------
# 5. reparent_case cycle guard
# ---------------------------------------------------------------------------

def test_reparent_raises_on_direct_cycle():
    """p -> c. reparent_case("p", "c") would make p a child of c — cycle."""
    parent = Case(id="p", name="parent", model=Model())
    child = Case(id="c", name="child", parent_case_id="p", model=Model())
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": parent, "c": child})

    with pytest.raises(ValueError, match="cycle"):
        CascadingEngine(ws).reparent_case("p", "c")


def test_reparent_raises_on_indirect_cycle():
    """p -> c -> g. reparent_case("p", "g") would also form a cycle."""
    p = Case(id="p", name="p", model=Model())
    c = Case(id="c", name="c", parent_case_id="p", model=Model())
    g = Case(id="g", name="g", parent_case_id="c", model=Model())
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": p, "c": c, "g": g})

    with pytest.raises(ValueError, match="cycle"):
        CascadingEngine(ws).reparent_case("p", "g")


# ---------------------------------------------------------------------------
# 6. remove_entity shields grandchild when intermediate child has diverged
# ---------------------------------------------------------------------------

def test_remove_entity_shields_grandchild_via_diverged_child():
    """p -> c -> g. All three have b1 value-identical to start.
    Then c diverges (name changed). Removing b1 from p:
      - removes it from p (operation target)
      - keeps it in c (diverged, shields cascade)
      - keeps it in g (cascade stopped at c, grandchild not reached)
    """
    b1_original = _body("b1", "bar")
    p = Case(id="p", name="p", model=Model(bodies=[copy.deepcopy(b1_original)]))
    c = Case(id="c", name="c", parent_case_id="p",
             model=Model(bodies=[copy.deepcopy(b1_original)]))
    g = Case(id="g", name="g", parent_case_id="c",
             model=Model(bodies=[copy.deepcopy(b1_original)]))
    ws = Workspace(id="w", name="w", schema_version="0.4.0",
                   root_case_ids=["p"], cases={"p": p, "c": c, "g": g})

    # Diverge c's b1 so it no longer equals p's b1
    c.model.bodies[0].name = "renamed-in-c"

    CascadingEngine(ws).remove_entity("p", "b1")

    # b1 gone from p (the operation target)
    assert not any(b.id == "b1" for b in p.model.bodies)
    # b1 present in c (diverged — cascade was shielded here)
    assert any(b.id == "b1" for b in c.model.bodies)
    # b1 present in g (cascade never reached g because it stopped at c)
    assert any(b.id == "b1" for b in g.model.bodies)
