import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from pyproj import Transformer
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

from geoevals.adapters import (
    GisBaselineAdapter,
    UnsupportedOperation,
    create_adapter,
    registered_adapter_names,
)
from geoevals.adapters.gis_baseline import OPERATIONS, UNITS_IN_M
from geoevals.cli import main
from geoevals.data.verify import verify_manifest
from geoevals.metrics.spatial import reproject
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
        {"status": "ok", "value": False, "units": "bool", "reason": "unclosed_ring", "crs": "x"},
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


# --- distance cases ----------------------------------------------------------------------------

DEGREE_TRAP_CASES = ["distance-005", "distance-007"]
"""Planar distance in degrees is wrong here: across the antimeridian and at latitude 70."""
METERS_PER_DEGREE = 111_320.0


def _cases_of(operation: str) -> list[dict[str, Any]]:
    return [case for path, case in _case_lines() if path.stem == operation]


def _loaded_case(case_id: str) -> Any:
    [case] = [c for c in load_cases(load_benchmark_spec(SPEC), BENCH) if c.case_id == case_id]
    return case


def _task_success(output: dict[str, Any], case_id: str) -> dict[str, Any]:
    case = _loaded_case(case_id)
    metrics = _resolve_metrics(load_benchmark_spec(SPEC))
    return _score(metrics, output, case.expected, case.params)["task_success"]


def _layer_points(path: str) -> dict[str, tuple[float, float]]:
    collection = json.loads((BENCH / path).read_text(encoding="utf-8"))
    return {
        feature["properties"]["name"]: tuple(feature["geometry"]["coordinates"])
        for feature in collection["features"]
    }


def test_distance_cases_cover_the_traps() -> None:
    cases = _cases_of("distance")
    assert len(cases) >= 8
    for case in cases:
        params, tolerances = case["inputs"]["params"], case["tolerances"]
        assert case["strata"]["method"] == params["method"], case["case_id"]
        assert isinstance(case["strata"]["trap"], bool), case["case_id"]
        assert tolerances["abs_tol"]["units"] == params["units"], case["case_id"]
        assert tolerances["rel_tol"]["units"] == "ratio", case["case_id"]
    expected = {case["case_id"]: case["expected"] for case in cases}
    geodesic = [case for case in cases if case["inputs"]["params"]["method"] == "geodesic"]

    def meters(case: dict[str, Any]) -> float:
        value = expected[case["case_id"]]
        return value["value"] * UNITS_IN_M[value["units"]]

    assert any(meters(case) < 10_000 for case in geodesic), "short geodesic distance"
    assert any(meters(case) > 1_000_000 for case in geodesic), "geodesic distance over 1,000 km"
    projected = [case for case in cases if case["inputs"]["params"]["method"] == "projected"]
    assert projected and all(case["inputs"]["params"]["crs"] for case in projected)
    assert {"m", "ft", "us_ft", "mi"} <= {case["inputs"]["params"]["units"] for case in cases}
    assert all(case["expected"]["crs"] == "OGC:CRS84" for case in geodesic)


@pytest.mark.parametrize("case_id", DEGREE_TRAP_CASES)
def test_planar_distance_in_degrees_fails(case_id: str) -> None:
    case = _loaded_case(case_id)
    params = case.input["inputs"]["params"]
    points = _layer_points(case.input["inputs"]["files"]["layer"])
    (x1, y1), (x2, y2) = points[params["from"]], points[params["to"]]
    degrees = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    naive = degrees * METERS_PER_DEGREE / UNITS_IN_M[params["units"]]
    output = {**case.expected, "value": naive}
    assert _task_success(case.expected, case_id)["passed"] is True
    result = _task_success(output, case_id)
    assert result["passed"] is False
    assert abs(naive - case.expected["value"]) / case.expected["value"] > 0.1


