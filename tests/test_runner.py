import json
import os
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from geoevals.adapters import AdapterResponse, registry
from geoevals.cli import main
from geoevals.metrics import Metric, MetricValue
from geoevals.metrics import registry as metric_registry
from geoevals.runner.config import (
    RunConfig,
    RunConfigError,
    config_hash,
    load_run_config,
    parse_run_config,
)
from geoevals.runner.run import RunError, run_benchmark
from geoevals.validation import validate_run_result_document
from geoevals.validation.validate import load_yaml

FIXTURES = Path(__file__).parent / "fixtures" / "runner"
SPEC = FIXTURES / "benchmark.yaml"
RUN_CONFIG = FIXTURES / "run_config.yaml"


class ExactMatch(Metric):
    id = "exact_match"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        passed = prediction == reference
        return MetricValue(value=1.0 if passed else 0.0, passed=passed)


class CrashingAdapter:
    """Kills its own process on the first call: a native crash, as seen by the runner."""

    name = "crashing"
    version = "0.0.1"

    def setup(self, config: Mapping[str, Any]) -> None:
        pass

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        os._exit(3)

    def teardown(self) -> None:
        pass


class NotAResponseAdapter(CrashingAdapter):
    name = "not_a_response"

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        return {"status": "ok"}  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def exact_match_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metric_registry, "_REGISTRY", {"exact_match": ExactMatch()})


def _config(**overrides: Any) -> RunConfig:
    document = load_yaml(RUN_CONFIG)
    document.update(overrides)
    return parse_run_config(document)


def _cases(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {case["case_id"]: case for case in result["cases"]}


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(metric_registry, "_REGISTRY", {"exact_match": ExactMatch()})
        return run_benchmark(SPEC, "mock", _config())


# --- config ---------------------------------------------------------------------------------


def test_config_hash_is_canonical() -> None:
    base = parse_run_config({"split": "test", "timeout_s": 1, "adapter": {"b": 1, "a": [2.0]}})
    same = parse_run_config(
        {
            "adapter": {"a": [2], "b": 1.0},
            "workers": 1,
            "max_retries": 0,
            "seed": 0,
            "timeout_s": 1.0,
            "split": "test",
        }
    )
    assert config_hash(base) == config_hash(same)
    assert len(config_hash(base)) == 64
    assert config_hash(base) != config_hash(parse_run_config({"split": "test", "timeout_s": 2}))
    assert config_hash(base) != config_hash(
        parse_run_config({"split": "test", "timeout_s": 1, "adapter": {"b": 1, "a": [2.5]}})
    )


def test_config_fields_and_defaults() -> None:
    config = load_run_config(RUN_CONFIG)
    assert (config.split, config.seed, config.timeout_s) == ("test", 7, 1.0)
    assert (config.max_retries, config.workers) == (2, 1)
    assert config.adapter["seed"] == 7
    defaults = parse_run_config({"split": "test"})
    assert (defaults.seed, defaults.max_retries, defaults.workers) == (0, 0, 1)
    assert defaults.adapter == {}


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"split": "test", "unknown": 1},
        {"split": "test", "workers": 0},
        {"split": "test", "timeout_s": 0},
        {"split": "test", "max_retries": -1},
        {"split": "test", "seed": "7"},
        ["split", "test"],
    ],
)
def test_invalid_config_is_rejected(document: Any) -> None:
    with pytest.raises(RunConfigError):
        parse_run_config(document)


# --- statuses -------------------------------------------------------------------------------


def test_run_result_is_valid_and_ordered(result: dict[str, Any]) -> None:
    assert validate_run_result_document(result) == []
    ids = [case["case_id"] for case in result["cases"]]
    assert ids == sorted(ids)
    assert len(ids) == 10
    assert result["config_hash"] == config_hash(_config())
    assert result["run_id"].startswith("runner_fixture-mock-")
    assert result["run_id"].endswith(result["config_hash"][:8])
    assert {f["case_id"] for f in result["failures"]} == {
        case["case_id"] for case in result["cases"] if case["status"] != "scored"
    }


