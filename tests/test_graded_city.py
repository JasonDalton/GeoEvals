import math
from pathlib import Path

import pytest
from pyproj import CRS as ProjCRS

from geoevals.graded.city import (
    CRS,
    LAYERS,
    CityError,
    building_height,
    convert_extract,
    layers_sha256,
    load_layers,
    parse_height,
    walkable,
    write_layers,
)
from graded_city import overpass_document


@pytest.mark.parametrize(
    ("text", "meters"),
    [
        ("12", 12.0),
        ("12 m", 12.0),
        ("12.5m", 12.5),
        ("40 ft", 40 * 0.3048),
        ("40'", 40 * 0.3048),
        ("tall", None),
        ("0", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_height(text: str | None, meters: float | None) -> None:
    assert parse_height(text) == (pytest.approx(meters) if meters is not None else None)


def test_building_height_prefers_the_height_tag() -> None:
    assert building_height({"height": "9", "building:levels": "5"}) == (9.0, "height")
    assert building_height({"building:levels": "4"}) == (12.0, "levels")
    assert building_height({"building:levels": "two"}) == (None, "unknown")
    assert building_height({}) == (None, "unknown")


def _ids(layers, name: str) -> set[str]:
    return set(layers[name]["feature_id"])


def test_layers_hold_the_expected_features() -> None:
    layers = convert_extract(overpass_document())
    assert tuple(layers) == LAYERS
    assert _ids(layers, "streets") == {"way/200", "way/201", "way/202", "way/203"}
    assert _ids(layers, "paths") == {"way/210", "way/211", "way/212"}
    assert _ids(layers, "railways") == {"way/300"}
    assert _ids(layers, "water") == {"way/100", "way/101"}
    assert _ids(layers, "parks") == {"way/600", "relation/703"}
    assert _ids(layers, "landuse") == {"way/610"}
    assert _ids(layers, "boundaries") == {"relation/700", "relation/701", "relation/702"}
    assert {"way/400", "way/404", "way/405", "way/412"} <= _ids(layers, "buildings")
    assert _ids(layers, "pois") == {
        "node/500",
        "node/501",
        "node/502",
        "node/504",
        "way/405",
        "way/412",
    }
    assert set(layers["pois"].geom_type) == {"Point"}
    for frame in layers.values():
        assert frame.crs == ProjCRS(CRS)


def test_building_heights_follow_the_rule() -> None:
    buildings = convert_extract(overpass_document())["buildings"].set_index("feature_id")
    assert buildings.loc["way/400", "height_m"] == 40.0
    assert buildings.loc["way/400", "height_source"] == "height"
    assert buildings.loc["way/401", "height_m"] == 6.0
    assert buildings.loc["way/401", "height_source"] == "levels"
    assert math.isnan(buildings.loc["way/404", "height_m"])
    assert buildings.loc["way/404", "height_source"] == "unknown"


def _barrier(tags: dict[str, str], layer: str, closed: bool = False) -> bool:
    points = [(0, 0), (100, 0), (100, 50), (0, 50), (0, 0)] if closed else [(0, 0), (100, 0)]
    way = {
        "type": "way",
        "id": 1,
        "geometry": [{"lon": 10 + x / 1e5, "lat": 50 + y / 1e5} for x, y in points],
        "tags": tags,
    }
    frame = convert_extract({"elements": [way]})[layer]
    assert len(frame) == 1, tags
    return bool(frame["walk_barrier"].iloc[0])


@pytest.mark.parametrize(
    ("tags", "barrier"),
    [
        ({"railway": "rail"}, True),
        ({"railway": "light_rail"}, True),
        ({"railway": "narrow_gauge"}, True),
        ({"railway": "monorail"}, True),
        ({"railway": "funicular"}, True),
        ({"railway": "rail", "tunnel": "no", "bridge": "no"}, True),
        ({"railway": "tram"}, False),
        ({"railway": "subway"}, False),
        ({"railway": "rail", "tunnel": "yes"}, False),
        ({"railway": "rail", "bridge": "viaduct"}, False),
        ({"railway": "light_rail", "location": "underground"}, False),
    ],
)
def test_walk_barrier_rail(tags: dict[str, str], barrier: bool) -> None:
    assert _barrier(tags, "railways") is barrier


@pytest.mark.parametrize(
    ("tags", "closed", "barrier"),
    [
        ({"waterway": "river"}, False, True),
        ({"waterway": "canal"}, False, True),
        ({"waterway": "stream"}, False, True),
        ({"waterway": "ditch"}, False, False),
        ({"waterway": "drain"}, False, False),
        ({"waterway": "culvert"}, False, False),
        ({"waterway": "stream", "tunnel": "culvert"}, False, False),
        ({"natural": "water"}, True, True),
        ({"natural": "water", "water": "pond"}, True, True),
        ({"waterway": "riverbank"}, True, True),
        ({"natural": "water"}, False, False),  # an unclosed outline is not an area
    ],
)
def test_walk_barrier_water(tags: dict[str, str], closed: bool, barrier: bool) -> None:
    assert _barrier(tags, "water", closed) is barrier


def test_a_water_point_is_not_a_barrier() -> None:
    node = {"type": "node", "id": 1, "lon": 10.0, "lat": 50.0, "tags": {"waterway": "waterfall"}}
    water = convert_extract({"elements": [node]})["water"]
    assert list(water["walk_barrier"]) == [False]


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "residential"}, True),
        ({"highway": "footway"}, True),
        ({"highway": "motorway"}, False),
        ({"highway": "motorway_link"}, False),
        ({"highway": "trunk"}, True),
        ({"highway": "service", "foot": "no"}, False),
        ({"highway": "path", "foot": "private"}, False),
        ({"highway": "service", "access": "no"}, False),
        ({"highway": "service", "access": "private"}, False),
        ({"highway": "service", "access": "private", "foot": "yes"}, True),
        ({"highway": "service", "access": "no", "foot": "designated"}, True),
        ({"highway": "service", "access": "private", "foot": "permissive"}, True),
        ({"highway": "service", "access": "private", "foot": "destination"}, False),
        ({"highway": "service", "access": "destination"}, True),
        ({"highway": "motorway", "foot": "yes"}, False),
    ],
)
def test_walkable(tags: dict[str, str], expected: bool) -> None:
    assert walkable(tags) is expected


