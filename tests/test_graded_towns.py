import io
import json
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.data.fetch import city_query, fetcher_for
from geoevals.graded.city import LAYERS, convert_extract
from geoevals.graded.towns import (
    EXTRACT_FILE,
    TownStats,
    fetch_candidate,
    measure_layers,
    stats_table,
)
from graded_city import BBOX, overpass_document


def test_city_query_asks_for_every_tagged_feature_at_the_snapshot() -> None:
    query = city_query((10.0, 50.0, 10.1, 50.1), "2026-01-01")
    assert '[date:"2026-01-01T00:00:00Z"]' in query
    assert "[bbox:50.0,10.0,50.1,10.1]" in query
    assert 'node[~"."~"."];' in query
    assert "way;" in query
    assert 'relation["type"="multipolygon"];' in query
    assert query.rstrip().endswith("out geom;")


def test_city_datasets_use_the_city_fetcher() -> None:
    assert fetcher_for("osm_city_example") == "overpass_city"
    assert fetcher_for("human_context_pilot") == "overpass"
    assert fetcher_for("unknown") is None


def test_measure_layers_on_the_synthetic_city() -> None:
    stats = measure_layers(convert_extract(overpass_document()), BBOX, extract_bytes=2_500_000)
    assert stats.buildings == 10
    assert stats.height_share == pytest.approx(0.5)
    assert stats.street_km == pytest.approx(2.1, rel=0.01)
    assert stats.path_km == pytest.approx(0.12, rel=0.01)
    assert stats.pois == 6
    assert stats.water_features == 2
    assert stats.landuse_share == pytest.approx(0.2, rel=0.02)
    assert stats.extract_mb == pytest.approx(2.5)


def test_stats_table_has_one_row_per_town() -> None:
    stats = TownStats(10, 0.5, 2.1, 0.12, 6, 0.2, 2, 2.5)
    table = stats_table([("Alpha", stats), ("Beta", stats)])
    lines = table.splitlines()
    assert lines[0].startswith("| Town | Buildings |")
    assert lines[2].startswith("| Alpha | 10 | 50% |")
    assert len(lines) == 4


def _opener(document: dict):
    def open_(request):
        assert b"out+geom" in request.data
        return io.BytesIO(json.dumps(document).encode("utf-8"))

    return open_


def test_fetch_candidate_writes_extract_and_record(tmp_path: Path) -> None:
    directory = fetch_candidate(
        "Alpha Town", BBOX, "2026-01-01", tmp_path, opener=_opener(overpass_document())
    )
    assert directory == tmp_path / "alpha_town"
    extract = json.loads((directory / EXTRACT_FILE).read_text(encoding="utf-8"))
    assert len(extract["elements"]) == len(overpass_document()["elements"])
    record = json.loads((directory / "fetch.json").read_text(encoding="utf-8"))
    assert record["snapshot_date"] == "2026-01-01"
    assert record["bbox"] == list(BBOX)


def test_measure_town_cli_with_a_fetched_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "alpha"
    source.mkdir()
    (source / EXTRACT_FILE).write_text(json.dumps(overpass_document()), encoding="utf-8")
    bbox = ",".join(str(v) for v in BBOX)
    code = main(
        [
            "evals",
            "measure-town",
            "--name",
            "Alpha",
            "--bbox",
            bbox,
            "--date",
            "2026-01-01",
            "--source",
            str(source),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "| Alpha | 10 |" in out
    assert sorted(p.name for p in (source / "layers").iterdir()) == sorted(
        f"{name}.parquet" for name in LAYERS
    )
