"""Metric interface: per-case scores, aggregates, and the bootstrap confidence interval.

A metric scores one prediction against one reference and aggregates the per-case scores over a
run. Metrics never see the adapter, so scoring stays independent of the system under test.
"""

import random
import statistics
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

BOOTSTRAP_SEED = 0
"""Fixed seed for the bootstrap, so the same values always give the same interval."""

BOOTSTRAP_RESAMPLES = 2000
CONFIDENCE_LEVEL = 0.95


@dataclass(frozen=True)
class MetricValue:
    """Score of one case. ``value`` is null when the metric could not compute a number."""

    value: float | None
    passed: bool | None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the run-result form (a case's ``metrics[<id>]`` entry)."""
        return asdict(self)


@dataclass(frozen=True)
class AggregateValue:
    """Aggregate of a metric over a run's cases.

    ``n`` counts the values that are not null; ``mean``, ``median`` and the confidence interval
    are computed over those and are null when ``n`` is 0. ``n_failed`` counts the values whose
    ``passed`` is false. ``ci_low``/``ci_high`` bound the 95% percentile bootstrap confidence
    interval of the mean.
    """

    mean: float | None
    median: float | None
    n: int
    n_failed: int
    ci_low: float | None
    ci_high: float | None


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile of already sorted values, ``q`` in [0, 1]."""
    position = (len(sorted_values) - 1) * q
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    fraction = position - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * fraction


def bootstrap_ci(
    values: Sequence[float],
    *,
    seed: int = BOOTSTRAP_SEED,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE_LEVEL,
) -> tuple[float, float] | None:
    """Percentile bootstrap confidence interval of the mean. Returns ``None`` for no values."""
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(n_resamples))
    alpha = (1 - confidence) / 2
    return _percentile(means, alpha), _percentile(means, 1 - alpha)


def aggregate_values(
    values: Sequence[MetricValue], *, seed: int = BOOTSTRAP_SEED
) -> AggregateValue:
    """Aggregate per-case metric values. An empty list gives ``n = 0`` and null statistics."""
    numbers = [v.value for v in values if v.value is not None]
    n_failed = sum(1 for v in values if v.passed is False)
    if not numbers:
        return AggregateValue(None, None, 0, n_failed, None, None)
    ci = bootstrap_ci(numbers, seed=seed)
    assert ci is not None
    return AggregateValue(
        mean=statistics.fmean(numbers),
        median=statistics.median(numbers),
        n=len(numbers),
        n_failed=n_failed,
        ci_low=ci[0],
        ci_high=ci[1],
    )


class Metric(ABC):
    """A versioned metric, registered by ``id``.

    Subclasses set ``id`` (lower_snake_case), ``version`` (semver; bump it whenever the
    semantics change), ``units`` and ``higher_is_better``, and implement ``score``.
    """

    id: ClassVar[str]
    version: ClassVar[str]
    units: ClassVar[str]
    higher_is_better: ClassVar[bool]

    @abstractmethod
    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        """Score one prediction against its reference."""

    def aggregate(self, values: Sequence[MetricValue]) -> AggregateValue:
        """Aggregate per-case values over a run."""
        return aggregate_values(values)

    def summary(self, aggregate: AggregateValue) -> dict[str, Any]:
        """Return the run-result ``summary_metrics[<id>]`` entry, which records the version."""
        return {"version": self.version, **asdict(aggregate)}