def test_wrong_distance_units_fail() -> None:
    expected = _loaded_case("distance-006").expected
    meters_as_us_ft = expected["value"] * UNITS_IN_M["us_ft"]
    assert _task_success({**expected, "value": meters_as_us_ft}, "distance-006")["passed"] is False
    feet_as_us_ft = expected["value"] * UNITS_IN_M["us_ft"] / UNITS_IN_M["ft"]
    assert _task_success({**expected, "value": feet_as_us_ft}, "distance-006")["passed"] is False


# --- buffer cases ------------------------------------------------------------------------------

BUFFER_KINDS = {
    "point_geographic",
    "line",
    "negative_collapse",
    "cap_style",
    "dissolve",
    "negative_units",
}


def test_buffer_cases_cover_the_kinds_and_state_tolerances() -> None:
    cases = _cases_of("buffer")
    assert len(cases) >= 6
    assert {case["strata"]["buffer_kind"] for case in cases} == BUFFER_KINDS
    for case in cases:
        assert set(case["tolerances"]) == {"tol_m", "area_tol_rel"}, case["case_id"]
        assert case["tolerances"]["tol_m"]["units"] == "m", case["case_id"]
        assert case["tolerances"]["area_tol_rel"]["units"] == "ratio", case["case_id"]
    by_kind = {case["strata"]["buffer_kind"]: case for case in cases}
    point = by_kind["point_geographic"]["inputs"]["params"]
    assert point["geometry"]["type"] == "Point" and "crs" not in point
    assert "source_crs" not in point, "geographic input"
    assert by_kind["line"]["inputs"]["params"]["geometry"]["type"] == "LineString"
    assert {case["inputs"]["params"].get("cap_style") for case in cases} >= {"flat", "square"}
    collapse = _loaded_case(by_kind["negative_collapse"]["case_id"]).expected
    assert collapse["geometry"] == {"type": "Polygon", "coordinates": []}
    dissolved = _loaded_case(by_kind["dissolve"]["case_id"]).expected
    assert dissolved["geometry"]["type"] == "MultiPolygon"
    assert len(dissolved["geometry"]["coordinates"]) == 2, "two of the three buffers overlap"


def test_buffer_scoring_reports_hausdorff_and_area_error() -> None:
    result = run_benchmark(SPEC, "gis_baseline", RunConfig(split="test"))
    buffers = [case for case in result["cases"] if case["case_id"].startswith("buffer-")]
    assert len(buffers) == len(_cases_of("buffer"))
    for case in buffers:
        detail = case["metrics"]["geometry_match"]["detail"]
        tolerances = {name: tol.value for name, tol in _tolerances(case["case_id"]).items()}
        assert detail["tol_m"] == tolerances["tol_m"]
        assert detail["area_tol_rel"] == tolerances["area_tol_rel"]
        assert detail["hausdorff_m"] <= detail["tol_m"], case["case_id"]
        assert detail["area_error_rel"] <= detail["area_tol_rel"], case["case_id"]
        assert case["metrics"]["task_success"]["value"] == 1.0, case["case_id"]


def _tolerances(case_id: str) -> dict[str, Tolerance]:
    [case] = [case for case in _cases_of("buffer") if case["case_id"] == case_id]
    return {name: Tolerance(**value) for name, value in case["tolerances"].items()}


def _buffered(geometry: BaseGeometry, crs: str, distance: float, **kwargs: Any) -> BaseGeometry:
    """Buffer ``geometry`` (in OGC:CRS84) by ``distance`` units of ``crs``, back in CRS84."""
    to_crs = Transformer.from_crs("OGC:CRS84", crs, always_xy=True)
    back = Transformer.from_crs(crs, "OGC:CRS84", always_xy=True)
    return reproject(reproject(geometry, to_crs).buffer(distance, **kwargs), back)


def _failed_buffer(
    output_geometry: BaseGeometry, case_id: str, failed: tuple[str, ...] = ("geometry_match",)
) -> dict[str, Any]:
    output = {**_loaded_case(case_id).expected, "geometry": mapping(output_geometry)}
    result = _task_success(json.loads(json.dumps(output)), case_id)
    assert result["passed"] is False
    assert result["detail"]["failed"] == list(failed)
    return result["detail"]["checks"]["geometry_match"]["detail"]


