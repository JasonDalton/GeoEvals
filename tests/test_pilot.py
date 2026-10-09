"""Real-geography pilot (US-026): fetching an OSM extract and building the pilot benchmark.

The offline tests use a synthetic Overpass response (invented streets and POIs, no OSM data)
and a fake HTTP opener. ``test_real_pilot_fetch_and_build`` downloads the real extract; it is
marked ``network`` and excluded from the default run and CI (run it with ``pytest -m network``).
"""

import datetime as dt
import io
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import yaml

from geoevals.cli import main
from geoevals.data import fetch
from geoevals.data.verify import verify_manifest
from geoevals.validation import load_benchmark_spec, validate_file

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "datasets/manifests/human_context_pilot.yaml"
BENCHMARK_DIR = ROOT / "benchmarks/human_context"

BBOX = (-73.2200, 44.4700, -73.2010, 44.4790)
"""About 1.5 km x 1 km; streets get sparser from west to east."""


def _overpass_response() -> dict[str, Any]:
    """A synthetic Overpass ``out:json`` response: three street grids of falling density."""
    elements: list[dict[str, Any]] = []
    node_id = 1000
    coordinates: dict[tuple[int, int], int] = {}

    def node(lon: float, lat: float) -> tuple[int, dict[str, float]]:
        nonlocal node_id
        key = (round(lon * 1e7), round(lat * 1e7))
        if key not in coordinates:
            node_id += 1
            coordinates[key] = node_id
        return coordinates[key], {"lat": round(lat, 7), "lon": round(lon, 7)}

    def way(points: list[tuple[float, float]]) -> None:
        ids, geometry = zip(*(node(lon, lat) for lon, lat in points), strict=True)
        elements.append(
            {
                "type": "way",
                "id": 500 + len(elements),
                "nodes": list(ids),
                "geometry": list(geometry),
                "tags": {"highway": "residential"},
            }
        )

    min_lon, min_lat, max_lon, max_lat = BBOX
    width = (max_lon - min_lon) / 3
    for part, step_m in enumerate((40.0, 90.0, 300.0)):
        west, east = min_lon + part * width, min_lon + (part + 1) * width
        step_lon, step_lat = step_m / 79400, step_m / 111130
        lats = [min_lat + i * step_lat for i in range(int((max_lat - min_lat) / step_lat) + 1)]
        lons = [west + i * step_lon for i in range(int((east - west) / step_lon) + 1)]
        for lat in lats:
            way([(lon, lat) for lon in lons])
        for lon in lons:
            way([(lon, lat) for lat in lats])
    pois = [
        ("node", 1, "shop", "supermarket", "Mo-Su 08:00-22:00", 0.10),
        ("node", 2, "shop", "convenience", None, 0.20),
        ("way", 3, "shop", "greengrocer", "Sa 09:00-13:00", 0.45),
        ("node", 4, "highway", "bus_stop", None, 0.15),
        ("node", 5, "highway", "bus_stop", None, 0.55),
        ("node", 6, "amenity", "pharmacy", "24/7", 0.30),
        ("node", 7, "amenity", "school", None, 0.60),
        ("node", 8, "leisure", "park", None, 0.80),
        ("node", 9, "amenity", "clinic", "Mo-Fr 08:00-17:00", 0.25),
        ("node", 10, "amenity", "bench", None, 0.35),
    ]
    for kind, osm_id, key, value, hours, at in pois:
        tags = {key: value, **({"opening_hours": hours} if hours else {})}
        point = {"lat": min_lat + 0.4 * (max_lat - min_lat), "lon": min_lon + at * 3 * width}
        element: dict[str, Any] = {"type": kind, "id": osm_id, "tags": tags}
        element.update(point if kind == "node" else {"center": point})
        elements.append(element)
    return {
        "version": 0.6,
        "generator": "synthetic",
        "osm3s": {"timestamp_osm_base": "2026-10-09T00:00:00Z", "copyright": "synthetic"},
        "elements": elements,
    }


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self


def _opener(document: dict[str, Any], seen: list[urllib.request.Request] | None = None) -> Any:
    def open_request(request: urllib.request.Request) -> _Response:
        if seen is not None:
            seen.append(request)
        return _Response(json.dumps(document).encode("utf-8"))

    return open_request


def _manifests(tmp_path: Path) -> Path:
    """A copy of the pilot manifest with the synthetic bounding box, in ``tmp/manifests``."""
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    asset = document["assets"][0]
    asset["bbox"] = list(BBOX)
    asset["path"] = "../raw/human_context_pilot/osm_extract.json"
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests/human_context_pilot.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return tmp_path / "manifests"


def _fetch(tmp_path: Path) -> fetch.FetchRecord:
    return fetch.fetch_dataset(
        "human_context_pilot",
        _manifests(tmp_path),
        today=dt.date(2026, 10, 9),
        opener=_opener(_overpass_response()),
    )


