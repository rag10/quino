# Unit System Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the inertia dimension, add compound inertia units (`kgmm2`/`kgm2`), add missing math functions (`sqrt`, `tan`, `pow`), and improve property panel UX with dimension hints and friendlier error messages.

**Architecture:** The `UnitService` currently maps each `Dimension` to a single SI base; we extend it with a `_UNIT_DIMS` dict that maps `Dimension.INERTIA` to the compound `{MASS:1, LENGTH:2}` SI basis. `Quantity.is_pure()` gets an explicit INERTIA branch. The `ExpressionService` regex and environment are extended for new unit tokens and math functions. GUI changes are isolated to `main_window.py` and `canvas.py`.

**Tech Stack:** Python 3.11+, PyQt6, pytest. Run tests with `pytest` from the project root.

---

## File Map

| File | Change |
|---|---|
| `quino/services/units.py` | Add `_UNIT_DIMS`, `kgmm2`/`kgm2`, update `quantity()` + `convert()`, fix `is_pure()` |
| `quino/services/expressions.py` | Add `kgmm2`/`kgm2` to regex; add `sqrt`, `tan`, `pow` to environment |
| `quino/application/service.py` | Change inertia dimension from `UNITLESS` → `INERTIA`, default unit `"unitless"` → `"kgmm2"` |
| `quino/gui/main_window.py` | Add dimension tooltips to inspector rows; improve `_evaluate_scalar` error message |
| `quino/gui/canvas.py` | Add convention hint to driver law dialog |
| `tests/test_units.py` | New file — unit service unit tests |
| `tests/test_application.py` | Add inertia integration tests |
| `tests/test_expressions.py` | New file — expression engine unit tests |

---

## Task 1: Extend UnitService with compound inertia units

**Files:**
- Modify: `quino/services/units.py`
- Create: `tests/test_units.py`

- [ ] **Step 1.1: Write failing tests**

Create `tests/test_units.py`:

```python
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
```

- [ ] **Step 1.2: Run tests to verify they fail**

```
pytest tests/test_units.py -v
```

Expected: FAIL — `kgmm2` not in `_UNITS`, `is_pure(INERTIA)` returns False.

- [ ] **Step 1.3: Implement the changes in `quino/services/units.py`**

Replace the entire file content (lines 1-80) with:

```python
from __future__ import annotations

from dataclasses import dataclass
import math

from quino.domain.types import Dimension


@dataclass(frozen=True, slots=True)
class Quantity:
    value_si: float
    dimensions: dict[Dimension, int]

    def to(self, factor: float) -> float:
        return self.value_si / factor

    @property
    def dimension_text(self) -> str:
        if not self.dimensions:
            return Dimension.UNITLESS.value
        parts: list[str] = []
        for dimension in sorted(self.dimensions, key=lambda item: item.value):
            exponent = self.dimensions[dimension]
            if exponent == 1:
                parts.append(dimension.value)
            else:
                parts.append(f"{dimension.value}^{exponent}")
        return "*".join(parts)

    def is_unitless(self) -> bool:
        return not self.dimensions

    def is_pure(self, dimension: Dimension) -> bool:
        if dimension is Dimension.UNITLESS:
            return not self.dimensions
        if dimension is Dimension.INERTIA:
            return self.dimensions == {Dimension.MASS: 1, Dimension.LENGTH: 2}
        return self.dimensions == {dimension: 1}


class UnitService:
    _UNITS: dict[str, tuple[Dimension, float]] = {
        "mm": (Dimension.LENGTH, 0.001),
        "m": (Dimension.LENGTH, 1.0),
        "deg": (Dimension.ANGLE, math.pi / 180.0),
        "rad": (Dimension.ANGLE, 1.0),
        "kg": (Dimension.MASS, 1.0),
        "s": (Dimension.TIME, 1.0),
        "unitless": (Dimension.UNITLESS, 1.0),
        "kgmm2": (Dimension.INERTIA, 1e-6),   # 1 kg·mm² = 1e-6 kg·m² (SI)
        "kgm2": (Dimension.INERTIA, 1.0),
    }

    # Maps each Dimension to its SI base-dimension exponents
    _UNIT_DIMS: dict[Dimension, dict[Dimension, int]] = {
        Dimension.LENGTH: {Dimension.LENGTH: 1},
        Dimension.ANGLE: {Dimension.ANGLE: 1},
        Dimension.MASS: {Dimension.MASS: 1},
        Dimension.TIME: {Dimension.TIME: 1},
        Dimension.INERTIA: {Dimension.MASS: 1, Dimension.LENGTH: 2},
        Dimension.UNITLESS: {},
    }

    def is_known(self, unit: str) -> bool:
        return unit in self._UNITS

    def dimension(self, unit: str) -> Dimension:
        if unit not in self._UNITS:
            raise ValueError(f"Unknown unit: {unit}")
        return self._UNITS[unit][0]

    def factor(self, unit: str) -> float:
        if unit not in self._UNITS:
            raise ValueError(f"Unknown unit: {unit}")
        return self._UNITS[unit][1]

    def known_units(self) -> set[str]:
        return set(self._UNITS.keys())

    def quantity(self, value: float, unit: str) -> Quantity:
        dimension = self.dimension(unit)
        return Quantity(value * self.factor(unit), dict(self._UNIT_DIMS[dimension]))

    def convert(self, quantity: Quantity, unit: str) -> float:
        target_dimension = self.dimension(unit)
        expected = self._UNIT_DIMS[target_dimension]
        if quantity.dimensions != expected:
            raise ValueError("Incompatible dimensions")
        return quantity.to(self.factor(unit))
```

