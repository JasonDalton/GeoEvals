import json
import time
from pathlib import Path
from typing import Any

import pytest

from geoevals.adapters import (
    Adapter,
    AdapterResponse,
    MockAdapter,
    MockAdapterError,
    MockConfigError,
    SkipCase,
    TokenUsage,
    create_adapter,
    register_adapter,
    registered_adapter_names,
    registry,
)
from geoevals.cli import main
from geoevals.validation.validate import load_yaml

FIXTURES = Path(__file__).parent / "fixtures" / "adapters"
MOCK_YAML = FIXTURES / "mock.yaml"
REFERENCE = {"area_m2": 12.5, "crs": "EPSG:3857", "valid": True, "coords": [[1, 2], [3.5, 4]]}


def _mock(config: dict[str, Any] | None = None) -> tuple[MockAdapter, list[float]]:
    slept: list[float] = []
    adapter = MockAdapter(sleep=slept.append)
    adapter.setup(config if config is not None else load_yaml(MOCK_YAML))
    return adapter, slept


def _outcome(adapter: MockAdapter, case_id: str) -> tuple[str, Any]:
    try:
        response = adapter.predict({"case_id": case_id})
    except MockAdapterError as exc:
        return ("error", str(exc))
    return ("ok", (response.output, response.tokens))


def test_mock_satisfies_protocol_and_is_registered() -> None:
    adapter = create_adapter("mock")
    assert isinstance(adapter, MockAdapter)
    assert isinstance(adapter, Adapter)
    assert (adapter.name, adapter.version) == ("mock", "0.1.0")
    assert "mock" in registered_adapter_names()


def test_adapter_response_fields() -> None:
    response = AdapterResponse(output={"a": 1})
    assert (response.tokens, response.trajectory, response.raw) == (None, None, None)
    full = AdapterResponse(
        output={}, tokens=TokenUsage(1, 2), trajectory=[{"tool": "buffer"}], raw="x"
    )
    assert full.tokens == TokenUsage(input=1, output=2)
    assert full.trajectory == [{"tool": "buffer"}]
    with pytest.raises(ValueError, match=">= 0"):
        TokenUsage(-1, 0)


def test_registry_rejects_duplicate_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})
    register_adapter("mock", MockAdapter)
    with pytest.raises(ValueError, match="already registered"):
        register_adapter("mock", MockAdapter)
    with pytest.raises(ValueError, match=r"unknown adapter 'nope' \(registered: mock\)"):
        create_adapter("nope")


def test_reference_behavior_with_synthetic_tokens() -> None:
    adapter, _ = _mock()
    response = adapter.predict({"case_id": "case-ref"})
    assert response.output == REFERENCE
    assert response.tokens == TokenUsage(input=120, output=30)
    assert response.raw == {"mock_behavior": "reference", "call": 1}


def test_returned_output_is_a_copy() -> None:
    adapter, _ = _mock()
    adapter.predict({"case_id": "case-ref"}).output["coords"].append([0, 0])
    assert adapter.predict({"case_id": "case-ref"}).output == REFERENCE


def test_wrong_behavior_keeps_shape_and_changes_values() -> None:
    adapter, _ = _mock()
    output = adapter.predict({"case_id": "case-wrong"}).output
    assert output == {
        "area_m2": 13.5,
        "crs": "EPSG:3857_wrong",
        "valid": False,
        "coords": [[2, 3], [4.5, 5]],
    }


def test_wrong_and_malformed_accept_explicit_output() -> None:
    adapter, _ = _mock(
        {
            "cases": {
                "a": {"behavior": "wrong", "output": {"area_m2": 0}},
                "b": {"behavior": "malformed", "output": {"bogus": []}},
            }
        }
    )
    assert adapter.predict({"case_id": "a"}).output == {"area_m2": 0}
    assert adapter.predict({"case_id": "b"}).output == {"bogus": []}


def test_malformed_behavior_default_output() -> None:
    adapter, _ = _mock()
    assert adapter.predict({"case_id": "case-malformed"}).output == {"mock_malformed_output": True}


def test_raise_behavior() -> None:
    adapter, _ = _mock()
    for _ in range(3):
        with pytest.raises(MockAdapterError, match=r"^boom$"):
            adapter.predict({"case_id": "case-raise"})


def test_skip_behavior_raises_skip_case() -> None:
    adapter = MockAdapter()
    adapter.setup({"cases": {"case-skip": {"behavior": "skip", "message": "not supported"}}})
    with pytest.raises(SkipCase, match=r"^not supported$"):
        adapter.predict({"case_id": "case-skip"})


def test_sleep_behavior_sleeps_then_returns_reference() -> None:
    adapter, slept = _mock()
    assert adapter.predict({"case_id": "case-sleep"}).output == {"area_m2": 1.0}
    assert slept == [5.0]


def test_sleep_behavior_really_sleeps() -> None:
    adapter = MockAdapter()
    adapter.setup({"references": {"c": {}}, "default": {"behavior": "sleep", "seconds": 0.05}})
    start = time.perf_counter()
    adapter.predict({"case_id": "c"})
    assert time.perf_counter() - start >= 0.05


