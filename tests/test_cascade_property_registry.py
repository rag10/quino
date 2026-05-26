# tests/test_cascade_property_registry.py
from quino.services.cascade_property_registry import (
    cascadable_properties,
    is_cascadable_property,
)
from quino.domain.model import Body, Joint, Marker, Slider, Driver, Load, Sensor, Spring


def test_body_cascadable_properties_include_mass_and_com():
    props = cascadable_properties(Body)
    assert "mass" in props
    assert "name" in props
    # structural lists are NOT cascadable
    assert "markers" not in props
    assert "edge_order" not in props
    # id is NOT cascadable
    assert "id" not in props


def test_marker_cascadable_properties_include_x_y():
    props = cascadable_properties(Marker)
    assert "x" in props
    assert "y" in props
    assert "id" not in props


def test_joint_cascadable_properties():
    props = cascadable_properties(Joint)
    assert "id" not in props


def test_is_cascadable_property_matches():
    assert is_cascadable_property(Body, "mass") is True
    assert is_cascadable_property(Body, "id") is False
    assert is_cascadable_property(Body, "nonexistent") is False


def test_all_supported_types_have_a_registry_entry():
    for cls in [Body, Joint, Marker, Slider, Driver, Load, Sensor, Spring]:
        props = cascadable_properties(cls)
        assert props, f"{cls.__name__} has no cascadable properties"
