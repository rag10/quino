from quino.domain.model import Body, Marker, Model, ScalarProperty
from quino.domain.types import BodyType, Dimension, MarkerType
from quino.domain.workspace import Case
from quino.services.case_entities import entity_lookup


def _scalar(value: float = 0.0) -> ScalarProperty:
    return ScalarProperty(expression=str(value), unit="mm", expected_dimension=Dimension.LENGTH)


def _case_with_body() -> Case:
    marker = Marker(
        id="mk1",
        name="tip",
        type=MarkerType.STRUCTURAL,
        x=_scalar(1.0),
        y=_scalar(0.0),
    )
    body = Body(
        id="b1",
        name="bar",
        type=BodyType.BAR,
        markers=[marker],
        edge_order=[],
        closed_shape=False,
    )
    model = Model(bodies=[body])
    return Case(id="c1", name="root", model=model)


def test_entity_lookup_includes_body_and_structural_marker():
    case = _case_with_body()
    lookup = entity_lookup(case)
    assert "b1" in lookup
    assert "mk1" in lookup
    assert lookup["b1"][1] is Body
    assert lookup["mk1"][1] is Marker
