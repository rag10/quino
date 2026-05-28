"""Tests for cascade property classification and registry-path coverage."""
from __future__ import annotations

from quino.domain.blocks import BlockInstance
from quino.domain.model import Body, Joint, Marker, Sensor
from quino.services.cascade_property_category import (
    PropertyCategory,
    classify,
    is_model_affecting,
)
from quino.services.cascade_property_registry import is_cascadable_property


def test_classify_visual_paths() -> None:
    assert classify("name") is PropertyCategory.VISUAL
    assert classify("visible") is PropertyCategory.VISUAL
    assert classify("position") is PropertyCategory.VISUAL
    assert classify("style") is PropertyCategory.VISUAL
    assert classify("style.color") is PropertyCategory.VISUAL
    assert classify("style.line_width") is PropertyCategory.VISUAL


def test_classify_model_paths() -> None:
    assert classify("mass") is PropertyCategory.MODEL
    assert classify("metadata.values.friction_coulomb") is PropertyCategory.MODEL
    assert classify("parameters.kp") is PropertyCategory.MODEL


def test_classify_structural_paths() -> None:
    assert classify("markers") is PropertyCategory.STRUCTURAL
    assert classify("edge_order") is PropertyCategory.STRUCTURAL
    assert classify("marker_ids") is PropertyCategory.STRUCTURAL
    assert classify("input_ports") is PropertyCategory.STRUCTURAL


def test_is_model_affecting_matches_classify() -> None:
    assert is_model_affecting("mass") is True
    assert is_model_affecting("style.color") is False
    assert is_model_affecting("name") is False
    assert is_model_affecting("position") is False


def test_registry_accepts_nested_metadata_paths() -> None:
    # The engine cascades metadata.values.<k> dynamically; the registry must agree.
    assert is_cascadable_property(Joint, "metadata.values.friction_coulomb") is True
    assert is_cascadable_property(Body, "metadata.values.foo") is True


def test_registry_accepts_block_parameters() -> None:
    assert is_cascadable_property(BlockInstance, "parameters.kp") is True
    # Non-block classes do not have a "parameters" dict, so a parameters.<k> path
    # is rejected.
    assert is_cascadable_property(Body, "parameters.kp") is False


def test_registry_rejects_structural_topology() -> None:
    assert is_cascadable_property(Body, "markers") is False
    assert is_cascadable_property(Body, "edge_order") is False
    assert is_cascadable_property(Sensor, "marker_ids") is False


def test_registry_accepts_style_paths() -> None:
    assert is_cascadable_property(Body, "style") is True
    assert is_cascadable_property(Body, "style.color") is True


def test_registry_root_field_still_works() -> None:
    assert is_cascadable_property(Body, "mass") is True
    assert is_cascadable_property(Marker, "type") is True
