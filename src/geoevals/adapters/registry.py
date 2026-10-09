"""Registry of adapters by name, used by ``--adapter <name>``."""

from collections.abc import Callable, Set

from geoevals.adapters.base import Adapter

AdapterFactory = Callable[[], Adapter]

_REGISTRY: dict[str, AdapterFactory] = {}
"""Registered adapter name -> factory that returns a new, not yet set up adapter."""


def register_adapter(name: str, factory: AdapterFactory) -> None:
    """Register ``factory`` under ``name``. Raises ``ValueError`` on a duplicate name."""
    if name in _REGISTRY:
        raise ValueError(f"adapter {name!r} is already registered")
    _REGISTRY[name] = factory


def registered_adapter_names() -> Set[str]:
    """Return the names of all registered adapters."""
    return frozenset(_REGISTRY)


def adapter_factory(name: str) -> AdapterFactory:
    """Return the factory registered as ``name``. Raises ``ValueError`` for an unknown name.

    The runner sends the factory to its worker processes, so it must be picklable (for example a
    module-level class).
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise ValueError(f"unknown adapter {name!r} (registered: {known})") from None


def create_adapter(name: str) -> Adapter:
    """Return a new adapter registered as ``name``. Raises ``ValueError`` for an unknown name."""
    return adapter_factory(name)()
