import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from geoevals.adapters import AdapterResponse, registry
from geoevals.cli import DEFAULT_PRICES, main
from geoevals.metrics import Metric, MetricValue
from geoevals.metrics import registry as metric_registry
from geoevals.runner.config import parse_run_config
from geoevals.runner.cost import (
    Price,
    PriceTableError,
    case_cost,
    load_price_table,
    parse_price_table,
)
from geoevals.runner.environment import ENVIRONMENT_KEYS, environment_fingerprint
from geoevals.runner.run import run_benchmark
from geoevals.validation import validate_run_result_document

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "runner"
SPEC = FIXTURES / "benchmark.yaml"

PRICES = {
    "mock": {
        "usd_per_1k_input_tokens": 0.5,
        "usd_per_1k_output_tokens": 2.0,
        "usd_per_call": 0.01,
    }
}


class ExactMatch(Metric):
    id = "exact_match"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        return MetricValue(value=float(prediction == reference), passed=prediction == reference)


class DeterministicAdapter:
    """A classical method: no paid calls, no token counts."""

    name = "deterministic"
    version = "0.0.1"
    deterministic = True

    def setup(self, config: Mapping[str, Any]) -> None:
        pass

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        return AdapterResponse(output={"status": "ok", "area_m2": 0.0})

    def teardown(self) -> None:
        pass


@pytest.fixture(autouse=True)
def exact_match_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metric_registry, "_REGISTRY", {"exact_match": ExactMatch()})


def _config(**adapter: Any) -> Any:
    return parse_run_config({"split": "test", "timeout_s": 1, "max_retries": 2, "adapter": adapter})


# --- price table ----------------------------------------------------------------------------


def test_example_price_table_is_valid() -> None:
    table = load_price_table(REPO / DEFAULT_PRICES)
    assert table.prices["mock"] == Price(
        usd_per_1k_input_tokens=0.0, usd_per_1k_output_tokens=0.0, usd_per_call=0.0
    )
    assert len(table.hash) == 64


def test_price_table_hash_is_canonical() -> None:
    reordered = {"mock": dict(reversed(list(PRICES["mock"].items())))}
    integral = {"mock": {**PRICES["mock"], "usd_per_1k_output_tokens": 2}}
    assert parse_price_table(PRICES).hash == parse_price_table(reordered).hash
    assert parse_price_table(PRICES).hash == parse_price_table(integral).hash
    changed = {"mock": {**PRICES["mock"], "usd_per_call": 0.02}}
    assert parse_price_table(PRICES).hash != parse_price_table(changed).hash


@pytest.mark.parametrize(
    "document",
    [
        ["mock"],
        {"mock": 1.0},
        {"mock": {"usd_per_1k_input_tokens": 0.5, "usd_per_1k_output_tokens": 2.0}},
        {"mock": {**PRICES["mock"], "usd_per_call": -0.01}},
        {"mock": {**PRICES["mock"], "usd_per_call": "0.01"}},
        {"mock": {**PRICES["mock"], "usd_per_call": float("nan")}},
        {"mock": {**PRICES["mock"], "currency": "usd"}},
    ],
)
def test_invalid_price_table_is_rejected(document: Any) -> None:
    with pytest.raises(PriceTableError):
        parse_price_table(document)


# --- case cost ------------------------------------------------------------------------------


def test_case_cost() -> None:
    price = Price.model_validate(PRICES["mock"])
    tokens = {"input": 10, "output": 2}
    # 1 call * 0.01 + 10/1000 * 0.5 + 2/1000 * 2.0
    assert case_cost(price, False, 1, tokens) == pytest.approx(0.019)
    assert case_cost(price, False, 3, tokens) == pytest.approx(0.039)
    assert case_cost(price, False, 1, None) is None
    assert case_cost(None, False, 1, tokens) is None
    assert case_cost(None, True, 1, tokens) == 0.0
    assert case_cost(price, True, 1, tokens) == 0.0
    per_call = Price(usd_per_1k_input_tokens=0, usd_per_1k_output_tokens=0, usd_per_call=0.01)
    assert case_cost(per_call, False, 2, None) == pytest.approx(0.02)


def test_run_cost_from_mock_token_counts() -> None:
    config = _config(tokens={"input": 10, "output": 2})
    result = run_benchmark(SPEC, "mock", config, parse_price_table(PRICES))
    assert validate_run_result_document(result) == []
    assert {case["status"] for case in result["cases"]} == {"scored"}
    for case in result["cases"]:
        assert case["tokens"] == {"input": 10, "output": 2}
        assert case["cost_usd"] == pytest.approx(0.019)
    efficiency = result["efficiency"]
    assert efficiency["tokens_input_total"] == 100
    assert efficiency["tokens_output_total"] == 20
    assert efficiency["cost_usd_total"] == pytest.approx(0.19)
    assert efficiency["cost_usd_per_case"] == pytest.approx(0.019)
    assert efficiency["price_table_hash"] == parse_price_table(PRICES).hash


