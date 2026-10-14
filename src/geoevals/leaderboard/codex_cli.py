"""Subscription-backed Codex app-server calls with client-owned benchmark tools.

Each case gets an ephemeral thread in an empty directory. Native tools, user MCP
servers, apps, skills and plugins are disabled. Only the answer tool and (on the
Python track) the existing offline Docker executor are permitted.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from geoevals.leaderboard.sandbox_mcp import TOOL

if TYPE_CHECKING:
    from geoevals.adapters.base import AdapterResponse

MODEL = "gpt-6-luna"
DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "hooks",
    "multi_agent",
    "multi_agent_v2",
    "code_mode_host",
    "code_mode",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "view_image",
    "image_generation",
    "sleep_tool",
    "memories",
    "skill_search",
    "skill_mcp_dependency_install",
    "workspace_dependencies",
    "worktrees",
    "tool_suggest",
    "auth_elicitation",
    "goals",
)
FORBIDDEN_ITEMS = {
    "commandExecution",
    "fileChange",
    "mcpToolCall",
    "webSearch",
    "imageGeneration",
    "collabAgentToolCall",
    "browserToolCall",
    "computerToolCall",
}


class CodexHarnessError(RuntimeError):
    """Auth, protocol or isolation failed; this is not a model benchmark failure."""


class CodexUsageLimit(CodexHarnessError):
    """No further subscription-backed cases should be attempted."""


def tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Give GeoJSON coordinate arrays explicit recursive numeric item types.

    Codex supplies string items for an array without an item schema. GeoEvals
    deliberately leaves coordinate nesting loose, so passing that schema through
    forces numbers and polygon rings into strings. Keep the benchmark validator
    unchanged and describe RFC 7946's numeric arrays in the tool schema instead.
    """
    result = json.loads(json.dumps(schema))
    geometry = result.get("$defs", {}).get("geometry")
    if not geometry:
        return result
    changed = False

    def visit(value: Any) -> None:
        nonlocal changed
        if isinstance(value, dict):
            coordinates = value.get("properties", {}).get("coordinates")
            if (
                isinstance(coordinates, dict)
                and coordinates.get("type") == "array"
                and "items" not in coordinates
            ):
                coordinates["items"] = {"$ref": "#/$defs/codex_coordinate"}
                changed = True
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(geometry)
    if changed:
        result["$defs"]["codex_coordinate"] = {
            "anyOf": [
                {"type": "number"},
                {"type": "array", "items": {"$ref": "#/$defs/codex_coordinate"}},
            ]
        }
    return result


def quota_snapshot(response: dict[str, Any]) -> dict[str, Any]:
    """Keep allowance windows, without account identifiers or credit balances."""

    def snapshot(value: dict[str, Any]) -> dict[str, Any]:
        return {
            k: value[k]
            for k in (
                "limitId",
                "limitName",
                "planType",
                "normalModelSlug",
                "primary",
                "secondary",
                "individualLimit",
                "rateLimitReachedType",
                "spendControlReached",
            )
            if k in value
        }

    result: dict[str, Any] = {"rateLimits": snapshot(response.get("rateLimits") or {})}
    if response.get("rateLimitsByLimitId"):
        result["rateLimitsByLimitId"] = {
            k: snapshot(v) for k, v in response["rateLimitsByLimitId"].items()
        }
    if "ordinaryUsageAllowed" in response:
        result["ordinaryUsageAllowed"] = response["ordinaryUsageAllowed"]
    return result