def test_point_buffer_without_projecting_fails() -> None:
    point = Point(13.405, 52.52)
    in_degrees = point.buffer(500 / METERS_PER_DEGREE)
    assert _failed_buffer(in_degrees, "buffer-001")["hausdorff_m"] > 100
    in_web_mercator = _buffered(point, "EPSG:3857", 500)
    assert _failed_buffer(in_web_mercator, "buffer-001")["area_error_rel"] > 0.5


def test_wrong_cap_style_fails() -> None:
    line = shape(_loaded_case("buffer-004").input["inputs"]["params"]["geometry"])
    detail = _failed_buffer(line.buffer(10), "buffer-004")
    assert detail["hausdorff_m"] == pytest.approx(10.0)


def test_buffers_that_are_not_dissolved_fail() -> None:
    points = [Point(*xy) for xy in _site_points()]
    parts = [_buffered(point, "EPSG:32633", 300) for point in points]
    assert all(isinstance(part, Polygon) for part in parts)
    # Overlapping MultiPolygon parts are also invalid geometry.
    detail = _failed_buffer(
        MultiPolygon(cast(list[Polygon], parts)), "buffer-006", ("geometry_match", "validity_match")
    )
    assert detail["topology"]["predicted"]["parts"] == 3
    assert detail["topology"]["expected"]["parts"] == 2


def _site_points() -> list[tuple[float, float]]:
    collection = json.loads((BENCH / "fixtures/buffer_sites.geojson").read_text(encoding="utf-8"))
    return [tuple(feature["geometry"]["coordinates"]) for feature in collection["features"]]


def test_negative_buffer_in_the_wrong_units_fails() -> None:
    rectangle = shape(_loaded_case("buffer-007").input["inputs"]["params"]["geometry"])
    detail = _failed_buffer(rectangle.buffer(-50), "buffer-007")
    assert detail["reason"] == "empty_prediction"


def test_negative_buffer_that_does_not_collapse_fails() -> None:
    square = shape(_loaded_case("buffer-003").input["inputs"]["params"]["geometry"])
    detail = _failed_buffer(square, "buffer-003")
    assert detail["reason"] == "empty_reference"


# --- validity cases ----------------------------------------------------------------------------

VALIDITY_DEFECTS = {
    ("detect", "bowtie"),
    ("detect", "unclosed_ring"),
    ("detect", "duplicate_vertex"),
    ("detect", "hole_outside_shell"),
    ("detect", "overlapping_parts"),
    ("detect", "zero_area_sliver"),
    ("detect", "empty"),
    ("repair", "bowtie"),
    ("repair", "figure_eight"),
}


def _validity_case(task: str, defect: str) -> Any:
    [case] = [
        case
        for case in _cases_of("validity")
        if (case["strata"]["task"], case["strata"]["defect"]) == (task, defect)
    ]
    return _loaded_case(case["case_id"])


def test_validity_cases_cover_the_defects() -> None:
    cases = _cases_of("validity")
    assert len(cases) >= 8
    assert {(c["strata"]["task"], c["strata"]["defect"]) for c in cases} == VALIDITY_DEFECTS
    for case in cases:
        assert isinstance(case["strata"]["trap"], bool), case["case_id"]
        expected = _loaded_case(case["case_id"]).expected
        if case["strata"]["task"] == "detect":
            assert isinstance(expected["value"], bool), case["case_id"]
            assert expected["reason"], case["case_id"]
            assert "geometry" not in expected, case["case_id"]
        else:
            assert shape(expected["geometry"]).is_valid, case["case_id"]
            assert set(case["tolerances"]) == {"tol_m", "area_tol_rel"}, case["case_id"]
    detected = {}
    for task, defect in VALIDITY_DEFECTS - {("repair", "bowtie"), ("repair", "figure_eight")}:
        expected = _validity_case(task, defect).expected
        detected[defect] = (expected["value"], expected["reason"])
    assert detected == {
        "bowtie": (False, "self_intersection"),
        "unclosed_ring": (False, "unclosed_ring"),
        "duplicate_vertex": (True, "valid"),
        "hole_outside_shell": (False, "hole_outside_shell"),
        "overlapping_parts": (False, "self_intersection"),
        "zero_area_sliver": (False, "self_intersection"),
        "empty": (True, "valid"),
    }


