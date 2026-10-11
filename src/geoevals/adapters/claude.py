"""Claude models through the local Claude Code CLI, in two tracks.

- ``claude_direct_<model>``: the model answers from the inlined input data, with no tools.
- ``claude_python_<model>``: the model has one tool, ``run_python``, that runs code in a
  per-case Docker container with no network (see ``geoevals.leaderboard.sandbox``).

Each model and track is its own registered adapter, for example ``claude_direct_opus_5_5``.
Calls go through ``geoevals.leaderboard.claude_cli`` on the maintainer's Claude subscription;
no API key is used. The adapter version records the Claude Code version
(``0.1.0+cc.2.1.296``), because the CLI's harness is part of what is measured.

Config (all optional)::

    effort: high            # --effort
    prompt_version: v1      # geoevals/adapters/prompts/<track>_<version>.md
    case_timeout_s: 840     # CLI wall-clock limit per case; keep it below the run's timeout_s
    max_case_usd: 5         # --max-budget-usd, a runaway guard at API list prices
    max_tool_calls: 20      # python track: run_python calls per case
    only_cases: [...]       # decline every other case (pilots)
    claude_command: [claude]
    sandbox_image: null     # python track: default geoevals-sandbox:<hash of uv.lock>
    prompt: benchmark       # graded: the graded-eval template (python track only)
    data_mount: null        # python track: a directory mounted read-only at /bench/data

When the subscription's usage limit is reached, the case and every later case are declined
(``SkipCase``), so the run has skipped cases and the leaderboard rejects it.
"""

import functools
import shutil
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from geoevals.adapters.base import AdapterResponse, SkipCase, TokenUsage
from geoevals.leaderboard import prompting
from geoevals.leaderboard.claude_cli import (
    ClaudeUsageLimit,
    ClaudeVersionChanged,
    CliCall,
    CliResult,
    claude_code_version,
    run_cli,
)

ADAPTER_VERSION = "0.1.0"
MODELS = {
    "opus_5_5": "claude-opus-5-5",
    "sonnet_5_5": "claude-sonnet-5-5",
    "haiku_5_5": "claude-haiku-5-5",
}
"""Model slug (as in the adapter name) -> model ID."""

SANDBOX_SERVER = "sandbox"
RUN_PYTHON_TOOL = f"mcp__{SANDBOX_SERVER}__run_python"
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"
ERROR_MESSAGE_LIMIT = 500


class ClaudeConfigError(ValueError):
    """The adapter config is invalid."""


class ClaudeAdapterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    prompt_version: str = Field(default="v1", pattern=r"^v[0-9]+$")
    case_timeout_s: float = Field(default=840.0, gt=0, allow_inf_nan=False)
    max_case_usd: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    max_tool_calls: int = Field(default=20, ge=1)
    only_cases: list[str] | None = None
    claude_command: list[str] = Field(default_factory=lambda: ["claude"], min_length=1)
    sandbox_image: str | None = None
    prompt: Literal["benchmark", "graded"] = "benchmark"
    data_mount: str | None = None


class _ClaudeAdapter:
    track: ClassVar[str]
    deterministic = False

    def __init__(self, slug: str) -> None:
        if slug not in MODELS:
            raise ValueError(f"unknown model slug {slug!r} (known: {', '.join(MODELS)})")
        self.slug = slug
        self.model = MODELS[slug]
        self.name = f"claude_{self.track}_{slug}"
        self.version = f"{ADAPTER_VERSION}+cc.{claude_code_version()}"
        self._config = ClaudeAdapterConfig()
        self._template = ""
        self._usage_limited = False
        self._cli_version = "unknown"

    def setup(self, config: Mapping[str, Any]) -> None:
        try:
            self._config = ClaudeAdapterConfig.model_validate(dict(config))
        except ValidationError as exc:
            raise ClaudeConfigError(f"invalid {self.name} config: {exc}") from exc
        if self.track != "python" and (
            self._config.prompt == "graded" or self._config.data_mount is not None
        ):
            raise ClaudeConfigError(
                f"{self.name}: graded evals and data_mount need the python track; the direct "
                "track cannot hold a city in its prompt"
            )
        template = f"graded_{self.track}" if self._config.prompt == "graded" else self.track
        self._template = prompting.load_template(template, self._config.prompt_version)
        if shutil.which(self._config.claude_command[0]) is None:
            raise RuntimeError(
                f"the Claude Code CLI ({self._config.claude_command[0]!r}) is not on PATH"
            )
        self._cli_version = claude_code_version(self._config.claude_command)

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        only = self._config.only_cases
        if only is not None and case_input.get("case_id") not in only:
            raise SkipCase("not in only_cases")
        if self._usage_limited:
            raise SkipCase("usage limit reached")
        try:
            return self._predict(case_input)
        except ClaudeUsageLimit as exc:
            self._usage_limited = True
            raise SkipCase(f"usage limit reached: {exc}") from exc

    def _predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        raise NotImplementedError

    def _run(self, call: CliCall) -> CliResult:
        """Run the call and check that it ran on the Claude Code version found at setup."""
        result = run_cli(call)
        if result.claude_code_version != self._cli_version:
            raise ClaudeVersionChanged(
                f"the case ran on Claude Code {result.claude_code_version}, "
                f"not {self._cli_version} (found at setup)"
            )
        return result

    def _call(self, case_input: Mapping[str, Any], user_message: str, **fields: Any) -> CliCall:
        task_statement, schema = prompting.spec_for(case_input)
        return CliCall(
            model=self.model,
            system_prompt=prompting.system_prompt(self._template, task_statement),
            user_message=user_message,
            json_schema=prompting.cli_schema(schema),
            effort=self._config.effort,
            max_budget_usd=self._config.max_case_usd,
            timeout_s=self._config.case_timeout_s,
            command=tuple(self._config.claude_command),
            **fields,
        )

    def teardown(self) -> None:
        pass