def test_streets_and_paths_carry_walkable() -> None:
    def way(id_: int, tags: dict[str, str]) -> dict:
        points = [
            {"lon": 10.0, "lat": 50.0 + id_ * 1e-4},
            {"lon": 10.001, "lat": 50.0 + id_ * 1e-4},
        ]
        return {"type": "way", "id": id_, "geometry": points, "tags": tags}

    layers = convert_extract(
        {
            "elements": [
                way(1, {"highway": "motorway"}),
                way(2, {"highway": "residential"}),
                way(3, {"highway": "footway", "access": "private"}),
                way(4, {"highway": "footway"}),
            ]
        }
    )
    streets = layers["streets"].set_index("feature_id")["walkable"]
    paths = layers["paths"].set_index("feature_id")["walkable"]
    assert streets.to_dict() == {"way/1": False, "way/2": True}
    assert paths.to_dict() == {"way/3": False, "way/4": True}


def test_multipolygon_relation_keeps_its_hole() -> None:
    parks = convert_extract(overpass_document())["parks"].set_index("feature_id")
    ring = parks.geometry["relation/703"]
    assert ring.geom_type == "Polygon"
    assert len(ring.interiors) == 1


def test_elements_without_geometry_are_left_out() -> None:
    document = overpass_document()
    document["elements"].append(
        {
            "type": "relation",
            "id": 999,
            "members": [{"type": "way", "role": "outer"}],
            "tags": {"type": "multipolygon", "landuse": "grass"},
        }
    )
    layers = convert_extract(document)
    features = _ids(layers, "all_features")
    assert "way/900" not in features, "no node positions"
    assert "way/901" not in features, "no tags"
    assert "relation/999" not in features, "members without geometry"


def test_all_features_keeps_every_tag_as_json() -> None:
    frame = convert_extract(overpass_document())["all_features"].set_index("feature_id")
    assert frame.loc["node/500", "tags"] == '{"amenity": "pharmacy", "name": "North Pharmacy"}'


def test_extract_without_elements_is_an_error() -> None:
    with pytest.raises(CityError, match="elements"):
        convert_extract({"remark": "runtime error"})


def test_layers_round_trip_and_hash(tmp_path: Path) -> None:
    layers = convert_extract(overpass_document())
    written = write_layers(layers, tmp_path / "layers")
    assert sorted(p.name for p in written) == sorted(f"{name}.parquet" for name in LAYERS)
    loaded = load_layers(tmp_path / "layers")
    for name in LAYERS:
        assert list(loaded[name]["feature_id"]) == list(layers[name]["feature_id"]), name
        assert loaded[name].geometry.geom_equals_exact(layers[name].geometry, 0).all(), name
    digest = layers_sha256(tmp_path / "layers")
    assert digest == layers_sha256(tmp_path / "layers")
    (tmp_path / "layers" / "pois.parquet").write_bytes(b"changed")
    assert layers_sha256(tmp_path / "layers") != digest


def test_load_layers_names_missing_layers(tmp_path: Path) -> None:
    write_layers(convert_extract(overpass_document()), tmp_path)
    (tmp_path / "parks.parquet").unlink()
    with pytest.raises(CityError, match="parks"):
        load_layers(tmp_path)


def _building_way(points: list[tuple[float, float]]) -> dict:
    return {
        "type": "way",
        "id": 1,
        "geometry": [{"lon": 10 + x * 1e-5, "lat": 50 + y * 1e-5} for x, y in points],
        "tags": {"building": "yes"},
    }


@pytest.mark.parametrize(
    "ring",
    [
        [(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)],  # a bowtie
        [(0, 0), (10, 0), (10, 10), (10, 20), (10, 10), (0, 10), (0, 0)],  # a spike
    ],
)
def test_an_invalid_building_ring_stays_a_building(ring: list[tuple[float, float]]) -> None:
    layers = convert_extract({"elements": [_building_way(ring)]})
    (geometry,) = layers["buildings"].geometry
    assert geometry.geom_type in ("Polygon", "MultiPolygon") and geometry.is_valid
    assert layers["all_features"].geometry.iloc[0].geom_type in ("Polygon", "MultiPolygon")


def test_a_line_that_collapses_to_a_point_is_left_out() -> None:
    way = {
        "type": "way",
        "id": 2,
        "geometry": [{"lon": 10.0, "lat": 50.0}, {"lon": 10.0, "lat": 50.0}],
        "tags": {"highway": "footway"},
    }
    layers = convert_extract({"elements": [way]})
    assert layers["paths"].empty and layers["all_features"].empty
