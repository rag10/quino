from __future__ import annotations

import textwrap
import threading
from datetime import datetime, timezone
from typing import Any

import numpy as np

from quino.domain.workspace import Metric, MetricResult

# ---------------------------------------------------------------------------
# NEW evaluator: user-written Python code via restricted exec
# ---------------------------------------------------------------------------

_SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
    "range": range, "enumerate": enumerate, "zip": zip, "map": map,
    "filter": filter, "sorted": sorted, "round": round, "float": float,
    "int": int, "bool": bool, "str": str, "list": list, "tuple": tuple,
    "dict": dict, "set": set, "any": any, "all": all,
}

_TIMEOUT_S = 5.0


def _cast(value: Any, value_type: str) -> Any:
    if value_type == "float":
        return float(value)
    if value_type == "int":
        return int(value)
    if value_type == "bool":
        return bool(value)
    if value_type == "str":
        return str(value)
    return value


def _build_callable(code: str):
    body = textwrap.indent(code if code.strip() else "return None", "    ")
    source = f"def _evaluate(data, meta):\n{body}\n"
    globals_ns = {"__builtins__": _SAFE_BUILTINS, "np": np}
    compiled = compile(source, "<metric>", "exec")
    exec(compiled, globals_ns)  # noqa: S102 - restricted namespace
    return globals_ns["_evaluate"]


def evaluate(metric: Metric, data: dict[str, Any], meta: dict[str, Any]) -> MetricResult:
    now = datetime.now(tz=timezone.utc).isoformat()
    holder: dict[str, Any] = {}

    def _target() -> None:
        try:
            fn = _build_callable(metric.code)
            raw = fn(data, meta)
            holder["value"] = _cast(raw, metric.value_type)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout=_TIMEOUT_S)
    if worker.is_alive():
        # Known limitation: a CPU-bound runaway metric cannot be cancelled, so
        # the daemon thread keeps running (and pins its closure) until process
        # exit. Acceptable for a local single-user desktop app.
        return MetricResult(value=None, status="error",
                            error=f"evaluation exceeded {_TIMEOUT_S}s", evaluated_at=now)
    if "error" in holder:
        return MetricResult(value=None, status="error", error=holder["error"], evaluated_at=now)
    return MetricResult(value=holder.get("value"), status="ok", evaluated_at=now)


def evaluate_all(analysis: Any, data: dict[str, Any], meta: dict[str, Any]) -> None:
    for metric in analysis.metrics:
        if not data:
            metric.result = MetricResult(value=None, status="no_data",
                                         evaluated_at=datetime.now(tz=timezone.utc).isoformat())
        else:
            metric.result = evaluate(metric, data, meta)

