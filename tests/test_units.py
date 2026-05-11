import pytest
from quino.services.units import UnitService, Quantity
from quino.domain.types import Dimension


def _svc() -> UnitService:
    return UnitService()


class TestInertiaUnits:
    def test_kgmm2_is_known(self):
        assert _svc().is_known("kgmm2")

    def test_kgm2_is_known(self):
        assert _svc().is_known("kgm2")

    def test_kgmm2_dimension_is_inertia(self):
        assert _svc().dimension("kgmm2") is Dimension.INERTIA

    def test_kgmm2_quantity_has_compound_dims(self):
        q = _svc().quantity(1.0, "kgmm2")
        assert q.dimensions == {Dimension.MASS: 1, Dimension.LENGTH: 2}

    def test_kgmm2_quantity_si_value(self):
        # 1 kg·mm² = 1e-6 kg·m²
        q = _svc().quantity(1.0, "kgmm2")
        assert q.value_si == pytest.approx(1e-6)

    def test_kgm2_quantity_si_value(self):
        q = _svc().quantity(1.0, "kgm2")
        assert q.value_si == pytest.approx(1.0)

    def test_kgmm2_roundtrip(self):
        svc = _svc()
        q = svc.quantity(250.0, "kgmm2")
        assert svc.convert(q, "kgmm2") == pytest.approx(250.0)

    def test_convert_kgmm2_to_kgm2(self):
        svc = _svc()
        q = svc.quantity(1_000_000.0, "kgmm2")  # 1e6 kg·mm² = 1 kg·m²
        assert svc.convert(q, "kgm2") == pytest.approx(1.0)

    def test_convert_rejects_length_as_inertia(self):
        svc = _svc()
        q = svc.quantity(1.0, "m")
        with pytest.raises(ValueError, match="Incompatible"):
            svc.convert(q, "kgm2")

    def test_convert_rejects_mass_as_inertia(self):
        svc = _svc()
        q = svc.quantity(1.0, "kg")
        with pytest.raises(ValueError, match="Incompatible"):
            svc.convert(q, "kgmm2")


class TestIsPureInertia:
    def test_is_pure_inertia_for_mass_length2(self):
        q = Quantity(1e-6, {Dimension.MASS: 1, Dimension.LENGTH: 2})
        assert q.is_pure(Dimension.INERTIA)

    def test_is_not_pure_inertia_for_mass_only(self):
        q = Quantity(1.0, {Dimension.MASS: 1})
        assert not q.is_pure(Dimension.INERTIA)

    def test_is_not_pure_inertia_for_unitless(self):
        q = Quantity(1.0, {})
        assert not q.is_pure(Dimension.INERTIA)

    def test_existing_is_pure_length_unchanged(self):
        q = Quantity(0.001, {Dimension.LENGTH: 1})
        assert q.is_pure(Dimension.LENGTH)

    def test_existing_is_pure_unitless_unchanged(self):
        q = Quantity(1.0, {})
        assert q.is_pure(Dimension.UNITLESS)