- [ ] **Step 1.4: Run tests to verify they pass**

```
pytest tests/test_units.py -v
```

Expected: all PASS.

- [ ] **Step 1.5: Run full test suite to check for regressions**

```
pytest --tb=short -q
```

Expected: all existing tests pass. If `test_expressions_accept_compact_units_and_decimal_comma` fails, that's expected — it will be fixed in Task 2.

- [ ] **Step 1.6: Commit**

```
git add quino/services/units.py tests/test_units.py
git commit -m "feat: add kgmm2/kgm2 inertia units with compound dimension support"
```

---

## Task 2: Add inertia unit tokens to the expression parser

**Files:**
- Modify: `quino/services/expressions.py`
- Create: `tests/test_expressions.py`

The expression engine parses `"250 kgmm2"` via a regex that rewrites it to `"(250*kgmm2)"`. The unit tokens `kgmm2` and `kgm2` must be added to that regex and registered as `Quantity` symbols in the evaluation environment.

- [ ] **Step 2.1: Write failing tests**

Create `tests/test_expressions.py`:

```python
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
```

- [ ] **Step 2.2: Run tests to verify they fail**

```
pytest tests/test_expressions.py -v
```

Expected: FAIL — `kgmm2` not in regex, `sqrt`/`tan`/`pow` not in environment.

- [ ] **Step 2.3: Implement changes in `quino/services/expressions.py`**

**2.3a** — Update the regex pattern at line 21 to include `kgmm2` and `kgm2` before `kg` (order matters — longer tokens must precede shorter prefixes):

```python
    _number_unit_pattern = re.compile(
        r"(?P<num>(?<![A-Za-z_])[-+]?\d+(?:[\.,]\d+)?)\s*"
        r"(?P<unit>kgmm2|kgm2|unitless|deg|rad|kg|mm|m|s)\b"
    )
```

**2.3b** — Add `_sqrt`, `_tan`, `_pow` methods to `ExpressionService`. Add them to `_environment()`.

Replace `_environment` method (lines 59-67):

```python
    def _environment(self) -> dict[str, object]:
        env: dict[str, object] = {}
        for unit in self.unit_service.known_units():
            env[unit] = self.unit_service.quantity(1.0, unit)
        env["pi"] = Quantity(math.pi, {})
        env["sin"] = self._sin
        env["cos"] = self._cos
        env["abs"] = self._abs
        env["sqrt"] = self._sqrt
        env["tan"] = self._tan
        env["pow"] = self._pow
        return env
```

Add these three methods after `_abs` (after line 139):

```python
    def _sqrt(self, value: Quantity) -> Quantity:
        if value.value_si < 0:
            raise ValueError("sqrt requires a non-negative value")
        halved = {dim: exp // 2 for dim, exp in value.dimensions.items() if exp % 2 == 0}
        if len(halved) != len(value.dimensions):
            raise ValueError("sqrt requires all dimension exponents to be even")
        return Quantity(math.sqrt(value.value_si), halved)

    def _tan(self, value: Quantity) -> Quantity:
        if not value.is_pure(Dimension.ANGLE):
            raise ValueError("tan expects an angle")
        return Quantity(math.tan(value.value_si), {})

    def _pow(self, base: Quantity, exponent: Quantity) -> Quantity:
        if not exponent.is_unitless():
            raise ValueError("pow exponent must be unitless")
        if not base.is_unitless():
            raise ValueError("pow base must be unitless")
        return Quantity(base.value_si ** exponent.value_si, {})
```

