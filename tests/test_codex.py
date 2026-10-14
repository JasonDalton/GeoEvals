"""Protocol checks use a fake server and never consume subscription allowance."""

from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from geoevals.leaderboard.codex_cli import (
    MODEL,
    CodexHarnessError,
    CodexUsageLimit,
    _run_case,
    quota_snapshot,
    tool_schema,
)
from geoevals.trajectory import trajectory_problem


class FakeServer:
    def __init__(self, events: list[dict[str, Any]], auth: str = "chatgpt") -> None:
        self.events = iter(events)
        self.auth = auth
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.replies: list[dict[str, Any]] = []
        self.quota: dict[str, Any] = {"ordinaryUsageAllowed": True, "rateLimits": {}}

    def initialize(self) -> str:
        return "0.160.0"

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, params))
        if method == "account/read":
            return {"account": {"type": self.auth, "email": "private@example.com"}}
        if method == "account/rateLimits/read":
            return self.quota
        if method == "config/read":
            return {"config": {"mcp_servers": {"private-server": {}}}}
        if method == "thread/start":
            return {"model": MODEL, "modelProvider": "openai", "thread": {"id": "test"}}
        return {}

    def receive(self) -> dict[str, Any]:
        return next(self.events)

    def send(self, message: dict[str, Any]) -> None:
        self.replies.append(message)


def tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": 50,
        "method": "item/tool/call",
        "params": {
            "tool": name,
            "arguments": arguments,
        },
    }


def finish() -> list[dict[str, Any]]:
    return [
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "tokenUsage": {
                    "total": {
                        "inputTokens": 100,
                        "cachedInputTokens": 40,
                        "outputTokens": 30,
                        "reasoningOutputTokens": 20,
                        "totalTokens": 130,
                    }
                }
            },
        },
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    ]


def run(server: Any, execute: Any = None) -> Any:
    return _run_case(
        server, "/tmp/empty", "system", "request", {"type": "object"}, "high", execute, 1, {}
    )


def test_direct_auth_isolation_and_tokens() -> None:
    server = FakeServer([tool("submit_answer", {"status": "ok"}), *finish()])
    response = run(server)
    assert response.output == {"status": "ok"}
    assert response.tokens.input == 100  # includes cache, not 140
    assert response.tokens.output == 30  # includes reasoning, not 50
    assert response.trajectory is None
    params = next(p for method, p in server.requests if method == "thread/start")
    assert params["model"] == MODEL and params["allowProviderModelFallback"] is False
    assert params["environments"] == [] and params["selectedCapabilityRoots"] == []
    assert [t["name"] for t in params["dynamicTools"]] == ["submit_answer"]
    assert params["config"]['mcp_servers."private-server".enabled'] is False
    assert params["config"]["features.shell_tool"] is False


def test_python_limit_and_trajectory() -> None:
    server = FakeServer(
        [
            tool("run_python", {"code": "print(1)"}),
            tool("run_python", {"code": "print(2)"}),
            tool("submit_answer", {"status": "ok"}),
            *finish(),
        ]
    )
    executed = []

    def execute(code: str) -> tuple[str, bool]:
        executed.append(code)
        return "1", True

    response = run(server, execute)
    assert executed == ["print(1)"]
    assert server.replies[1]["result"]["success"] is False
    assert trajectory_problem(response.trajectory) is None


@pytest.mark.parametrize(
    "event",
    [
        tool("run_python", {"code": "print(1)"}),
        tool("shell", {"command": "cat expected.json"}),
        {"method": "item/started", "params": {"item": {"type": "webSearch"}}},
    ],
)
def test_direct_rejects_unexpected_tools(event: dict[str, Any]) -> None:
    with pytest.raises(CodexHarnessError):
        run(FakeServer([event]))


def test_api_auth_rejected_before_inference() -> None:
    server = FakeServer([], auth="apiKey")
    with pytest.raises(CodexHarnessError, match="subscription auth"):
        run(server)
    assert not any(m == "thread/start" for m, _ in server.requests)


def test_no_allowance_stops_before_inference() -> None:
    server = FakeServer([])
    server.quota["ordinaryUsageAllowed"] = False
    with pytest.raises(CodexUsageLimit):
        run(server)
    assert not any(m == "thread/start" for m, _ in server.requests)


def test_quota_omits_account_and_balance() -> None:
    result = quota_snapshot(
        {
            "accountId": "private",
            "rateLimits": {
                "credits": {"balance": "private"},
                "primary": {"usedPercent": 20},
            },
        }
    )
    assert result == {"rateLimits": {"primary": {"usedPercent": 20}}}


def test_geometry_schema_preserves_numeric_nesting_without_changing_benchmark() -> None:
    from geoevals.leaderboard.prompting import spec_for

    _, original = spec_for({"benchmark_dir": "benchmarks/gis_correctness"})
    translated = tool_schema(original)
    validator = Draft202012Validator(translated)
    for geometry in [
        {"type": "Point", "coordinates": [1.1, 2.2]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]},
    ]:
        validator.validate({"status": "ok", "crs": "OGC:CRS84", "geometry": geometry})
    assert "codex_coordinate" not in original["$defs"]
    assert original["$defs"]["geometry"]["oneOf"][0]["properties"]["coordinates"] == {
        "type": "array"
    }
    with pytest.raises(ValidationError, match="not valid"):
        validator.validate(
            {
                "status": "ok",
                "crs": "OGC:CRS84",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": ["[[0,0],[1,0],[1,1],[0,0]]"],
                },
            }
        )


def test_walking_access_schema_is_preserved() -> None:
    from geoevals.leaderboard.prompting import spec_for

    _, original = spec_for({"benchmark_dir": "benchmarks/human_context"})
    assert tool_schema(original) == original


def test_cli_version_change_rejected_before_inference() -> None:
    server: Any = FakeServer([])
    with pytest.raises(CodexHarnessError, match=r"not 0\.159\.0"):
        _run_case(
            server,
            "/tmp/empty",
            "system",
            "request",
            {"type": "object"},
            "high",
            None,
            1,
            {},
            "0.159.0",
        )
    assert server.requests == []


def test_sandbox_failure_stops_later_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from geoevals.adapters import codex
    from geoevals.adapters.base import SkipCase

    monkeypatch.setattr(
        codex.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="codex-cli 0.160.0")
    )
    adapter = codex.CodexPythonAdapter()
    adapter.setup({"sandbox_image": "test-image"})
    calls = []

    def fail_start(*args: Any) -> None:
        raise codex.sandbox.SandboxError("Docker unavailable")

    def fake_run(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return kwargs["execute"]("print(1)")

    monkeypatch.setattr(codex.sandbox, "start_container", fail_start)
    monkeypatch.setattr(codex, "run_case", fake_run)
    case = {"case_id": "test", "benchmark_dir": "benchmarks/gis_correctness"}
    monkeypatch.setattr(codex.prompting, "python_message", lambda case: "request")
    with pytest.raises(CodexHarnessError, match="Docker unavailable"):
        adapter.predict(case)
    with pytest.raises(SkipCase, match="harness failed"):
        adapter.predict(case)
    assert len(calls) == 1