def test_scored_case(result: dict[str, Any]) -> None:
    case = _cases(result)["case-ref"]
    assert case["status"] == "scored"
    assert case["split"] == "test"
    assert case["output"] == {"status": "ok", "area_m2": 12.5}
    assert case["metrics"] == {"exact_match": {"value": 1.0, "passed": True, "detail": {}}}
    assert case["tokens"] == {"input": 10, "output": 2}
    assert case["retries"] == 0
    assert case["error"] is None
    assert case["strata"] == {"operation": "area", "region": "europe"}
    wrong = _cases(result)["case-wrong"]
    assert wrong["status"] == "scored"
    assert wrong["metrics"]["exact_match"]["passed"] is False


def test_adapter_error_is_recorded_and_retried(result: dict[str, Any]) -> None:
    case = _cases(result)["case-raise"]
    assert case["status"] == "adapter_error"
    assert case["error"] == {"type": "MockAdapterError", "message": "boom"}
    assert case["retries"] == 2
    assert case["output"] is None
    assert case["metrics"] == {}


def test_retry_succeeds_and_count_is_recorded(result: dict[str, Any]) -> None:
    case = _cases(result)["case-flaky"]
    assert case["status"] == "scored"
    assert case["retries"] == 2


@pytest.mark.parametrize("max_retries", [0, 1])
def test_retries_are_limited(max_retries: int) -> None:
    config = _config(
        max_retries=max_retries, adapter={"cases": load_yaml(RUN_CONFIG)["adapter"]["cases"]}
    )
    cases = _cases(run_benchmark(SPEC, "mock", config))
    for case_id in ("case-flaky", "case-raise"):
        assert cases[case_id]["status"] == "adapter_error"
        assert cases[case_id]["retries"] == max_retries


def test_invalid_output(result: dict[str, Any]) -> None:
    case = _cases(result)["case-malformed"]
    assert case["status"] == "invalid_output"
    assert case["error"]["type"] == "InvalidOutput"
    assert "'status' is a required property" in case["error"]["message"]
    assert case["output"] == {"mock_malformed_output": True}
    assert case["metrics"] == {}
    assert case["retries"] == 0


def test_timeout_kills_case_and_run_continues(result: dict[str, Any]) -> None:
    cases = _cases(result)
    case = cases["case-sleep"]
    assert case["status"] == "timeout"
    assert case["error"] == {"type": "TimeoutError", "message": "case exceeded timeout_s=1"}
    assert case["retries"] == 0
    assert 1.0 <= case["latency_s"] < 3.0
    # case-wrong sorts after case-sleep, so it ran in a restarted worker.
    assert cases["case-wrong"]["status"] == "scored"


def test_timeout_case_finishes_quickly() -> None:
    config = _config(adapter={"cases": {"case-sleep": {"behavior": "sleep", "seconds": 5}}})
    start = time.perf_counter()
    result = run_benchmark(SPEC, "mock", config)
    elapsed = time.perf_counter() - start
    assert _cases(result)["case-sleep"]["status"] == "timeout"
    assert _cases(result)["case-sleep"]["latency_s"] < 3.0
    assert elapsed < 4.5  # one 5 s sleep cut to 1 s, plus worker start-up and nine fast cases


def test_summary_metrics(result: dict[str, Any]) -> None:
    summary = result["summary_metrics"]["exact_match"]
    scored = [c for c in result["cases"] if c["status"] == "scored"]
    assert summary["version"] == "1.0.0"
    assert summary["n"] == len(scored)
    assert summary["n_failed"] == sum(not c["metrics"]["exact_match"]["passed"] for c in scored)
    assert result["efficiency"]["cases_total"] == 10
    assert result["efficiency"]["retries_total"] == sum(c["retries"] for c in result["cases"])


# --- determinism ----------------------------------------------------------------------------


def _comparable(result: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [(c["case_id"], c["status"], c["output"], c["metrics"]) for c in result["cases"]]


def test_two_runs_are_identical(result: dict[str, Any]) -> None:
    again = run_benchmark(SPEC, "mock", _config())
    assert _comparable(again) == _comparable(result)
    assert again["config_hash"] == result["config_hash"]
    statuses = {
        c["case_id"]: c["metrics"]["exact_match"]["passed"]
        for c in again["cases"]
        if c["case_id"].startswith("case-rand")
    }
    assert len(statuses) == 4


def test_workers_do_not_change_results(result: dict[str, Any]) -> None:
    parallel = run_benchmark(SPEC, "mock", _config(workers=3))
    assert _comparable(parallel) == _comparable(result)


# --- worker failures ------------------------------------------------------------------------


def test_worker_crash_is_an_adapter_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {"crashing": CrashingAdapter})
    result = run_benchmark(SPEC, "crashing", _config(adapter={}, max_retries=1))
    for case in result["cases"]:
        assert case["status"] == "adapter_error"
        assert case["error"]["type"] == "WorkerCrashed"
        assert case["retries"] == 1


