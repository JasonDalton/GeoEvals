import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from geoevals.adapters import AdapterResponse, MockAdapter, MockConfigError, registry
from geoevals.cli import main
from geoevals.reporting.report import render_markdown, report_context
from geoevals.runner.config import RunConfig
from geoevals.runner.run import load_cases, run_benchmark
from geoevals.trajectory import run_aggregates, summarize_trajectory, trajectory_problem
from geoevals.validation import load_benchmark_spec, validate_run_result_document
from geoevals.validation.run_result import AgentSummary, TrajectoryStep
from geoevals.validation.validate import load_schema

REPO = Path(__file__).resolve().parent.parent
GIS = REPO / "benchmarks" / "gis_correctness" / "benchmark.yaml"
SMOKE = REPO / "benchmarks" / "smoke" / "benchmark.yaml"

WRONG_CASE = "distance-001"
RECOVER_CASE = "buffer-001"
LOOP_CASE = "overlay-001"
MAX_STEPS = 5
WRONG_OUTPUT = {"status": "ok", "value": 7.9, "units": "km", "crs": "OGC:CRS84"}


def _step(step: int, tool: str | None = "buffer", **fields: Any) -> dict[str, Any]:
    return {
        "step": step,
        "tool": tool,
        "args": {},
        "status": "ok",
        "error_message": None,
        "duration_s": 0.5,
        "tokens": None,
        **fields,
    }


# --- schema ------------------------------------------------------------------------------------


def test_schema_defines_the_trajectory_step_fields() -> None:
    schema = load_schema("run-result.schema.json")
    step = schema["$defs"]["trajectoryStep"]
    fields = {"step", "tool", "args", "status", "error_message", "duration_s", "tokens"}
    assert set(step["required"]) == fields == set(step["properties"])
    assert step["properties"]["status"]["enum"] == ["ok", "error"]
    assert step["properties"]["args"]["type"] == "object"
    case = schema["$defs"]["caseRecord"]
    assert case["properties"]["trajectory"]["items"] == {"$ref": "#/$defs/trajectoryStep"}
    agent = schema["$defs"]["agentSummary"]
    assert set(agent["required"]) == {"tool_calls", "tool_errors", "agent_steps", "agent_runtime_s"}
    assert {"tool_error_rate", "mean_steps"} <= set(schema["$defs"]["efficiency"]["properties"])
    assert set(TrajectoryStep.model_fields) == fields
    assert set(AgentSummary.model_fields) == set(agent["required"])


@pytest.mark.parametrize(
    ("steps", "problem"),
    [
        ([], None),
        ([_step(0), _step(1, tool=None)], None),
        ([_step(0, status="error", error_message="boom", duration_s=None)], None),
        ([_step(0, tokens={"input": 3, "output": 1})], None),
        ([_step(0, status="error")], "trajectory.0.error_message: None is not of type 'string'"),
        ([_step(0, error_message="boom")], "trajectory.0.error_message: 'boom' is not of type"),
        ([_step(0, status="skipped")], "trajectory.0.status: 'skipped' is not one of"),
        ([_step(0, args=[1])], "trajectory.0.args: [1] is not of type 'object'"),
        ([_step(0, duration_s=-1)], "trajectory.0.duration_s: -1 is less than the minimum"),
        ([_step(0, tool="")], "trajectory.0.tool"),
        ([{k: v for k, v in _step(0).items() if k != "tokens"}], "'tokens' is a required"),
        ([_step(0, extra=1)], "Additional properties are not allowed"),
        ([_step(1)], "step 0 has step number 1; steps are numbered from 0"),
        ([_step(0), _step(0)], "step 1 has step number 0"),
        ([_step(0, duration_s=float("nan"))], "trajectory is not JSON"),
        ({"step": 0}, "trajectory.<root>: {'step': 0} is not of type 'array'"),
    ],
)
def test_trajectory_problem(steps: Any, problem: str | None) -> None:
    found = trajectory_problem(steps)
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found, found


