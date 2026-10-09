"""Mock adapter that returns scripted outputs and injects failures.

The config (usually loaded from YAML) chooses a behavior for each case::

    seed: 42
    tokens: {input: 120, output: 30}      # optional, reported on every response
    references:                           # reference output per case ID
      case-001: {area_m2: 12.5}
    default: {behavior: reference}
    cases:                                # per case ID; checked first
      case-002: {behavior: raise, message: boom}
      case-003: {behavior: sleep, seconds: 5}
      case-004: {behavior: fail_then_succeed, failures: 2}
    random:                               # by probability; checked when no case rule matches
      - {probability: 0.1, behavior: wrong}
      - {probability: 0.05, behavior: malformed, tokens: {input: 0, output: 0}}

Behaviors:

- ``reference``: return the case's reference output.
- ``wrong``: return ``output`` if given, else the reference with every number increased by 1,
  every bool flipped, and ``_wrong`` appended to every string (same shape, wrong values).
- ``malformed``: return ``output`` if given, else ``{"mock_malformed_output": true}``.
- ``raise``: raise ``MockAdapterError(message)`` (the runner records ``adapter_error``).
- ``skip``: raise ``SkipCase(message)`` (the runner records ``skipped``).
- ``sleep``: sleep ``seconds``, then return the reference output.
- ``fail_then_succeed``: raise on the first ``failures`` calls for the case, then return the
  reference output. The count is kept per adapter instance and reset by ``setup``.

``mode: mock_agent`` makes the adapter act as a scripted agent: every response also carries a
trajectory (see ``geoevals.trajectory``), shaped by the rule's ``script`` (default ``all_ok``)::

    mode: mock_agent
    max_steps: 6                          # loop guard: tool calls before the agent is stopped
    step_seconds: 0.01                    # duration_s recorded for each step (not slept)
    cases:
      case-001: {behavior: wrong, script: all_ok}
      case-002: {behavior: reference, script: error_then_recover}
      case-003: {behavior: malformed, script: loop_guard}

Scripts (tool steps call ``read_inputs`` and then a tool named after the case's ``operation``):

- ``all_ok``: every tool call succeeds, then a final-answer step (``tool: null``).
- ``error_then_recover``: the operation tool fails once, is called again and succeeds, then a
  final-answer step.
- ``loop_guard``: the agent repeats the same operation call until ``max_steps`` tool calls, then a
  guard step (``tool: null``, ``status: error``) stops it. The guard stops the agent before it
  answers, so the script needs behavior ``wrong`` or ``malformed``.

The script shapes only the trajectory; ``behavior`` still decides the output. So ``all_ok`` with
``wrong`` is an agent whose tool calls all succeed and whose answer is still wrong.

Each case draws one number from a ``random.Random`` seeded with ``"<seed>:<case_id>"``, so the
chosen behavior depends only on the seed and case ID, not on call order, retries, or workers.
The probability rules are tried in order against that draw; when none matches, ``default``
applies.
"""

import copy
import random
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from geoevals.adapters.base import AdapterResponse, SkipCase, TokenUsage

MockBehavior = Literal[
    "reference", "wrong", "malformed", "raise", "skip", "sleep", "fail_then_succeed"
]
MockMode = Literal["mock", "mock_agent"]
AgentScript = Literal["all_ok", "error_then_recover", "loop_guard"]

DEFAULT_MALFORMED_OUTPUT: dict[str, Any] = {"mock_malformed_output": True}


class MockAdapterError(RuntimeError):
    """The failure that the mock adapter raises on purpose."""


