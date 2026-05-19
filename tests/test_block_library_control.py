"""Tests for control blocks in quino.blocks.library (Paso 2.5)."""

import numpy as np

from quino.blocks.library import get_block_def


class TestPID:
    def test_proportional_only(self) -> None:
        b = get_block_def("PID")
        state = b.init_state({})
        result = b.update({"error": np.array([2.0])}, {"kp": 3.0, "ki": 0.0, "kd": 0.0}, 0.1, 0.1, state)
        assert np.isclose(result["out"][0], 6.0)

    def test_integral_accumulation(self) -> None:
        b = get_block_def("PID")
        state = b.init_state({})
        params = {"kp": 0.0, "ki": 1.0, "kd": 0.0}
        result = b.update({"error": np.array([1.0])}, params, 0.1, 0.1, state)
        state = {k: result[k] for k in ("integral", "last_error", "last_t")}
        result = b.update({"error": np.array([1.0])}, params, 0.2, 0.1, state)
        assert np.isclose(result["out"][0], 0.2)  # integral = 1*0.1 + 1*0.1 = 0.2

    def test_saturation(self) -> None:
        b = get_block_def("PID")
        state = b.init_state({})
        params = {"kp": 10.0, "ki": 0.0, "kd": 0.0, "lower": -5.0, "upper": 5.0}
        result = b.update({"error": np.array([2.0])}, params, 0.1, 0.1, state)
        assert np.isclose(result["out"][0], 5.0)

    def test_anti_windup(self) -> None:
        b = get_block_def("PID")
        state = b.init_state({})
        params = {"kp": 0.0, "ki": 1.0, "kd": 0.0, "lower": -1.0, "upper": 1.0, "anti_windup": True}
        # Saturate output high
        result = b.update({"error": np.array([10.0])}, params, 0.1, 0.1, state)
        state = {k: result[k] for k in ("integral", "last_error", "last_t")}
        assert np.isclose(result["out"][0], 1.0)
        # Next step: integral should not have grown unbounded
        result2 = b.update({"error": np.array([10.0])}, params, 0.2, 0.1, state)
        assert result2["integral"][0] < 2.0


class TestDerivativeFiltered:
    def test_constant_input_zero_output(self) -> None:
        b = get_block_def("DerivativeFiltered")
        state = b.init_state({})
        params = {"time_constant": 0.01}
        result = b.update({"in": np.array([5.0])}, params, 0.0, 0.0, state)
        # First call has no derivative yet
        assert np.isclose(result["out"][0], 0.0)
        state = {k: result[k] for k in ("last_input", "last_output", "last_t")}
        result = b.update({"in": np.array([5.0])}, params, 0.1, 0.1, state)
        # Constant input -> derivative should trend to 0
        assert abs(result["out"][0]) < 1.0

    def test_ramp_input(self) -> None:
        b = get_block_def("DerivativeFiltered")
        state = b.init_state({})
        params = {"time_constant": 0.001}
        for i in range(1, 11):
            result = b.update({"in": np.array([float(i)])}, params, i * 0.1, 0.1, state)
            state = {k: result[k] for k in ("last_input", "last_output", "last_t")}
        # Ramp slope = 1.0 per step (10 steps / 1.0 s) -> derivative should approach 10.0
        # Actually: input goes 1..10 in steps of 1 every 0.1s -> slope = 10.0
        assert np.isclose(result["out"][0], 10.0, rtol=0.1)