# --- manifest and download instructions ----------------------------------------------------


def test_pilot_manifest_is_valid_and_restricted() -> None:
    kind, issues = validate_file(MANIFEST)
    assert (kind, issues) == ("dataset manifest", [])
    [asset] = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["assets"]
    assert asset["license"] == "ODbL-1.0"
    assert asset["attribution"] == "© OpenStreetMap contributors"
    assert asset["redistributable"] is False
    assert asset["path"].startswith("../../data/raw/")
    assert "PLACEHOLDER" in yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["description"]


def test_download_instructions_name_the_command_and_the_license() -> None:
    text = (ROOT / "datasets/download_instructions/human_context_pilot.md").read_text("utf-8")
    for needle in (
        "geoevals data fetch human_context_pilot",
        "geoevals bench build human_context_pilot",
        "data/raw/human_context_pilot/",
        "ODbL-1.0",
        "© OpenStreetMap contributors",
        "access_date",
        "sha256",
        "pytest -m network",
    ):
        assert needle in text


def test_network_tests_are_excluded_by_default() -> None:
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"-m", "not network"' in config
    assert "network: " in config


# --- fetch ---------------------------------------------------------------------------------


def test_overpass_query_uses_the_bbox_and_snapshot_date() -> None:
    query = fetch.overpass_query((-73.225, 44.465, -73.2, 44.485), "2026-01-01")
    assert "[bbox:44.465,-73.225,44.485,-73.2]" in query
    assert '[date:"2026-01-01T00:00:00Z"]' in query
    assert "out geom;" in query and "out center tags;" in query


def test_normalized_extract_ignores_header_and_element_order() -> None:
    document = _overpass_response()
    shuffled = {**document, "osm3s": {"timestamp_osm_base": "2027-01-01T00:00:00Z"}}
    shuffled["elements"] = list(reversed(document["elements"]))
    assert fetch.normalize_overpass(document) == fetch.normalize_overpass(shuffled)
    assert b"osm3s" not in fetch.normalize_overpass(document)


def test_parse_bbox() -> None:
    assert fetch.parse_bbox("-73.2,44.4,-73.1,44.5") == (-73.2, 44.4, -73.1, 44.5)
    for text in ("1,2,3", "a,b,c,d", "-73.1,44.4,-73.2,44.5"):
        with pytest.raises(fetch.FetchError):
            fetch.parse_bbox(text)


def test_fetch_writes_extract_and_records_access_date_and_sha256(tmp_path: Path) -> None:
    seen: list[urllib.request.Request] = []
    manifests = _manifests(tmp_path)
    committed = (manifests / "human_context_pilot.yaml").read_bytes()
    record = fetch.fetch_dataset(
        "human_context_pilot",
        manifests,
        today=dt.date(2026, 10, 9),
        opener=_opener(_overpass_response(), seen),
    )
    out = tmp_path / "raw/human_context_pilot"
    assert sorted(path.name for path in out.iterdir()) == [
        "fetch.json",
        "manifest.yaml",
        "osm_extract.json",
    ]
    assert seen[0].full_url == "https://overpass-api.de/api/interpreter"
    assert record.access_date == "2026-10-09"
    assert record.snapshot_date == "2026-01-01"
    assert record.osm_base == "2026-10-09T00:00:00Z"
    local = yaml.safe_load((out / "manifest.yaml").read_text(encoding="utf-8"))
    [asset] = local["assets"]
    assert asset["access_date"] == "2026-10-09"
    assert asset["sha256"] == record.sha256
    assert asset["path"] == "osm_extract.json"
    assert asset["license"] == "ODbL-1.0" and asset["redistributable"] is False
    assert [check.status for check in verify_manifest(out / "manifest.yaml")] == ["ok"]
    saved = json.loads((out / "fetch.json").read_text(encoding="utf-8"))
    assert saved["sha256"] == record.sha256 and saved["access_date"] == "2026-10-09"
    assert (manifests / "human_context_pilot.yaml").read_bytes() == committed


def test_fetch_bbox_and_date_override_the_manifest(tmp_path: Path) -> None:
    seen: list[urllib.request.Request] = []
    record = fetch.fetch_dataset(
        "human_context_pilot",
        _manifests(tmp_path),
        bbox=(1.0, 2.0, 3.0, 4.0),
        snapshot_date="2025-06-01",
        opener=_opener(_overpass_response(), seen),
    )
    assert record.bbox == [1.0, 2.0, 3.0, 4.0]
    assert "bbox%3A2.0%2C1.0%2C4.0%2C3.0" in str(seen[0].data)
    assert "2025-06-01" in record.query


