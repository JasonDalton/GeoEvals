import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from claude_fakes import FAKE_COMMAND, MODEL, FakeClaude, init_event, result_event
from geoevals.leaderboard.claude_cli import (
    HARNESS_ERRORS,
    ClaudeAuthError,
    ClaudeBudgetExceeded,
    ClaudeCliError,
    ClaudeNoAnswer,
    ClaudeRefusal,
    ClaudeRunError,
    ClaudeTimeout,
    ClaudeUnexpectedModel,
    ClaudeUsageLimit,
    CliCall,
    build_command,
    claude_code_version,
    run_cli,
)

SCHEMA = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}


def _call(**fields: object) -> CliCall:
    defaults: dict[str, object] = {
        "model": MODEL,
        "system_prompt": "You answer GIS questions.",
        "user_message": "What is the area?",
        "json_schema": SCHEMA,
        "command": FAKE_COMMAND,
    }
    return CliCall(**{**defaults, **fields})  # type: ignore[arg-type]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    return FakeClaude(tmp_path, monkeypatch)


def test_build_command_has_the_isolation_flags(tmp_path: Path) -> None:
    command = build_command(_call(command=("claude",)), None)
    assert command[:2] == ["claude", "-p"]
    for flag in [
        "--restricted",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--verbose",
    ]:
        assert flag in command, flag

    def value(flag: str) -> str:
        return command[command.index(flag) + 1]

    assert value("--tools") == ""
    assert value("--model") == MODEL
    assert value("--effort") == "high"
    assert value("--permission-prompts") == "none"
    assert value("--output-format") == "stream-json"
    assert value("--system-prompt") == "You answer GIS questions."
    assert value("--max-budget-usd") == "5"
    assert json.loads(value("--json-schema")) == SCHEMA
    assert " " not in value("--json-schema")
    assert "--mcp-config" not in command
    assert "--allowedTools" not in command
    assert "What is the area?" not in command

    mcp_path = tmp_path / "mcp.json"
    with_mcp = build_command(
        _call(mcp_config={"mcpServers": {}}, allowed_tools=("mcp__sandbox__run_python",)),
        mcp_path,
    )
    assert with_mcp[with_mcp.index("--mcp-config") + 1] == str(mcp_path)
    assert with_mcp[with_mcp.index("--allowedTools") + 1] == "mcp__sandbox__run_python"


def test_run_cli_returns_the_answer_and_summed_tokens(fake: FakeClaude) -> None:
    fake.set([init_event(), result_event({"status": "ok", "value": 3})])
    result = run_cli(_call())
    assert result.structured_output == {"status": "ok", "value": 3}
    assert result.input_tokens == 2 + 1099 + 10
    assert result.output_tokens == 115
    assert result.models == (MODEL,)
    assert result.num_turns == 2
    assert result.claude_code_version == "9.9.9"
    assert [event["type"] for event in result.events] == ["system", "result"]


def test_tokens_are_summed_over_requests_of_the_model(fake: FakeClaude) -> None:
    usage = {
        MODEL: {
            "inputTokens": 5,
            "outputTokens": 7,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 0,
        }
    }
    fake.set([init_event(), result_event({"status": "ok"}, model_usage=usage)])
    result = run_cli(_call())
    assert (result.input_tokens, result.output_tokens) == (5, 7)


def test_user_message_goes_on_stdin_not_argv(fake: FakeClaude) -> None:
    message = "x" * 200_000
    run_cli(_call(user_message=message))
    assert fake.record["stdin"] == message
    assert all(message not in argument for argument in fake.record["argv"])