def test_summary_counts_tool_calls_errors_steps_and_runtime() -> None:
    steps = [
        _step(0, tool="read"),
        _step(1, status="error", error_message="bad args", duration_s=0.25),
        _step(2),
        _step(3, tool=None, status="error", error_message="loop guard"),
    ]
    assert summarize_trajectory(steps) == {
        "tool_calls": 3,
        "tool_errors": 1,  # the guard step calls no tool, so it is not a tool error
        "agent_steps": 4,
        "agent_runtime_s": 1.75,
    }
    assert summarize_trajectory([_step(0, duration_s=None)])["agent_runtime_s"] is None
    assert summarize_trajectory([]) == {
        "tool_calls": 0,
        "tool_errors": 0,
        "agent_steps": 0,
        "agent_runtime_s": 0.0,
    }


def test_run_aggregates() -> None:
    summaries = [
        {"tool_calls": 3, "tool_errors": 1, "agent_steps": 4},
        {"tool_calls": 1, "tool_errors": 0, "agent_steps": 1},
    ]
    assert run_aggregates(summaries) == {"tool_error_rate": 0.25, "mean_steps": 2.5}
    assert run_aggregates([]) == {"tool_error_rate": None, "mean_steps": None}
    no_calls = [{"tool_calls": 0, "tool_errors": 0, "agent_steps": 1}]
    assert run_aggregates(no_calls) == {"tool_error_rate": None, "mean_steps": 1.0}


# --- mock_agent mode ---------------------------------------------------------------------------


def _mock_agent(rule: dict[str, Any], **config: Any) -> MockAdapter:
    adapter = MockAdapter()
    adapter.setup(
        {
            "mode": "mock_agent",
            "references": {"c": {"status": "ok", "value": 2.0, "units": "m"}},
            "cases": {"c": rule},
            **config,
        }
    )
    return adapter


CASE_INPUT = {"case_id": "c", "operation": "distance", "inputs": {"params": {"units": "m"}}}


def test_mock_agent_all_ok_with_wrong_answer() -> None:
    response = _mock_agent({"behavior": "wrong", "script": "all_ok"}).predict(CASE_INPUT)
    assert response.output == {"status": "ok_wrong", "value": 3.0, "units": "m_wrong"}
    trajectory = response.trajectory
    assert trajectory is not None and trajectory_problem(trajectory) is None
    assert [(s["tool"], s["status"]) for s in trajectory] == [
        ("read_inputs", "ok"),
        ("distance", "ok"),
        (None, "ok"),
    ]
    assert trajectory[1]["args"] == {"params": {"units": "m"}}
    assert response.raw == {"mock_behavior": "wrong", "call": 1, "mock_script": "all_ok"}


def test_mock_agent_error_then_recover() -> None:
    adapter = _mock_agent({"behavior": "reference", "script": "error_then_recover"})
    response = adapter.predict(CASE_INPUT)
    assert response.output == {"status": "ok", "value": 2.0, "units": "m"}
    trajectory = response.trajectory
    assert trajectory is not None and trajectory_problem(trajectory) is None
    assert [(s["tool"], s["status"]) for s in trajectory] == [
        ("read_inputs", "ok"),
        ("distance", "error"),
        ("distance", "ok"),
        (None, "ok"),
    ]
    assert trajectory[1]["error_message"] == (
        "mock tool error: distance called without its parameters"
    )
    assert summarize_trajectory(trajectory)["tool_errors"] == 1


def test_mock_agent_loop_guard() -> None:
    adapter = _mock_agent({"behavior": "malformed", "script": "loop_guard"}, max_steps=4)
    response = adapter.predict(CASE_INPUT)
    assert response.output == {"mock_malformed_output": True}
    trajectory = response.trajectory
    assert trajectory is not None and trajectory_problem(trajectory) is None
    assert [s["tool"] for s in trajectory] == ["read_inputs", *["distance"] * 3, None]
    guard = trajectory[-1]
    assert (guard["status"], guard["error_message"]) == (
        "error",
        "loop guard: stopped after 4 tool calls without an answer",
    )
    assert summarize_trajectory(trajectory) == {
        "tool_calls": 4,
        "tool_errors": 0,
        "agent_steps": 5,
        "agent_runtime_s": pytest.approx(0.05),
    }