**Note on `_sqrt` semantics:** `sqrt(100 mm * 100 mm)` = `sqrt(Quantity(1e-4, {LENGTH:2}))`. Halving exponents: `{LENGTH:1}`. Result: `Quantity(1e-2, {LENGTH:1})` = 10 mm. This is dimensionally consistent.

- [ ] **Step 2.4: Run tests to verify they pass**

```
pytest tests/test_expressions.py -v
```

Expected: all PASS.

- [ ] **Step 2.5: Run full test suite**

```
pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 2.6: Commit**

```
git add quino/services/expressions.py tests/test_expressions.py
git commit -m "feat: add kgmm2/kgm2 unit tokens and sqrt/tan/pow to expression engine"
```

---

## Task 3: Wire inertia to Dimension.INERTIA in the service layer

**Files:**
- Modify: `quino/application/service.py`
- Modify: `tests/test_application.py`

This task changes the dimension and default unit for the `"inertia"` property path so that new `ScalarProperty` objects use `Dimension.INERTIA` and unit `"kgmm2"`. Existing projects serialised with `"expected_dimension": "unitless"` will continue loading without error (their `ScalarProperty` still has `UNITLESS`, which is preserved by the JSON loader).

- [ ] **Step 3.1: Write failing tests**

Append to `tests/test_application.py` (after the last test function, before EOF):

```python
def test_body_inertia_accepts_kgmm2_expression() -> None:
    app = make_app()
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "P")])
    body = app._find_body(body_id)
    app.update_property(body.id, "inertia", PropertyValueInput("expression", "250 kgmm2"))
    assert body.inertia is not None
    assert body.inertia.expected_dimension is Dimension.INERTIA
    result = app.expression_service.evaluate_property(body.inertia, app.project.parameters)
    assert result.value == pytest.approx(250.0)
    assert result.unit == "kgmm2"


def test_body_inertia_rejects_plain_length_expression() -> None:
    app = make_app()
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "P")])
    body = app._find_body(body_id)
    with pytest.raises(ValueError):
        app.update_property(body.id, "inertia", PropertyValueInput("expression", "50 mm"))


def test_body_inertia_default_unit_is_kgmm2() -> None:
    app = make_app()
    body_id = app.create_body("Block", [MarkerInput("0 mm", "0 mm", "P")])
    body = app._find_body(body_id)
    app.update_property(body.id, "inertia", PropertyValueInput("expression", "500 kgmm2"))
    assert body.inertia.unit == "kgmm2"
```

Check which imports `test_application.py` already has; add `Dimension` to its imports if missing (it's from `quino.domain.types`).

- [ ] **Step 3.2: Run tests to verify they fail**

```
pytest tests/test_application.py::test_body_inertia_accepts_kgmm2_expression tests/test_application.py::test_body_inertia_rejects_plain_length_expression tests/test_application.py::test_body_inertia_default_unit_is_kgmm2 -v
```

Expected: FAIL — currently `"inertia"` is mapped to `Dimension.UNITLESS` so `"250 kgmm2"` raises a dimension mismatch.

- [ ] **Step 3.3: Update `quino/application/service.py`**

**3.3a** — In `_build_validated_scalar_property` (line ~1398), change the inertia entry in `dimension_map`:

Old:
```python
            "inertia": Dimension.UNITLESS,
```

New:
```python
            "inertia": Dimension.INERTIA,
```

**3.3b** — Change the default unit assignment for inertia (lines ~1405-1406):

Old:
```python
        if property_path == "inertia":
            unit = "unitless"
```

New:
```python
        if property_path == "inertia":
            unit = "kgmm2"