def test_fetch_reports_overpass_errors(tmp_path: Path) -> None:
    failing = {"elements": [], "remark": "runtime error: Query timed out"}
    manifests = _manifests(tmp_path)
    with pytest.raises(fetch.FetchError, match="timed out"):
        fetch.fetch_dataset("human_context_pilot", manifests, opener=_opener(failing))
    assert not (tmp_path / "raw/human_context_pilot/osm_extract.json").exists()
    with pytest.raises(fetch.FetchError, match="no fetcher"):
        fetch.fetch_dataset("unknown_dataset", manifests)


def _git_repo(path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / ".gitignore").write_text("data/raw/\n", encoding="utf-8")
    return path


def test_fetch_never_writes_into_a_path_git_would_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path / "repo", monkeypatch)
    manifests = _manifests(tmp_path)
    opener = _opener(_overpass_response())
    with pytest.raises(fetch.FetchError, match="refusing to write"):
        fetch.fetch_dataset("human_context_pilot", manifests, repo / "datasets", opener=opener)
    assert not (repo / "datasets").exists()
    record = fetch.fetch_dataset(
        "human_context_pilot", manifests, repo / "data/raw/pilot", opener=opener
    )
    assert Path(record.path) == repo / "data/raw/pilot/osm_extract.json"


def test_cli_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifests = _manifests(tmp_path)
    original = fetch.fetch_dataset

    def patched(*args: Any, **kwargs: Any) -> fetch.FetchRecord:
        return original(*args, opener=_opener(_overpass_response()), **kwargs)

    monkeypatch.setattr("geoevals.cli.fetch_dataset", patched)
    assert main(["data", "fetch", "human_context_pilot", "--manifests", str(manifests)]) == 0
    out, err = capsys.readouterr()
    assert "sha256" in out and "warning" in err  # the synthetic extract differs from OSM
    with pytest.raises(SystemExit):
        main(["data", "fetch", "human_context_pilot", "--bbox", "1,2,3"])
    assert "expected four numbers" in capsys.readouterr().err


