import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from quino.domain.workspace import SweepDef
from quino.gui.widgets.sweep_slider_row import SweepSliderRow


def test_row_emits_index_changed() -> None:
    sweep = SweepDef(
        id="sw1",
        variable_kind="marker_x",
        target_ids=["m"],
        mode="linear",
        start=0.0,
        end=10.0,
        steps=11,
        label="m.x",
    )
    row = SweepSliderRow(sweep)
    events: list[int] = []
    row.index_changed.connect(events.append)
    row._slider.setValue(5)
    assert events == [5]
    assert "m.x" in row._title_label.text()


def test_row_edit_button_emits_signal() -> None:
    sweep = SweepDef(id="sw1", variable_kind="marker_x", target_ids=["m"], mode="linear", start=0.0, end=10.0, steps=11)
    row = SweepSliderRow(sweep)
    edits: list[str] = []
    row.edit_requested.connect(edits.append)
    row._edit_btn.click()
    assert edits == ["sw1"]
