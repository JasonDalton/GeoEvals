"""GeoEvals adapters package."""

from geoevals.adapters.access_baseline import AccessBaselineAdapter, UnsupportedAccessOperation
from geoevals.adapters.base import Adapter, AdapterResponse, SkipCase, TokenUsage
from geoevals.adapters.claude import ClaudeDirectAdapter, ClaudePythonAdapter, adapter_factories
from geoevals.adapters.gis_baseline import GisBaselineAdapter, UnsupportedOperation
from geoevals.adapters.mock import MockAdapter, MockAdapterError, MockConfigError
from geoevals.adapters.registry import (
    adapter_factory,
    create_adapter,
    register_adapter,
    registered_adapter_names,
)

register_adapter(MockAdapter.name, MockAdapter)
register_adapter(AccessBaselineAdapter.name, AccessBaselineAdapter)
register_adapter(GisBaselineAdapter.name, GisBaselineAdapter)
for _name, _factory in adapter_factories().items():
    register_adapter(_name, _factory)

__all__ = [
    "AccessBaselineAdapter",
    "Adapter",
    "AdapterResponse",
    "ClaudeDirectAdapter",
    "ClaudePythonAdapter",
    "GisBaselineAdapter",
    "MockAdapter",
    "MockAdapterError",
    "MockConfigError",
    "SkipCase",
    "TokenUsage",
    "UnsupportedAccessOperation",
    "UnsupportedOperation",
    "adapter_factory",
    "create_adapter",
    "register_adapter",
    "registered_adapter_names",
]