def test_repairs_keep_the_area_of_every_lobe() -> None:
    for defect in ("bowtie", "figure_eight"):
        case = _validity_case("repair", defect)
        repaired = shape(case.expected["geometry"])
        assert isinstance(repaired, MultiPolygon) and len(repaired.geoms) == 2
        lobes = shape(case.input["inputs"]["params"]["geometry"]).buffer(0)
        assert repaired.area > lobes.area, "buffer(0) drops a lobe"


def test_gis_baseline_passes_every_validity_case() -> None:
    result = run_benchmark(SPEC, "gis_baseline", RunConfig(split="test"))
    cases = [case for case in result["cases"] if case["case_id"].startswith("validity-")]
    assert len(cases) == len(_cases_of("validity"))
    for case in cases:
        assert case["metrics"]["task_success"]["value"] == 1.0, case["case_id"]
        checks = case["metrics"]["task_success"]["detail"]["checks"]
        if "value_equal" in checks:
            assert "reason_match" in checks, case["case_id"]


def _detection(case: Any, value: bool, reason: str) -> dict[str, Any]:
    return _task_success({**case.expected, "value": value, "reason": reason}, case.case_id)


def test_shapely_closing_the_ring_is_not_a_valid_answer() -> None:
    case = _validity_case("detect", "unclosed_ring")
    assert shape(case.input["inputs"]["params"]["geometry"]).is_valid
    result = _detection(case, True, "valid")
    assert result["detail"]["failed"] == ["value_equal", "reason_match"]


def test_wrong_reason_category_fails() -> None:
    case = _validity_case("detect", "hole_outside_shell")
    result = _detection(case, False, "self_intersection")
    assert result["detail"]["failed"] == ["reason_match"]
    detail = result["detail"]["checks"]["reason_match"]["detail"]
    assert (detail["predicted"], detail["expected"]) == ("self_intersection", "hole_outside_shell")
    missing = _task_success({"status": "ok", "value": False, "units": "bool"}, case.case_id)
    assert missing["detail"]["failed"] == ["crs_match", "reason_match"]


def test_empty_geometry_reported_invalid_fails() -> None:
    case = _validity_case("detect", "empty")
    assert _detection(case, False, "empty")["passed"] is False


def test_repair_that_drops_a_lobe_fails() -> None:
    case = _validity_case("repair", "bowtie")
    bowtie = shape(case.input["inputs"]["params"]["geometry"])
    output = {**case.expected, "geometry": mapping(bowtie.buffer(0))}
    result = _task_success(json.loads(json.dumps(output)), case.case_id)
    assert result["detail"]["failed"] == ["geometry_match"]
    detail = result["detail"]["checks"]["geometry_match"]["detail"]
    assert detail["area_error_rel"] == pytest.approx(0.5)
    unrepaired = {**case.expected, "geometry": case.input["inputs"]["params"]["geometry"]}
    result = _task_success(unrepaired, case.case_id)
    assert "validity_match" in result["detail"]["failed"]


# --- spatial join and overlay cases ------------------------------------------------------------

JOIN_KINDS = {
    "points_in_polygons",
    "intersects_vs_within",
    "nearest_max_distance",
    "shared_boundary",
    "crs_mismatch",
    "one_to_many",
}
OVERLAY_KINDS = {
    "intersection",
    "union",
    "difference",
    "symmetric_difference",
    "clip",
    "mixed_types",
}
FEATURE_CHECKS = {"feature_count", "geometry_match", "attribute_match", "crs_match"}


def _join_case(kind: str, predicate: str | None = None) -> Any:
    [case] = [
        case
        for case in _cases_of("spatial_join")
        if case["strata"]["join"] == kind and predicate in (None, case["strata"]["predicate"])
    ]
    return _loaded_case(case["case_id"])