def test_non_response_is_an_adapter_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {"not_a_response": NotAResponseAdapter})
    result = run_benchmark(SPEC, "not_a_response", _config(adapter={}, max_retries=0))
    case = _cases(result)["case-ref"]
    assert case["status"] == "adapter_error"
    assert case["error"]["type"] == "TypeError"


def test_adapter_setup_failure_stops_the_run() -> None:
    with pytest.raises(RunError, match="adapter setup failed: MockConfigError"):
        run_benchmark(SPEC, "mock", _config(adapter={"unknown_key": 1}))


def test_unknown_split_stops_the_run() -> None:
    with pytest.raises(RunError, match="split 'train'"):
        run_benchmark(SPEC, "mock", _config(split="train"))


# --- efficiency -----------------------------------------------------------------------------

THROUGHPUT_SPEC = FIXTURES / "throughput.yaml"


class SlowMetric(ExactMatch):
    """Takes 0.3 s to score, so scoring time is clearly separate from adapter latency."""

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        time.sleep(0.3)
        return super().score(prediction, reference, params)


class AllocatingAdapter(CrashingAdapter):
    """Allocates 8 MB during each call and releases it before returning."""

    name = "allocating"

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        block = bytearray(8_000_000)
        del block
        return AdapterResponse(output={"status": "ok", "area_m2": 0.0})


def test_efficiency_figures(result: dict[str, Any]) -> None:
    efficiency = result["efficiency"]
    cases = result["cases"]
    latencies = sorted(c["latency_s"] for c in cases)
    assert efficiency["cases_total"] == 10
    assert efficiency["cases_per_s"] == pytest.approx(10 / efficiency["wall_clock_s"])
    assert efficiency["latency_max_s"] == latencies[-1]
    assert efficiency["latency_p50_s"] == pytest.approx((latencies[4] + latencies[5]) / 2)
    assert efficiency["latency_p50_s"] <= efficiency["latency_p90_s"] <= efficiency["latency_p99_s"]
    assert efficiency["latency_p99_s"] <= efficiency["latency_max_s"]
    assert efficiency["timeout_rate"] == pytest.approx(1 / 10)  # case-sleep
    failed = sum(c["status"] != "scored" for c in cases)
    assert efficiency["failure_rate"] == pytest.approx(failed / 10)
    assert efficiency["retries_total"] == 4  # case-raise 2, case-flaky 2
    assert isinstance(efficiency["peak_rss_bytes"], int)
    assert efficiency["peak_rss_bytes"] > 10_000_000  # at least the runner's own interpreter


def test_scoring_time_is_separate_from_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metric_registry, "_REGISTRY", {"exact_match": SlowMetric()})
    result = run_benchmark(SPEC, "mock", _config(adapter={}))
    case = _cases(result)["case-ref"]
    assert case["status"] == "scored"
    assert case["latency_s"] < 0.2
    assert case["scoring_s"] >= 0.3
    unscored = [c for c in result["cases"] if c["status"] != "scored"]
    assert all(c["scoring_s"] is None for c in unscored)


def test_per_case_memory_with_one_worker(result: dict[str, Any]) -> None:
    for case in result["cases"]:
        if case["status"] == "timeout":
            assert case["peak_memory_bytes"] is None
            assert "killed" in case["memory_note"]
        else:
            assert isinstance(case["peak_memory_bytes"], int)
            assert "memory_note" not in case


def test_per_case_memory_measures_predict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {"allocating": AllocatingAdapter})
    result = run_benchmark(SPEC, "allocating", _config(adapter={}))
    for case in result["cases"]:
        assert case["peak_memory_bytes"] >= 8_000_000


