import json
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from geoevals.leaderboard import sandbox
from geoevals.leaderboard.sandbox import (
    FIXTURES_MOUNT,
    ExecResult,
    docker_available,
    exec_python,
    image_tag,
    remove_container,
    start_container,
    truncate,
)
from geoevals.leaderboard.sandbox_mcp import TOOL_NAME, SandboxServer

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "benchmarks" / "gis_correctness" / "fixtures"
PLAIN_IMAGE = "python:3.12-slim"


def test_truncate_keeps_the_head_and_marks_the_cut() -> None:
    assert truncate("abc", 5) == "abc"
    cut = truncate("x" * 30, 10)
    assert cut.startswith("x" * 10)
    assert "truncated at 10 characters" in cut
    assert cut.count("x") == 10


def test_image_tag_follows_the_lock_file(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("a", encoding="utf-8")
    first = image_tag(tmp_path)
    assert first.startswith("geoevals-sandbox:") and len(first.split(":")[1]) == 12
    assert image_tag(tmp_path) == first
    (tmp_path / "uv.lock").write_text("b", encoding="utf-8")
    assert image_tag(tmp_path) != first


def test_repo_root_holds_the_lock_file() -> None:
    assert sandbox.repo_root() == REPO.resolve()


@pytest.fixture
def container() -> Iterator[str]:
    name = f"geoevals-test-{uuid.uuid4().hex[:8]}"
    start_container(PLAIN_IMAGE, name, FIXTURES)
    try:
        yield name
    finally:
        remove_container(name)


def _run(name: str, code: str, **limits: float) -> ExecResult:
    return exec_python(name, code, **limits)  # type: ignore[arg-type]


@pytest.mark.docker
@pytest.mark.skipif(not docker_available(), reason="needs a running Docker daemon")
def test_sandbox_isolation(container: str) -> None:
    network = _run(
        container,
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('connected')\n"
        "except OSError as exc:\n"
        "    print('no network', type(exc).__name__)\n",
    )
    assert "no network" in network.stdout, network
    write = _run(container, f"open('{FIXTURES_MOUNT}/new.txt', 'w')")
    assert write.exit_code != 0 and "Read-only file system" in write.stderr
    listing = _run(container, "import os; print(sorted(os.listdir('.')))")
    assert listing.stdout.strip() == "['fixtures']"
    fixtures = _run(container, "import os; print(sorted(os.listdir('fixtures')))")
    assert sorted(eval(fixtures.stdout)) == sorted(p.name for p in FIXTURES.iterdir())
    tmp = _run(container, "open('/tmp/x', 'w').write('ok'); print(open('/tmp/x').read())")
    assert tmp.stdout.strip() == "ok"
    root = _run(container, "open('/usr/x', 'w')")
    assert root.exit_code != 0
    user = _run(container, "import os; print(os.getuid())")
    assert user.stdout.strip() == "65534"


@pytest.mark.docker
@pytest.mark.skipif(not docker_available(), reason="needs a running Docker daemon")
def test_exec_timeout(container: str) -> None:
    result = _run(container, "import time; time.sleep(10)", timeout_s=2)
    assert result.timed_out
    assert "time limit" in result.stderr


@pytest.mark.docker
@pytest.mark.skipif(not docker_available(), reason="needs a running Docker daemon")
def test_exec_output_limit_and_errors(container: str) -> None:
    long = _run(container, "print('y' * 50_000)", max_output=1000)
    assert long.stdout.startswith("y" * 1000)
    assert "truncated at 1000 characters" in long.stdout
    failing = _run(container, "raise ValueError('boom')")
    assert failing.exit_code == 1 and "ValueError: boom" in failing.stderr
    assert not failing.timed_out


@pytest.mark.docker
@pytest.mark.skipif(not docker_available(), reason="needs a running Docker daemon")
def test_remove_container() -> None:
    name = f"geoevals-test-{uuid.uuid4().hex[:8]}"
    start_container(PLAIN_IMAGE, name, None)
    remove_container(name)
    assert _run(name, "print(1)").exit_code != 0
    remove_container(name)  # a second removal does not raise


def test_docker_available_without_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert docker_available() is False


# --- MCP server -------------------------------------------------------------------------------


def _server(
    results: list[ExecResult] | None = None, max_calls: int = 3
) -> tuple[SandboxServer, list[str]]:
    ran: list[str] = []
    queue = list(results or [])

    def execute(code: str) -> ExecResult:
        ran.append(code)
        return queue.pop(0) if queue else ExecResult(0, "out\n", "", False)

    return SandboxServer(execute, max_calls), ran


def _call(server: SandboxServer, code: object, request_id: int = 3) -> dict:
    reply = server.handle(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": TOOL_NAME, "arguments": {"code": code}},
        }
    )
    assert reply is not None
    return reply["result"]


def test_mcp_initialize_and_list() -> None:
    server, _ = _server()
    init = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2099-01-01"},
        }
    )
    assert init is not None
    assert init["result"]["protocolVersion"] == "2099-01-01"
    assert "tools" in init["result"]["capabilities"]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed is not None
    [tool] = listed["result"]["tools"]
    assert tool["name"] == "run_python"
    assert tool["inputSchema"]["required"] == ["code"]
    assert tool["inputSchema"]["properties"]["code"]["type"] == "string"


def test_mcp_call_formats_the_result_and_flags_errors() -> None:
    server, ran = _server(
        [
            ExecResult(0, "42\n", "", False),
            ExecResult(1, "", "boom", False),
            ExecResult(137, "", "slow", True),
        ]
    )
    ok = _call(server, "print(42)")
    assert ok["isError"] is False
    assert ok["content"][0]["text"] == "exit code: 0\n--- stdout ---\n42\n\n--- stderr ---\n"
    assert _call(server, "x")["isError"] is True
    assert _call(server, "y")["isError"] is True
    assert ran == ["print(42)", "x", "y"]


def test_mcp_call_limit_runs_nothing_more() -> None:
    server, ran = _server(max_calls=2)
    _call(server, "a")
    _call(server, "b")
    limited = _call(server, "c")
    assert limited["isError"] is True
    assert "Submit your answer" in limited["content"][0]["text"]
    assert ran == ["a", "b"]


def test_mcp_rejects_bad_calls() -> None:
    server, ran = _server()
    assert _call(server, 7)["isError"] is True
    unknown = server.handle(
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "shell"}}
    )
    assert unknown is not None and unknown["result"]["isError"] is True
    missing = server.handle({"jsonrpc": "2.0", "id": 10, "method": "resources/list"})
    assert missing is not None and missing["error"]["code"] == -32601
    assert ran == []


def test_mcp_main_over_stdio() -> None:
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "geoevals.leaderboard.sandbox_mcp",
            "--image",
            "unused",
            "--name",
            "unused",
        ],
        input="".join(json.dumps(m) + "\n" for m in messages),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    replies = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
    assert replies[1]["result"]["tools"][0]["name"] == "run_python"
