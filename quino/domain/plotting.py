from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class YSeries:
    sensor_id: str
    channel: str = ""
    label: str = ""
    color: str = ""


@dataclass(slots=True)
class PlotDef:
    id: str
    title: str
    x_kind: str = "time"
    x_target: str = ""
    y_series: list[YSeries] = field(default_factory=list)
    style: dict = field(default_factory=dict)


@dataclass(slots=True)
class MetricDef:
    id: str
    key: str
    name: str
    kind: str = "max"
    target: str = ""
    params: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