def test_mock_agent_default_script_and_plain_mode() -> None:
    response = _mock_agent({"behavior": "reference"}, step_seconds=0.0).predict(CASE_INPUT)
    assert response.trajectory is not None
    assert [s["tool"] for s in response.trajectory] == ["read_inputs", "distance", None]
    assert {s["duration_s"] for s in response.trajectory} == {0.0}

    plain = MockAdapter()
    plain.setup({"references": {"c": {"status": "ok"}}})
    assert plain.predict(CASE_INPUT).trajectory is None


PLAIN_MODE_SCRIPT = "'script' applies only to mode 'mock_agent'"


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"cases": {"c": {"script": "all_ok"}}}, PLAIN_MODE_SCRIPT),
        ({"default": {"script": "error_then_recover"}}, PLAIN_MODE_SCRIPT),
        (
            {"mode": "mock_agent", "cases": {"c": {"script": "loop_guard"}}},
            "script 'loop_guard' requires behavior 'wrong' or 'malformed'",
        ),
        ({"mode": "mock_agent", "max_steps": 0}, "max_steps"),
        ({"mode": "agent"}, "mode"),
        ({"mode": "mock_agent", "cases": {"c": {"script": "forever"}}}, "script"),
    ],
)
def test_mock_agent_config_errors(config: dict[str, Any], message: str) -> None:
    with pytest.raises(MockConfigError, match=message):
        MockAdapter().setup(config)


# --- a mock_agent run over the GIS benchmark ---------------------------------------------------


@pytest.fixture(scope="module")
def agent_run() -> dict[str, Any]:
    spec = load_benchmark_spec(GIS)
    references = {case.case_id: case.expected for case in load_cases(spec, GIS.parent)}
    adapter = {
        "mode": "mock_agent",
        "max_steps": MAX_STEPS,
        "references": references,
        "cases": {
            # a well-formed answer with a wrong distance
            WRONG_CASE: {"behavior": "wrong", "script": "all_ok", "output": WRONG_OUTPUT},
            RECOVER_CASE: {"behavior": "reference", "script": "error_then_recover"},
            LOOP_CASE: {"behavior": "malformed", "script": "loop_guard"},
        },
    }
    return run_benchmark(GIS, "mock", RunConfig(split="test", adapter=adapter))


def _case(result: dict[str, Any], case_id: str) -> dict[str, Any]:
    [case] = [case for case in result["cases"] if case["case_id"] == case_id]
    return case


def test_all_ok_trajectory_with_wrong_output_fails_task_success(agent_run: dict[str, Any]) -> None:
    case = _case(agent_run, WRONG_CASE)
    assert {step["status"] for step in case["trajectory"]} == {"ok"}
    assert case["agent"] == {
        "tool_calls": 2,
        "tool_errors": 0,
        "agent_steps": 3,
        "agent_runtime_s": pytest.approx(0.03),
    }
    assert case["status"] == "scored"
    task_success = case["metrics"]["task_success"]
    assert (task_success["value"], task_success["passed"]) == (0.0, False)


def test_tool_error_then_recovery_scores_on_the_answer(agent_run: dict[str, Any]) -> None:
    case = _case(agent_run, RECOVER_CASE)
    assert case["agent"]["tool_errors"] == 1
    assert (case["status"], case["retries"]) == ("scored", 0)
    assert case["metrics"]["task_success"]["passed"] is True


def test_loop_guard_case_keeps_its_trajectory(agent_run: dict[str, Any]) -> None:
    case = _case(agent_run, LOOP_CASE)
    assert case["status"] == "invalid_output"
    assert case["metrics"] == {}
    assert case["agent"]["tool_calls"] == MAX_STEPS
    assert case["agent"]["agent_steps"] == MAX_STEPS + 1
    assert case["trajectory"][-1]["error_message"].startswith("loop guard")


