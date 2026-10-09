"""Registry of metric IDs.

Benchmark specs reference metrics by ID; validation rejects IDs that are not registered here.
"""

from collections.abc import Set

_REGISTRY: dict[str, str] = {}
"""Registered metric ID -> metric version."""


def register_metric(metric_id: str, version: str) -> None:
    """Register ``metric_id`` at ``version``. Raises ``ValueError`` on a duplicate ID."""
    if metric_id in _REGISTRY:
        raise ValueError(f"metric {metric_id!r} is already registered")
    _REGISTRY[metric_id] = version


def registered_metric_ids() -> Set[str]:
    """Return the IDs of all registered metrics."""
    return frozenset(_REGISTRY)