```

- [ ] **Step 3.4: Run the three new tests**

```
pytest tests/test_application.py::test_body_inertia_accepts_kgmm2_expression tests/test_application.py::test_body_inertia_rejects_plain_length_expression tests/test_application.py::test_body_inertia_default_unit_is_kgmm2 -v
```

Expected: all PASS.

- [ ] **Step 3.5: Run full test suite**

```
pytest --tb=short -q
```

Expected: all pass. If any test that sets inertia as a bare number (e.g., `"0.5"`) fails, find that test and update the expression to `"0.5 kgmm2"`.

- [ ] **Step 3.6: Commit**

```
git add quino/application/service.py tests/test_application.py
git commit -m "feat: wire body inertia to Dimension.INERTIA with default unit kgmm2"
```

---

## Task 4: Property inspector — dimension tooltips and friendly error messages

**Files:**
- Modify: `quino/gui/main_window.py`

This task makes two GUI improvements:
1. Each editable expression row in the inspector gets a tooltip on the **Property** cell showing the expected dimension (e.g., `"Expected: length"`).
2. `_evaluate_scalar` returns a friendlier message when the expression fails because a unit is missing (bare number in a dimensioned field).

Neither change requires new application-layer code. No new tests are needed beyond manual verification; the existing `test_gui.py` suite covers the inspector render path.

- [ ] **Step 4.1: Understand the inspector row structure**

In `main_window.py`, `_build_entity_rows` returns a list of tuples. Each row has the form:

```python
(group, label, value, kind, evaluated)
```

The method is called at line ~1700. Each call to `prop(...)` is defined as a local helper at the top of `_build_entity_rows`:

```python
def prop(label, path, value, kind, evaluated):
    rows.append((label, path, value, kind, evaluated))
```

The inspector is populated in `_refresh_inspector` (search for where `inspector.setItem` is called with these tuples). Locate how the **Property** column cell (`column 0`) is created. Add `setToolTip` there.

- [ ] **Step 4.2: Add dimension hint to the inspector property column**

Find `_refresh_inspector` (search for `self.inspector.setItem`). Locate the block that creates the property-column cell for expression rows. It will look roughly like:

```python
label_item = QtWidgets.QTableWidgetItem(label)
self.inspector.setItem(row_idx, 0, label_item)
```

Add a tooltip mapping from property path to expected dimension. Insert this dict near the top of `_refresh_inspector` (or as a module-level constant):

```python
_PROPERTY_DIMENSION_HINTS: dict[str, str] = {
    "x": "length (e.g. 50 mm)",
    "y": "length (e.g. 50 mm)",
    "origin_x": "length (e.g. 50 mm)",
    "origin_y": "length (e.g. 50 mm)",
    "travel_min": "length (e.g. 50 mm)",
    "travel_max": "length (e.g. 50 mm)",
    "angle": "angle (e.g. 90 deg)",
    "mass": "mass (e.g. 1.5 kg)",
    "inertia": "inertia (e.g. 250 kgmm2)",
    "radius": "length (e.g. 25 mm)",
    "value": "see constraint type",
    "law": "angle or length (e.g. 90 deg * t / 1 s)",
}
```

Then after `label_item = QtWidgets.QTableWidgetItem(label)`, add:

```python
hint = _PROPERTY_DIMENSION_HINTS.get(path)
if hint:
    label_item.setToolTip(hint)
```

Place the dict as a **module-level constant** just before the `MainWindow` class definition (search for `class MainWindow`). Use the exact name `_PROPERTY_DIMENSION_HINTS`.

- [ ] **Step 4.3: Improve `_evaluate_scalar` error messages**

Find `_evaluate_scalar` at line ~1874. The current except block is:

```python
        except Exception as exc:
            return f"ERROR: {exc}"
```

Replace it with:

```python
        except Exception as exc:
            msg = str(exc)
            if "but got unitless" in msg:
                unit_hint = scalar.unit if hasattr(scalar, "unit") else "mm"
                return f"Missing unit — e.g. 1 {unit_hint}"
            return f"ERROR: {msg}"
