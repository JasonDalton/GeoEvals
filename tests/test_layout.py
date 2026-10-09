import json
import re
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas
import pyarrow.parquet as pq
import pytest

from geoevals import cli
from geoevals.cli import main
from geoevals.metrics import Metric, MetricValue
from geoevals.metrics import registry as metric_registry
from geoevals.reporting.compare import MISSING, Difference, compare_runs
from geoevals.runner import run as run_module
from geoevals.runner.config import config_hash, load_run_config
from geoevals.runner.layout import (
    artifact_name,
    dumps,
    find_geometries,
    make_run_id,
    write_run_dir,
)
from geoevals.validation import validate_run_result_document

FIXTURES = Path(__file__).parent / "fixtures" / "layout"
SPEC = FIXTURES / "benchmark.yaml"
RUN_CONFIG = FIXTURES / "run_config.yaml"
RUN_ID = re.compile(r"^layout_fixture-mock-\d{8}T\d{6}Z-[0-9a-f]{8}$")


class ExactMatch(Metric):
    id = "exact_match"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        passed = prediction == reference
        return MetricValue(value=1.0 if passed else 0.0, passed=passed)


@pytest.fixture(autouse=True)
def exact_match_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metric_registry, "_REGISTRY", {"exact_match": ExactMatch()})


def _run(out: Path, config: Path = RUN_CONFIG) -> int:
    args = ["run", "--benchmark", str(SPEC), "--adapter", "mock", "--config", str(config)]
    return main([*args, "--out", str(out), "--prices", str(FIXTURES / "prices.yaml")])


def _run_dir(out: Path) -> Path:
    [run_dir] = out.iterdir()
    return run_dir


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("layout") / "out"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(metric_registry, "_REGISTRY", {"exact_match": ExactMatch()})
        assert _run(out) == 0
    return _run_dir(out)


# --- JSON formatting ------------------------------------------------------------------------


def test_dumps_sorts_keys_and_stabilizes_floats() -> None:
    value = {"b": 0.1 + 0.2, "a": {"z": -0.0, "y": 1.0, "x": 2}, "c": [1 / 3]}
    assert dumps(value, indent=None) == (
        '{"a":{"x":2,"y":1.0,"z":0.0},"b":0.3,"c":[0.333333333333333]}'
    )
    assert dumps(value) == dumps(json.loads(dumps(value)))
    with pytest.raises(ValueError):
        dumps({"x": float("nan")})


def test_make_run_id() -> None:
    started = datetime(2026, 10, 9, 8, 7, 6, 543210, tzinfo=UTC)
    run_id = make_run_id("my_bench", "mock", started, "0123456789abcdef" * 4)
    assert run_id == "my_bench-mock-20261009T080706Z-01234567"


# --- run directory --------------------------------------------------------------------------


def test_run_directory_layout(run_dir: Path) -> None:
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "artifacts",
        "cases.jsonl",
        "config.yaml",
        "result.json",
        "run.log",
    ]
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert validate_run_result_document(result) == []
    assert run_dir.name == result["run_id"]
    assert RUN_ID.match(result["run_id"])
    assert result["run_id"].endswith(result["config_hash"][:8])


def test_result_json_is_sorted_and_stable(run_dir: Path) -> None:
    text = (run_dir / "result.json").read_text(encoding="utf-8")
    assert text == dumps(json.loads(text)) + "\n"
    # 0.30000000000000004 in the case file is written as 0.3.
    assert '"area_m2": 0.3,' in text
    assert "0.30000000000000004" not in text
    assert "0.30000000000000004" not in text


