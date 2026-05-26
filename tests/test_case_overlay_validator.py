# tests/test_case_overlay_validator.py
import pytest

from quino.domain.model import Body, Marker, Model, ScalarProperty
from quino.domain.workspace import Case, CaseOverlay, EntityOverlay
from quino.services.case_overlay_validator import OverlayInvariantError, validate_overlay


def _make_marker(id_: str, name: str) -> Marker:
    from quino.domain.model import ScalarProperty
    from quino.domain.types import Dimension, MarkerType
    return Marker(
        id=id_, name=name, type=MarkerType.STRUCTURAL,
        x=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
        y=ScalarProperty("0 mm", "mm", Dimension.LENGTH),
    )


def _make_body(id_: str = "b1") -> Body:
    from quino.domain.types import BodyType
    return Body(
        id=id_, name="bar", type=BodyType.BAR,
        markers=[_make_marker("m1", "A"), _make_marker("m2", "B")],
        edge_order=["m1", "m2"], closed_shape=False,
    )


def test_root_case_with_no_overlay_is_valid():
    case = Case(id="root", name="Root", model=Model(bodies=[_make_body()]))
    validate_overlay(case, parent=None)


def test_child_overlay_must_have_entry_per_entity():
    body = _make_body()
    parent = Case(id="P", name="P", model=Model(bodies=[body]))
    child = Case(
        id="C", name="C", parent_case_id="P",
        model=Model(bodies=[body]),
        overlay=CaseOverlay(entities={}),  # missing entries — invalid
    )
    with pytest.raises(OverlayInvariantError):
        validate_overlay(child, parent=parent)


def test_inherited_entity_must_exist_in_parent():
    body = _make_body()
    parent = Case(id="P", name="P", model=Model(bodies=[]))
    child = Case(
        id="C", name="C", parent_case_id="P",
        model=Model(bodies=[body]),
        overlay=CaseOverlay(entities={
            "b1": EntityOverlay(origin="inherited", linked_properties={"name"}),
            "m1": EntityOverlay(origin="inherited", linked_properties=set()),
            "m2": EntityOverlay(origin="inherited", linked_properties=set()),
        }),
    )
    with pytest.raises(OverlayInvariantError):
        validate_overlay(child, parent=parent)


def test_local_origin_with_linked_properties_is_invalid():
    """Test that the validator catches local+linked_properties violation bypassing __post_init__."""
    body = _make_body()
    parent = Case(id="P", name="P", model=Model(bodies=[body]))

    # With slots=True, object.__new__ + object.__setattr__ works to bypass __post_init__
    bad = object.__new__(EntityOverlay)
    object.__setattr__(bad, 'origin', 'local')
    object.__setattr__(bad, 'linked_properties', {'mass'})

    m1 = EntityOverlay(origin="local")
    m2 = EntityOverlay(origin="local")
    child = Case(
        id="C", name="C", parent_case_id="P",
        model=Model(bodies=[body]),
        overlay=CaseOverlay(entities={"b1": bad, "m1": m1, "m2": m2}),
    )
    with pytest.raises(OverlayInvariantError):
        validate_overlay(child, parent=parent)
