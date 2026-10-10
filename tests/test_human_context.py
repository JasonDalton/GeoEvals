"""Tests for the ``human_context_access`` benchmark: the synthetic town, its cases, the reference
workflow (networkx) and the ``access_baseline`` adapter (scipy.sparse.csgraph)."""

import hashlib
import importlib.util
import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import geopandas
import networkx as nx
import pyarrow.parquet as pq
import pytest
from jsonschema import Draft202012Validator

from geoevals.adapters import (
    AccessBaselineAdapter,
    UnsupportedAccessOperation,
    access_baseline,
    create_adapter,
    registered_adapter_names,
)
from geoevals.cli import main
from geoevals.data.verify import verify_manifest
from geoevals.metrics.network import DEFAULT_WALK_SPEED_MPS, WEIGHT
from geoevals.regenerate import expected_outputs, find_benchmark_dir
from geoevals.reporting.compare import Tolerance, diff_values
from geoevals.reporting.report import report_context
from geoevals.runner.config import RunConfig
from geoevals.runner.run import _resolve_metrics, _score, load_cases, run_benchmark
from geoevals.validation import load_benchmark_spec, load_dataset_manifest, validate_file

REPO = Path(__file__).parent.parent
BENCH = REPO / "benchmarks" / "human_context"
SPEC = BENCH / "benchmark.yaml"
BENCHMARK_ID = "human_context_access"
CASE_FIELDS = {"case_id", "operation", "prompt", "inputs", "expected", "tolerances", "strata"}
FILES = {
    "nodes": "fixtures/town_nodes.parquet",
    "edges": "fixtures/town_edges.parquet",
    "pois": "fixtures/town_pois.parquet",
}
AGREEMENT_TOL_S = 1e-6
"""The networkx and scipy shortest-path times must agree within this many seconds."""
PLATFORM_TOL = Tolerance(abs=0.0, rel=1e-12)
"""Committed and regenerated expected numbers match within this (see the test)."""


def _module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"human_context_{name}", BENCH / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reference() -> ModuleType:
    return _module("reference")


@pytest.fixture(scope="module")
def make_fixture() -> ModuleType:
    return _module("make_fixture")


