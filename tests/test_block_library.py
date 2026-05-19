"""Tests for quino.blocks.library (Paso 2.3)."""

import numpy as np
import pytest

from quino.blocks.library import get_block_def


class TestSources:
    def test_constant(self) -> None:
        b = get_block_def("Constant")
        out = b.compute({}, {"value": 3.5}, 0.0)
        assert np.isclose(out["out"][0], 3.5)

    def test_step_before_time(self) -> None:
        b = get_block_def("Step")
        out = b.compute({}, {"step_time": 1.0, "initial_value": 0.0, "final_value": 5.0}, 0.5)
        assert np.isclose(out["out"][0], 0.0)

    def test_step_after_time(self) -> None:
        b = get_block_def("Step")
        out = b.compute({}, {"step_time": 1.0, "initial_value": 0.0, "final_value": 5.0}, 2.0)
        assert np.isclose(out["out"][0], 5.0)

    def test_ramp(self) -> None:
        b = get_block_def("Ramp")
        out = b.compute({}, {"slope": 2.0, "start_time": 1.0}, 3.0)
        assert np.isclose(out["out"][0], 4.0)  # 2 * (3-1)

    def test_sine(self) -> None:
        b = get_block_def("Sine")
        out = b.compute({}, {"amplitude": 2.0, "frequency": 1.0, "phase": 0.0, "bias": 1.0}, 0.25)
        expected = 1.0 + 2.0 * np.sin(2.0 * np.pi * 0.25)
        assert np.isclose(out["out"][0], expected)


class TestMath:
    def test_gain(self) -> None:
        b = get_block_def("Gain")
        out = b.compute({"in": np.array([4.0])}, {"k": 2.5}, 0.0)
        assert np.isclose(out["out"][0], 10.0)

    def test_adder(self) -> None:
        b = get_block_def("Adder")
        out = b.compute(
            {"in0": np.array([1.0]), "in1": np.array([2.0])},
            {},
            0.0,
        )
        assert np.isclose(out["out"][0], 3.0)

    def test_product(self) -> None:
        b = get_block_def("Product")
        out = b.compute(
            {"in0": np.array([3.0]), "in1": np.array([4.0])},
            {},
            0.0,
        )
        assert np.isclose(out["out"][0], 12.0)

    def test_saturation(self) -> None:
        b = get_block_def("Saturation")
        out = b.compute({"in": np.array([5.0])}, {"lower": -1.0, "upper": 1.0}, 0.0)
        assert np.isclose(out["out"][0], 1.0)
        out = b.compute({"in": np.array([-5.0])}, {"lower": -1.0, "upper": 1.0}, 0.0)
        assert np.isclose(out["out"][0], -1.0)

    def test_dead_zone(self) -> None:
        b = get_block_def("DeadZone")
        out = b.compute({"in": np.array([0.3])}, {"deadband": 0.5}, 0.0)
        assert np.isclose(out["out"][0], 0.0)
        out = b.compute({"in": np.array([0.7])}, {"deadband": 0.5}, 0.0)
        assert np.isclose(out["out"][0], 0.2)


class TestRouting:
    def test_mux(self) -> None:
        b = get_block_def("Mux")
        out = b.compute(
            {"in0": np.array([1.0]), "in1": np.array([2.0])},
            {},
            0.0,
        )
        assert np.allclose(out["out"], np.array([1.0, 2.0]))

    def test_demux(self) -> None:
        b = get_block_def("Demux")
        out = b.compute({"in": np.array([3.0, 4.0])}, {}, 0.0)
        assert np.isclose(out["out0"][0], 3.0)
        assert np.isclose(out["out1"][0], 4.0)


class TestUnknownBlock:
    def test_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown block type"):
            get_block_def("NonExistent")
