import copy
import json
import pickle
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest

from claude_fakes import FAKE_COMMAND, MODEL, FakeClaude, init_event, result_event
from geoevals.adapters import SkipCase, TokenUsage, adapter_factory, registered_adapter_names
from geoevals.adapters import claude as claude_module
from geoevals.adapters.claude import (
    MODELS,
    RUN_PYTHON_TOOL,
    ClaudeConfigError,
    ClaudeDirectAdapter,
    ClaudePythonAdapter,
    trajectory_from_events,
)
from geoevals.leaderboard import sandbox
from geoevals.leaderboard.claude_cli import (
    ClaudeRefusal,
    ClaudeTimeout,
    ClaudeVersionChanged,
    CliCall,
    CliResult,
)
from geoevals.leaderboard.prompting import (
    cli_schema,
    direct_message,
    load_template,
    python_message,
    spec_for,
    system_prompt,
)
from geoevals.runner.config import parse_run_config
from geoevals.runner.run import Case, load_cases, run_benchmark
from geoevals.trajectory import trajectory_problem
from geoevals.validation import load_benchmark_spec

REPO = Path(__file__).parent.parent
GIS = REPO / "benchmarks" / "gis_correctness"
ACCESS = REPO / "benchmarks" / "human_context"


def _case(bench_dir: Path, case_id: str) -> Case:
    spec = load_benchmark_spec(bench_dir / "benchmark.yaml")
    return next(case for case in load_cases(spec, bench_dir) if case.case_id == case_id)


def _strip_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return {k: _strip_key(v, key) for k, v in value.items() if k != key}
    if isinstance(value, list):
        return [_strip_key(item, key) for item in value]
    return value


# --- prompting --------------------------------------------------------------------------------


def test_direct_message_inlines_geojson_and_withholds_answers() -> None:
    case = _case(GIS, "spatial_join-005")
    message = direct_message(case.input)
    assert case.input["prompt"] in message
    assert json.dumps(case.input["inputs"]["params"], indent=2) in message
    stations = (GIS / "fixtures" / "join_stations.geojson").read_text(encoding="utf-8")
    assert stations.strip() in message
    assert 'Input file "right" (fixtures/join_stations.geojson, GeoJSON):' in message
    for withheld in ["spatial_join-005", "expected", "trap", "tol_m", "float_tol"]:
        assert withheld not in message, withheld


def test_parquet_inputs_become_geojson() -> None:
    case = _case(ACCESS, "nearest_amenity-001")
    message = direct_message(case.input)
    for name in ["nodes", "edges", "pois"]:
        relative = case.input["inputs"]["files"][name]
        header = f'Input file "{name}" ({relative}, GeoJSON):\n'
        assert header in message
        text = message.split(header, 1)[1].split("\n\nInput file ", 1)[0]
        collection = json.loads(text)
        frame = gpd.read_parquet(ACCESS / relative)
        assert collection["type"] == "FeatureCollection"
        assert len(collection["features"]) == len(frame)
        assert collection == json.loads(frame.to_json(drop_id=True))


def test_python_message_gives_container_paths() -> None:
    case = _case(GIS, "spatial_join-005")
    message = python_message(case.input)
    assert case.input["prompt"] in message
    assert 'Input file "right": /bench/fixtures/join_stations.geojson' in message
    assert "FeatureCollection" not in message
    assert "spatial_join-005" not in message


def test_cli_schema_drops_evidence_type_only() -> None:
    access = load_benchmark_spec(ACCESS / "benchmark.yaml").output_schema
    original = copy.deepcopy(access)
    cleaned = cli_schema(access)
    assert "evidence_type" not in json.dumps(cleaned)
    assert cleaned == _strip_key(original, "evidence_type")
    assert access == original, "the spec schema is not modified"
    gis = load_benchmark_spec(GIS / "benchmark.yaml").output_schema
    assert cli_schema(gis) == gis


def test_templates_exist_and_take_the_task_statement() -> None:
    for track in ["direct", "python"]:
        template = load_template(track, "v1")
        assert template.count("{task_statement}") == 1
        assert "TASK X" in system_prompt(template, "TASK X")
        assert "to 5 decimal places" in " ".join(template.split())
        assert "{task_statement}" not in system_prompt(template, "TASK X")
    with pytest.raises(ValueError, match="v9"):
        load_template("direct", "v9")


def test_spec_for_reads_the_cases_benchmark() -> None:
    case = _case(ACCESS, "nearest_amenity-001")
    task_statement, schema = spec_for(case.input)
    spec = load_benchmark_spec(ACCESS / "benchmark.yaml")
    assert task_statement == spec.task_statement
    assert schema == spec.output_schema


# --- direct adapter ---------------------------------------------------------------------------