def _case_lines() -> list[tuple[Path, dict[str, Any]]]:
    return [
        (path, json.loads(line))
        for path in sorted((BENCH / "cases").glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _cases() -> list[dict[str, Any]]:
    return [case for _, case in _case_lines()]


# --- spec, cases and output contract ----------------------------------------------------------


def test_spec_validates_with_id_and_version() -> None:
    assert validate_file(SPEC) == ("benchmark spec", [])
    spec = load_benchmark_spec(SPEC)
    assert (spec.id, spec.version, spec.pillar) == (BENCHMARK_ID, "0.2.0", "human_context")
    assert validate_file(BENCH / "manifest.yaml") == ("dataset manifest", [])


def test_spec_lists_every_case_file() -> None:
    spec = load_benchmark_spec(SPEC)
    listed = [spec.cases] if isinstance(spec.cases, str) else list(spec.cases)
    on_disk = sorted(f"cases/{p.name}" for p in (BENCH / "cases").glob("*.jsonl"))
    assert sorted(listed) == on_disk


def test_case_format() -> None:
    input_validator = Draft202012Validator(load_benchmark_spec(SPEC).input_schema)
    lines = _case_lines()
    assert lines
    for path, case in lines:
        assert set(case) >= CASE_FIELDS, case.get("case_id")
        assert path.stem == case["operation"], f"{case['case_id']} is in {path.name}"
        assert case["case_id"].startswith(f"{case['operation']}-")
        assert case["strata"]["operation"] == case["operation"]
        assert case["inputs"]["files"] == FILES
        case_input = {key: value for key, value in case.items() if key != "expected"}
        errors = [error.message for error in input_validator.iter_errors(case_input)]
        assert errors == [], case["case_id"]


def test_cases_cover_the_story() -> None:
    cases = _cases()
    assert len(cases) >= 20
    operations = Counter(case["operation"] for case in cases)
    assert set(operations) == {
        "nearest_amenity",
        "amenity_count",
        "network_detour",
        "open_amenities",
        "abstention",
    }
    thresholds = {
        c["inputs"]["params"]["minutes"] for c in cases if c["operation"] == "amenity_count"
    }
    assert thresholds == {10, 15}
    abstentions = {c["strata"]["abstention"] for c in cases if c["operation"] == "abstention"}
    assert {"destination_off_network", "origin_off_network", "no_path"} <= abstentions
    statuses = {c["expected"]["status"] for c in cases if c["operation"] == "abstention"}
    assert statuses == {"insufficient_data", "invalid_request", "needs_clarification"}
    answered = [c for c in cases if c["operation"] != "abstention"]
    assert all(c["expected"]["status"] == "ok" for c in answered)


def _timed(case: dict[str, Any]) -> bool:
    return "open_amenities" in (case["operation"], case["inputs"]["params"].get("operation"))


def test_time_specific_cases_cover_the_story() -> None:
    timed = [case for case in _cases() if _timed(case)]
    answered = [case for case in timed if case["operation"] == "open_amenities"]
    assert len(answered) >= 10
    for case in timed:
        params = case["inputs"]["params"]
        assert isinstance(params["timezone"], str), case["case_id"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", params["date"]), case["case_id"]
        assert params["date"] in case["prompt"] and params["timezone"] in case["prompt"]
    for case in answered:
        assert case["inputs"]["params"]["timezone"] == "Africa/Abidjan"
        assert re.fullmatch(r"\d\d:\d\d", case["inputs"]["params"]["time"])
        assert "unknown_ids" in case["expected"]
    features = Counter(case["strata"]["hours_feature"] for case in answered)
    assert {"overnight", "public_holiday", "missing_hours", "24_7"} <= set(features)
    # Missing hours: an explicit unknown bucket, and insufficient_data when nothing else is known.
    assert any(case["expected"]["unknown_ids"] for case in answered)
    missing = [c for c in timed if c["strata"].get("abstention") == "hours_missing"]
    assert [c["expected"]["status"] for c in missing] == ["insufficient_data"]
    times_of_day = {case["strata"]["time_of_day"] for case in answered}
    assert times_of_day == {"night", "morning", "afternoon", "evening"}
    holidays = [c for c in answered if c["strata"]["hours_feature"] == "public_holiday"]
    assert all(c["inputs"]["params"]["public_holidays"] for c in holidays)


def test_time_of_day_stratum_matches_the_case_time() -> None:
    buckets = {range(0, 6): "night", range(6, 12): "morning", range(12, 18): "afternoon"}
    for case in _cases():
        clock = case["inputs"]["params"].get("time")
        expected = "none"
        if clock is not None:
            hour = int(clock[:2])
            expected = next((name for hours, name in buckets.items() if hour in hours), "evening")
        assert case["strata"]["time_of_day"] == expected, case["case_id"]


def test_strata_include_neighborhood_type_and_amenity_category() -> None:
    cases = [case for case in _cases() if case["operation"] != "abstention"]
    neighborhoods = {case["strata"]["neighborhood_type"] for case in cases}
    assert neighborhoods == {"grid", "mixed_use_core", "cul_de_sac_suburban", "rural_fringe"}
    categories = {case["strata"]["amenity_category"] for case in cases}
    assert categories >= {"grocery", "pharmacy", "school", "park", "transit_stop", "clinic"}
    for case in cases:
        params = case["inputs"]["params"]
        assert case["strata"]["amenity_category"] == params.get("category", "none")


def test_expected_outputs_satisfy_the_output_contract() -> None:
    spec = load_benchmark_spec(SPEC)
    validator = Draft202012Validator(spec.output_schema)
    for case in load_cases(spec, BENCH):
        errors = [error.message for error in validator.iter_errors(case.expected)]
        assert errors == [], case.case_id


# --- fixture ----------------------------------------------------------------------------------


def test_fixtures_are_small_geoparquet_and_in_the_manifest() -> None:
    fixtures = [path for path in (BENCH / "fixtures").rglob("*") if path.is_file()]
    assert fixtures and all(path.suffix == ".parquet" for path in fixtures)
    assert sum(path.stat().st_size for path in fixtures) < 1_000_000
    manifest = load_dataset_manifest(BENCH / "manifest.yaml")
    listed = {(BENCH / asset.path).resolve() for asset in manifest.assets}
    assert {path.resolve() for path in fixtures} == listed
    assert all(asset.redistributable for asset in manifest.assets)
    assert all(check.status == "ok" for check in verify_manifest(BENCH / "manifest.yaml"))
    for path in fixtures:
        geo = json.loads(pq.read_schema(path).metadata[b"geo"])
        assert geo["version"] == "1.1.0"
        assert geopandas.read_parquet(path).crs == "OGC:CRS84"


def test_town_contents() -> None:
    nodes = geopandas.read_parquet(BENCH / FILES["nodes"])
    edges = geopandas.read_parquet(BENCH / FILES["edges"])
    pois = geopandas.read_parquet(BENCH / FILES["pois"])
    neighborhoods = geopandas.read_parquet(BENCH / "fixtures" / "town_neighborhoods.parquet")
    assert len(edges) >= 200
    assert set(edges["u"]) | set(edges["v"]) <= set(nodes["node_id"])
    assert (edges["length_m"] > 0).all()
    types = {"grid", "mixed_use_core", "cul_de_sac_suburban", "rural_fringe"}
    assert set(nodes["neighborhood_type"]) == types
    assert set(neighborhoods["neighborhood_type"]) == types
    assert len(pois) >= 40
    assert pois["poi_id"].is_unique
    categories = Counter(pois["amenity_category"])
    assert set(categories) == {"grocery", "pharmacy", "school", "park", "transit_stop", "clinic"}
    hours = [value for value in pois["opening_hours"] if isinstance(value, str)]
    assert len(hours) == len(pois) - 2
    weekdays = r"(Mo|Tu|We|Th|Fr|Sa|Su)(-(Mo|Tu|We|Th|Fr|Sa|Su))?"
    span = r"\d\d:\d\d-\d\d:\d\d"
    rule = rf"(24/7|({weekdays}|PH)(,({weekdays}|PH))* (off|{span}(,{span})*))"
    assert all(re.fullmatch(rf"{rule}(; {rule})*", value) for value in hours), hours


def test_regenerated_fixture_matches_the_manifest(make_fixture: ModuleType, tmp_path: Path) -> None:
    digests = make_fixture.write_fixture(tmp_path)
    manifest = load_dataset_manifest(BENCH / "manifest.yaml")
    expected = {Path(asset.path).name: asset.sha256 for asset in manifest.assets}
    assert digests == expected
    for name, digest in digests.items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest


def test_fixture_generator_depends_on_the_seed(make_fixture: ModuleType) -> None:
    assert make_fixture.build_town().pois == make_fixture.build_town().pois
    assert make_fixture.build_town(1).pois != make_fixture.build_town().pois


# --- reference workflow and the second implementation -----------------------------------------


def _json_lines(text: str) -> list[Any]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_committed_expected_outputs_match_the_reference_workflow() -> None:
    """Like ``geoevals bench regenerate --check``, but numbers match within ``PLATFORM_TOL``:
    PROJ's geodesic (in the detour ratios) differs between macOS and Linux in the last digit."""
    differences = []
    for path, content in expected_outputs(BENCH, BENCHMARK_ID).items():
        assert path.is_file(), f"{path} is missing: run `geoevals bench regenerate {BENCHMARK_ID}`"
        committed = _json_lines(path.read_text(encoding="utf-8"))
        differences += list(diff_values(committed, _json_lines(content), path.name, PLATFORM_TOL))
    assert differences == [], f"run `geoevals bench regenerate {BENCHMARK_ID}`"


def test_cli_regenerate_finds_the_benchmark_by_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = REPO / "benchmarks"
    assert find_benchmark_dir(root, BENCHMARK_ID) == root / "human_context"
    assert find_benchmark_dir(root, "gis_correctness") == root / "gis_correctness"
    assert find_benchmark_dir(root, "missing") == root / "missing"
    shutil.copytree(BENCH, tmp_path / "human_context", ignore=shutil.ignore_patterns("__pycache__"))
    args = ["bench", "regenerate", BENCHMARK_ID, "--root", str(tmp_path)]
    assert main(args) == 0
    capsys.readouterr()
    assert main([*args, "--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def _agree(a: dict[str, Any], b: dict[str, Any]) -> None:
    assert set(a) == set(b)
    assert a["status"] == b["status"]
    assert a.get("units") == b.get("units")
    assert a.get("ids") == b.get("ids")
    if a.get("units") == "s":
        assert abs(a["value"] - b["value"]) <= AGREEMENT_TOL_S
    elif a.get("units") == "ratio":
        # A ratio of two lengths: 1e-6 s of walking is 1.33e-6 m of network length.
        assert abs(a["value"] - b["value"]) <= 1e-9
    else:
        assert a.get("value") == b.get("value")


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["case_id"])
def test_networkx_and_csgraph_agree_on_every_case(
    reference: ModuleType, case: dict[str, Any]
) -> None:
    case_input = {key: value for key, value in case.items() if key != "expected"}
    networkx_output = reference.reference_output(case_input, BENCH)
    response = AccessBaselineAdapter().predict({**case_input, "benchmark_dir": str(BENCH)})
    _agree(networkx_output, response.output)


def test_networkx_and_csgraph_agree_on_every_node_pair(reference: ModuleType) -> None:
    inputs = {"files": FILES, "params": {}}
    graph, _ = reference._town(inputs, BENCH)
    net, _ = access_baseline._network(inputs, BENCH)
    order = list(geopandas.read_parquet(BENCH / FILES["nodes"])["node_id"])
    assert list(graph.nodes) == order
    worst = 0.0
    pairs = 0
    for i, lengths in nx.all_pairs_dijkstra_path_length(graph, weight=WEIGHT):
        distances = net.distances_from(order.index(i))
        reachable = {order[j] for j, d in enumerate(distances) if math.isfinite(d)}
        assert reachable == set(lengths), i
        for node, length in lengths.items():
            difference = abs(length - float(distances[order.index(node)]))
            worst = max(worst, difference / DEFAULT_WALK_SPEED_MPS)
            pairs += 1
    assert pairs > 30_000
    assert worst <= AGREEMENT_TOL_S


# --- access_baseline --------------------------------------------------------------------------


def test_access_baseline_is_registered() -> None:
    assert "access_baseline" in registered_adapter_names()
    adapter = create_adapter("access_baseline")
    assert isinstance(adapter, AccessBaselineAdapter)
    assert adapter.deterministic is True


def test_access_baseline_rejects_config_and_unknown_operations() -> None:
    with pytest.raises(ValueError, match="takes no config"):
        AccessBaselineAdapter().setup({"x": 1})
    with pytest.raises(UnsupportedAccessOperation, match="unsupported operation 'nope'"):
        AccessBaselineAdapter().predict({"operation": "nope", "inputs": {"files": {}}})


@pytest.mark.integration
def test_access_baseline_scores_full_task_success() -> None:
    result = run_benchmark(SPEC, "access_baseline", RunConfig(split="test"))
    assert {case["status"] for case in result["cases"]} == {"scored"}
    assert result["summary_metrics"]["task_success"]["mean"] == 1.0
    assert result["summary_metrics"]["task_success"]["n"] == len(_case_lines())
    assert result["efficiency"]["cost_usd_total"] == 0.0
    strata = {key for case in result["cases"] for key in case["strata"]}
    assert {"neighborhood_type", "amenity_category", "time_of_day"} <= strata
    breakdowns = {item["key"]: item for item in report_context(result, "test")["strata"]}
    rows = [row["value"] for row in breakdowns["time_of_day"]["rows"]]
    assert sorted(rows) == ["afternoon", "evening", "morning", "night", "none"]


# --- wrong answers fail -----------------------------------------------------------------------


def _task_success(case_id: str, output: dict[str, Any]) -> float | None:
    spec = load_benchmark_spec(SPEC)
    [case] = [case for case in load_cases(spec, BENCH) if case.case_id == case_id]
    metrics = _score(_resolve_metrics(spec), output, case.expected, case.params)
    return metrics["task_success"]["value"]


def _with_pois(tmp_path: Path, hours: dict[str, Any]) -> Path:
    """A copy of the benchmark whose POIs have the given ``opening_hours`` values."""
    copy = tmp_path / "human_context"
    shutil.copytree(BENCH, copy, ignore=shutil.ignore_patterns("__pycache__"))
    pois = geopandas.read_parquet(copy / FILES["pois"])
    for poi_id, value in hours.items():
        pois.loc[pois["poi_id"] == poi_id, "opening_hours"] = value
    pois.to_parquet(copy / FILES["pois"])
    return copy


def test_unparseable_hours_are_missing_data_not_adapter_errors(
    reference: ModuleType, tmp_path: Path
) -> None:
    """open_amenities-001 (pharmacies, Sunday 21:30): poi-004 is open; with unparseable hours it
    moves to the unknown bucket in both implementations, and neither raises."""
    copy = _with_pois(tmp_path, {"poi-004": "sunrise-sunset", "poi-005": "Mo-Fr 9-17"})
    [case] = [case for case in _cases() if case["case_id"] == "open_amenities-001"]
    case_input = {key: value for key, value in case.items() if key != "expected"}
    expected = {
        "status": "ok",
        "value": 0,
        "units": "count",
        "ids": [],
        "unknown_ids": ["poi-004", "poi-005"],
    }
    assert reference.reference_output(case_input, copy) == expected
    response = AccessBaselineAdapter().predict({**case_input, "benchmark_dir": str(copy)})
    assert response.output == expected


def test_every_poi_within_reach_unknown_is_insufficient_data(
    reference: ModuleType, tmp_path: Path
) -> None:
    copy = _with_pois(tmp_path, {poi: "Mo-Fr 9-17" for poi in ("poi-001", "poi-002", "poi-003")})
    [case] = [case for case in _cases() if case["case_id"] == "open_amenities-014"]
    case_input = {key: value for key, value in case.items() if key != "expected"}
    assert reference.reference_output(case_input, copy) == {"status": "insufficient_data"}
    response = AccessBaselineAdapter().predict({**case_input, "benchmark_dir": str(copy)})
    assert response.output == {"status": "insufficient_data"}


def test_wrong_answers_fail() -> None:
    cases = {case["case_id"]: case["expected"] for case in _cases()}
    time = cases["nearest_amenity-001"]
    assert _task_success("nearest_amenity-001", time) == 1.0
    assert _task_success("nearest_amenity-001", {**time, "value": time["value"] + 1}) == 0.0
    assert _task_success("nearest_amenity-001", {**time, "units": "min"}) == 0.0
    count = cases["amenity_count-002"]
    assert _task_success("amenity_count-002", {**count, "value": count["value"] - 1}) == 0.0
    detour = cases["network_detour-003"]
    assert _task_success("network_detour-003", {**detour, "value": 1.0}) == 0.0
    assert _task_success("abstention-002", {"status": "ok", "value": 1.0, "units": "ratio"}) == 0.0
    assert _task_success("abstention-006", {"status": "insufficient_data"}) == 0.0
    # Ignoring opening hours counts every pharmacy within reach (4 instead of 1).
    sunday = cases["open_amenities-001"]
    assert _task_success("open_amenities-001", sunday) == 1.0
    assert _task_success("open_amenities-001", {**sunday, "value": 4}) == 0.0
    # Ignoring the public-holiday rule.
    assert _task_success("open_amenities-002", {**sunday}) == 0.0
    # Treating missing hours as open.
    missing = cases["open_amenities-014"]
    assert _task_success("open_amenities-014", {**missing, "value": 4}) == 0.0
    assert _task_success("abstention-013", {"status": "ok", "value": 0, "units": "count"}) == 0.0


def test_unknown_bucket_is_scored() -> None:
    spec = load_benchmark_spec(SPEC)
    [case] = [case for case in load_cases(spec, BENCH) if case.case_id == "open_amenities-014"]
    closed = {**case.expected, "unknown_ids": []}
    metrics = _score(_resolve_metrics(spec), closed, case.expected, case.params)
    assert metrics["unknown_set_jaccard"]["passed"] is False
    assert metrics["unknown_set_jaccard"]["detail"]["missing"] == ["poi-036"]
