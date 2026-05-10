from __future__ import annotations

from quino.domain.inputs import SketchSplineInput
from quino.domain.model import Sketch, SketchSpline
from quino.domain.types import SketchEntityType


def test_sketch_spline_can_be_created() -> None:
    spline = SketchSpline(
        id="s1",
        name="Spline 1",
        type=SketchEntityType.SPLINE,
        control_point_ids=["p1", "p2", "p3"],
    )
    assert spline.id == "s1"
    assert spline.name == "Spline 1"
    assert spline.control_point_ids == ["p1", "p2", "p3"]
    assert spline.construction is False
    assert spline.visible is True
    assert spline.selectable is True


def test_sketch_spline_stored_in_sketch_entities() -> None:
    spline = SketchSpline(
        id="s1",
        name="Spline 1",
        type=SketchEntityType.SPLINE,
        control_point_ids=["p1", "p2"],
    )
    sketch = Sketch(id="sk1", name="Test")
    sketch.entities["s1"] = spline
    assert "s1" in sketch.entities
    assert isinstance(sketch.entities["s1"], SketchSpline)


def test_sketch_spline_input_has_control_point_ids() -> None:
    inp = SketchSplineInput(control_point_ids=["p1", "p2", "p3"])
    assert inp.control_point_ids == ["p1", "p2", "p3"]
    assert inp.name is None


def test_sketch_entity_type_has_spline() -> None:
    assert SketchEntityType.SPLINE == "spline"
