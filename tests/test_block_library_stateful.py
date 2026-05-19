"""Tests for stateful blocks in quino.blocks.library (Paso 2.4)."""

import numpy as np

from quino.blocks.library import get_block_def


class TestIntegrator:
    def test_integration(self) -> None:
        b = get_block_def("Integrator")
        state = b.init_state({"initial_condition": 0.0})
        # step 1: input=1.0, dt=0.1
        result = b.update({"in": np.array([1.0])}, {}, 0.1, 0.1, state)
        state = {"x": result["x"]}
        assert np.isclose(result["out"][0], 0.1)
        # step 2: input=2.0, dt=0.1
        result = b.update({"in": np.array([2.0])}, {}, 0.2, 0.1, state)
        assert np.isclose(result["out"][0], 0.3)  # 0.1 + 2*0.1

    def test_initial_condition(self) -> None:
        b = get_block_def("Integrator")
        state = b.init_state({"initial_condition": 5.0})
        result = b.update({"in": np.array([0.0])}, {}, 0.0, 0.1, state)
        assert np.isclose(result["out"][0], 5.0)


class TestIntegratorLimited:
    def test_saturation(self) -> None:
        b = get_block_def("IntegratorLimited")
        state = b.init_state({"initial_condition": 0.0})
        params = {"lower": -1.0, "upper": 1.0}
        # Integrate positive input beyond upper limit
        for _ in range(20):
            result = b.update({"in": np.array([1.0])}, params, 0.0, 0.1, state)
            state = {"x": result["x"]}
        assert np.isclose(result["out"][0], 1.0)


class TestUnitDelay:
    def test_delay(self) -> None:
        b = get_block_def("UnitDelay")
        state = b.init_state({"initial_condition": 0.0})
        result = b.update({"in": np.array([1.0])}, {}, 0.1, 0.1, state)
        assert np.isclose(result["out"][0], 0.0)  # initial condition
        state = {"x": result["x"]}
        result = b.update({"in": np.array([2.0])}, {}, 0.2, 0.1, state)
        assert np.isclose(result["out"][0], 1.0)  # previous input