# --- build ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    """The pilot built from the synthetic extract, under a copy of the benchmark root."""
    from geoevals import pilot

    tmp_path = tmp_path_factory.mktemp("pilot")
    _fetch(tmp_path)
    root = tmp_path / "benchmarks"
    shutil.copytree(BENCHMARK_DIR, root / "human_context")
    settings = yaml.safe_load((root / "human_context/pilot.yaml").read_text(encoding="utf-8"))
    settings["dataset_manifest"] = "../../manifests/human_context_pilot.yaml"
    (root / "human_context/pilot.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    result = pilot.build_pilot("human_context_pilot", root)
    return tmp_path, result


def _built_cases(out_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in sorted((out_dir / "cases").glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_build_writes_a_valid_benchmark(built: tuple[Path, Any]) -> None:
    tmp_path, result = built
    assert result.out_dir == tmp_path / "raw/human_context_pilot/benchmark"
    spec = load_benchmark_spec(result.out_dir / "benchmark.yaml")
    assert spec.id == "human_context_pilot"
    assert spec.license == "ODbL-1.0"
    assert validate_file(result.out_dir / "manifest.yaml") == ("dataset manifest", [])
    assert [check.status for check in verify_manifest(result.out_dir / "manifest.yaml")] == [
        "ok"
    ] * 3


def test_build_samples_at_least_30_origins_in_3_density_terciles(
    built: tuple[Path, Any],
) -> None:
    _, result = built
    cases = _built_cases(result.out_dir)
    origins = {case["origin_id"]: case["strata"]["neighborhood_type"] for case in cases}
    assert result.origins == len(origins) >= 30
    counts = {kind: list(origins.values()).count(kind) for kind in set(origins.values())}
    assert counts == {"low_density": 12, "medium_density": 12, "high_density": 12}
    operations = {case["operation"] for case in cases}
    assert operations == {"nearest_amenity", "amenity_count", "open_amenities"}
    assert result.cases == len(cases) == 4 * len(origins)
    assert all(case["expected"]["status"] in ("ok", "insufficient_data") for case in cases)
    assert any(case["expected"]["status"] == "ok" for case in cases)


def test_density_terciles_follow_street_density(built: tuple[Path, Any]) -> None:
    """The synthetic streets thin out from west to east, so the terciles do too."""
    _, result = built
    by_type: dict[str, list[float]] = {}
    for case in _built_cases(result.out_dir):
        by_type.setdefault(case["strata"]["neighborhood_type"], []).append(
            case["inputs"]["params"]["origin"][0]
        )
    mean = {kind: sum(lons) / len(lons) for kind, lons in by_type.items()}
    assert mean["high_density"] < mean["medium_density"] < mean["low_density"]


def test_report_has_freshness_missingness_and_sensitivity(built: tuple[Path, Any]) -> None:
    _, result = built
    report = result.report.read_text(encoding="utf-8")
    for heading in (
        "## Data freshness",
        "## Missingness",
        "### POIs without `opening_hours`",
        "### Origins that fail to snap",
        "## Spatial-unit sensitivity",
        "Mean (250 m cells) | Mean (1000 m cells) | Difference",
    ):
        assert heading in report
    assert "| Extract date (OSM snapshot) | 2026-01-01 (00:00 UTC) |" in report
    assert "| Access date (fetched) | 2026-10-09 |" in report
    # 9 synthetic POIs (the bench is not one), 5 without opening_hours.
    assert "| **all** | 9 | 5 | 55.6% |" in report
    assert "© OpenStreetMap contributors" in report


def test_access_baseline_agrees_with_the_reference_on_the_pilot(built: tuple[Path, Any]) -> None:
    from geoevals.adapters import create_adapter

    _, result = built
    adapter = create_adapter("access_baseline")
    adapter.setup({})
    for case in _built_cases(result.out_dir):
        inputs = {**case, "benchmark_dir": str(result.out_dir)}
        del inputs["expected"]
        output = adapter.predict(inputs).output
        assert output["status"] == case["expected"]["status"], case["case_id"]
        if output["status"] == "ok":
            assert output["value"] == pytest.approx(case["expected"]["value"], abs=1e-6)
            assert output["ids"] == case["expected"]["ids"]


def test_build_requires_a_fetched_extract(tmp_path: Path) -> None:
    from geoevals import pilot

    _manifests(tmp_path)
    root = tmp_path / "benchmarks"
    (root / "human_context").mkdir(parents=True)
    (root / "human_context/pilot.yaml").write_text(
        (BENCHMARK_DIR / "pilot.yaml")
        .read_text(encoding="utf-8")
        .replace("../../datasets/manifests/", "../../manifests/"),
        encoding="utf-8",
    )
    with pytest.raises(pilot.PilotError, match="geoevals data fetch human_context_pilot"):
        pilot.build_pilot("human_context_pilot", root)
    with pytest.raises(pilot.PilotError, match=r"no pilot\.yaml"):
        pilot.build_pilot("other_pilot", root)


def test_sensitivity_aggregates_nested_cells() -> None:
    from geoevals import pilot

    rows = pilot.sensitivity(
        [((100.0, 100.0), 2), ((200.0, 100.0), 4), ((300.0, 100.0), 9), ((1100.0, 0.0), 1)],
        [250, 1000],
    )
    assert [row["mean_250"] for row in rows] == [3, 3, 9, 1]
    assert [row["mean_1000"] for row in rows] == [5, 5, 5, 1]


def test_density_terciles_split_cells_evenly() -> None:
    from geoevals import pilot

    density = {(i, 0): float(value) for i, value in enumerate([0, 0, 0, 5, 1, 9, 7, 3, 2])}
    types = pilot.density_terciles(density)
    low, medium, high = pilot.DENSITY_TYPES
    assert [types[i, 0] for i in range(9)] == [
        low, low, low, high, medium, high, high, medium, medium
    ]  # fmt: skip


def test_poi_categories() -> None:
    from geoevals import pilot

    assert pilot.poi_category({"shop": "supermarket"}) == "grocery"
    assert pilot.poi_category({"amenity": "doctors"}) == "clinic"
    assert pilot.poi_category({"railway": "tram_stop"}) == "transit_stop"
    assert pilot.poi_category({"amenity": "bench"}) is None


# --- real data (manual) --------------------------------------------------------------------


@pytest.mark.network
def test_real_pilot_fetch_and_build(tmp_path: Path) -> None:
    """Download the default extract from Overpass and build the pilot (a minute or more)."""
    from geoevals import pilot

    out = tmp_path / "raw"
    record = fetch.fetch_dataset("human_context_pilot", ROOT / "datasets/manifests", out)
    committed = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["assets"][0]["sha256"]
    if record.sha256 != committed:
        pytest.fail(f"Overpass returned different data: sha256 {record.sha256} != {committed}")
    result = pilot.build_pilot("human_context_pilot", ROOT / "benchmarks", out, tmp_path / "b")
    assert result.origins >= 30
    assert "## Spatial-unit sensitivity" in result.report.read_text(encoding="utf-8")


def test_benchmark_card_documents_the_pilot() -> None:
    card = (BENCHMARK_DIR / "README.md").read_text(encoding="utf-8")
    section = card[card.index("## Real-geography pilot") :]
    for needle in (
        "### Purpose",
        "placeholder",
        "Time range",
        "### Licenses",
        "ODbL-1.0",
        "### Known biases",
        "OSM completeness varies by region",
        "### Prohibited uses",
        "pytest -m network",
    ):
        assert needle in section
