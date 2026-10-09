"""GeoEvals adapters package."""

from geoevals.adapters.base import Adapter, AdapterResponse, TokenUsage
from geoevals.adapters.mock import MockAdapter, MockAdapterError, MockConfigError
from geoevals.adapters.registry import (
    create_adapter,
    register_adapter,
    registered_adapter_names,
)

register_adapter(MockAdapter.name, MockAdapter)

__all__ = [
    "Adapter",
    "AdapterResponse",
    "MockAdapter",
    "MockAdapterError",
    "MockConfigError",
    "TokenUsage",
    "create_adapter",
    "register_adapter",
    "registered_adapter_names",
]
