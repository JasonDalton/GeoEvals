import json
import shutil
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.reporting.compare import Tolerance, compare_runs, diff_values, load_run
from geoevals.reproduce import RUN_CASE_ID, compare_reproduction
from geoevals.runner.config import config_hash, load_run_config
from geoevals.runner.run import load_cases
from geoevals.validation import load_benchmark_spec

REPO = Path(__file__).parent.parent
BASELINE = REPO / "baselines" / "gis_correctness" / "gis_baseline"
SPEC = REPO / "benchmarks" / "gis_correctness" / "benchmark.yaml"


# --- the committed baseline -----------------------------------------------------------------


def test_baseline_has_the_committed_files() -> None:
    for name in ("result.json", "cases.jsonl", "config.yaml", "report.md"):
        assert (BASELINE / name).is_file(), name


def test_baseline_config_is_the_one_it_ran_with() -> None:
    result = load_run(BASELINE)
    assert config_hash(load_run_config(BASELINE / "config.yaml")) == result["config_hash"]
    assert result["adapter"]["name"] == "gis_baseline"


def test_baseline_covers_every_benchmark_case() -> None:
    cases = load_cases(load_benchmark_spec(SPEC), SPEC.parent)
    assert len(cases) >= 50
    result = load_run(BASELINE)
    assert sorted(case["case_id"] for case in result["cases"]) == [c.case_id for c in cases]
    lines = (BASELINE / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == result["cases"]


@pytest.mark.integration
def test_reproduce_the_committed_baseline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO)
    assert main(["reproduce", "baselines/gis_correctness/gis_baseline"]) == 0
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