def test_per_case_memory_unavailable_with_several_workers() -> None:
    result = run_benchmark(SPEC, "mock", _config(workers=2))
    assert validate_run_result_document(result) == []
    for case in result["cases"]:
        assert case["peak_memory_bytes"] is None
        assert case["memory_note"] == "per-case memory unavailable when workers > 1"


def test_workers_increase_throughput() -> None:
    adapter = {"default": {"behavior": "sleep", "seconds": 0.2}}
    runs = {
        workers: run_benchmark(
            THROUGHPUT_SPEC, "mock", _config(workers=workers, max_retries=0, adapter=adapter)
        )
        for workers in (1, 4)
    }
    for run in runs.values():
        assert [c["case_id"] for c in run["cases"]] == [f"case-{i:02d}" for i in range(1, 21)]
        assert {c["status"] for c in run["cases"]} == {"scored"}
        assert all(c["latency_s"] >= 0.2 for c in run["cases"])
    serial, parallel = runs[1]["efficiency"], runs[4]["efficiency"]
    assert serial["cases_total"] == parallel["cases_total"] == 20
    assert parallel["cases_per_s"] > serial["cases_per_s"]


# --- CLI ------------------------------------------------------------------------------------


def _run_cli(tmp_path: Path, *extra: str, spec: Path = SPEC) -> int:
    return main(
        [
            "run",
            "--benchmark",
            str(spec),
            "--adapter",
            "mock",
            "--config",
            str(RUN_CONFIG),
            "--out",
            str(tmp_path / "out"),
            *extra,
        ]
    )


def run_dir_of(out: Path) -> Path:
    [run_dir] = out.iterdir()
    return run_dir


def test_cli_run_writes_result_and_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run_cli(tmp_path) == 0
    run_dir = run_dir_of(tmp_path / "out")
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert validate_run_result_document(result) == []
    assert run_dir.name == result["run_id"]
    assert _comparable(result)[0][0] == "case-flaky"
    log = (run_dir / "run.log").read_text(encoding="utf-8")
    # Records logged before the run directory existed are in the log too.
    assert "geoevals.runner.run: benchmark runner_fixture 0.1.0 and manifest" in log
    assert "INFO geoevals.runner.run: case case-ref: scored" in log
    assert "WARNING geoevals.runner.run: case case-sleep: timeout" in log
    captured = capsys.readouterr()
    assert "case case-ref: scored" in captured.err
    assert str(run_dir) in captured.out


def test_cli_log_level(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run_cli(tmp_path, "--log-level", "warning") == 0
    log = (run_dir_of(tmp_path / "out") / "run.log").read_text(encoding="utf-8")
    assert "case case-sleep: timeout" in log
    assert "case case-ref: scored" not in log
    assert "case case-ref: scored" not in capsys.readouterr().err


def test_cli_rejects_invalid_spec(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_dir = tmp_path / "spec"
    shutil.copytree(FIXTURES, spec_dir)
    shutil.copytree(FIXTURES.parent / "manifests", tmp_path / "manifests")
    spec = spec_dir / "benchmark.yaml"
    spec.write_text(spec.read_text().replace("pillar: spatial_reasoning", "pillar: nope"))
    assert _run_cli(tmp_path, spec=spec) == 1
    err = capsys.readouterr().err
    assert "pillar" in err
    # The spec has no valid ID, so there is no run_id and no run directory.
    assert not (tmp_path / "out").exists()


def test_cli_rejects_invalid_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_dir = tmp_path / "spec"
    shutil.copytree(FIXTURES, spec_dir)
    shutil.copytree(FIXTURES.parent / "manifests", tmp_path / "manifests")
    manifest = tmp_path / "manifests" / "valid_manifest.yaml"
    manifest.write_text(manifest.read_text().replace("    license: MIT\n", ""))
    assert _run_cli(tmp_path, spec=spec_dir / "benchmark.yaml") == 1
    assert "license" in capsys.readouterr().err


def test_cli_rejects_invalid_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("split: test\nworkers: 0\n")
    code = main(
        [
            "run",
            "--benchmark",
            str(SPEC),
            "--adapter",
            "mock",
            "--config",
            str(config),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert code == 1
    assert "workers" in capsys.readouterr().err