class AppServer:
    """A deadline-bounded JSON-RPC client; the watchdog handles worker termination."""

    def __init__(self, cwd: str, timeout_s: float, container: str | None = None) -> None:
        self.deadline = time.monotonic() + timeout_s
        args = [sys.executable, "-m", "geoevals.leaderboard.watchdog"]
        if container:
            args += ["--container", container]
        args += ["--", "codex", "app-server", "-c", "analytics.enabled=false"]
        environment = dict(os.environ)
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
            environment.pop(key, None)
        self.process = subprocess.Popen(
            args,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=environment,
        )
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.serial = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    self.messages.put(message)
        finally:
            self.messages.put(None)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message, allow_nan=False) + "\n")
        self.process.stdin.flush()

    def receive(self) -> dict[str, Any]:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Codex case exceeded its time limit")
        try:
            message = self.messages.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError("Codex case exceeded its time limit") from None
        if message is None:
            raise CodexHarnessError("Codex app-server exited before completing the case")
        return message

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.serial += 1
        request_id = self.serial
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            message = self.receive()
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise CodexHarnessError(f"{method}: {message['error']}")
                return message["result"]
            if "id" in message and "method" in message:
                raise CodexHarnessError(f"unexpected server request: {message['method']}")

    def initialize(self) -> str:
        result = self.request(
            "initialize",
            {
                "clientInfo": {"name": "geoevals", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.send({"method": "initialized", "params": {}})
        user_agent = result.get("userAgent", "")
        return user_agent.split("/", 1)[1].split(" ", 1)[0] if "/" in user_agent else "unknown"

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.process.wait(timeout=10)
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()


def run_case(
    *,
    system_prompt: str,
    user_message: str,
    schema: dict[str, Any],
    effort: str,
    timeout_s: float,
    execute: Callable[[str], tuple[str, bool]] | None = None,
    max_tool_calls: int = 20,
    container: str | None = None,
    telemetry_path: Path | None = None,
    case_id: str = "",
    expected_cli_version: str | None = None,
) -> AdapterResponse:
    """Run exactly one Luna case, recording detailed tokens and quota separately."""
    telemetry: dict[str, Any] = {"case_id": case_id, "model": MODEL}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="geoevals-codex-") as cwd:
        server = AppServer(cwd, timeout_s, container)
        try:
            return _run_case(
                server,
                cwd,
                system_prompt,
                user_message,
                schema,
                effort,
                execute,
                max_tool_calls,
                telemetry,
                expected_cli_version,
            )
        except Exception as exc:
            telemetry["error_type"] = type(exc).__name__
            raise
        finally:
            telemetry["elapsed_s"] = time.monotonic() - started
            try:
                if telemetry_path:
                    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
                    with telemetry_path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(telemetry, allow_nan=False) + "\n")
            finally:
                server.close()


def _run_case(
    server: AppServer,
    cwd: str,
    system_prompt: str,
    user_message: str,
    schema: dict[str, Any],
    effort: str,
    execute: Callable[[str], tuple[str, bool]] | None,
    max_tool_calls: int,
    telemetry: dict[str, Any],
    expected_cli_version: str | None = None,
) -> AdapterResponse:
    from geoevals.adapters.base import AdapterResponse, TokenUsage

    cli_version = server.initialize()
    telemetry["codex_cli_version"] = cli_version
    if expected_cli_version is not None and cli_version != expected_cli_version:
        raise CodexHarnessError(
            f"the case ran on Codex CLI {cli_version}, not {expected_cli_version} (found at setup)"
        )
    account = server.request("account/read", {}).get("account") or {}
    if account.get("type") != "chatgpt":
        raise CodexHarnessError("GeoEvals requires ChatGPT subscription auth, not API-key auth")
    telemetry["auth"] = {"type": "chatgpt", "planType": account.get("planType")}
    before = server.request("account/rateLimits/read", {})
    telemetry["quota_before"] = quota_snapshot(before)
    if before.get("ordinaryUsageAllowed") is False:
        raise CodexUsageLimit("ordinary subscription usage is unavailable")
    config: dict[str, Any] = {
        "model_reasoning_effort": effort,
        "web_search": "disabled",
        "project_doc_max_bytes": 0,
        "developer_instructions": "",
        "features.skip_host_skill_discovery": True,
    }
    for feature in DISABLED_FEATURES:
        config[f"features.{feature}"] = False
    # Read effective config only to disable every inherited MCP server. Never log it.
    inherited = server.request("config/read", {"includeLayers": False}).get("config") or {}
    for name in inherited.get("mcp_servers") or {}:
        config[f"mcp_servers.{json.dumps(name)}.enabled"] = False
    tools = [
        {
            "type": "function",
            "name": "submit_answer",
            "description": "Submit the final benchmark answer exactly following this schema.",
            "inputSchema": tool_schema(schema),
        }
    ]
    if execute:
        tools.append({"type": "function", **TOOL})
    thread = server.request(
        "thread/start",
        {
            "model": MODEL,
            "modelProvider": "openai",
            "allowProviderModelFallback": False,
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "baseInstructions": system_prompt,
            "developerInstructions": "Use only submit_answer"
            + (" and run_python." if execute else ".")
            + " After submit_answer succeeds, end your turn immediately.",
            "config": config,
            "dynamicTools": tools,
            "environments": [],
            "selectedCapabilityRoots": [],
            "serviceTier": "default",
        },
    )
    if thread["model"] != MODEL or thread["modelProvider"] != "openai":
        raise CodexHarnessError("Codex selected a different model or provider")
    if thread.get("instructionSources"):
        raise CodexHarnessError("Codex loaded external instruction files")
    telemetry["service_tier"] = thread.get("serviceTier")
    thread_id = thread["thread"]["id"]
    server.request(
        "turn/start",
        {
            "threadId": thread_id,
            "input": [{"type": "text", "text": user_message}],
            "model": MODEL,
            "effort": effort,
            "serviceTierForTurn": "default",
            "environments": [],
        },
    )
    answer: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = []
    calls = 0
    while True:
        message = server.receive()
        method = message.get("method")
        params = message.get("params") or {}
        if method == "thread/tokenUsage/updated":
            telemetry["tokens"] = params["tokenUsage"]["total"]
        elif method == "item/started" and params.get("item", {}).get("type") in FORBIDDEN_ITEMS:
            raise CodexHarnessError(f"forbidden native tool: {params['item']['type']}")
        elif method == "item/tool/call":
            tool = params["tool"]
            arguments = params["arguments"]
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise CodexHarnessError("tool arguments were not an object")
            call_start = time.monotonic()
            success = True
            if tool == "submit_answer":
                if answer is not None:
                    raise CodexHarnessError("Codex submitted more than one final answer")
                answer = arguments
                text = "Answer received. End your turn now without any more tool calls."
            elif tool == "run_python" and execute and answer is None:
                if calls >= max_tool_calls:
                    text, success = "Tool call limit reached. Submit your answer now.", False
                elif not isinstance(arguments.get("code"), str):
                    text, success = "run_python requires a code string.", False
                else:
                    calls += 1
                    text, success = execute(arguments["code"])
            else:
                raise CodexHarnessError(f"unexpected tool: {tool}")
            steps.append(
                {
                    "step": len(steps),
                    "tool": None if tool == "submit_answer" else tool,
                    "args": {} if tool == "submit_answer" else arguments,
                    "status": "ok" if success else "error",
                    "error_message": None if success else text[:500],
                    "duration_s": time.monotonic() - call_start,
                    "tokens": None,
                }
            )
            server.send(
                {
                    "id": message["id"],
                    "result": {
                        "contentItems": [{"type": "inputText", "text": text}],
                        "success": success,
                    },
                }
            )
        elif "id" in message and method:
            raise CodexHarnessError(f"unexpected server request: {method}")
        elif method == "turn/completed":
            turn = params["turn"]
            if turn["status"] != "completed":
                error = turn.get("error") or {}
                if "usageLimit" in json.dumps(error) or "usage limit" in json.dumps(error).lower():
                    raise CodexUsageLimit("Codex subscription usage limit reached")
                raise CodexHarnessError(f"Codex turn failed: {error}")
            break
    telemetry["quota_after"] = quota_snapshot(server.request("account/rateLimits/read", {}))
    telemetry["python_calls"] = calls
    if answer is None:
        raise RuntimeError("Codex completed without submitting a structured answer")
    tokens = telemetry.get("tokens")
    if not tokens:
        raise CodexHarnessError("Codex did not report token usage")
    # Input includes cached input; output includes reasoning. Do not add either twice.
    return AdapterResponse(
        output=answer,
        tokens=TokenUsage(input=tokens["inputTokens"], output=tokens["outputTokens"]),
        trajectory=steps if execute else None,
    )