def test_retries_are_billed_and_unknown_tokens_give_null() -> None:
    config = _config(
        tokens={"input": 10, "output": 2},
        cases={
            "case-flaky": {"behavior": "fail_then_succeed", "failures": 2},
            "case-raise": {"behavior": "raise", "message": "boom"},
        },
    )
    result = run_benchmark(SPEC, "mock", config, parse_price_table(PRICES))
    cases = {case["case_id"]: case for case in result["cases"]}
    assert cases["case-flaky"]["retries"] == 2
    assert cases["case-flaky"]["cost_usd"] == pytest.approx(0.039)
    assert cases["case-raise"]["tokens"] is None
    assert cases["case-raise"]["cost_usd"] is None
    assert result["efficiency"]["cost_usd_total"] is None
    assert result["efficiency"]["cost_usd_per_case"] is None
    assert result["efficiency"]["tokens_input_total"] == 90


def test_adapter_missing_from_price_table_gives_null() -> None:
    other = parse_price_table({"other": PRICES["mock"]})
    result = run_benchmark(SPEC, "mock", _config(tokens={"input": 10, "output": 2}), other)
    assert {case["cost_usd"] for case in result["cases"]} == {None}
    assert result["efficiency"]["cost_usd_total"] is None
    assert result["efficiency"]["price_table_hash"] == other.hash
    no_table = run_benchmark(SPEC, "mock", _config())
    assert no_table["efficiency"]["price_table_hash"] is None
    assert no_table["efficiency"]["cost_usd_total"] is None


def test_deterministic_adapter_costs_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {"deterministic": DeterministicAdapter})
    result = run_benchmark(SPEC, "deterministic", _config(), None)
    assert validate_run_result_document(result) == []
    assert {case["cost_usd"] for case in result["cases"]} == {0.0}
    efficiency = result["efficiency"]
    assert (efficiency["tokens_input_total"], efficiency["tokens_output_total"]) == (0, 0)
    assert efficiency["cost_usd_total"] == 0.0
    assert efficiency["cost_usd_per_case"] == 0.0


# --- CLI ------------------------------------------------------------------------------------


def _run_cli(tmp_path: Path, *extra: str) -> int:
    config = tmp_path / "run.yaml"
    config.write_text("split: test\nadapter: {tokens: {input: 10, output: 2}}\n", encoding="utf-8")
    args = ["run", "--benchmark", str(SPEC), "--adapter", "mock", "--config", str(config)]
    return main([*args, "--out", str(tmp_path / "out"), *extra])


def test_cli_prices(tmp_path: Path) -> None:
    prices = tmp_path / "prices.yaml"
    prices.write_text(json.dumps(PRICES), encoding="utf-8")
    assert _run_cli(tmp_path, "--prices", str(prices)) == 0
    result = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
    assert result["efficiency"]["cost_usd_total"] == pytest.approx(0.19)


def test_cli_default_prices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)
    assert _run_cli(tmp_path) == 0
    result = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
    assert result["efficiency"]["price_table_hash"] == load_price_table(DEFAULT_PRICES).hash
    assert result["efficiency"]["cost_usd_total"] == 0.0
    # Without the default file the run still works, with null costs.
    monkeypatch.chdir(tmp_path)
    assert _run_cli(tmp_path) == 0
    result = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
    assert result["efficiency"]["price_table_hash"] is None


def test_cli_rejects_bad_prices(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run_cli(tmp_path, "--prices", str(tmp_path / "missing.yaml")) == 1
    assert "missing.yaml: file not found" in capsys.readouterr().err
    bad = tmp_path / "bad.yaml"
    bad.write_text("mock: {usd_per_call: -1}\n", encoding="utf-8")
    assert _run_cli(tmp_path, "--prices", str(bad)) == 1
    assert "bad.yaml: mock: invalid prices" in capsys.readouterr().err


# --- environment fingerprint ----------------------------------------------------------------


def test_fingerprint_contains_all_keys() -> None:
    fingerprint = environment_fingerprint(REPO)
    assert set(fingerprint) == set(ENVIRONMENT_KEYS)
    for key in ("python", "os", "platform", "cpu_count_logical", "ram_total_bytes"):
        assert fingerprint[key], key
    assert fingerprint["ram_total_bytes"] > 0
    assert fingerprint["geoevals_version"] is not None
    assert (
        fingerprint["uv_lock_sha256"] == hashlib.sha256((REPO / "uv.lock").read_bytes()).hexdigest()
    )
    assert len(fingerprint["git_commit"]) == 40
    assert isinstance(fingerprint["git_dirty"], bool)


def test_run_result_records_fingerprint() -> None:
    result = run_benchmark(SPEC, "mock", _config())
    assert set(result["environment"]) == set(ENVIRONMENT_KEYS)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_fingerprint_git_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    outside = environment_fingerprint(tmp_path)
    if outside["git_commit"] is not None:
        pytest.skip(f"{tmp_path} is inside a git working tree")
    assert (outside["git_dirty"], outside["uv_lock_sha256"]) == (None, None)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "uv.lock").write_text("lock\n", encoding="utf-8")
    _git(repo, "add", "uv.lock")
    _git(repo, "commit", "-q", "-m", "init")
    clean = environment_fingerprint(repo / ".")
    assert clean["git_dirty"] is False
    assert len(clean["git_commit"]) == 40
    assert clean["uv_lock_sha256"] == hashlib.sha256(b"lock\n").hexdigest()
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    assert environment_fingerprint(repo)["git_dirty"] is True
