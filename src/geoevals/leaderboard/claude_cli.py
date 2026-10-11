"""Run one case through the local Claude Code CLI (``claude -p``) and parse its output.

The CLI runs signed in to the maintainer's Claude subscription: every ``ANTHROPIC_*`` variable
(API keys, base URLs) and every ``CLAUDE*`` variable except ``CLAUDE_CONFIG_DIR`` (Bedrock,
Vertex and Foundry switches, and the settings of a Claude Code session the run was started
from) is removed from its environment, auto-update is turned off for the call, and the
``apiKeySource`` it reports must be ``none``. Each call is isolated from the maintainer's own setup:

- ``--restricted`` ignores the user, project and local settings files, so plugins, hooks and
  ``CLAUDE.md`` do not reach the model;
- ``--tools ""`` removes every built-in tool, so the model sees only ``StructuredOutput`` (from
  ``--json-schema``) and the MCP tools named in ``allowed_tools``;
- the CLI runs in a new empty temporary directory, and the user message goes on stdin (a case
  can inline more input than a command line holds).

The final answer is the ``structured_output`` of the ``result`` event. Tokens are summed over
``modelUsage``: input counts every prompt token the model processed (uncached, cache creation
and cache reads), output counts output tokens (thinking included).

The CLI runs under ``geoevals.leaderboard.watchdog``, which stops it (and removes the case's
container) if the adapter worker is killed.

Errors are exceptions whose class name the runner records as the case's error type.
``HARNESS_ERRORS`` names the ones that say the harness, not the model, failed; the leaderboard
rejects a run that has any of them.
"""

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REMOVED_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE")
KEPT_ENV = frozenset({"CLAUDE_CONFIG_DIR"})
"""``CLAUDE*`` variables of the launching session (``CLAUDE_EFFORT``, ``CLAUDE_CODE_*``) are
removed so that a run does not depend on where it was started; the config directory, which
locates the sign-in, is kept."""
ADDED_ENV = {"DISABLE_AUTOUPDATER": "1"}
STDERR_TAIL = 2000
TERMINATE_GRACE_S = 30.0
USAGE_LIMIT_MARKERS = ("usage limit", "rate limit", "rate_limit", "limit reached", "429")


class ClaudeCliError(RuntimeError):
    """The CLI call did not produce an answer."""


class ClaudeTimeout(ClaudeCliError):
    """The CLI ran longer than the case's time limit and was killed."""


class ClaudeRunError(ClaudeCliError):
    """The CLI exited without a result, or reported an error result (a harness failure)."""


class ClaudeBudgetExceeded(ClaudeCliError):
    """The case passed ``max_case_usd`` at API list prices (the model ran away)."""


class ClaudeRefusal(ClaudeCliError):
    """The model declined to answer (stop reason ``refusal``)."""


class ClaudeNoAnswer(ClaudeCliError):
    """The result has no structured output."""


class ClaudeUnexpectedModel(ClaudeCliError):
    """A model other than the requested one answered part of the case."""


class ClaudeAuthError(ClaudeCliError):
    """The CLI did not run on the subscription sign-in."""


class ClaudeUsageLimit(ClaudeCliError):
    """The subscription's usage limit was reached (HTTP 429 after the CLI's own retries)."""


class ClaudeVersionChanged(ClaudeCliError):
    """The case ran on a different Claude Code version than the adapter recorded."""


HARNESS_ERRORS = frozenset(
    {
        "ClaudeRunError",
        "ClaudeUnexpectedModel",
        "ClaudeAuthError",
        "ClaudeUsageLimit",
        "ClaudeVersionChanged",
        "WorkerCrashed",
    }
)
"""Error types that say the harness failed; the model's own failures (timeout, refusal, no
answer, budget) are not in it."""


@dataclass(frozen=True)
class CliCall:
    """One CLI call. ``command`` is the CLI executable and any leading arguments."""

    model: str
    system_prompt: str
    user_message: str
    json_schema: dict[str, Any]
    effort: str = "high"
    max_budget_usd: float = 5.0
    timeout_s: float = 840.0
    mcp_config: dict[str, Any] | None = None
    allowed_tools: tuple[str, ...] = ()
    command: tuple[str, ...] = ("claude",)
    container: str | None = None
    """Docker container the watchdog removes if the call is stopped."""


@dataclass(frozen=True)
class CliResult:
    structured_output: dict[str, Any] | None
    input_tokens: int
    output_tokens: int
    models: tuple[str, ...]
    num_turns: int
    claude_code_version: str | None
    events: list[dict[str, Any]] = field(repr=False)


