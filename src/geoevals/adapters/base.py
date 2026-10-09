"""The adapter protocol that every model, classical method, or agent implements."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TokenUsage:
    """Token counts for one ``predict`` call. Same fields as ``tokens`` in a run result."""

    input: int
    output: int

    def __post_init__(self) -> None:
        if self.input < 0 or self.output < 0:
            raise ValueError(f"token counts must be >= 0, got {self.input}/{self.output}")


@dataclass(frozen=True)
class AdapterResponse:
    """What an adapter returns for one case.

    ``trajectory`` holds the agent's tool-call records in order (US-020 defines their fields).
    ``raw`` is free-form debugging data; it is not scored.
    """

    output: dict[str, Any]
    tokens: TokenUsage | None = None
    trajectory: list[dict[str, Any]] | None = None
    raw: Any = None


@runtime_checkable
class Adapter(Protocol):
    """A model, classical method, or agent that the runner can call for each case.

    The runner calls ``setup`` once with the adapter config, ``predict`` once per attempt for
    each case, and ``teardown`` once at the end. ``predict`` signals a failed case by raising.
    """

    name: str
    version: str

    def setup(self, config: Mapping[str, Any]) -> None: ...

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse: ...

    def teardown(self) -> None: ...
