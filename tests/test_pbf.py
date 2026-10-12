import datetime as dt
import json
from pathlib import Path
from typing import Any

import osmium
import pytest
import yaml

from geoevals.cli import main
from geoevals.data.fetch import FetchError, fetch_dataset
from geoevals.data.pbf import pbf_timestamp, read_pbf
from geoevals.data.verify import sha256_file, verify_manifest
from geoevals.graded.city import LAYERS, convert_extract
from graded_city import BBOX, lonlat, overpass_document

REPO = Path(__file__).parent.parent
TIMESTAMP = "2026-10-11T20:21:06Z"


def write_pbf(path: Path, document: dict[str, Any], timestamp: str | None = TIMESTAMP) -> Path:
    """Write an Overpass ``out geom`` document as a ``.osm.pbf``: every distinct coordinate is a
    node (a tagged node's own when one stands there), and a relation's way members become ways."""
    nodes: dict[int, tuple[tuple[float, float], dict[str, str]]] = {}
    at: dict[tuple[float, float], int] = {}
    for element in document["elements"]:
        if element["type"] == "node":
            point = (element["lon"], element["lat"])
            nodes[element["id"]] = (point, element.get("tags") or {})
            at[point] = element["id"]

    def refs(geometry: list[Any]) -> list[int]:
        ids = []
        for position, coordinate in enumerate(geometry):
            if coordinate is None:  # a node without a position: refer to a missing node
                ids.append(900_000_000 + position)
                continue
            point = (coordinate["lon"], coordinate["lat"])
            if point not in at:
                at[point] = 1_000_000 + len(at)
                nodes[at[point]] = (point, {})
            ids.append(at[point])
        return ids

    ways: dict[int, tuple[list[int], dict[str, str]]] = {}
    relations: dict[int, tuple[list[tuple[str, int, str]], dict[str, str]]] = {}
    for element in document["elements"]:
        if element["type"] == "way":
            ways[element["id"]] = (refs(element["geometry"]), element.get("tags") or {})
        elif element["type"] == "relation":
            members = []
            for member in element["members"]:
                ways.setdefault(member["ref"], (refs(member["geometry"]), {}))
                members.append(("w", member["ref"], member["role"]))
            relations[element["id"]] = (members, element["tags"])
    header = osmium.io.Header()
    if timestamp is not None:
        header.set("osmosis_replication_timestamp", timestamp)
    writer = osmium.SimpleWriter(str(path), header=header)
    try:
        for id_, (point, tags) in sorted(nodes.items()):
            writer.add_node(osmium.osm.mutable.Node(id=id_, location=point, tags=tags))
        for id_, (node_refs, tags) in sorted(ways.items()):
            writer.add_way(osmium.osm.mutable.Way(id=id_, nodes=node_refs, tags=tags))
        for id_, (members, tags) in sorted(relations.items()):
            writer.add_relation(osmium.osm.mutable.Relation(id=id_, members=members, tags=tags))
    finally:
        writer.close()
    return path


def _elements(data: bytes) -> dict[str, dict[str, Any]]:
    return {f"{e['type']}/{e['id']}": e for e in json.loads(data)["elements"]}


def test_the_synthetic_city_from_pbf_gives_the_overpass_layers(tmp_path: Path) -> None:
    path = write_pbf(tmp_path / "city.osm.pbf", overpass_document())
    from_pbf = convert_extract(json.loads(read_pbf(path, BBOX)))
    from_overpass = convert_extract(overpass_document())
    for name in LAYERS:
        expected, actual = from_overpass[name], from_pbf[name]
        assert list(actual["feature_id"]) == list(expected["feature_id"]), name
        assert actual.geometry.geom_equals_exact(expected.geometry, 1e-7).all(), name
        columns = [c for c in expected.columns if c != "geometry"]
        assert actual[columns].equals(expected[columns]), name


def _point(x: float, y: float) -> dict[str, float]:
    lon, lat = lonlat(x, y)
    return {"lon": lon, "lat": lat}


def _way(id_: int, points: list[tuple[float, float]], tags: dict[str, str]) -> dict[str, Any]:
    return {"type": "way", "id": id_, "geometry": [_point(*p) for p in points], "tags": tags}


def _box_document() -> dict[str, Any]:
    """Features in and around the box from (0, 0) to (100, 100)."""
    inside, outside = lonlat(50, 50), lonlat(500, 50)
    lake = [(80, 80), (300, 80), (300, 300), (80, 300), (80, 80)]  # partly in the box
    county = [(-900, -900), (900, -900), (900, 900), (-900, 900), (-900, -900)]
    return {
        "elements": [
            {"type": "node", "id": 1, "lon": inside[0], "lat": inside[1], "tags": {"shop": "x"}},
            {"type": "node", "id": 2, "lon": outside[0], "lat": outside[1], "tags": {"shop": "y"}},
            _way(10, [(10, 10), (20, 10)], {"highway": "footway"}),
            _way(11, [(-50, 50), (150, 50)], {"highway": "residential"}),  # no vertex inside
            _way(12, [(400, 400), (500, 400)], {"highway": "residential"}),  # outside
            {
                "type": "relation",
                "id": 20,
                "members": [{"role": "outer", "ref": 200, "geometry": [_point(*p) for p in lake]}],
                "tags": {"type": "multipolygon", "natural": "water"},
            },
            {
                "type": "relation",
                "id": 21,
                "members": [{"role": "outer", "ref": 210, "geometry": [_point(*p) for p in lake]}],
                "tags": {"type": "boundary", "boundary": "administrative", "admin_level": "6"},
            },
            {
                "type": "relation",
                "id": 22,
                "members": [
                    {"role": "outer", "ref": 220, "geometry": [_point(*p) for p in county]}
                ],
                "tags": {"type": "boundary", "boundary": "administrative", "admin_level": "8"},
            },
            {
                "type": "relation",
                "id": 23,
                "members": [{"role": "outer", "ref": 230, "geometry": [_point(*p) for p in lake]}],
                "tags": {"type": "route", "route": "bus"},
            },
        ]
    }


