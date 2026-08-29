"""Metric choices for the File-page monitoring graph."""

from __future__ import annotations

from dataclasses import dataclass

from carveracontroller.translation import tr

GRAPH_METRIC_NONE = "none"
GRAPH_METRIC_DEFAULT_LINE1 = "temp"
GRAPH_METRIC_DEFAULT_LINE2 = "spindle_power"


@dataclass(frozen=True)
class GraphMetric:
    key: str
    label: str
    cnc_var: str | None
    ylabel: str
    ymin: float
    ymax: float

    @property
    def visible(self) -> bool:
        return self.cnc_var is not None


GRAPH_METRICS = (
    GraphMetric(GRAPH_METRIC_NONE, "None", None, "", 0.0, 1.0),
    GraphMetric("temp", "Temp", "spindletemp", "Temp (°C)", 20.0, 60.0),
    GraphMetric("spindle_power", "Spindle Power", "spindle_pwm_request", "Spindle Power (%)", 0.0, 100.0),
    GraphMetric("spindle_rpm", "Spindle RPM", "curspindle", "Spindle RPM", 3000.0, 12000.0),
    GraphMetric("feed", "Feed", "curfeed", "Feed", 100.0, 1000.0),
)

GRAPH_METRICS_BY_KEY = {metric.key: metric for metric in GRAPH_METRICS}


def graph_metric_choices() -> list[str]:
    return [tr._(metric.label) for metric in GRAPH_METRICS]


def graph_metric_label(key: str) -> str:
    metric = GRAPH_METRICS_BY_KEY.get(key, GRAPH_METRICS_BY_KEY[GRAPH_METRIC_NONE])
    return tr._(metric.label)


def graph_metric_key_from_label(label: str) -> str:
    for metric in GRAPH_METRICS:
        if label in (tr._(metric.label), metric.label):
            return metric.key
    return GRAPH_METRIC_NONE


def graph_metric_ylim(key: str, samples: list[float] | tuple[float, ...] | None = None) -> tuple[float, float]:
    """Return the axis range, expanding the default min/max if samples fall outside it."""
    metric = GRAPH_METRICS_BY_KEY.get(key, GRAPH_METRICS_BY_KEY[GRAPH_METRIC_NONE])
    ymin, ymax = metric.ymin, metric.ymax
    if samples:
        ymin = min(ymin, min(samples))
        ymax = max(ymax, max(samples))
    return ymin, ymax