def test_fail_then_succeed_behavior() -> None:
    adapter, _ = _mock()
    with pytest.raises(MockAdapterError, match=r"attempt 1 of 2"):
        adapter.predict({"case_id": "case-flaky"})
    with pytest.raises(MockAdapterError, match=r"attempt 2 of 2"):
        adapter.predict({"case_id": "case-flaky"})
    response = adapter.predict({"case_id": "case-flaky"})
    assert response.output == {"area_m2": 2.0}
    assert response.tokens == TokenUsage(input=7, output=3)
    # setup() resets the failure count.
    adapter.setup(load_yaml(MOCK_YAML))
    with pytest.raises(MockAdapterError, match=r"attempt 1 of 2"):
        adapter.predict({"case_id": "case-flaky"})


def test_per_case_behaviors_are_deterministic() -> None:
    case_ids = ["case-ref", "case-wrong", "case-malformed", "case-raise", "case-sleep"]
    case_ids += ["case-flaky"] * 3
    runs = []
    for _ in range(2):
        adapter, _ = _mock()
        runs.append([_outcome(adapter, case_id) for case_id in case_ids])
    assert runs[0] == runs[1]


PROBABILITY_CONFIG: dict[str, Any] = {
    "seed": 7,
    "references": {f"c{i}": {"value": i} for i in range(400)},
    "random": [
        {"probability": 0.2, "behavior": "wrong"},
        {"probability": 0.1, "behavior": "malformed"},
        {"probability": 0.1, "behavior": "raise"},
        {"probability": 0.1, "behavior": "sleep", "seconds": 2},
        {"probability": 0.1, "behavior": "fail_then_succeed", "failures": 1},
        {"probability": 0.1, "behavior": "reference", "tokens": {"input": 5, "output": 1}},
    ],
}


def _behaviors(seed: int, case_ids: list[str]) -> dict[str, str]:
    adapter, _ = _mock({**PROBABILITY_CONFIG, "seed": seed})
    return {case_id: adapter.select_rule(case_id).behavior for case_id in case_ids}


def test_probability_behaviors_are_deterministic_for_fixed_seed() -> None:
    case_ids = [f"c{i}" for i in range(400)]
    first = _behaviors(7, case_ids)
    assert _behaviors(7, case_ids) == first
    # The choice depends only on seed and case ID, not on call order.
    assert _behaviors(7, list(reversed(case_ids))) == first
    assert _behaviors(8, case_ids) != first
    # Every behavior is drawn at least once, close to its probability.
    counts = {b: list(first.values()).count(b) for b in set(first.values())}
    assert set(counts) == {"reference", "wrong", "malformed", "raise", "sleep", "fail_then_succeed"}
    assert 40 <= counts["wrong"] <= 120

    outcomes = []
    for _ in range(2):
        adapter, slept = _mock(PROBABILITY_CONFIG)
        outcomes.append(([_outcome(adapter, case_id) for case_id in case_ids * 2], slept))
    assert outcomes[0] == outcomes[1]


def test_case_rule_takes_precedence_over_probability() -> None:
    adapter, _ = _mock(
        {
            "references": {"x": {"v": 1}},
            "cases": {"x": {"behavior": "reference"}},
            "random": [{"probability": 1.0, "behavior": "raise"}],
        }
    )
    assert adapter.predict({"case_id": "x"}).output == {"v": 1}
    with pytest.raises(MockAdapterError):
        adapter.predict({"case_id": "y"})


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"cases": {"a": {"behavior": "sleep"}}}, "requires 'seconds'"),
        ({"cases": {"a": {"behavior": "fail_then_succeed"}}}, "requires 'failures'"),
        ({"cases": {"a": {"behavior": "explode"}}}, "behavior"),
        ({"cases": {"a": {"behavior": "raise", "output": {}}}}, "'output' applies only"),
        ({"random": [{"probability": 0.7}, {"probability": 0.6}]}, "more than 1"),
        ({"random": [{"probability": 1.5}]}, "probability"),
        ({"seeed": 1}, "seeed"),
        ({"seed": "1"}, "seed"),
    ],
)
def test_invalid_config_is_rejected(config: dict[str, Any], message: str) -> None:
    with pytest.raises(MockConfigError, match=message):
        MockAdapter().setup(config)


def test_predict_errors() -> None:
    with pytest.raises(RuntimeError, match="before setup"):
        MockAdapter().predict({"case_id": "a"})
    adapter, _ = _mock()
    with pytest.raises(MockConfigError, match="case_id"):
        adapter.predict({})
    with pytest.raises(MockConfigError, match="no reference output for case 'unknown'"):
        adapter.predict({"case_id": "unknown"})


def test_cli_adapters_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["adapters", "list"]) == 0
    assert "mock" in capsys.readouterr().out.split()


def _predict_args(case: Path) -> list[str]:
    return ["adapters", "predict", "--adapter", "mock", "--config", str(MOCK_YAML), str(case)]


def test_cli_adapters_predict(capsys: pytest.CaptureFixture[str]) -> None:
    case = FIXTURES / "case_ref.json"
    assert main(_predict_args(case)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["output"] == REFERENCE
    assert printed["tokens"] == {"input": 120, "output": 30}


def test_cli_adapters_predict_reports_adapter_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "case.json"
    case.write_text('{"case_id": "case-raise"}', encoding="utf-8")
    assert main(_predict_args(case)) == 1
    assert "MockAdapterError: boom" in capsys.readouterr().err


def test_cli_rejects_unknown_adapter(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["adapters", "predict", "--adapter", "nope", "case.json"])
    assert exc.value.code == 2
    assert "invalid choice: 'nope'" in capsys.readouterr().err