def test_agent_run_aggregates(agent_run: dict[str, Any]) -> None:
    assert validate_run_result_document(agent_run) == []
    cases = agent_run["cases"]
    assert all("trajectory" in case for case in cases)
    calls = sum(case["agent"]["tool_calls"] for case in cases)
    steps = sum(case["agent"]["agent_steps"] for case in cases)
    # every case calls read_inputs and its operation once; buffer-001 calls it twice and
    # overlay-001 loops until the guard
    assert calls == 2 * len(cases) + 1 + (MAX_STEPS - 2)
    efficiency = agent_run["efficiency"]
    assert efficiency["tool_error_rate"] == pytest.approx(1 / calls)
    assert efficiency["mean_steps"] == pytest.approx(steps / len(cases))
    # trajectories never reach the metrics: the mean is that of the per-case answers
    passed = [c["metrics"]["task_success"]["passed"] for c in cases if c["status"] == "scored"]
    assert passed.count(False) == 1


def test_report_shows_trajectories_of_failed_cases(agent_run: dict[str, Any]) -> None:
    context = report_context(agent_run, "test")
    trajectories = context["trajectories"]
    assert len(trajectories["summary"]) == len(agent_run["cases"])
    assert [case["case_id"] for case in trajectories["failed"]] == [WRONG_CASE, LOOP_CASE]
    [loop] = [case for case in trajectories["failed"] if case["case_id"] == LOOP_CASE]
    assert len(loop["steps"]) == MAX_STEPS + 1
    markdown = render_markdown(context)
    assert f"### Trajectory of {WRONG_CASE} (failed)" in markdown
    assert f"### Trajectory of {LOOP_CASE} (not scored)" in markdown
    assert f"### Trajectory of {RECOVER_CASE}" not in markdown
    assert f"| {WRONG_CASE} | scored | failed | 2 | 0 | 3 | 0.03 |" in markdown


def test_report_without_trajectories() -> None:
    result = run_benchmark(SMOKE, "mock", RunConfig(split="test"))
    assert all("trajectory" not in case for case in result["cases"])
    assert result["efficiency"]["tool_error_rate"] is None
    assert result["efficiency"]["mean_steps"] is None
    markdown = render_markdown(report_context(result, "test"))
    assert "No case recorded an agent trajectory." in markdown


# --- the runner checks trajectories ------------------------------------------------------------


class BadTrajectoryAdapter:
    """Answers every case correctly, with a trajectory whose step numbers skip 0."""

    name = "bad_trajectory"
    version = "0.0.1"

    def setup(self, config: Mapping[str, Any]) -> None:
        pass

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        return AdapterResponse(output={"status": "ok"}, trajectory=[_step(1)])

    def teardown(self) -> None:
        pass


def test_runner_rejects_a_bad_trajectory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {"bad_trajectory": BadTrajectoryAdapter})
    result = run_benchmark(SMOKE, "bad_trajectory", RunConfig(split="test"))
    case = result["cases"][0]
    assert case["status"] == "invalid_output"
    assert case["error"] == {
        "type": "InvalidTrajectory",
        "message": "step 0 has step number 1; steps are numbered from 0",
    }
    assert case["output"] == {"status": "ok"}
    assert "trajectory" not in case and "agent" not in case


# --- run result checks -------------------------------------------------------------------------


def test_validation_rejects_agent_counts_that_do_not_match(agent_run: dict[str, Any]) -> None:
    doc = copy.deepcopy(agent_run)
    doc["cases"][0]["agent"]["tool_errors"] = 7
    doc["cases"][1]["trajectory"][0]["step"] = 3
    del doc["cases"][2]["agent"]
    issues = [str(issue) for issue in validate_run_result_document(doc)]
    assert any("'agent' is a dependency of 'trajectory'" in issue for issue in issues), issues

    doc["cases"][2]["agent"] = agent_run["cases"][2]["agent"]
    issues = [str(issue) for issue in validate_run_result_document(doc)]
    assert issues == [
        "cases[0].trajectory: tool_errors is 7, but the trajectory gives 0",
        "cases[1].trajectory: step 0 has step number 3; steps are numbered from 0",
    ]


def test_cli_report_on_an_agent_run(
    tmp_path: Path, agent_run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "result.json").write_text(json.dumps(agent_run), encoding="utf-8")
    assert main(["report", str(tmp_path)]) == 0
    capsys.readouterr()
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<h2>6. Agent trajectories</h2>" in html
    assert f"<h3>Trajectory of {WRONG_CASE} (failed)</h3>" in html