def _overlay_case(kind: str) -> Any:
    [case] = [case for case in _cases_of("overlay") if case["strata"]["overlay"] == kind]
    return _loaded_case(case["case_id"])


def _features_of(output: dict[str, Any]) -> list[dict[str, Any]]:
    return output["features"]["features"]


def _with_features(case: Any, features: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    output = json.loads(json.dumps(case.expected))
    output["features"]["features"] = json.loads(json.dumps(features))
    return {**output, **fields}


def test_join_and_overlay_cases_cover_the_kinds() -> None:
    joins, overlays = _cases_of("spatial_join"), _cases_of("overlay")
    assert len(joins) >= 6 and len(overlays) >= 6
    assert {case["strata"]["join"] for case in joins} == JOIN_KINDS
    assert {case["strata"]["overlay"] for case in overlays} == OVERLAY_KINDS
    assert {"intersects", "within"} <= {
        case["strata"]["predicate"]
        for case in joins
        if case["strata"]["join"] == "intersects_vs_within"
    }
    for case in joins + overlays:
        assert case["tolerances"]["tol_m"]["units"] == "m", case["case_id"]
        assert case["metric_params"]["key"], "features are matched by a stated key"
        assert isinstance(case["strata"]["trap"], bool), case["case_id"]
        assert _features_of(_loaded_case(case["case_id"]).expected), case["case_id"]
    nearest = _join_case("nearest_max_distance").input["inputs"]["params"]
    assert (nearest["predicate"], nearest["max_distance"], nearest["units"]) == (
        "nearest",
        2000,
        "m",
    )


def test_boundary_point_semantics() -> None:
    """A point on the edge two zones share intersects both of them and is within neither."""
    on_edge = "p4"
    within = _join_case("points_in_polygons").expected
    assert on_edge not in [f["properties"]["point_id"] for f in _features_of(within)]
    intersects = _join_case("shared_boundary").expected
    zones = [f["properties"]["zone_id"] for f in _features_of(intersects)
             if f["properties"]["point_id"] == on_edge]  # fmt: skip
    assert zones == ["z1", "z2"]


def test_mixed_type_overlay_holds_a_polygon_and_a_line() -> None:
    [feature] = _features_of(_overlay_case("mixed_types").expected)
    geometry = shape(feature["geometry"])
    assert isinstance(geometry, GeometryCollection)
    assert sorted(part.geom_type for part in geometry.geoms) == ["LineString", "Polygon"]


def test_gis_baseline_passes_every_join_and_overlay_case() -> None:
    result = run_benchmark(SPEC, "gis_baseline", RunConfig(split="test"))
    cases = [c for c in result["cases"] if c["case_id"].startswith(("spatial_join-", "overlay-"))]
    assert len(cases) == len(_cases_of("spatial_join")) + len(_cases_of("overlay"))
    for case in cases:
        task_success = case["metrics"]["task_success"]
        assert task_success["value"] == 1.0, case["case_id"]
        assert set(task_success["detail"]["checks"]) >= FEATURE_CHECKS, case["case_id"]
        for metric in ("geometry_match", "attribute_match", "crs_match"):
            assert case["metrics"][metric]["passed"] is True, (case["case_id"], metric)


def test_within_instead_of_intersects_misses_the_boundary_point() -> None:
    case = _join_case("shared_boundary")
    within = _features_of(_join_case("points_in_polygons").expected)
    result = _task_success(_with_features(case, within), case.case_id)
    assert result["detail"]["failed"] == [
        "feature_count",
        "geometry_match",
        "validity_match",
        "attribute_match",
    ]
    count = result["detail"]["checks"]["feature_count"]["detail"]
    assert (count["predicted"], count["expected"]) == (4, 6)
    geometry = result["detail"]["checks"]["geometry_match"]["detail"]
    assert geometry["missing"] == [["p4", "z1"], ["p4", "z2"]]


def test_one_to_many_join_collapsed_to_one_match_fails_the_count() -> None:
    case = _join_case("one_to_many")
    first_only = {f["properties"]["zone_id"]: f for f in reversed(_features_of(case.expected))}
    result = _task_success(_with_features(case, list(first_only.values())), case.case_id)
    assert result["detail"]["failed"] == [
        "feature_count",
        "geometry_match",
        "validity_match",
        "attribute_match",
    ]


def test_join_without_reprojecting_finds_no_match() -> None:
    case = _join_case("crs_mismatch")
    result = _task_success(_with_features(case, []), case.case_id)
    assert "feature_count" in result["detail"]["failed"]
    assert "crs_match" not in result["detail"]["failed"]


def test_wrong_attribute_fails_only_attribute_match() -> None:
    case = _join_case("intersects_vs_within", "intersects")
    features = _features_of(case.expected)
    features[0]["properties"]["zone_name"] = "east"
    result = _task_success(_with_features(case, features), case.case_id)
    assert result["detail"]["failed"] == ["attribute_match"]
    detail = result["detail"]["checks"]["attribute_match"]["detail"]
    [failure] = detail["features"]
    assert failure["differences"] == [
        {"attribute": "zone_name", "predicted": "east", "expected": "west"}
    ]


def test_wrong_crs_label_fails_only_crs_match() -> None:
    case = _overlay_case("intersection")
    result = _task_success({**case.expected, "crs": "EPSG:4326"}, case.case_id)
    assert result["detail"]["failed"] == ["crs_match"]


def test_nearest_join_without_the_max_distance_fails_attributes() -> None:
    case = _join_case("nearest_max_distance")
    features = _features_of(case.expected)
    unmatched = [f for f in features if f["properties"]["station_id"] is None]
    assert unmatched
    for feature in unmatched:
        feature["properties"].update(station_id="s1", station_name="Station One", distance_m=6000.0)
    result = _task_success(_with_features(case, features), case.case_id)
    assert result["detail"]["failed"] == ["attribute_match"]


def test_overlay_that_drops_the_line_fails_geometry() -> None:
    case = _overlay_case("mixed_types")
    [feature] = _features_of(case.expected)
    polygon = next(g for g in feature["geometry"]["geometries"] if g["type"] == "Polygon")
    result = _task_success(_with_features(case, [{**feature, "geometry": polygon}]), case.case_id)
    assert result["detail"]["failed"] == ["geometry_match"]
    assert "topology" in result["detail"]["checks"]["geometry_match"]["detail"]["features"][0]


def test_union_without_the_outside_pieces_fails_the_count() -> None:
    case = _overlay_case("union")
    both = [f for f in _features_of(case.expected) if None not in f["properties"].values()]
    result = _task_success(_with_features(case, both), case.case_id)
    count = result["detail"]["checks"]["feature_count"]["detail"]
    assert (count["predicted"], count["expected"]) == (3, 8)


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


def test_load_cases_reads_metric_params(tmp_path: Path) -> None:
    tolerances = {"tol_m": {"value": 0.5, "units": "m"}}
    params = {"key": ["a", "b"]}
    _write_cases(
        tmp_path,
        {"case_id": "a", "expected": {}, "tolerances": tolerances, "metric_params": params},
        {"case_id": "b", "expected": {}, "metric_params": {"tol_m": 1}, "tolerances": tolerances},
        {"case_id": "c", "expected": {}, "metric_params": []},
    )
    with pytest.raises(RunError) as error:
        load_cases(load_benchmark_spec(SMOKE_SPEC), tmp_path)
    assert "case 'b' names ['tol_m'] in both tolerances and metric_params" in str(error.value)
    assert "case 'c' metric_params must be an object" in str(error.value)
    _write_cases(
        tmp_path,
        {"case_id": "a", "expected": {}, "tolerances": tolerances, "metric_params": params},
    )
    [case] = load_cases(load_benchmark_spec(SMOKE_SPEC), tmp_path)
    assert case.params == {"tol_m": 0.5, "key": ["a", "b"]}


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
