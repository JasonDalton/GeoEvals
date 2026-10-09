import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from geoevals.metrics import (
    AggregateValue,
    Metric,
    MetricValue,
    aggregate_values,
    bootstrap_ci,
    get_metric,
    register_metric,
    registered_metric_ids,
    registry,
)
from geoevals.validation import validate_run_result_document

EXAMPLE = Path(__file__).parent / "fixtures" / "run_results" / "example_run" / "result.json"


class AbsError(Metric):
    id = "value_abs_error"
    version = "1.0.0"
    units = "m"
    higher_is_better = False

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        error = abs(prediction["value"] - reference["value"])
        return MetricValue(error, error <= params["tolerance"], {"units": self.units})


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})


# --- interface -------------------------------------------------------------------------------


def test_metric_declares_interface() -> None:
    metric = AbsError()
    assert (metric.id, metric.version, metric.units, metric.higher_is_better) == (
        "value_abs_error",
        "1.0.0",
        "m",
        False,
    )
    value = metric.score({"value": 3.0}, {"value": 1.0}, {"tolerance": 1.0})
    assert value == MetricValue(2.0, False, {"units": "m"})
    assert value.to_dict() == {"value": 2.0, "passed": False, "detail": {"units": "m"}}


def test_metric_without_score_cannot_be_instantiated() -> None:
    class NoScore(Metric):
        id = "no_score"
        version = "1.0.0"
        units = "m"
        higher_is_better = False

    with pytest.raises(TypeError):
        NoScore()  # type: ignore[abstract]


def test_metric_value_passed_may_be_null() -> None:
    assert MetricValue(None, None).to_dict() == {"value": None, "passed": None, "detail": {}}


# --- registry --------------------------------------------------------------------------------


def test_register_and_get() -> None:
    metric = AbsError()
    register_metric(metric)
    assert get_metric("value_abs_error") is metric
    assert registered_metric_ids() == {"value_abs_error"}


def test_registry_rejects_duplicate_ids() -> None:
    register_metric(AbsError())
    with pytest.raises(
        ValueError, match=r"metric 'value_abs_error' is already registered \(version 1\.0\.0"
    ):
        register_metric(AbsError())
    assert registered_metric_ids() == {"value_abs_error"}


def test_registry_rejects_unknown_ids() -> None:
    register_metric(AbsError())
    with pytest.raises(ValueError, match=r"unknown metric 'nope' \(registered: value_abs_error\)"):
        get_metric("nope")


def test_unknown_id_with_empty_registry() -> None:
    with pytest.raises(ValueError, match=r"unknown metric 'nope' \(registered: none\)"):
        get_metric("nope")


def test_registry_rejects_bad_version_and_id() -> None:
    class BadVersion(AbsError):
        version = "1.0"

    class BadId(AbsError):
        id = "Bad-Id"

    with pytest.raises(ValueError, match=r"version '1\.0' is not semver"):
        register_metric(BadVersion())
    with pytest.raises(ValueError, match="'Bad-Id' is not a lower_snake_case identifier"):
        register_metric(BadId())
    assert registered_metric_ids() == frozenset()


# --- aggregation -----------------------------------------------------------------------------


def test_aggregate_empty_list() -> None:
    assert AbsError().aggregate([]) == AggregateValue(
        mean=None, median=None, n=0, n_failed=0, ci_low=None, ci_high=None
    )


def test_aggregate_all_null_values_counts_failures() -> None:
    values = [MetricValue(None, False), MetricValue(None, None)]
    assert aggregate_values(values) == AggregateValue(None, None, 0, 1, None, None)


def test_aggregate_statistics() -> None:
    values = [
        MetricValue(1.0, True),
        MetricValue(2.0, True),
        MetricValue(6.0, False),
        MetricValue(None, False),
    ]
    agg = aggregate_values(values)
    assert (agg.mean, agg.median, agg.n, agg.n_failed) == (3.0, 2.0, 3, 2)
    assert agg.mean is not None and agg.ci_low is not None and agg.ci_high is not None
    assert 1.0 <= agg.ci_low <= agg.mean <= agg.ci_high <= 6.0


def test_aggregate_single_value_has_degenerate_interval() -> None:
    agg = aggregate_values([MetricValue(4.0, True)])
    assert (agg.mean, agg.median, agg.ci_low, agg.ci_high) == (4.0, 4.0, 4.0, 4.0)


def test_bootstrap_is_reproducible_for_fixed_seed() -> None:
    data = [0.3, 1.7, 2.2, 5.9, 0.1, 3.3, 8.4, 2.0]
    values = [MetricValue(x, None) for x in data]
    assert aggregate_values(values) == aggregate_values(values)
    assert bootstrap_ci(data, seed=7) == bootstrap_ci(data, seed=7)
    assert bootstrap_ci(data, seed=7) != bootstrap_ci(data, seed=8)
    assert bootstrap_ci([]) is None


# --- run result ------------------------------------------------------------------------------


def test_summary_records_version_and_validates_in_run_result() -> None:
    metric = AbsError()
    values = [
        metric.score({"value": 0.0}, {"value": 0.0}, {"tolerance": 1.0}),
        metric.score({"value": 5021.3}, {"value": 0.0}, {"tolerance": 1.0}),
    ]
    summary = metric.summary(metric.aggregate(values))
    assert summary["version"] == "1.0.0"
    assert set(summary) == {"version", "mean", "median", "n", "n_failed", "ci_low", "ci_high"}

    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    doc["summary_metrics"] = {metric.id: summary}
    for case, value in zip(doc["cases"][:2], values, strict=True):
        case["metrics"] = {metric.id: value.to_dict()}
    assert validate_run_result_document(doc) == []
