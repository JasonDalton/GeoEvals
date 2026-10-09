"""Registry of metrics by ID.

Benchmark specs reference metrics by ID; validation rejects IDs that are not registered here.
"""

import re
from collections.abc import Set
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from geoevals.metrics.base import Metric

_REGISTRY: dict[str, "Metric"] = {}
"""Registered metric ID -> metric."""


def register_metric(metric: "Metric") -> None:
    """Register ``metric`` under its ID.

    Raises ``ValueError`` for a duplicate ID, an ID that is not lower_snake_case, or a version
    that is not semver.
    """
    # Imported here: geoevals.validation imports this module, so a top-level import is circular.
    from geoevals.validation.benchmark import IDENTIFIER_PATTERN, SEMVER_PATTERN

    if not re.match(IDENTIFIER_PATTERN, metric.id):
        raise ValueError(f"metric ID {metric.id!r} is not a lower_snake_case identifier")
    if not re.match(SEMVER_PATTERN, metric.version):
        raise ValueError(f"metric {metric.id!r} version {metric.version!r} is not semver")
    if metric.id in _REGISTRY:
        existing = _REGISTRY[metric.id]
        raise ValueError(
            f"metric {metric.id!r} is already registered "
            f"(version {existing.version}, {type(existing).__qualname__})"
        )
    _REGISTRY[metric.id] = metric


def get_metric(metric_id: str) -> "Metric":
    """Return the metric registered as ``metric_id``. Raises ``ValueError`` for an unknown ID."""
    try:
        return _REGISTRY[metric_id]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise ValueError(f"unknown metric {metric_id!r} (registered: {known})") from None


def registered_metric_ids() -> Set[str]:
    """Return the IDs of all registered metrics."""
    return frozenset(_REGISTRY)
