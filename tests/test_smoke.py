import json
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.metrics import StatusMatch, get_metric

REPO = Path(__file__).parent.parent
SMOKE = REPO / "benchmarks" / "smoke"


# --- status_match ---------------------------------------------------------------------------


def test_status_match_is_registered() -> None:
    assert isinstance(get_metric("status_match"), StatusMatch)


@pytest.mark.parametrize(
    ("prediction", "reference", "value"),
    [
        ({"status": "ok", "value": 2}, {"status": "ok", "value": 1}, 1.0),
        ({"status": "needs_clarification"}, {"status": "ok"}, 0.0),
        ({"value": 1}, {"status": "ok"}, 0.0),
        ("ok", {"status": "ok"}, 0.0),
        (None, None, 1.0),
    ],
)
def test_status_match_scores(prediction: object, reference: object, value: float) -> None:
    result = StatusMatch().score(prediction, reference, {})
    assert result.value == value
    assert result.passed is (value == 1.0)


def test_status_match_detail_names_both_statuses() -> None:
    result = StatusMatch().score({"status": "invalid_request"}, {"status": "ok"}, {})
    assert result.detail == {
        "predicted": "invalid_request",
        "expected": "ok",
        "reason": "abstained_when_should_answer",
    }
    passed = StatusMatch().score({"status": "ok"}, {"status": "ok"}, {})
    assert passed.detail == {"predicted": "ok", "expected": "ok"}


@pytest.mark.parametrize(
    ("predicted", "expected", "reason"),
    [
        ("ok", "needs_clarification", "answered_when_should_abstain"),
        ("ok", "insufficient_data", "answered_when_should_abstain"),
        ("ok", "invalid_request", "answered_when_should_abstain"),
        ("invalid_request", "insufficient_data", "wrong_abstention_status"),
        (None, "invalid_request", "status_differs"),
        ("done", "ok", "status_differs"),
    ],
)
def test_status_match_names_the_mismatch(predicted: object, expected: str, reason: str) -> None:
    result = StatusMatch().score({"status": predicted}, {"status": expected}, {})
    assert (result.value, result.passed) == (0.0, False)
    assert result.detail["reason"] == reason


# --- smoke benchmark ------------------------------------------------------------------------


def test_smoke_files_validate() -> None:
    assert main(["validate", str(SMOKE / "benchmark.yaml")]) == 0
    assert main(["validate", str(SMOKE / "manifest.yaml")]) == 0
    assert main(["data", "verify", str(SMOKE / "manifest.yaml")]) == 0


def test_smoke_run_and_report(tmp_path: Path) -> None:
    args = ["run", "--benchmark", str(SMOKE / "benchmark.yaml"), "--adapter", "mock"]
    args += ["--config", str(SMOKE / "run_config.yaml"), "--out", str(tmp_path)]
    assert main(args) == 0
    [run_dir] = tmp_path.iterdir()

    result = json.loads((run_dir / "result.json").read_text())
    statuses = {case["case_id"]: case["status"] for case in result["cases"]}
    assert len(statuses) == 5
    assert statuses.pop("smoke-05-malformed") == "invalid_output"
    assert set(statuses.values()) == {"scored"}
    summary = result["summary_metrics"]["status_match"]
    assert (summary["n"], summary["n_failed"], summary["mean"]) == (4, 1, 0.75)

    assert main(["report", str(run_dir)]) == 0
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "report.html").is_file()


def _smoke_run_args(out: Path) -> list[str]:
    args = ["run", "--benchmark", str(SMOKE / "benchmark.yaml"), "--adapter", "mock"]
    return [*args, "--config", str(SMOKE / "run_config.yaml"), "--out", str(out)]


def test_run_with_report_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    assert main([*_smoke_run_args(tmp_path), "--report"]) == 0
    [run_dir] = tmp_path.iterdir()
    assert capsys.readouterr().out.splitlines() == [
        str(run_dir),
        str(run_dir / "report.md"),
        str(run_dir / "report.html"),
    ]
    assert opened == []


def test_run_with_open_opens_the_html_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or False)
    assert main([*_smoke_run_args(tmp_path), "--open"]) == 0
    [run_dir] = tmp_path.iterdir()
    html = (run_dir / "report.html").resolve()
    assert html.is_file() and (run_dir / "report.md").is_file()
    assert opened == [html.as_uri()]
    assert "no web browser found" in capsys.readouterr().err