```

- [ ] **Step 4.4: Run the test suite**

```
pytest --tb=short -q
```

Expected: all pass (no logic changes, only display text).

- [ ] **Step 4.5: Commit**

```
git add quino/gui/main_window.py
git commit -m "feat: add dimension tooltips and friendly unit error in property inspector"
```

---

## Task 5: Driver law dialog — convention hint

**Files:**
- Modify: `quino/gui/canvas.py`

The driver law edit dialog (`_edit_driver_law_dialog` at line ~3948) uses a plain `QInputDialog.getText()` with no guidance. Because `t` carries a TIME dimension, the correct pattern to get a pure-angle law is `"90 deg * t / 1 s"` (dividing by `1 s` cancels the time dimension). This task adds a label explaining the convention.

- [ ] **Step 5.1: Locate the driver law dialog in `canvas.py`**

Find `_edit_driver_law_dialog` (line ~3948). Current implementation:

```python
    def _edit_driver_law_dialog(self, driver_id: str) -> None:
        driver = self.app_service.get_entity(driver_id)
        if driver is None or not hasattr(driver, "law"):
            return
        name, accepted = QtWidgets.QInputDialog.getText(self, "Driver Law", "Law:", text=driver.law.expression)
        if not accepted:
            return
        self.app_service.update_property(driver_id, "law", PropertyValueInput("expression", name.strip()))
```

- [ ] **Step 5.2: Replace with a QDialog that includes a hint label**

Replace the method body with:

```python
    def _edit_driver_law_dialog(self, driver_id: str) -> None:
        driver = self.app_service.get_entity(driver_id)
        if driver is None or not hasattr(driver, "law"):
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Edit Driver Law")
        layout = QtWidgets.QVBoxLayout(dialog)

        hint = QtWidgets.QLabel(
            "Expression for position/angle as a function of time.\n"
            "Use <b>t</b> for time (has unit <i>s</i>).\n"
            "Examples: &nbsp;<code>90 deg * t / 1 s</code> &nbsp;|&nbsp; <code>50 mm * sin(t * 1 rad / 1 s)</code>"
        )
        hint.setWordWrap(True)
        hint.setTextFormat(QtCore.Qt.TextFormat.RichText)
        layout.addWidget(hint)

        form = QtWidgets.QFormLayout()
        law_edit = QtWidgets.QLineEdit(driver.law.expression)
        form.addRow("Law:", law_edit)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        self.app_service.update_property(driver_id, "law", PropertyValueInput("expression", law_edit.text().strip()))
```

- [ ] **Step 5.3: Run the test suite**

```
pytest --tb=short -q
```

Expected: all pass. The existing `test_canvas_helpers_can_rename_joint_toggle_type_and_edit_driver` test in `test_gui.py` (line ~742) calls `_edit_driver_law_dialog` via monkeypatch — verify it still works. If the test directly calls `QInputDialog.getText`, it will need updating to patch `QDialog.exec` instead. Check and fix if needed.

- [ ] **Step 5.4: Fix test if it breaks**

Open `tests/test_gui.py` and find the test at line ~742. If it patches `QInputDialog.getText`, change it to patch `QtWidgets.QDialog.exec` to return `QDialog.DialogCode.Accepted` and set the law edit field text directly. The existing test at line 779 asserts `law.expression == "45 deg * t / 1 s"` — confirm that assertion still holds after patching.

- [ ] **Step 5.5: Run tests again after any fix**

```
pytest tests/test_gui.py -v -k "driver"
```

Expected: PASS.

- [ ] **Step 5.6: Commit**

```
git add quino/gui/canvas.py tests/test_gui.py
git commit -m "feat: replace driver law plain dialog with a form that shows the t convention"
```

---

## Self-Review

**Spec coverage check:**

| Issue from analysis | Task |
|---|---|
| `inertia` classified as UNITLESS (semantic error) | Task 1 + Task 3 |
| Driver law `t` / convention undocumented | Task 5 |
| Limited unit vocabulary for inertia | Task 1 + Task 2 |
| Missing math functions `sqrt`, `tan`, `pow` | Task 2 |
| Property panel: no expected-unit guidance | Task 4 |
| Property panel: opaque "Expected X but got unitless" error | Task 4 |

**Out of scope (separate plan):**
- Global unit system preference (mm vs m project-level toggle)
- Sensor output unit configuration  
- Compound velocity units (`mm/s`, `deg/s`) — requires larger refactor of simulation output pipeline

**Placeholder scan:** None found. All code blocks are complete and compilable.

**Type consistency:** `_PROPERTY_DIMENSION_HINTS` is declared module-level and referenced by path string keys that match exactly the `property_path` strings passed to `prop(...)` in `_build_entity_rows`. `Dimension.INERTIA` is used consistently across tasks 1–3. `kgmm2`/`kgm2` unit names are used consistently in the regex pattern, `_UNITS` dict, and test assertions.
