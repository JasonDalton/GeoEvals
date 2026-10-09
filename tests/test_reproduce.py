import json
import shutil
from pathlib import Path

import pytest
import yaml

from geoevals.cli import main
from geoevals.reporting.compare import Tolerance, compare_runs, diff_values, load_run
from geoevals.reproduce import RUN_CASE_ID, compare_reproduction
from geoevals.runner.config import config_hash, load_run_config
from geoevals.runner.run import load_cases
from geoevals.validation import load_benchmark_spec

REPO = Path(__file__).parent.parent
BASELINES = REPO / "baselines"
BASELINE = BASELINES / "gis_correctness" / "gis_baseline"
MOCK_BASELINE = BASELINES / "gis_correctness" / "mock_failures"
SPEC = REPO / "benchmarks" / "gis_correctness" / "benchmark.yaml"
CI = REPO / ".github" / "workflows" / "ci.yml"

PUBLISHED = {
    "gis_correctness/gis_baseline": ("gis_baseline", "benchmarks/gis_correctness"),
    "gis_correctness/mock_failures": ("mock", "benchmarks/gis_correctness"),
    "human_context_access/access_baseline": ("access_baseline", "benchmarks/human_context"),
}
"""Baseline directory -> (adapter, benchmark directory)."""

CASE_STATUSES = {"scored", "adapter_error", "timeout", "invalid_output", "skipped"}


# --- the committed baselines ----------------------------------------------------------------


