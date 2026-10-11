import copy
import json
import shutil
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.reporting.compare import load_run
from geoevals.reproduce import compare_reproduction
from geoevals.rescore import RescoreError, rescore_run
from geoevals.validation import validate_run_result_document

REPO = Path(__file__).parent.parent
SPEC = REPO / "benchmarks" / "gis_correctness" / "benchmark.yaml"
BASELINES = REPO / "baselines" / "gis_correctness"
LABEL_CASE = "overlay-001"
"""A case whose expected answer is labeled ``OGC:CRS84``."""


def _baseline(name: str = "gis_baseline") -> dict:
    return copy.deepcopy(load_run(BASELINES / name))


def _case(result: dict, case_id: str) -> dict:
    [case] = [c for c in result["cases"] if c["case_id"] == case_id]
    return case


def test_rescoring_an_unchanged_run_changes_no_score() -> None:
    for name in ("gis_baseline", "mock_failures"):
        baseline = _baseline(name)
        rescored = rescore_run(baseline, SPEC)
        assert compare_reproduction(baseline, rescored) == [], name
        assert rescored["run_id"] == baseline["run_id"]
        assert validate_run_result_document(rescored) == []


def test_rescoring_applies_the_current_metrics_and_records_the_old_version() -> None:
    old = _baseline()
    old["benchmark"]["version"] = "0.2.0"
    case = _case(old, LABEL_CASE)
    assert case["output"]["crs"] == "OGC:CRS84"
    case["output"]["crs"] = "EPSG:4326"
    case["metrics"]["crs_match"] = {"value": 0.0, "passed": False, "detail": {}}
    case["metrics"]["task_success"] = {"value": 0.0, "passed": False, "detail": {}}

    rescored = rescore_run(old, SPEC)

    assert rescored["benchmark"]["version"] == "0.3.0"
    assert _case(rescored, LABEL_CASE)["metrics"]["task_success"]["passed"] is True
    assert rescored["summary_metrics"]["task_success"]["mean"] == 1.0
    assert rescored["summary_metrics"]["crs_match"]["version"] == "1.1.0"
    [note] = [line for line in rescored["limitations"] if line.startswith("Rescored")]
    assert "gis_correctness 0.2.0" in note and "0.3.0" in note
    for field in ("started_at", "finished_at", "efficiency", "environment", "config_hash"):
        assert rescored[field] == old[field], field
    assert old["benchmark"]["version"] == "0.2.0"  # the input is not modified


def test_rescoring_twice_keeps_both_notes() -> None:
    old = _baseline()
    old["benchmark"]["version"] = "0.2.0"
    twice = rescore_run(rescore_run(old, SPEC), SPEC)
    notes = [line for line in twice["limitations"] if line.startswith("Rescored")]
    assert len(notes) == 2
    assert "previously scored against gis_correctness 0.2.0" in notes[0]
    assert "previously scored against gis_correctness 0.3.0" in notes[1]


def test_rescoring_keeps_failed_cases_as_they_were() -> None:
    baseline = _baseline("mock_failures")
    rescored = rescore_run(baseline, SPEC)
    for before, after in zip(baseline["cases"], rescored["cases"], strict=True):
        if before["status"] != "scored":
            assert after == before
    assert rescored["failures"] == baseline["failures"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r["benchmark"].update(id="human_context_access"), "benchmark"),
        (lambda r: r.update(dataset_manifest_hash="0" * 64), "manifest"),
        (lambda r: r["cases"].pop(), "case"),
        (lambda r: _case(r, LABEL_CASE)["output"].pop("crs"), "output schema"),
    ],
)
def test_rescoring_refuses_a_run_that_does_not_fit_the_benchmark(change, message) -> None:
    result = _baseline()
    change(result)
    with pytest.raises(RescoreError, match=message):
        rescore_run(result, SPEC)


def test_rescore_command_rewrites_result_and_cases(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    shutil.copytree(BASELINES / "gis_baseline", run_dir)
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    result["benchmark"]["version"] = "0.2.0"
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")

    assert main(["rescore", str(run_dir)]) == 0

    rescored = load_run(run_dir)
    assert rescored["benchmark"]["version"] == "0.3.0"
    cases = (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["case_id"] for line in cases] == [
        c["case_id"] for c in rescored["cases"]
    ]


def test_rescore_command_without_cases_file_writes_only_the_result(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shutil.copy(BASELINES / "gis_baseline" / "result.json", run_dir)
    assert main(["rescore", str(run_dir)]) == 0
    assert sorted(p.name for p in run_dir.iterdir()) == ["result.json"]


def test_rescore_command_reports_a_refusal(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "run"
    shutil.copytree(BASELINES / "gis_baseline", run_dir)
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    result["dataset_manifest_hash"] = "0" * 64
    original = json.dumps(result)
    (run_dir / "result.json").write_text(original, encoding="utf-8")
    assert main(["rescore", str(run_dir)]) == 1
    assert "manifest" in capsys.readouterr().err
    assert (run_dir / "result.json").read_text(encoding="utf-8") == original