def _tokens(result: CliResult) -> TokenUsage:
    return TokenUsage(input=result.input_tokens, output=result.output_tokens)


class ClaudeDirectAdapter(_ClaudeAdapter):
    """The model answers from the inlined input data, with no tools."""

    track = "direct"

    def _predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        result = self._run(self._call(case_input, prompting.direct_message(case_input)))
        assert result.structured_output is not None  # check_result guarantees it
        return AdapterResponse(output=result.structured_output, tokens=_tokens(result))


class ClaudePythonAdapter(_ClaudeAdapter):
    """The model can run Python in a per-case Docker container with no network."""

    track = "python"

    def setup(self, config: Mapping[str, Any]) -> None:
        super().setup(config)
        from geoevals.leaderboard import sandbox

        if not sandbox.docker_available():
            raise RuntimeError(
                "the python track needs Docker, and the Docker daemon is not running"
            )
        self._image = self._config.sandbox_image or sandbox.ensure_image()

    def _predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        from geoevals.leaderboard import sandbox

        name = f"geoevals-{uuid.uuid4().hex[:12]}"
        fixtures = Path(case_input["benchmark_dir"]) / "fixtures"
        args = [
            "-m",
            "geoevals.leaderboard.sandbox_mcp",
            "--image",
            self._image,
            "--name",
            name,
            "--max-calls",
            str(self._config.max_tool_calls),
        ]
        if fixtures.is_dir():
            args += ["--fixtures", str(fixtures)]
        if self._config.data_mount is not None:
            args += ["--data", self._config.data_mount]
        mcp_config = {"mcpServers": {SANDBOX_SERVER: {"command": sys.executable, "args": args}}}
        call = self._call(
            case_input,
            prompting.python_message(case_input, sandbox.MOUNT),
            mcp_config=mcp_config,
            allowed_tools=(RUN_PYTHON_TOOL,),
            container=name,
        )
        try:
            result = self._run(call)
        finally:
            sandbox.remove_container(name)
        assert result.structured_output is not None  # check_result guarantees it
        return AdapterResponse(
            output=result.structured_output,
            tokens=_tokens(result),
            trajectory=trajectory_from_events(result.events),
        )


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
    return ""


def trajectory_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One trajectory step per tool call in the CLI's stream-json events.

    ``run_python`` calls keep their code as args; a ``StructuredOutput`` call (the final answer)
    is a step with no tool. A step is an error when its tool result is.
    """
    results: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("type") != "user":
            continue
        for block in event.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                results[str(block.get("tool_use_id"))] = block
    steps: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            tool: str | None
            if name == STRUCTURED_OUTPUT_TOOL:
                tool, args = None, {}
            else:
                tool = RUN_PYTHON_TOOL.rsplit("__", 1)[1] if name == RUN_PYTHON_TOOL else name
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
            outcome = results.get(str(block.get("id")), {})
            error = bool(outcome.get("is_error"))
            message = _text(outcome.get("content"))[:ERROR_MESSAGE_LIMIT] or "tool error"
            steps.append(
                {
                    "step": len(steps),
                    "tool": tool,
                    "args": args,
                    "status": "error" if error else "ok",
                    "error_message": message if error else None,
                    "duration_s": None,
                    "tokens": None,
                }
            )
    return steps


def adapter_factories() -> dict[str, functools.partial[_ClaudeAdapter]]:
    """Adapter name -> factory, for every model and track."""
    factories: dict[str, functools.partial[_ClaudeAdapter]] = {}
    for cls in (ClaudeDirectAdapter, ClaudePythonAdapter):
        for slug in MODELS:
            factories[f"claude_{cls.track}_{slug}"] = functools.partial(cls, slug)
    return factories
