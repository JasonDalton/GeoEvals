"""Metrics for network access answers (the human-context pillar).

They compare an answer with its reference and need no network, so they are registered without
the ``geoevals[network]`` extra; the references are computed with ``geoevals.metrics.network``.

An answer is ``{status, value, units}``; a reachable-set answer also has ``ids``, the list of
reachable point-of-interest IDs. A metric applies to a case only when the reference has what it
checks: ``travel_time_abs_error_s`` a numeric ``value`` in ``units: s``,
``reachable_count_error`` in ``units: count``, ``route_stretch_abs_error`` in ``units: ratio``
and ``reachable_set_jaccard`` an ``ids`` list. Tolerance params (inclusive): ``time_tol_s``
(seconds), ``count_tol`` (count), ``stretch_tol`` (unitless), all default 0.0, and
``min_jaccard`` (default 1.0). The full definitions are in ``docs/metrics.md``.
"""

from collections.abc import Mapping
from typing import Any

from geoevals.metrics.base import Metric, MetricValue
from geoevals.metrics.gis import NOT_APPLICABLE, _document, _value_pair


def _abs_error(
    pred: Mapping[str, Any], ref: Mapping[str, Any], units: str, tolerance: float
) -> MetricValue:
    """``|pred.value - ref.value|`` when the reference value is in ``units``, passed when
    <= ``tolerance``."""
    if ref.get("units") != units:
        return NOT_APPLICABLE
    pair = _value_pair(pred, ref)
    if pair is None:
        return NOT_APPLICABLE
    if isinstance(pair, MetricValue):
        return pair
    predicted, expected = pair
    error = abs(predicted - expected)
    passed = error <= tolerance
    detail: dict[str, Any] = {"signed_error": predicted - expected}
    if not passed:
        detail.update(predicted=predicted, expected=expected, tolerance=tolerance)
    return MetricValue(error, passed, detail)


class TravelTimeAbsError(Metric):
    """Absolute error of a walking travel time in seconds, passed when <= ``time_tol_s``."""

    id = "travel_time_abs_error_s"
    version = "1.0.0"
    units = "s"
    higher_is_better = False

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        tolerance = float(params.get("time_tol_s", 0.0))
        return _abs_error(_document(prediction), _document(reference), "s", tolerance)


class ReachableCountError(Metric):
    """Absolute error of a reachable-destination count, passed when <= ``count_tol``."""

    id = "reachable_count_error"
    version = "1.0.0"
    units = "count"
    higher_is_better = False

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        tolerance = float(params.get("count_tol", 0.0))
        return _abs_error(_document(prediction), _document(reference), "count", tolerance)


class RouteStretchAbsError(Metric):
    """Absolute error of a network detour ratio (unitless), passed when <= ``stretch_tol``."""

    id = "route_stretch_abs_error"
    version = "1.0.0"
    units = "ratio"
    higher_is_better = False

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        tolerance = float(params.get("stretch_tol", 0.0))
        return _abs_error(_document(prediction), _document(reference), "ratio", tolerance)


def _is_id(value: Any) -> bool:
    return isinstance(value, str | int) and not isinstance(value, bool)


def _sorted_ids(ids: set[Any]) -> list[Any]:
    """IDs in a stable order (numbers before strings)."""
    return sorted(ids, key=lambda value: (isinstance(value, str), value))


class ReachableSetJaccard(Metric):
    """Jaccard index of the predicted and reference reachable ID sets, passed when
    >= ``min_jaccard``."""

    id = "reachable_set_jaccard"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        pred, ref = _document(prediction), _document(reference)
        expected_ids = ref.get("ids")
        if not isinstance(expected_ids, list):
            return NOT_APPLICABLE
        predicted_ids = pred.get("ids")
        if not isinstance(predicted_ids, list) or not all(_is_id(i) for i in predicted_ids):
            return MetricValue(None, False, {"reason": "missing_ids", "predicted": predicted_ids})
        predicted, expected = set(predicted_ids), set(expected_ids)
        union = predicted | expected
        jaccard = len(predicted & expected) / len(union) if union else 1.0
        minimum = float(params.get("min_jaccard", 1.0))
        passed = jaccard >= minimum
        detail: dict[str, Any] = {}
        if missing := expected - predicted:
            detail["missing"] = _sorted_ids(missing)
        if extra := predicted - expected:
            detail["extra"] = _sorted_ids(extra)
        if len(predicted_ids) != len(predicted):
            detail["duplicates"] = True
        if not passed:
            detail["min_jaccard"] = minimum
        return MetricValue(jaccard, passed, detail)


ACCESS_METRICS: tuple[Metric, ...] = (
    TravelTimeAbsError(),
    ReachableCountError(),
    ReachableSetJaccard(),
    RouteStretchAbsError(),
)
"""The network access metrics registered in ``geoevals.metrics``."""
