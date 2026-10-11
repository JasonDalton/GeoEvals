"""A stdio MCP server with one tool, ``run_python``, for the python track.

Claude Code starts it for one case (``--mcp-config``), so one server serves one case. It speaks
JSON-RPC 2.0, one message per line, with the MCP methods Claude Code uses: ``initialize``,
``tools/list``, ``tools/call`` and ``ping``. Notifications get no reply.

The case's container is started on the first ``run_python`` call and removed when stdin closes.
Each call returns the exit code, stdout and stderr; a non-zero exit or a timeout is a tool error
the model can recover from. After ``--max-calls`` calls, the tool returns an error asking the
model to submit its answer, and runs nothing.

Run it as ``python -m geoevals.leaderboard.sandbox_mcp --image <tag> --name <container>
[--fixtures <dir>] [--max-calls 20] [--timeout-s 60] [--max-output 20000]``.
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from geoevals.leaderboard.sandbox import (
    ExecResult,
    exec_python,
    remove_container,
    start_container,
)

TOOL_NAME = "run_python"
SERVER_INFO = {"name": "geoevals-sandbox", "version": "0.1.0"}
DEFAULT_PROTOCOL = "2025-06-18"
TOOL = {
    "name": TOOL_NAME,
    "description": (
        "Run Python 3.12 code in the sandbox and return its exit code, stdout and stderr. "
        "GeoPandas, Shapely, pyproj, NetworkX and SciPy are installed; there is no network. "
        "Each call is a new process; files written to /tmp persist for this task."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Python source to run."}},
        "required": ["code"],
        "additionalProperties": False,
    },
}


def format_result(result: ExecResult) -> str:
    return (
        f"exit code: {result.exit_code}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


def _text_result(text: str, is_error: bool) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


class SandboxServer:
    """Answers MCP messages. ``execute`` runs one piece of code in the case's container."""

    def __init__(self, execute: Callable[[str], ExecResult], max_calls: int) -> None:
        self._execute = execute
        self._max_calls = max_calls
        self.calls = 0

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """The reply to ``message``, or None for a notification."""
        if "id" not in message:
            return None
        method = message.get("method")
        params = message.get("params") or {}
        if method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": params.get("protocolVersion", DEFAULT_PROTOCOL),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        elif method == "tools/list":
            result = {"tools": [TOOL]}
        elif method == "tools/call":
            result = self._call(params)
        elif method == "ping":
            result = {}
        else:
            error = {"code": -32601, "message": f"method not found: {method}"}
            return {"jsonrpc": "2.0", "id": message["id"], "error": error}
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("name") != TOOL_NAME:
            return _text_result(f"unknown tool {params.get('name')!r}", True)
        code = (params.get("arguments") or {}).get("code")
        if not isinstance(code, str):
            return _text_result("run_python needs a string argument 'code'", True)
        if self.calls >= self._max_calls:
            return _text_result(
                f"Tool call limit reached ({self._max_calls} calls). Nothing was run. "
                "Submit your answer now with the structured-output tool.",
                True,
            )
        self.calls += 1
        try:
            result = self._execute(code)
        except Exception as exc:
            return _text_result(f"the sandbox failed: {type(exc).__name__}: {exc}", True)
        return _text_result(format_result(result), result.exit_code != 0 or result.timed_out)


def serve(server: SandboxServer, lines: Any, write: Callable[[str], None]) -> None:
    """Answer each JSON-RPC line of ``lines`` until it ends."""
    for line in lines:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "parse error"},
                    }
                )
            )
            continue
        reply = server.handle(message) if isinstance(message, dict) else None
        if reply is not None:
            write(json.dumps(reply))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCP server with a sandboxed run_python tool.")
    parser.add_argument("--image", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--max-calls", type=int, default=20)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--max-output", type=int, default=20_000)
    args = parser.parse_args(argv)
    started = False

    def execute(code: str) -> ExecResult:
        nonlocal started
        if not started:
            start_container(args.image, args.name, args.fixtures)
            started = True
        return exec_python(args.name, code, args.timeout_s, args.max_output)

    def write(text: str) -> None:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    try:
        serve(SandboxServer(execute, args.max_calls), sys.stdin, write)
    finally:
        if started:
            remove_container(args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