def _direct(config: dict[str, Any] | None = None, slug: str = "haiku_5_5") -> ClaudeDirectAdapter:
    adapter = ClaudeDirectAdapter(slug)
    adapter.setup({"claude_command": list(FAKE_COMMAND), **(config or {})})
    return adapter


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    return FakeClaude(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def no_real_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapters read the CLI version; tests never run the real CLI."""
    monkeypatch.setattr(claude_module, "claude_code_version", lambda command=None: "9.9.9")


def test_direct_adapter_returns_answer_and_tokens(fake: FakeClaude) -> None:
    answer = {"status": "ok", "value": 1.5, "units": "m", "crs": "EPSG:32633"}
    fake.set([init_event(), result_event(answer)])
    case = _case(GIS, "distance-003")
    response = _direct().predict(case.input)
    assert response.output == answer
    assert response.tokens == TokenUsage(input=2 + 1099 + 10, output=115)
    assert response.trajectory is None
    argv = fake.record["argv"]
    assert argv[argv.index("--model") + 1] == MODEL
    system = argv[argv.index("--system-prompt") + 1]
    assert load_benchmark_spec(GIS / "benchmark.yaml").task_statement.strip() in system
    assert fake.record["stdin"] == direct_message(case.input)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == cli_schema(
        load_benchmark_spec(GIS / "benchmark.yaml").output_schema
    )


def test_adapter_name_and_version() -> None:
    adapter = ClaudeDirectAdapter("opus_5_5")
    assert adapter.name == "claude_direct_opus_5_5"
    assert adapter.model == "claude-opus-5-5"
    assert adapter.version.startswith("0.1.0+cc.")
    assert ClaudePythonAdapter("sonnet_5_5").name == "claude_python_sonnet_5_5"
    with pytest.raises(ValueError, match="gpt"):
        ClaudeDirectAdapter("gpt")


def test_only_cases_skips_other_cases(fake: FakeClaude) -> None:
    adapter = _direct({"only_cases": ["distance-003"]})
    with pytest.raises(SkipCase, match="only_cases"):
        adapter.predict(_case(GIS, "distance-001").input)
    assert not fake.called
    adapter.predict(_case(GIS, "distance-003").input)
    assert fake.called


def test_usage_limit_skips_later_cases(fake: FakeClaude) -> None:
    limit = result_event(
        None, subtype="error_during_execution", is_error=True, api_error_status=429
    )
    fake.set([init_event(), limit])
    adapter = _direct()
    with pytest.raises(SkipCase, match="usage limit reached"):
        adapter.predict(_case(GIS, "distance-001").input)
    fake.record_path.unlink()
    with pytest.raises(SkipCase, match="usage limit reached"):
        adapter.predict(_case(GIS, "distance-003").input)
    assert not fake.called


def test_errors_propagate_with_their_type(fake: FakeClaude) -> None:
    fake.set([init_event(), result_event(None, stop_reason="refusal")])
    with pytest.raises(ClaudeRefusal):
        _direct().predict(_case(GIS, "distance-001").input)


def test_setup_fails_when_the_cli_is_missing() -> None:
    with pytest.raises(RuntimeError, match="not on PATH"):
        ClaudeDirectAdapter("haiku_5_5").setup({"claude_command": ["geoevals-no-such-claude"]})


def test_config_rejects_unknown_keys_and_templates() -> None:
    with pytest.raises(ClaudeConfigError, match="temperature"):
        ClaudeDirectAdapter("haiku_5_5").setup({"temperature": 0})
    with pytest.raises(ValueError, match="v7"):
        ClaudeDirectAdapter("haiku_5_5").setup({"prompt_version": "v7"})


def test_registered_names_and_factories_pickle() -> None:
    names = {f"claude_{track}_{slug}" for track in ["direct", "python"] for slug in MODELS}
    assert names <= set(registered_adapter_names())
    for name in names:
        factory = pickle.loads(pickle.dumps(adapter_factory(name)))
        assert factory.func in (ClaudeDirectAdapter, ClaudePythonAdapter)


@pytest.mark.integration
def test_direct_adapter_in_a_full_run(fake: FakeClaude) -> None:
    right = _case(GIS, "distance-003")
    fake.set([init_event(), result_event(right.expected)])
    config = parse_run_config(
        {
            "split": "test",
            "adapter": {
                "claude_command": list(FAKE_COMMAND),
                "only_cases": ["distance-003", "distance-001"],
            },
        }
    )
    result = run_benchmark(GIS / "benchmark.yaml", "claude_direct_haiku_5_5", config)
    statuses = {case["case_id"]: case["status"] for case in result["cases"]}
    assert statuses["distance-003"] == "scored"
    assert statuses["distance-001"] == "scored"
    assert sum(status == "skipped" for status in statuses.values()) == len(statuses) - 2
    record = next(case for case in result["cases"] if case["case_id"] == "distance-003")
    assert record["metrics"]["task_success"]["passed"] is True
    assert record["tokens"] == {"input": 2 + 1099 + 10, "output": 115}
    assert record["cost_usd"] is None
    assert result["adapter"]["name"] == "claude_direct_haiku_5_5"


# --- python adapter ---------------------------------------------------------------------------


def _python(monkeypatch: pytest.MonkeyPatch, removed: list[str]) -> ClaudePythonAdapter:
    monkeypatch.setattr(sandbox, "docker_available", lambda: True)
    monkeypatch.setattr(sandbox, "remove_container", removed.append)
    adapter = ClaudePythonAdapter("haiku_5_5")
    adapter.setup({"claude_command": list(FAKE_COMMAND), "sandbox_image": "img:1"})
    return adapter


def _tool_use(tool_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    block = {"type": "tool_use", "id": tool_id, "name": name, "input": payload}
    return {"type": "assistant", "message": {"content": [block]}}


def _tool_result(tool_id: str, text: object, is_error: bool = False) -> dict[str, Any]:
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}
    return {"type": "user", "message": {"content": [block]}}


ANSWER = {"status": "ok", "value": 1.5, "units": "m", "crs": "EPSG:32633"}
TOOL_EVENTS = [
    _tool_use("t1", RUN_PYTHON_TOOL, {"code": "print(1/0)"}),
    _tool_result("t1", "exit code: 1\n--- stderr ---\nZeroDivisionError", is_error=True),
    _tool_use("t2", RUN_PYTHON_TOOL, {"code": "print(1.5)"}),
    _tool_result("t2", [{"type": "text", "text": "exit code: 0\n1.5"}]),
    _tool_use("t3", "StructuredOutput", ANSWER),
    _tool_result("t3", "Structured output provided successfully"),
]


def test_trajectory_from_events() -> None:
    steps = trajectory_from_events([init_event(), *TOOL_EVENTS, result_event(ANSWER)])
    assert trajectory_problem(steps) is None
    assert [step["step"] for step in steps] == [0, 1, 2]
    assert [step["tool"] for step in steps] == ["run_python", "run_python", None]
    assert steps[0]["status"] == "error" and "ZeroDivisionError" in steps[0]["error_message"]
    assert steps[1] == {
        "step": 1,
        "tool": "run_python",
        "args": {"code": "print(1.5)"},
        "status": "ok",
        "error_message": None,
        "duration_s": None,
        "tokens": None,
    }
    assert steps[2]["args"] == {}


def test_python_adapter_passes_the_mcp_server_and_paths(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[str] = []
    adapter = _python(monkeypatch, removed)
    tools = ["StructuredOutput", RUN_PYTHON_TOOL]
    fake.set([init_event(tools=tools), *TOOL_EVENTS, result_event(ANSWER)])
    case = _case(GIS, "distance-003")
    response = adapter.predict(case.input)
    assert response.output == ANSWER
    assert response.trajectory is not None and len(response.trajectory) == 3
    record = fake.record
    argv = record["argv"]
    assert argv[argv.index("--allowedTools") + 1] == RUN_PYTHON_TOOL
    assert record["cwd_entries"] == ["mcp.json"]
    assert "/bench/fixtures/distance_points.geojson" in record["stdin"]
    assert "FeatureCollection" not in record["stdin"]
    system = argv[argv.index("--system-prompt") + 1]
    assert "run_python" in system
    [name] = removed
    assert name.startswith("geoevals-")


def test_python_adapter_mcp_config(fake: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[CliCall] = []
    monkeypatch.setattr(claude_module, "run_cli", lambda call: calls.append(call) or _ok_result())
    removed: list[str] = []
    adapter = _python(monkeypatch, removed)
    adapter.predict(_case(GIS, "distance-003").input)
    [call] = calls
    assert call.mcp_config is not None
    server = call.mcp_config["mcpServers"]["sandbox"]
    args = server["args"]
    assert args[:2] == ["-m", "geoevals.leaderboard.sandbox_mcp"]
    assert args[args.index("--image") + 1] == "img:1"
    assert args[args.index("--name") + 1] == removed[0]
    assert call.container == removed[0], "the watchdog removes the container if stopped"
    assert args[args.index("--max-calls") + 1] == "20"
    assert Path(args[args.index("--fixtures") + 1]) == GIS.resolve() / "fixtures"


def _ok_result() -> CliResult:
    return CliResult(ANSWER, 10, 5, (MODEL,), 2, "9.9.9", [])


def test_python_adapter_removes_the_container_on_error(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[str] = []
    adapter = _python(monkeypatch, removed)
    fake.set([init_event(), result_event(ANSWER)], sleep_s=30)
    adapter.setup(
        {"claude_command": list(FAKE_COMMAND), "sandbox_image": "img:1", "case_timeout_s": 1}
    )
    with pytest.raises(ClaudeTimeout):
        adapter.predict(_case(GIS, "distance-003").input)
    assert len(removed) == 1


def test_python_setup_fails_without_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "docker_available", lambda: False)
    with pytest.raises(RuntimeError, match="Docker"):
        ClaudePythonAdapter("haiku_5_5").setup({"claude_command": list(FAKE_COMMAND)})


def test_version_change_during_a_run_fails_the_case(
    fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _direct()
    init = {**init_event(), "claude_code_version": "9.9.10"}
    fake.set([init, result_event({"status": "ok"})])
    with pytest.raises(ClaudeVersionChanged, match=r"9\.9\.10"):
        adapter.predict(_case(GIS, "distance-001").input)
