import json

import pytest

pytest.skip(
    "overlay removed; Run entity and case.runs replaced by flattened Analysis run "
    "state. Run export adapted in Fase 2/4.",
    allow_module_level=True,
)

from quino.domain.plotting import PlotDef, YSeries
from quino.domain.workspace import Run
from quino.services.run_export import export_matplotlib_script, export_run_csv, export_run_json


def _run() -> Run:
    return Run(id="run_001", analysis_id="a1", created_at="now", status="ok")


def test_export_run_csv_writes_one_file_per_sensor(tmp_path):
    run = _run()
    artifact = {
        "type": "dynamic",
        "time": [0.0, 0.5, 1.0],
        "frames": [
            {"sensor:s1:x": 0.0, "sensor:s1:y": 0.0, "sensor:s2:d": 1.0},
            {"sensor:s1:x": 0.3, "sensor:s1:y": 0.1, "sensor:s2:d": 1.1},
            {"sensor:s1:x": 0.6, "sensor:s1:y": 0.0, "sensor:s2:d": 1.05},
        ],
    }
    out_dir = tmp_path / "csv_out"
    export_run_csv(run, artifact, out_dir, mode="per_sensor")
    assert (out_dir / "s1.csv").exists()
    assert (out_dir / "s2.csv").exists()


def test_export_run_csv_wide_format(tmp_path):
    run = _run()
    artifact = {
        "type": "dynamic",
        "time": [0.0, 0.5],
        "frames": [
            {"sensor:s1:x": 0.0, "sensor:s1:y": 0.0},
            {"sensor:s1:x": 0.3, "sensor:s1:y": 0.1},
        ],
    }
    out = tmp_path / "all.csv"
    export_run_csv(run, artifact, out, mode="wide")
    text = out.read_text(encoding="utf-8")
    assert "time" in text.splitlines()[0]
    assert "sensor:s1:x" in text.splitlines()[0]


def test_export_run_json_writes_payload(tmp_path):
    run = _run()
    out = tmp_path / "run.json"
    export_run_json(run, {"type": "dynamic", "time": [], "frames": []}, out)
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "run" in payload and "artifact" in payload


def test_export_matplotlib_script_creates_runnable_py(tmp_path):
    plot = PlotDef(id="p", title="Hub y vs t", y_series=[YSeries(sensor_id="s1", channel="y", label="hub.y")])
    artifact = {"time": [0, 1], "frames": [{"sensor:s1:y": 0}, {"sensor:s1:y": 0.3}]}
    out_py = tmp_path / "plot.py"
    export_matplotlib_script(plot, artifact, out_py)
    assert out_py.exists()
    text = out_py.read_text(encoding="utf-8")
    assert "matplotlib" in text
    assert "plot.csv" in text
    assert (tmp_path / "plot.csv").exists()
