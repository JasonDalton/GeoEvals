"""GeoEvals adapters package."""

from geoevals.adapters.base import Adapter, AdapterResponse, TokenUsage
from geoevals.adapters.gis_baseline import GisBaselineAdapter, UnsupportedOperation
from geoevals.adapters.mock import MockAdapter, MockAdapterError, MockConfigError
from geoevals.adapters.registry import (
    adapter_factory,
    create_adapter,
    register_adapter,
    registered_adapter_names,
)

register_adapter(MockAdapter.name, MockAdapter)
register_adapter(GisBaselineAdapter.name, GisBaselineAdapter)

__all__ = [
    "Adapter",
    "AdapterResponse",
    "GisBaselineAdapter",
    "MockAdapter",
    "MockAdapterError",
    "MockConfigError",
    "TokenUsage",
    "UnsupportedOperation",
    "adapter_factory",
    "create_adapter",
    "register_adapter",
    "registered_adapter_names",
]
