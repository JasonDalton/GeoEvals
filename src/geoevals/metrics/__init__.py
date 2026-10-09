"""GeoEvals metrics package."""

from geoevals.metrics.access import ACCESS_METRICS
from geoevals.metrics.base import (
    BOOTSTRAP_SEED,
    AggregateValue,
    Metric,
    MetricValue,
    aggregate_values,
    bootstrap_ci,
    percentile,
)
from geoevals.metrics.gis import SPATIAL_METRICS
from geoevals.metrics.registry import get_metric, register_metric, registered_metric_ids
from geoevals.metrics.status import StatusMatch

register_metric(StatusMatch())
for _metric in (*SPATIAL_METRICS, *ACCESS_METRICS):
    register_metric(_metric)

__all__ = [
    "BOOTSTRAP_SEED",
    "AggregateValue",
    "Metric",
    "MetricValue",
    "StatusMatch",
    "aggregate_values",
    "bootstrap_ci",
    "get_metric",
    "percentile",
    "register_metric",
    "registered_metric_ids",
]
