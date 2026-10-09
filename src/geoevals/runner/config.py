"""Run config (YAML) and its canonical SHA-256 hash.

A run config looks like::

    split: test           # required; a split named in the benchmark spec
    seed: 0               # seeds Python's `random` for each case
    timeout_s: 60         # per case, for each attempt
    max_retries: 0        # extra attempts after an adapter_error
    workers: 1            # cases run at the same time, each in its own worker process
    adapter: {}           # passed to the adapter's setup()
"""

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from geoevals.validation.benchmark import IDENTIFIER_PATTERN


class RunConfigError(ValueError):
    """The run config is invalid."""


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, regex_engine="python-re")

    split: str = Field(pattern=IDENTIFIER_PATTERN)
    seed: int = 0
    timeout_s: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=0, ge=0)
    workers: int = Field(default=1, ge=1)
    adapter: dict[str, Any] = Field(default_factory=dict)


def parse_run_config(document: Any) -> RunConfig:
    """Validate a parsed run config. Raises ``RunConfigError`` if it is invalid."""
    if not isinstance(document, Mapping):
        raise RunConfigError("run config must be a mapping")
    try:
        return RunConfig.model_validate(dict(document))
    except ValidationError as exc:
        raise RunConfigError(f"invalid run config: {exc}") from exc


def load_run_config(path: Path) -> RunConfig:
    """Load and validate a YAML run config."""
    # Imported here: geoevals.validation imports the metric registry; keep this module light.
    from geoevals.validation.validate import load_yaml

    return parse_run_config(load_yaml(path))


def _normalize(value: Any) -> Any:
    """Map ``value`` to plain JSON types, with integral floats as ints (``1.0`` -> ``1``)."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RunConfigError(f"run config contains a non-finite number: {value!r}")
        return int(value) if value.is_integer() else value
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize(item) for item in value]
    raise RunConfigError(f"run config contains a value that is not JSON: {value!r}")


def canonical_config(config: RunConfig) -> dict[str, Any]:
    """Return the resolved config (defaults filled in) with normalized types."""
    return _normalize(config.model_dump(mode="python"))


def config_hash(config: RunConfig) -> str:
    """SHA-256 of the canonical config, serialized as compact JSON with sorted keys."""
    text = json.dumps(
        canonical_config(config),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
