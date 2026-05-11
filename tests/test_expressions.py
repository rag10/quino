import pytest
from quino.services.units import UnitService
from quino.services.expressions import ExpressionService
from quino.domain.types import Dimension


def _svc() -> ExpressionService:
    return ExpressionService(UnitService())


class TestInertiaExpressions:
    def test_kgmm2_literal_evaluates_to_inertia(self):
        svc = _svc()
        q = svc.evaluate_expression("250 kgmm2", [])
        assert q.is_pure(Dimension.INERTIA)
        assert q.value_si == pytest.approx(250 * 1e-6)

    def test_kgm2_literal_evaluates_to_inertia(self):
        svc = _svc()
        q = svc.evaluate_expression("0.5 kgm2", [])
        assert q.is_pure(Dimension.INERTIA)
        assert q.value_si == pytest.approx(0.5)

    def test_inertia_arithmetic(self):
        # 1 kgm2 == 1e6 kgmm2
        svc = _svc()
        q = svc.evaluate_expression("1 kgm2 + 0 kgmm2", [])
        assert svc.unit_service.convert(q, "kgmm2") == pytest.approx(1_000_000.0)

    def test_compact_kgmm2_no_space(self):
        svc = _svc()
        q = svc.evaluate_expression("100kgmm2", [])
        assert q.is_pure(Dimension.INERTIA)


class TestMathFunctions:
    def test_sqrt_of_length_squared_is_length(self):
        svc = _svc()
        q = svc.evaluate_expression("sqrt(100 mm * 100 mm)", [])
        assert q.is_pure(Dimension.LENGTH)
        assert svc.unit_service.convert(q, "mm") == pytest.approx(100.0)

    def test_sqrt_of_unitless(self):
        svc = _svc()
        q = svc.evaluate_expression("sqrt(9 unitless)", [])
        assert q.is_unitless()
        assert q.value_si == pytest.approx(3.0)

    def test_tan_accepts_angle(self):
        svc = _svc()
        q = svc.evaluate_expression("tan(45 deg)", [])
        assert q.is_unitless()
        assert q.value_si == pytest.approx(1.0, rel=1e-9)

    def test_tan_rejects_length(self):
        svc = _svc()
        with pytest.raises(ValueError, match="angle"):
            svc.evaluate_expression("tan(10 mm)", [])

    def test_pow_unitless_base_and_exponent(self):
        svc = _svc()
        q = svc.evaluate_expression("pow(2 unitless, 3 unitless)", [])
        assert q.is_unitless()
        assert q.value_si == pytest.approx(8.0)

    def test_pow_rejects_non_unitless_exponent(self):
        svc = _svc()
        with pytest.raises(ValueError, match="unitless"):
            svc.evaluate_expression("pow(2 mm, 3 unitless)", [])
