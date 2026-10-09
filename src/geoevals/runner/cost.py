"""Price table (YAML) and per-case cost.

A price table maps adapter name to its prices::

    mock:
      usd_per_1k_input_tokens: 0.0
      usd_per_1k_output_tokens: 0.0
      usd_per_call: 0.0

A case's cost is ``calls * usd_per_call`` plus the token prices applied to the tokens the adapter
reported. ``calls`` counts every attempt, retries included. Only the tokens of the last attempt
are recorded, so the token part covers that attempt only.

Rules (FR-17: a missing price gives ``null``, never ``0``):

- A deterministic adapter (class attribute ``deterministic = True``) makes no paid calls, so
  every case costs ``0.0`` whether or not the table lists it.
- An adapter that is missing from the table gives ``null`` for every case and for the totals.
- A case without token counts (for example a timeout) gives ``null`` when a token price is not
  zero, because the token part is unknown.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PriceTableError(ValueError):
    """The price table is invalid."""


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    usd_per_1k_input_tokens: float = Field(ge=0, allow_inf_nan=False)
    usd_per_1k_output_tokens: float = Field(ge=0, allow_inf_nan=False)
    usd_per_call: float = Field(ge=0, allow_inf_nan=False)


@dataclass(frozen=True)
class PriceTable:
    prices: dict[str, Price]
    hash: str
    """SHA-256 of the canonical JSON of the table (sorted keys), so comments and layout do not
    change it."""


def parse_price_table(document: Any) -> PriceTable:
    """Validate a parsed price table. Raises ``PriceTableError`` if it is invalid."""
    if not isinstance(document, Mapping):
        raise PriceTableError("price table must be a mapping of adapter name to prices")
    prices: dict[str, Price] = {}
    for name, entry in document.items():
        if not isinstance(name, str):
            raise PriceTableError(f"adapter name must be a string, got {name!r}")
        if not isinstance(entry, Mapping):
            raise PriceTableError(f"{name}: prices must be a mapping")
        try:
            prices[name] = Price.model_validate(dict(entry))
        except ValidationError as exc:
            raise PriceTableError(f"{name}: invalid prices: {exc}") from exc
    canonical = {name: price.model_dump() for name, price in prices.items()}
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return PriceTable(prices, hashlib.sha256(text.encode("utf-8")).hexdigest())


def load_price_table(path: Path) -> PriceTable:
    """Load and validate a YAML price table."""
    # Imported here: geoevals.validation imports the metric registry; keep this module light.
    from geoevals.validation.validate import load_yaml

    return parse_price_table(load_yaml(path))


def case_cost(price: Price | None, deterministic: bool, calls: int, tokens: Any) -> float | None:
    """Return the cost of one case. ``tokens`` is the record's ``{"input", "output"}`` or None."""
    if deterministic:
        return 0.0
    if price is None:
        return None
    cost = calls * price.usd_per_call
    token_priced = price.usd_per_1k_input_tokens > 0 or price.usd_per_1k_output_tokens > 0
    if tokens is None:
        return None if token_priced else cost
    cost += tokens["input"] / 1000 * price.usd_per_1k_input_tokens
    cost += tokens["output"] / 1000 * price.usd_per_1k_output_tokens
    return cost