def test_api_key_is_removed_and_cwd_is_empty(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    run_cli(_call())
    record = fake.record
    assert record["env_has_api_key"] is False
    assert record["cwd_entries"] == []
    assert Path(record["cwd"]).resolve() != Path.cwd().resolve()
    assert not Path(record["cwd"]).exists(), "the temporary directory is removed afterwards"


def test_mcp_config_is_written_to_the_temporary_directory(fake: FakeClaude) -> None:
    config = {"mcpServers": {"sandbox": {"command": "python3", "args": []}}}
    run_cli(_call(mcp_config=config, allowed_tools=("mcp__sandbox__run_python",)))
    record = fake.record
    assert record["cwd_entries"] == ["mcp.json"]
    argv = record["argv"]
    mcp_path = Path(argv[argv.index("--mcp-config") + 1])
    assert mcp_path.parent.resolve() == Path(record["cwd"]).resolve()


OTHER_USAGE = {
    MODEL: {
        "inputTokens": 1,
        "outputTokens": 1,
        "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 0,
    },
    "claude-sonnet-5-5": {
        "inputTokens": 1,
        "outputTokens": 1,
        "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 0,
    },
}


@pytest.mark.parametrize(
    ("events", "error", "message"),
    [
        (
            [init_event("ANTHROPIC_API_KEY"), result_event({"status": "ok"})],
            ClaudeAuthError,
            "ANTHROPIC_API_KEY",
        ),
        (
            [
                init_event(),
                result_event(
                    None, subtype="error_during_execution", is_error=True, api_error_status=429
                ),
            ],
            ClaudeUsageLimit,
            "usage limit",
        ),
        ([init_event(), result_event(None, stop_reason="refusal")], ClaudeRefusal, "refusal"),
        (
            [init_event(), result_event(None, subtype="error_max_budget_usd", is_error=True)],
            ClaudeBudgetExceeded,
            "max_case_usd",
        ),
        (
            [init_event(), result_event({"status": "ok"}, model_usage=OTHER_USAGE)],
            ClaudeUnexpectedModel,
            "claude-sonnet-5-5",
        ),
        ([init_event(), result_event(None)], ClaudeNoAnswer, "structured"),
    ],
)
def test_errors(
    fake: FakeClaude, events: list[dict], error: type[ClaudeCliError], message: str
) -> None:
    fake.set(events)
    with pytest.raises(error, match=message):
        run_cli(_call())


def test_missing_result_event_reports_exit_code_and_stderr(fake: FakeClaude) -> None:
    fake.set([init_event()], exit_code=3, stderr="Error: something broke")
    with pytest.raises(ClaudeRunError, match=r"exit code 3.*something broke"):
        run_cli(_call())


def test_timeout_kills_the_process_group(fake: FakeClaude) -> None:
    fake.set([init_event(), result_event({"status": "ok"})], sleep_s=30)
    start = time.monotonic()
    with pytest.raises(ClaudeTimeout, match="1"):
        run_cli(_call(timeout_s=1))
    assert time.monotonic() - start < 10
    pid = fake.record["pid"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"fake claude (pid {pid}) is still running")


def test_claude_code_version() -> None:
    assert claude_code_version(FAKE_COMMAND) == "9.9.9"
    assert claude_code_version(("geoevals-no-such-command",)) == "unknown"


def test_missing_init_event_is_an_auth_error(fake: FakeClaude) -> None:
    fake.set([result_event({"status": "ok"})])
    with pytest.raises(ClaudeAuthError, match="None"):
        run_cli(_call())


def test_usage_limit_in_the_result_text(fake: FakeClaude) -> None:
    text = "Claude usage limit reached. Your limit will reset at 5pm."
    fake.set([init_event(), result_event(None, subtype="success", is_error=True, result=text)])
    with pytest.raises(ClaudeUsageLimit, match="reset at 5pm"):
        run_cli(_call())


def test_usage_limit_on_stderr_without_a_result(fake: FakeClaude) -> None:
    fake.set([init_event()], exit_code=1, stderr="API Error: 429 rate_limit_error")
    with pytest.raises(ClaudeUsageLimit, match="429"):
        run_cli(_call())


def test_other_error_results_are_harness_errors(fake: FakeClaude) -> None:
    fake.set(
        [
            init_event(),
            result_event(
                None, subtype="error_during_execution", is_error=True, api_error_status=529
            ),
        ]
    )
    with pytest.raises(ClaudeRunError, match="529"):
        run_cli(_call())
    assert "ClaudeRunError" in HARNESS_ERRORS
    for model_failure in [
        "ClaudeTimeout",
        "ClaudeRefusal",
        "ClaudeNoAnswer",
        "ClaudeBudgetExceeded",
    ]:
        assert model_failure not in HARNESS_ERRORS


def test_provider_and_key_variables_are_removed(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in [
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
    ]:
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("CLAUDE_EFFORT", "low")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "outer")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/claude-config")
    run_cli(_call())
    env = fake.record["env"]
    assert sorted(env) == ["CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER"]
    assert env["DISABLE_AUTOUPDATER"] == "1"


def _gone(pid: int, within_s: float) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_watchdog_stops_the_cli_when_its_parent_is_killed(fake: FakeClaude, tmp_path: Path) -> None:
    """The runner kills an adapter worker with SIGKILL on a run timeout; the CLI must not
    outlive it."""
    fake.set([init_event(), result_event({"status": "ok"})], sleep_s=60)
    script = tmp_path / "parent.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).parent)!r})\n"
        "from claude_fakes import FAKE_COMMAND\n"
        "from geoevals.leaderboard.claude_cli import CliCall, run_cli\n"
        "run_cli(CliCall(model='claude-haiku-5-5', system_prompt='s', user_message='u',"
        " json_schema={}, command=FAKE_COMMAND, timeout_s=120))\n",
        encoding="utf-8",
    )
    parent = subprocess.Popen([sys.executable, str(script)])
    deadline = time.monotonic() + 30
    while not fake.called and time.monotonic() < deadline:
        time.sleep(0.05)
    assert fake.called, "the fake CLI did not start"
    parent.kill()
    parent.wait()
    assert _gone(fake.record["pid"], within_s=10), "the CLI outlived its killed parent"
