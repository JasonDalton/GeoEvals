import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from geoevals.adapters import (
    GisBaselineAdapter,
    UnsupportedOperation,
    create_adapter,
    registered_adapter_names,
)
from geoevals.adapters.gis_baseline import OPERATIONS
from geoevals.cli import main
from geoevals.data.verify import verify_manifest
from geoevals.regenerate import RegenerateError, expected_outputs, regenerate
from geoevals.runner.config import RunConfig
from geoevals.runner.run import RunError, _resolve_metrics, _score, load_cases, run_benchmark
from geoevals.validation import load_benchmark_spec, load_dataset_manifest, validate_file
from geoevals.validation.benchmark import Tolerance

REPO = Path(__file__).parent.parent
BENCH = REPO / "benchmarks" / "gis_correctness"
SPEC = BENCH / "benchmark.yaml"
SMOKE_SPEC = REPO / "benchmarks" / "smoke" / "benchmark.yaml"
"""One split and ``cases: cases.jsonl``, so ``load_cases`` reads ``<dir>/cases.jsonl``."""
STATUSES = ["ok", "needs_clarification", "insufficient_data", "invalid_request"]
CASE_FIELDS = {"case_id", "operation", "prompt", "inputs", "expected", "tolerances", "strata"}


def _case_lines() -> list[tuple[Path, dict[str, Any]]]:
    return [
        (path, json.loads(line))
        for path in sorted((BENCH / "cases").glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _output_validator() -> Draft202012Validator:
    return Draft202012Validator(load_benchmark_spec(SPEC).output_schema)


# --- spec, cases and output contract ----------------------------------------------------------


def test_spec_validates_with_id_and_version() -> None:
    kind, issues = validate_file(SPEC)
    assert (kind, issues) == ("benchmark spec", [])
    spec = load_benchmark_spec(SPEC)
    assert (spec.id, spec.version) == ("gis_correctness", "0.1.0")


def test_spec_lists_every_case_file() -> None:
    spec = load_benchmark_spec(SPEC)
    listed = [spec.cases] if isinstance(spec.cases, str) else list(spec.cases)
    on_disk = sorted(f"cases/{p.name}" for p in (BENCH / "cases").glob("*.jsonl"))
    assert sorted(listed) == on_disk


def test_case_format() -> None:
    lines = _case_lines()
    assert lines
    input_validator = Draft202012Validator(load_benchmark_spec(SPEC).input_schema)
    for path, case in lines:
        assert set(case) >= CASE_FIELDS, case.get("case_id")
        assert path.stem == case["operation"], f"{case['case_id']} is in {path.name}"
        assert case["case_id"].startswith(f"{case['operation']}-")
        assert case["strata"]["operation"] == case["operation"]
        assert set(case["inputs"]) == {"files", "params"}
        for file in case["inputs"]["files"].values():
            assert (BENCH / file).is_file() and file.startswith("fixtures/")
        case_input = {key: value for key, value in case.items() if key != "expected"}
        errors = [error.message for error in input_validator.iter_errors(case_input)]
        assert errors == [], case["case_id"]


def test_expected_outputs_satisfy_the_output_contract() -> None:
    spec = load_benchmark_spec(SPEC)
    validator = _output_validator()
    for case in load_cases(spec, BENCH):
        errors = [error.message for error in validator.iter_errors(case.expected)]
        assert errors == [], case.case_id


@pytest.mark.parametrize(
    "output",
    [
        {"status": "ok", "geometry": {"type": "Point", "coordinates": [1, 2]}, "crs": "EPSG:3857"},
        {"status": "ok", "features": {"type": "FeatureCollection", "features": []}, "crs": "x"},
        {"status": "ok", "value": 1.5, "units": "m", "crs": "EPSG:32633"},
        {"status": "ok", "value": True, "units": "bool", "crs": "OGC:CRS84"},
        *({"status": status} for status in STATUSES[1:]),
    ],
)
def test_output_contract_accepts(output: dict[str, Any]) -> None:
    assert list(_output_validator().iter_errors(output)) == []


@pytest.mark.parametrize(
    "output",
    [
        {},
        {"status": "done"},
        {"status": "ok"},
        {"status": "ok", "crs": "EPSG:4326"},
        {"status": "ok", "geometry": {"type": "Point", "coordinates": [1, 2]}},
        {"status": "ok", "value": 1.5, "crs": "EPSG:4326"},
        {"status": "ok", "value": 1.5, "units": "m", "geometry": {"type": "Point",
         "coordinates": [1, 2]}, "crs": "EPSG:4326"},
        {"status": "ok", "geometry": {"type": "Circle", "coordinates": [1, 2]}, "crs": "x"},
        {"status": "ok", "features": {"type": "Feature", "features": []}, "crs": "x"},
    ],
)  # fmt: skip
def test_output_contract_rejects(output: dict[str, Any]) -> None:
    assert list(_output_validator().iter_errors(output)) != []


# --- fixtures and manifest --------------------------------------------------------------------


def test_fixtures_are_small_and_in_the_manifest() -> None:
    fixtures = [path for path in (BENCH / "fixtures").rglob("*") if path.is_file()]
    assert fixtures
    assert sum(path.stat().st_size for path in fixtures) < 1_000_000
    manifest = load_dataset_manifest(BENCH / "manifest.yaml")
    listed = {(BENCH / asset.path).resolve() for asset in manifest.assets}
    assert {path.resolve() for path in fixtures} == listed
    assert all(asset.redistributable for asset in manifest.assets)
    assert validate_file(BENCH / "manifest.yaml") == ("dataset manifest", [])
    assert all(check.status == "ok" for check in verify_manifest(BENCH / "manifest.yaml"))


# --- reference workflow -----------------------------------------------------------------------


def test_committed_expected_outputs_match_the_reference_workflow() -> None:
    stale = regenerate(BENCH, "gis_correctness", write=False)
    assert stale == [], "run `geoevals bench regenerate gis_correctness`"


def test_regenerate_rewrites_stale_outputs(tmp_path: Path) -> None:
    copy = tmp_path / "gis_correctness"
    shutil.copytree(BENCH, copy, ignore=shutil.ignore_patterns("__pycache__"))
    expected_files = sorted((copy / "expected").glob("*.json"))
    expected_files[0].write_text("{}\n", encoding="utf-8")
    expected_files[1].unlink()
    case_file = copy / "cases" / "distance.jsonl"
    original = case_file.read_text(encoding="utf-8")
    case_file.write_text(original.replace('"value": 8', '"value": 9', 1), encoding="utf-8")
    assert original != case_file.read_text(encoding="utf-8")

    stale = regenerate(copy, "gis_correctness")
    assert sorted(stale) == sorted([expected_files[0], expected_files[1], case_file])
    assert case_file.read_text(encoding="utf-8") == original
    assert regenerate(copy, "gis_correctness") == []
    for path in expected_files:
        assert path.read_bytes() == (BENCH / "expected" / path.name).read_bytes()


def test_regenerate_checks_the_benchmark_id() -> None:
    with pytest.raises(RegenerateError, match="not 'smoke'"):
        expected_outputs(BENCH, "smoke")


def test_cli_regenerate_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(REPO / "benchmarks")
    assert main(["bench", "regenerate", "gis_correctness", "--root", root, "--check"]) == 0
    assert "up to date" in capsys.readouterr().out

    shutil.copytree(BENCH, tmp_path / "gis_correctness")
    target = next((tmp_path / "gis_correctness" / "expected").glob("*.json"))
    target.write_text("{}\n", encoding="utf-8")
    args = ["bench", "regenerate", "gis_correctness", "--root", str(tmp_path)]
    assert main([*args, "--check"]) == 1
    assert "out of date" in capsys.readouterr().out
    assert main(args) == 0
    assert "written" in capsys.readouterr().out
    assert main([*args, "--check"]) == 0
    assert main(["bench", "regenerate", "missing", "--root", str(tmp_path)]) == 1


# --- gis_baseline -----------------------------------------------------------------------------


def test_gis_baseline_is_registered() -> None:
    assert "gis_baseline" in registered_adapter_names()
    adapter = create_adapter("gis_baseline")
    assert isinstance(adapter, GisBaselineAdapter)
    assert adapter.deterministic is True


def test_gis_baseline_dispatches_on_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake(inputs: Any, base: Path) -> dict[str, Any]:
        calls.append((inputs, base))
        return {"status": "insufficient_data"}

    monkeypatch.setitem(OPERATIONS, "fake_operation", fake)
    adapter = GisBaselineAdapter()
    adapter.setup({})
    case = {"operation": "fake_operation", "inputs": {"files": {}, "params": {}}}
    response = adapter.predict({**case, "benchmark_dir": str(BENCH)})
    assert response.output == {"status": "insufficient_data"}
    assert calls == [(case["inputs"], BENCH)]
    with pytest.raises(UnsupportedOperation, match="unsupported operation 'nope'"):
        adapter.predict({"operation": "nope", "inputs": {"files": {}, "params": {}}})


def test_gis_baseline_rejects_config() -> None:
    with pytest.raises(ValueError, match="takes no config"):
        GisBaselineAdapter().setup({"x": 1})


def test_gis_baseline_scores_full_task_success() -> None:
    result = run_benchmark(SPEC, "gis_baseline", RunConfig(split="test"))
    assert {case["status"] for case in result["cases"]} == {"scored"}
    assert result["summary_metrics"]["task_success"]["mean"] == 1.0
    assert result["summary_metrics"]["task_success"]["n"] == len(_case_lines())
    assert result["efficiency"]["cost_usd_total"] == 0.0


# --- CRS transformation cases ------------------------------------------------------------------

CRS_FAMILIES = {
    "web_mercator",
    "utm",
    "state_plane",
    "datum_shift",
    "mercator",
    "polar_stereographic",
    "invalid",
}
AXIS_TRAP_CASE = "crs_transform-005"
"""UTM zone 33N to EPSG:4326, whose authority axis order is latitude, longitude."""


def _crs_cases() -> list[dict[str, Any]]:
    return [case for path, case in _case_lines() if path.stem == "crs_transform"]


def test_crs_cases_cover_the_traps() -> None:
    cases = _crs_cases()
    assert len(cases) >= 8
    for case in cases:
        assert case["tolerances"]["tol_m"]["units"] == "m", case["case_id"]
        assert isinstance(case["strata"]["trap"], bool), case["case_id"]
        assert case["strata"]["crs_family"] in CRS_FAMILIES, case["case_id"]
    assert {case["strata"]["crs_family"] for case in cases} == CRS_FAMILIES
    by_id = {case["case_id"]: case for case in cases}
    params = [case["inputs"]["params"] for case in cases]
    assert any(p.get("source_crs") == "EPSG:4267" for p in params), "NAD27 datum change"
    assert by_id[AXIS_TRAP_CASE]["inputs"]["params"]["target_crs"] == "EPSG:4326"
    points = [p["geometry"]["coordinates"] for p in params if p.get("source_crs") == "OGC:CRS84"]
    assert any(abs(lon) >= 179 for lon, _ in points), "point near the antimeridian"
    assert any(abs(lat) >= 75 for _, lat in points), "high-latitude point"
    invalid = [case for case in cases if case["expected"] == {"status": "invalid_request"}]
    assert invalid and all(case["strata"]["trap"] for case in invalid)


def test_gis_baseline_passes_every_crs_case() -> None:
    result = run_benchmark(SPEC, "gis_baseline", RunConfig(split="test"))
    crs = [case for case in result["cases"] if case["case_id"].startswith("crs_transform-")]
    assert len(crs) == len(_crs_cases())
    assert {case["case_id"]: case["metrics"]["task_success"]["value"] for case in crs} == {
        case["case_id"]: 1.0 for case in crs
    }


def test_mock_with_swapped_axes_fails_and_names_the_swap() -> None:
    spec = load_benchmark_spec(SPEC)
    references = {case.case_id: case.expected for case in load_cases(spec, BENCH)}
    swapped = json.loads(json.dumps(references[AXIS_TRAP_CASE]))
    swapped["geometry"]["coordinates"].reverse()
    adapter = {
        "references": references,
        "cases": {AXIS_TRAP_CASE: {"behavior": "wrong", "output": swapped}},
    }
    result = run_benchmark(SPEC, "mock", RunConfig(split="test", adapter=adapter))
    [case] = [case for case in result["cases"] if case["case_id"] == AXIS_TRAP_CASE]
    task_success = case["metrics"]["task_success"]
    assert (task_success["value"], task_success["passed"]) == (0.0, False)
    assert task_success["detail"]["failed"] == ["geometry_match"]
    geometry = task_success["detail"]["checks"]["geometry_match"]["detail"]
    assert (geometry["reason"], geometry["axis_swapped"]) == ("axis_order_swapped", True)
    assert case["metrics"]["geometry_match"]["detail"]["reason"] == "axis_order_swapped"
    others = [c for c in result["cases"] if c["case_id"] != AXIS_TRAP_CASE]
    assert all(c["metrics"]["task_success"]["passed"] for c in others)


# --- runner: expected files, tolerances, benchmark_dir -----------------------------------------


def _write_cases(directory: Path, *cases: dict[str, Any]) -> None:
    lines = "".join(json.dumps(case) + "\n" for case in cases)
    (directory / "cases.jsonl").write_text(lines, encoding="utf-8")


def test_load_cases_reads_expected_files_and_tolerances(tmp_path: Path) -> None:
    (tmp_path / "expected").mkdir()
    (tmp_path / "expected" / "a.json").write_text('{"status": "ok"}', encoding="utf-8")
    tolerances = {"tol_m": {"value": 0.5, "units": "m"}, "abs_tol": {"value": 2, "units": "m"}}
    _write_cases(
        tmp_path,
        {"case_id": "a", "expected": "expected/a.json", "tolerances": tolerances},
        {"case_id": "b", "expected": {"status": "invalid_request"}},
    )
    a, b = load_cases(load_benchmark_spec(SMOKE_SPEC), tmp_path)
    assert a.expected == {"status": "ok"}
    assert a.tolerances == {"tol_m": 0.5, "abs_tol": 2.0}
    assert a.input["benchmark_dir"] == str(tmp_path.resolve())
    assert "expected" not in a.input
    assert (b.expected, b.tolerances) == ({"status": "invalid_request"}, {})


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ({"case_id": "a", "expected": "expected/none.json"}, "file not found"),
        ({"case_id": "a", "expected": {}, "tolerances": []}, "tolerances must be an object"),
        ({"case_id": "a", "expected": {}, "tolerances": {"t": 1}}, "tolerance 't'"),
        ({"case_id": "a", "expected": {}, "tolerances": {"t": {"value": -1, "units": "m"}}}, "'t'"),
        ({"case_id": "a", "expected": {}, "tolerances": {"t": {"value": 1}}}, "tolerance 't'"),
        ({"case_id": "a", "expected": {}, "tolerances": {"t": {"value": True, "units": "m"}}},
         "'t'"),
    ],
)  # fmt: skip
def test_load_cases_rejects_bad_expected_and_tolerances(
    tmp_path: Path, case: dict[str, Any], message: str
) -> None:
    _write_cases(tmp_path, case)
    with pytest.raises(RunError, match=message):
        load_cases(load_benchmark_spec(SMOKE_SPEC), tmp_path)


def test_tolerances_reach_metric_params() -> None:
    spec = load_benchmark_spec(SPEC).model_copy(
        update={"tolerances": {"abs_tol": Tolerance(value=5.0, units="m")}}
    )
    [(metric, params)] = [m for m in _resolve_metrics(spec) if m[0].id == "value_abs_error"]
    assert params == {"abs_tol": 5.0}
    expected = {"status": "ok", "value": 10.0, "units": "m"}
    output = {"status": "ok", "value": 13.0, "units": "m"}
    assert _score([(metric, params)], output, expected, {})["value_abs_error"]["passed"] is True
    scored = _score([(metric, params)], output, expected, {"abs_tol": 1.0})
    assert scored["value_abs_error"]["passed"] is False