def build_command(call: CliCall, mcp_config_path: Path | None) -> list[str]:
    """The CLI's argument list. The user message is not in it: it goes on stdin."""
    command = [
        *call.command,
        "-p",
        "--model",
        call.model,
        "--effort",
        call.effort,
        "--restricted",
        "--tools",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--permission-prompts",
        "none",
        "--system-prompt",
        call.system_prompt,
        "--json-schema",
        json.dumps(call.json_schema, separators=(",", ":"), ensure_ascii=False),
        "--max-budget-usd",
        f"{call.max_budget_usd:g}",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if mcp_config_path is not None:
        command += ["--mcp-config", str(mcp_config_path)]
    if call.allowed_tools:
        command += ["--allowedTools", ",".join(call.allowed_tools)]
    return command


def parse_events(stdout: str) -> list[dict[str, Any]]:
    """The JSON objects of a stream-json output, one per line; other lines are ignored."""
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def check_result(
    events: list[dict[str, Any]], model: str, exit_code: int = 0, stderr: str = ""
) -> CliResult:
    """The answer and token counts of a finished call. Raises a ``ClaudeCliError`` subclass."""
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is None:
        tail = stderr.strip()[-STDERR_TAIL:]
        if any(marker in tail.lower() for marker in USAGE_LIMIT_MARKERS):
            raise ClaudeUsageLimit(f"usage limit reached (exit code {exit_code}): {tail}")
        raise ClaudeRunError(f"the CLI exited with exit code {exit_code} and no result: {tail}")
    source = init.get("apiKeySource")
    if source != "none":
        raise ClaudeAuthError(f"the CLI reported apiKeySource {source!r}, not the subscription")
    if _usage_limited(result):
        raise ClaudeUsageLimit(f"usage limit reached: {str(result.get('result'))[:STDERR_TAIL]}")
    if result.get("stop_reason") == "refusal":
        detail = result.get("result")
        raise ClaudeRefusal(f"the model declined to answer (stop reason refusal): {detail}")
    if result.get("subtype") == "error_max_budget_usd":
        raise ClaudeBudgetExceeded("the case passed max_case_usd at API list prices")
    if result.get("subtype") != "success" or result.get("is_error"):
        status = result.get("api_error_status")
        raise ClaudeRunError(
            f"error result {result.get('subtype')} (api_error_status {status}): "
            f"{str(result.get('result'))[:STDERR_TAIL]}"
        )
    usage: dict[str, Any] = result.get("modelUsage") or {}
    others = sorted(set(usage) - {model})
    if others:
        raise ClaudeUnexpectedModel(f"answered in part by {', '.join(others)}, not only {model}")
    answer = result.get("structured_output")
    if not isinstance(answer, dict):
        raise ClaudeNoAnswer("the result has no structured output")
    input_tokens = sum(
        u.get("inputTokens", 0)
        + u.get("cacheCreationInputTokens", 0)
        + u.get("cacheReadInputTokens", 0)
        for u in usage.values()
    )
    output_tokens = sum(u.get("outputTokens", 0) for u in usage.values())
    return CliResult(
        structured_output=answer,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        models=tuple(sorted(usage)),
        num_turns=int(result.get("num_turns") or 0),
        claude_code_version=init.get("claude_code_version"),
        events=events,
    )


def _usage_limited(result: dict[str, Any]) -> bool:
    if result.get("api_error_status") == 429:
        return True
    if not (result.get("is_error") or result.get("subtype") != "success"):
        return False
    text = str(result.get("result") or "").lower()
    return any(marker in text for marker in USAGE_LIMIT_MARKERS)


def _environment() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in KEPT_ENV or not key.startswith(REMOVED_ENV_PREFIXES)
    }
    return {**env, **ADDED_ENV}


def _watched(command: list[str], container: str | None) -> list[str]:
    watchdog = [sys.executable, "-m", "geoevals.leaderboard.watchdog"]
    if container is not None:
        watchdog += ["--container", container]
    return [*watchdog, "--", *command]


def run_cli(call: CliCall) -> CliResult:
    """Run the CLI for one case and return its answer. Raises a ``ClaudeCliError`` subclass.

    The CLI runs under the watchdog. On timeout the watchdog is told to stop the CLI's process
    group (the CLI and any MCP server it started) and remove the container.
    """
    env = _environment()
    with tempfile.TemporaryDirectory(prefix="geoevals-claude-") as tmp:
        mcp_path = None
        if call.mcp_config is not None:
            mcp_path = Path(tmp) / "mcp.json"
            mcp_path.write_text(json.dumps(call.mcp_config), encoding="utf-8")
        process = subprocess.Popen(
            _watched(build_command(call, mcp_path), call.container),
            cwd=tmp,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(call.user_message, timeout=call.timeout_s)
        except subprocess.TimeoutExpired:
            _stop(process)
            raise ClaudeTimeout(f"the CLI exceeded case_timeout_s={call.timeout_s:g}") from None
        except BaseException:
            _stop(process)
            raise
    return check_result(parse_events(stdout), call.model, process.returncode, stderr)


def _stop(process: subprocess.Popen[str]) -> None:
    """Ask the watchdog to stop the CLI and clean up; kill its group if it does not exit."""
    with contextlib.suppress(ProcessLookupError):
        process.send_signal(signal.SIGTERM)
    try:
        process.communicate(timeout=TERMINATE_GRACE_S)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()


def claude_code_version(command: Sequence[str] = ("claude",)) -> str:
    """The CLI's version (``2.1.296``), or ``unknown`` when it cannot be run."""
    try:
        completed = subprocess.run(
            [*command, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    words = completed.stdout.split()
    return words[0] if completed.returncode == 0 and words else "unknown"
