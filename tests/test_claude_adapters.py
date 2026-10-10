import copy
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest

from geoevals.leaderboard.prompting import (
    cli_schema,
    direct_message,
    load_template,
    python_message,
    spec_for,
    system_prompt,
)
from geoevals.runner.run import Case, load_cases
from geoevals.validation import load_benchmark_spec

REPO = Path(__file__).parent.parent
GIS = REPO / "benchmarks" / "gis_correctness"
ACCESS = REPO / "benchmarks" / "human_context"


def _case(bench_dir: Path, case_id: str) -> Case:
    spec = load_benchmark_spec(bench_dir / "benchmark.yaml")
    return next(case for case in load_cases(spec, bench_dir) if case.case_id == case_id)


def _strip_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return {k: _strip_key(v, key) for k, v in value.items() if k != key}
    if isinstance(value, list):
        return [_strip_key(item, key) for item in value]
    return value


# --- prompting --------------------------------------------------------------------------------


def test_direct_message_inlines_geojson_and_withholds_answers() -> None:
    case = _case(GIS, "spatial_join-005")
    message = direct_message(case.input)
    assert case.input["prompt"] in message
    assert json.dumps(case.input["inputs"]["params"], indent=2) in message
    stations = (GIS / "fixtures" / "join_stations.geojson").read_text(encoding="utf-8")
    assert stations.strip() in message
    assert 'Input file "right" (fixtures/join_stations.geojson, GeoJSON):' in message
    for withheld in ["spatial_join-005", "expected", "trap", "tol_m", "float_tol"]:
        assert withheld not in message, withheld


def test_parquet_inputs_become_geojson() -> None:
    case = _case(ACCESS, "nearest_amenity-001")
    message = direct_message(case.input)
    for name in ["nodes", "edges", "pois"]:
        relative = case.input["inputs"]["files"][name]
        header = f'Input file "{name}" ({relative}, GeoJSON):\n'
        assert header in message
        text = message.split(header, 1)[1].split("\n\nInput file ", 1)[0]
        collection = json.loads(text)
        frame = gpd.read_parquet(ACCESS / relative)
        assert collection["type"] == "FeatureCollection"
        assert len(collection["features"]) == len(frame)
        assert collection == json.loads(frame.to_json(drop_id=True))


def test_python_message_gives_container_paths() -> None:
    case = _case(GIS, "spatial_join-005")
    message = python_message(case.input)
    assert case.input["prompt"] in message
    assert 'Input file "right": /bench/fixtures/join_stations.geojson' in message
    assert "FeatureCollection" not in message
    assert "spatial_join-005" not in message


def test_cli_schema_drops_evidence_type_only() -> None:
    access = load_benchmark_spec(ACCESS / "benchmark.yaml").output_schema
    original = copy.deepcopy(access)
    cleaned = cli_schema(access)
    assert "evidence_type" not in json.dumps(cleaned)
    assert cleaned == _strip_key(original, "evidence_type")
    assert access == original, "the spec schema is not modified"
    gis = load_benchmark_spec(GIS / "benchmark.yaml").output_schema
    assert cli_schema(gis) == gis


def test_templates_exist_and_take_the_task_statement() -> None:
    for track in ["direct", "python"]:
        template = load_template(track, "v1")
        assert template.count("{task_statement}") == 1
        assert "TASK X" in system_prompt(template, "TASK X")
        assert "{task_statement}" not in system_prompt(template, "TASK X")
    with pytest.raises(ValueError, match="v9"):
        load_template("direct", "v9")


def test_spec_for_reads_the_cases_benchmark() -> None:
    case = _case(ACCESS, "nearest_amenity-001")
    task_statement, schema = spec_for(case.input)
    spec = load_benchmark_spec(ACCESS / "benchmark.yaml")
    assert task_statement == spec.task_statement
    assert schema == spec.output_schema