def test_published_baselines_are_the_expected_ones() -> None:
    dirs = sorted(
        path.relative_to(BASELINES).as_posix() for path in BASELINES.glob("*/*") if path.is_dir()
    )
    assert dirs == sorted(PUBLISHED)


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_baseline_has_the_committed_files(name: str) -> None:
    for file in ("result.json", "cases.jsonl", "config.yaml", "report.md"):
        assert (BASELINES / name / file).is_file(), file
    assert not (BASELINES / name / "report.html").exists()


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_baseline_config_is_the_one_it_ran_with(name: str) -> None:
    baseline = BASELINES / name
    result = load_run(baseline)
    assert config_hash(load_run_config(baseline / "config.yaml")) == result["config_hash"]
    assert result["adapter"]["name"] == PUBLISHED[name][0]
    assert result["benchmark"]["id"] == name.split("/")[0]


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_baseline_covers_every_benchmark_case(name: str) -> None:
    spec = REPO / PUBLISHED[name][1] / "benchmark.yaml"
    cases = load_cases(load_benchmark_spec(spec), spec.parent)
    result = load_run(BASELINES / name)
    assert sorted(case["case_id"] for case in result["cases"]) == [c.case_id for c in cases]
    lines = (BASELINES / name / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == result["cases"]


def test_gis_baseline_has_at_least_50_cases() -> None:
    assert len(load_run(BASELINE)["cases"]) >= 50


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_baseline_report_states_model_adapter_manifest_and_limitations(name: str) -> None:
    result = load_run(BASELINES / name)
    report = (BASELINES / name / "report.md").read_text(encoding="utf-8")
    adapter = result["adapter"]
    assert f"| Adapter | {adapter['name']} {adapter['version']} |" in report
    assert "| Model | " in report
    assert f"| Dataset manifest hash | {result['dataset_manifest_hash']} |" in report
    assert f"| Run ID | {result['run_id']} |" in report
    limitations = report.split("## 9. Limitations", 1)[1]
    assert result["limitations"]
    for limitation in result["limitations"]:
        assert f"- {limitation}" in limitations


def test_mock_baseline_shows_every_status_and_the_abstention_penalty() -> None:
    result = load_run(MOCK_BASELINE)
    assert {case["status"] for case in result["cases"]} == CASE_STATUSES
    reasons = [
        case["metrics"]["status_match"]["detail"].get("reason")
        for case in result["cases"]
        if case["status"] == "scored"
    ]
    assert "answered_when_should_abstain" in reasons
    report = (MOCK_BASELINE / "report.md").read_text(encoding="utf-8")
    failures = report.split("## 5. Failures", 1)[1].split("## 6.", 1)[0]
    failed = {
        case["case_id"]
        for case in result["cases"]
        if case["status"] != "scored"
        or any(metric["passed"] is False for metric in case["metrics"].values())
    }
    assert failed
    for case_id in failed:
        assert f"| {case_id} |" in failures


def test_ci_reproduces_every_baseline_in_a_clean_environment() -> None:
    workflow = yaml.safe_load(CI.read_text(encoding="utf-8"))
    job = workflow["jobs"]["reproduce"]
    assert job["env"]["UV_NO_CACHE"] == "1"
    setup = next(step for step in job["steps"] if step.get("uses", "").startswith("astral-sh/"))
    assert setup["with"]["enable-cache"] is False
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "uv sync --frozen --no-cache" in commands
    assert "find baselines -mindepth 2 -maxdepth 2 -type d" in commands
    assert "geoevals reproduce" in commands


@pytest.mark.integration
@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_reproduce_the_committed_baseline(
    name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO)
    assert main(["reproduce", f"baselines/{name}"]) == 0
    assert "no differences" in capsys.readouterr().out


@pytest.mark.integration
def test_reproduce_reports_a_changed_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline"
    shutil.copytree(BASELINE, baseline)
    result = json.loads((baseline / "result.json").read_text(encoding="utf-8"))
    case = next(case for case in result["cases"] if case["case_id"] == "distance-001")
    case["output"]["value"] += 1.0
    (baseline / "result.json").write_text(json.dumps(result), encoding="utf-8")
    out = tmp_path / "runs"

    code = main(["reproduce", str(baseline), "--root", str(REPO / "benchmarks"), "--out", str(out)])

    assert code == 1
    assert "distance-001: output.value:" in capsys.readouterr().out
    [run_dir] = out.iterdir()
    assert (run_dir / "result.json").is_file()


def test_reproduce_unreadable_baseline_exits_2(tmp_path: Path) -> None:
    assert main(["reproduce", str(tmp_path)]) == 2


# --- comparison with a tolerance ------------------------------------------------------------


def _diff(a: object, b: object, tolerance: Tolerance) -> list[tuple[str, object, object]]:
    return list(diff_values(a, b, "x", tolerance))


def test_exact_by_default() -> None:
    assert _diff(1.0, 1.0 + 1e-15, Tolerance()) == [("x", 1.0, 1.0 + 1e-15)]


@pytest.mark.parametrize(
    ("a", "b", "close"),
    [
        (1.0, 1.0 + 1e-12, True),
        (0.0, 5e-8, True),
        (0.0, 2e-7, False),
        (1e6, 1e6 + 5e-4, True),
        (1e6, 1e6 + 5e-3, False),
        (1, 1.0, False),
        (True, 1, False),
        ("a", "b", False),
    ],
)
def test_tolerance_only_absorbs_close_numbers_of_one_type(
    a: object, b: object, close: bool
) -> None:
    assert (_diff(a, b, Tolerance(abs=1e-7, rel=1e-9)) == []) is close


def test_tolerance_reaches_nested_values() -> None:
    a = {"cases": [{"case_id": "c", "status": "ok", "output": {"v": [1.0, 2.0]}, "metrics": {}}]}
    b = {
        "cases": [
            {"case_id": "c", "status": "ok", "output": {"v": [1.0, 2.0 + 1e-9]}, "metrics": {}}
        ]
    }
    assert len(compare_runs(a, b)) == 1
    assert compare_runs(a, b, Tolerance(abs=1e-7)) == []


def test_reproduction_compares_run_level_fields() -> None:
    baseline = load_run(BASELINE)
    rerun = json.loads(json.dumps(baseline))
    rerun["run_id"] = "other"
    rerun["started_at"] = "2000-01-01T00:00:00Z"
    rerun["environment"] = {}
    assert compare_reproduction(baseline, rerun) == []
    rerun["dataset_manifest_hash"] = "0" * 64
    [difference] = compare_reproduction(baseline, rerun)
    assert (difference.case_id, difference.field) == (RUN_CASE_ID, "dataset_manifest_hash")