def test_read_pbf_keeps_what_the_city_query_would(tmp_path: Path) -> None:
    path = write_pbf(tmp_path / "box.osm.pbf", _box_document())
    bbox = (*lonlat(0, 0), *lonlat(100, 100))
    elements = _elements(read_pbf(path, bbox))
    assert "node/1" in elements and "node/2" not in elements, "tagged nodes in the box"
    assert not any(e["type"] == "node" and not e.get("tags") for e in elements.values())
    assert {"way/10", "way/11"} <= set(elements) and "way/12" not in elements
    assert "relation/20" in elements, "a multipolygon with a member in the box"
    assert "relation/21" not in elements, "a county boundary"
    assert "relation/22" not in elements, "its only member has no vertex in the box"
    assert "relation/23" not in elements, "not a multipolygon or boundary"
    lake = elements["relation/20"]["members"][0]["geometry"]
    assert len(lake) == 5, "a member keeps its full geometry, outside the box too"


def test_read_pbf_is_stable(tmp_path: Path) -> None:
    path = write_pbf(tmp_path / "city.osm.pbf", overpass_document())
    assert read_pbf(path, BBOX) == read_pbf(path, BBOX)


def test_pbf_timestamp(tmp_path: Path) -> None:
    assert pbf_timestamp(write_pbf(tmp_path / "a.osm.pbf", overpass_document())) == TIMESTAMP
    assert pbf_timestamp(write_pbf(tmp_path / "b.osm.pbf", overpass_document(), None)) is None


def test_read_pbf_reports_unreadable_files(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="no such file"):
        read_pbf(tmp_path / "missing.osm.pbf", BBOX)
    bad = tmp_path / "bad.osm.pbf"
    bad.write_bytes(b"not a pbf")
    with pytest.raises(FetchError, match=r"bad\.osm\.pbf"):
        read_pbf(bad, BBOX)


# --- fetch and measure-town from a local extract --------------------------------------------


def _city_manifest(tmp_path: Path) -> Path:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    pilot = yaml.safe_load(
        (REPO / "datasets/manifests/human_context_pilot.yaml").read_text(encoding="utf-8")
    )
    pilot["dataset_id"] = "osm_city_test"
    asset = pilot["assets"][0]
    asset["path"] = "../raw/osm_city_test/osm_extract.json"
    asset["source_url"] = "https://download.geofabrik.de/north-america/us/oregon-261011.osm.pbf"
    asset["bbox"] = list(BBOX)
    asset["time_range"] = {"start": "2026-10-11", "end": "2026-10-11"}
    (manifests / "osm_city_test.yaml").write_text(yaml.safe_dump(pilot), encoding="utf-8")
    return manifests


def test_fetch_a_city_from_a_local_extract(tmp_path: Path) -> None:
    pbf = write_pbf(tmp_path / "region.osm.pbf", overpass_document())
    record = fetch_dataset(
        "osm_city_test", _city_manifest(tmp_path), today=dt.date(2026, 10, 12), pbf=pbf
    )
    out = tmp_path / "raw/osm_city_test"
    assert (out / "osm_extract.json").read_bytes() == read_pbf(pbf, BBOX)
    assert record.osm_base == TIMESTAMP and record.source_sha256 == sha256_file(pbf)
    saved = json.loads((out / "fetch.json").read_text(encoding="utf-8"))
    assert saved["source_sha256"] == record.source_sha256
    local = yaml.safe_load((out / "manifest.yaml").read_text(encoding="utf-8"))
    assert local["assets"][0]["sha256"] == record.sha256
    assert "--pbf" in local["assets"][0]["processing_steps"][-1]
    assert [check.status for check in verify_manifest(out / "manifest.yaml")] == ["ok"]


def test_fetch_refuses_an_extract_from_another_date(tmp_path: Path) -> None:
    pbf = write_pbf(tmp_path / "region.osm.pbf", overpass_document(), "2026-09-01T20:00:00Z")
    with pytest.raises(FetchError, match="not on the snapshot date 2026-10-11"):
        fetch_dataset("osm_city_test", _city_manifest(tmp_path), pbf=pbf)


def test_only_city_datasets_read_a_local_extract(tmp_path: Path) -> None:
    pbf = write_pbf(tmp_path / "region.osm.pbf", overpass_document())
    with pytest.raises(FetchError, match="only osm_city_"):
        fetch_dataset("human_context_pilot", REPO / "datasets/manifests", pbf=pbf)


def test_measure_town_cli_from_a_local_extract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pbf = write_pbf(tmp_path / "region.osm.pbf", overpass_document())
    bbox = ",".join(str(v) for v in BBOX)
    args = ["evals", "measure-town", "--name", "Alpha", "--bbox", bbox, "--out", str(tmp_path)]
    assert main([*args, "--pbf", str(pbf)]) == 0
    assert "| Alpha | 10 |" in capsys.readouterr().out
    record = json.loads((tmp_path / "alpha/fetch.json").read_text(encoding="utf-8"))
    assert record["snapshot_date"] == "2026-10-11"
    assert record["source_sha256"] == sha256_file(pbf)
    assert main(args) == 1, "fetching from Overpass needs --date"
    assert "--date" in capsys.readouterr().err