class MockConfigError(ValueError):
    """The mock adapter config is invalid, or a case cannot be served with it."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MockTokens(_Model):
    input: int = Field(ge=0)
    output: int = Field(ge=0)


class MockRule(_Model):
    behavior: MockBehavior = "reference"
    output: dict[str, Any] | None = None
    message: str = "mock adapter failure"
    seconds: float | None = Field(default=None, ge=0)
    failures: int | None = Field(default=None, ge=1)
    tokens: MockTokens | None = None
    script: AgentScript | None = None

    @model_validator(mode="after")
    def _check_behavior_fields(self) -> "MockRule":
        if self.behavior == "sleep" and self.seconds is None:
            raise ValueError("behavior 'sleep' requires 'seconds'")
        if self.behavior == "fail_then_succeed" and self.failures is None:
            raise ValueError("behavior 'fail_then_succeed' requires 'failures'")
        if self.output is not None and self.behavior not in ("wrong", "malformed"):
            raise ValueError("'output' applies only to behaviors 'wrong' and 'malformed'")
        if self.script == "loop_guard" and self.behavior not in ("wrong", "malformed"):
            raise ValueError("script 'loop_guard' requires behavior 'wrong' or 'malformed'")
        return self


class MockProbabilityRule(MockRule):
    probability: float = Field(ge=0, le=1)


class MockConfig(_Model):
    mode: MockMode = "mock"
    max_steps: int = Field(default=8, ge=1)
    step_seconds: float = Field(default=0.01, ge=0)
    seed: int = 0
    tokens: MockTokens | None = None
    references: dict[str, dict[str, Any]] = Field(default_factory=dict)
    default: MockRule = Field(default_factory=MockRule)
    cases: dict[str, MockRule] = Field(default_factory=dict)
    random: list[MockProbabilityRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_probabilities(self) -> "MockConfig":
        total = sum(rule.probability for rule in self.random)
        if total > 1:
            raise ValueError(f"probabilities in 'random' sum to {total}, more than 1")
        if self.mode != "mock_agent":
            rules = [self.default, *self.cases.values(), *self.random]
            if any(rule.script is not None for rule in rules):
                raise ValueError("'script' applies only to mode 'mock_agent'")
        return self


def _make_wrong(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int | float):
        return value + 1
    if isinstance(value, str):
        return value + "_wrong"
    if isinstance(value, list):
        return [_make_wrong(item) for item in value]
    if isinstance(value, dict):
        return {key: _make_wrong(item) for key, item in value.items()}
    return value


def _script_trajectory(
    script: AgentScript, case_input: Mapping[str, Any], config: MockConfig
) -> list[dict[str, Any]]:
    """The scripted trajectory of a ``mock_agent`` case."""
    operation = case_input.get("operation")
    tool = operation if isinstance(operation, str) and operation else "answer"
    inputs = case_input.get("inputs")
    params = inputs.get("params") if isinstance(inputs, Mapping) else None
    tool_args = {"params": dict(params)} if isinstance(params, Mapping) else {}
    calls: list[tuple[str | None, dict[str, Any], str | None]] = [
        ("read_inputs", {"case_id": case_input["case_id"]}, None)
    ]
    if script == "error_then_recover":
        calls.append((tool, {}, f"mock tool error: {tool} called without its parameters"))
        calls.append((tool, tool_args, None))
    elif script == "loop_guard":
        calls += [(tool, tool_args, None)] * (config.max_steps - 1)
        message = f"loop guard: stopped after {config.max_steps} tool calls without an answer"
        calls.append((None, {}, message))
    else:
        calls.append((tool, tool_args, None))
    if script != "loop_guard":
        calls.append((None, {}, None))  # the final answer
    return [
        {
            "step": number,
            "tool": name,
            "args": copy.deepcopy(args),
            "status": "ok" if error is None else "error",
            "error_message": error,
            "duration_s": config.step_seconds,
            "tokens": None,
        }
        for number, (name, args, error) in enumerate(calls)
    ]


class MockAdapter:
    """Adapter for testing the runner and reports without a real model."""

    name = "mock"
    version = "0.1.0"

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self._sleep = sleep
        self._config: MockConfig | None = None
        self._calls: dict[str, int] = {}

    def setup(self, config: Mapping[str, Any]) -> None:
        try:
            self._config = MockConfig.model_validate(dict(config))
        except ValidationError as exc:
            raise MockConfigError(f"invalid mock adapter config: {exc}") from exc
        self._calls = {}

    def select_rule(self, case_id: str) -> MockRule:
        """Return the rule that applies to ``case_id``."""
        config = self._require_config()
        if case_id in config.cases:
            return config.cases[case_id]
        draw = random.Random(f"{config.seed}:{case_id}").random()
        threshold = 0.0
        for rule in config.random:
            threshold += rule.probability
            if draw < threshold:
                return rule
        return config.default

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        config = self._require_config()
        case_id = case_input.get("case_id")
        if not isinstance(case_id, str):
            raise MockConfigError("mock adapter needs a string 'case_id' in the case input")
        rule = self.select_rule(case_id)
        call = self._calls.get(case_id, 0) + 1
        self._calls[case_id] = call

        if rule.behavior == "raise":
            raise MockAdapterError(rule.message)
        if rule.behavior == "skip":
            raise SkipCase(rule.message)
        if rule.behavior == "fail_then_succeed" and call <= (rule.failures or 0):
            raise MockAdapterError(f"{rule.message} (attempt {call} of {rule.failures})")
        if rule.behavior == "sleep":
            self._sleep(rule.seconds or 0.0)

        if rule.behavior == "malformed":
            output = rule.output if rule.output is not None else DEFAULT_MALFORMED_OUTPUT
        elif rule.behavior == "wrong" and rule.output is not None:
            output = rule.output
        else:
            output = self._reference(case_id)
            if rule.behavior == "wrong":
                output = _make_wrong(output)

        tokens = rule.tokens or config.tokens
        trajectory = None
        raw: dict[str, Any] = {"mock_behavior": rule.behavior, "call": call}
        if config.mode == "mock_agent":
            script = rule.script or "all_ok"
            trajectory = _script_trajectory(script, case_input, config)
            raw["mock_script"] = script
        return AdapterResponse(
            output=copy.deepcopy(output),
            tokens=TokenUsage(tokens.input, tokens.output) if tokens else None,
            trajectory=trajectory,
            raw=raw,
        )

    def teardown(self) -> None:
        self._config = None
        self._calls = {}

    def _require_config(self) -> MockConfig:
        if self._config is None:
            raise RuntimeError("mock adapter used before setup()")
        return self._config

    def _reference(self, case_id: str) -> dict[str, Any]:
        references = self._require_config().references
        if case_id not in references:
            raise MockConfigError(f"no reference output for case {case_id!r} in mock config")
        return references[case_id]