def test_cases_jsonl_matches_result(run_dir: Path) -> None:
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    lines = (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == result["cases"]
    assert lines == [dumps(case, indent=None) for case in result["cases"]]


def test_config_yaml_is_the_resolved_config(run_dir: Path) -> None:
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    config = load_run_config(run_dir / "config.yaml")
    assert config_hash(config) == result["config_hash"]
    assert config.max_retries == 0  # defaults are filled in
    assert "max_retries" in (run_dir / "config.yaml").read_text(encoding="utf-8")


def test_run_log(run_dir: Path) -> None:
    log = (run_dir / "run.log").read_text(encoding="utf-8")
    assert "benchmark layout_fixture 0.1.0 and manifest" in log
    assert "case point: scored" in log
    assert "output.geometry is not a readable geometry" in log


def test_geoparquet_artifacts(run_dir: Path) -> None:
    artifacts = run_dir / "artifacts"
    # No file for the case without geometry, nor for the one whose only geometry is unreadable.
    assert sorted(p.name for p in artifacts.iterdir()) == ["features.parquet", "point.parquet"]
    point = geopandas.read_parquet(artifacts / "point.parquet")
    assert list(point["path"]) == ["geometry"]
    assert list(point.geometry.to_wkt()) == ["POINT (13.4 52.5)"]
    assert point.crs is None
    features = geopandas.read_parquet(artifacts / "features.parquet")
    assert list(features["path"]) == [
        "result.features[0].geometry",
        "result.features[1].geometry",
    ]
    assert list(features.geom_type) == ["LineString", "Polygon"]
    assert b"geo" in pq.read_metadata(artifacts / "features.parquet").metadata


def test_find_geometries() -> None:
    point = {"type": "Point", "coordinates": [0, 0]}
    collection = {"type": "GeometryCollection", "geometries": [point]}
    assert find_geometries(point) == [("<root>", point)]
    assert find_geometries({"b": [collection], "a": {"type": "Point"}}) == [("b[0]", collection)]
    assert find_geometries({"type": "Feature", "geometry": None}) == []


def test_artifact_name() -> None:
    assert artifact_name("case-1.a_b") == "case-1.a_b.parquet"
    assert artifact_name("a/b") != artifact_name("a_b")
    assert re.fullmatch(r"a_b-[0-9a-f]{8}\.parquet", artifact_name("a/b"))


def test_existing_run_directory_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixed = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "FixedDatetime":
            return cls.fromtimestamp(fixed.timestamp(), tz)

    monkeypatch.setattr(run_module, "datetime", FixedDatetime)
    out = tmp_path / "out"
    assert _run(out) == 0
    run_dir = _run_dir(out)
    before = (run_dir / "result.json").read_bytes()
    capsys.readouterr()
    assert _run(out) == 1
    assert "already exists" in capsys.readouterr().err
    assert (run_dir / "result.json").read_bytes() == before


def test_invalid_written_result_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def corrupt(result: Mapping[str, Any], run_dir: Path) -> None:
        write_run_dir({**result, "schema_version": "9.9.9"}, run_dir)

    monkeypatch.setattr(cli, "write_run_dir", corrupt)
    assert _run(tmp_path / "out") == 1
    err = capsys.readouterr().err
    assert "schema_version" in err
    assert "invalid run result" in err


# --- compare --------------------------------------------------------------------------------


def _edit(run_dir: Path, edit: Any) -> None:
    path = run_dir / "result.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    edit(result)
    path.write_text(dumps(result) + "\n", encoding="utf-8")


def test_compare_identical_runs(
    run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path / "out") == 0
    other = _run_dir(tmp_path / "out")
    capsys.readouterr()
    # Two runs differ in run_id (maybe), timestamps, timing and memory, and compare as equal.
    assert main(["compare", str(run_dir), str(other / "result.json")]) == 0
    assert capsys.readouterr().out == "no differences\n"


def test_compare_ignores_timing_memory_and_ids(
    run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "other"
    shutil.copytree(run_dir, other)

    def edit(result: dict[str, Any]) -> None:
        result["run_id"] = "something-else"
        result["started_at"] = "2000-01-01T00:00:00Z"
        result["efficiency"]["wall_clock_s"] = 999.0
        for case in result["cases"]:
            case["latency_s"] = 5.0
            case["peak_memory_bytes"] = None
            case["memory_note"] = "not measured"

    _edit(other, edit)
    assert main(["compare", str(run_dir), str(other)]) == 0


def test_compare_lists_differences(
    run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "other"
    shutil.copytree(run_dir, other)

    def edit(result: dict[str, Any]) -> None:
        cases = {case["case_id"]: case for case in result["cases"]}
        cases["point"]["output"]["geometry"]["coordinates"] = [13.4, 52.6]
        cases["point"]["metrics"]["exact_match"] = {"value": 0.0, "passed": False, "detail": {}}
        cases["no/geometry"]["status"] = "timeout"
        result["cases"] = [case for case in result["cases"] if case["case_id"] != "features"]

    _edit(other, edit)
    capsys.readouterr()
    assert main(["compare", str(run_dir), str(other)]) == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "features: only in run a",
        'no/geometry: status: "scored" -> "timeout"',
        "point: output.geometry.coordinates[1]: 52.5 -> 52.6",
        "point: metrics.exact_match.passed: true -> false",
        "point: metrics.exact_match.value: 1.0 -> 0.0",
    ]
    assert "5 difference(s) in 3 case(s)" in captured.err


def test_compare_runs_values() -> None:
    def run(*cases: dict[str, Any]) -> dict[str, Any]:
        return {"cases": list(cases)}

    a = {"case_id": "c", "status": "scored", "output": {"n": 1, "xs": [1, 2]}, "metrics": {}}
    b = {"case_id": "c", "status": "scored", "output": {"n": 1.0, "xs": [1]}, "metrics": {}}
    assert compare_runs(run(a), run(a)) == []
    assert compare_runs(run(a), run(b)) == [
        Difference("c", "output.n", 1, 1.0),
        Difference("c", "output.xs", [1, 2], [1]),
    ]
    c = {**a, "output": {"xs": [1, 2]}}
    [difference] = compare_runs(run(a), run(c))
    assert difference == Difference("c", "output.n", 1, MISSING)
    assert str(difference) == "c: output.n: 1 -> <missing>"
    assert str(compare_runs(run(), run(a))[0]) == "c: only in run b"


def test_compare_unreadable_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["compare", str(tmp_path / "nope"), str(tmp_path / "nope")]) == 2
    assert "file not found" in capsys.readouterr().err
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "result.json").write_text("{}", encoding="utf-8")
    assert main(["compare", str(bad), str(bad)]) == 2
    assert "invalid" in capsys.readouterr().err
