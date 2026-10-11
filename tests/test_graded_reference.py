from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from geoevals.graded.city import convert_extract
from geoevals.graded.reference import load_reference
from geoevals.validation import load_eval_spec
from graded_city import ORIGIN, VIEWPOINT, lonlat, overpass_document

REPO = Path(__file__).parent.parent
SAMPLE = REPO / "tests" / "fixtures" / "graded" / "sample" / "eval.yaml"
LAYERS = convert_extract(overpass_document())
compute_key = load_reference(SAMPLE, load_eval_spec(SAMPLE))
module = compute_key.__globals__  # the reference module's namespace


def test_proximity_separates_straight_line_and_walking() -> None:
    key = compute_key(
        "proximity",
        {"from": {"point": ORIGIN}, "category": {"amenity": "pharmacy"}, "top": 2},
        LAYERS,
    )
    assert key["straight_line_nearest"] == "node/501"
    assert key["walking_nearest"] == "node/500"
    assert key["same_nearest"] is False
    by_walk = {row["feature_id"]: row for row in key["by_walking"]}
    assert by_walk["node/500"]["walking_m"] == pytest.approx(330, rel=0.01)
    assert by_walk["node/501"]["walking_m"] == pytest.approx(880, rel=0.01)
    by_line = {row["feature_id"]: row for row in key["by_straight_line"]}
    assert by_line["node/501"]["straight_line_m"] == pytest.approx(120, rel=0.01)
    assert key["unreachable"] == []


def test_keys_round_floats_to_one_decimal() -> None:
    key = compute_key(
        "proximity", {"from": {"point": ORIGIN}, "category": {"amenity": "pharmacy"}}, LAYERS
    )

    def floats(value):
        if isinstance(value, float):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from floats(v)
        elif isinstance(value, list):
            for v in value:
                yield from floats(v)

    assert all(round(v, 1) == v for v in floats(key))


def test_unreachable_places_are_reported() -> None:
    far = lonlat(0, 1000)  # over 700 m from every network vertex
    key = compute_key(
        "proximity", {"from": {"point": far}, "category": {"amenity": "pharmacy"}}, LAYERS
    )
    assert key["walking_nearest"] is None
    assert key["unreachable"] == ["node/500", "node/501"]
    route = module["WalkGraph"](LAYERS).route(module["Point"](*far), module["Point"](*ORIGIN))
    assert route["reachable"] is False and route["reason"] == "too_far_from_network"


def test_proximity_without_candidates_is_an_error() -> None:
    with pytest.raises(module["KeyComputationError"], match="no feature tagged"):
        compute_key(
            "proximity", {"from": {"point": ORIGIN}, "category": {"amenity": "bank"}}, LAYERS
        )


def test_containment_points_inside_and_on_boundaries() -> None:
    key = compute_key(
        "containment",
        {
            "points": [
                {"label": "P1", "point": lonlat(0, 150)},
                {"label": "P2", "point": lonlat(-50, 200)},
                {"label": "P3", "point": lonlat(350, -150)},
            ],
            "features": ["way/410", "way/400"],
        },
        LAYERS,
    )
    assert key["points"]["P1"] == {
        "inside": ["relation/702"],
        "on_boundary": ["relation/700", "relation/701"],
    }
    assert key["points"]["P2"] == {"inside": ["relation/700", "relation/702"], "on_boundary": []}
    assert key["points"]["P3"] == {"inside": ["relation/701"], "on_boundary": []}
    assert key["features"]["way/410"] == {"within": ["relation/700"], "overlaps": [], "touches": []}
    assert key["features"]["way/400"] == {
        "within": ["relation/701"],
        "overlaps": ["relation/702"],
        "touches": [],
    }


def test_unknown_key_type_and_feature_are_errors() -> None:
    with pytest.raises(module["KeyComputationError"], match="unknown key type"):
        compute_key("guess", {}, LAYERS)
    with pytest.raises(module["KeyComputationError"], match="no feature 'way/1'"):
        compute_key("containment", {"features": ["way/1"]}, LAYERS)


def test_a_place_beside_the_middle_of_a_long_street_is_reachable() -> None:
    place = module["Point"](*lonlat(-125, 120))  # 20 m off North Street, 125 m from its vertices
    graph = module["WalkGraph"](LAYERS)
    assert graph.snap(place)[1] < 25
    route = graph.route(place, module["Point"](*lonlat(-250, 140)))
    assert route["reachable"] is True
    key = compute_key(
        "proximity",
        {"from": {"point": lonlat(-125, 120)}, "category": {"amenity": "pharmacy"}},
        LAYERS,
    )
    assert key["walking_nearest"] == "node/500"


def test_adjacency_tells_shared_walls_from_corners() -> None:
    key = compute_key(
        "adjacency", {"features": ["way/410", "way/411", "way/412", "way/413"]}, LAYERS
    )
    relations = {(p["a"], p["b"]): p for p in key["pairs"]}
    assert relations["way/410", "way/411"]["relation"] == "shared_edge"
    assert relations["way/410", "way/411"]["shared_m"] == pytest.approx(20, abs=0.5)
    assert relations["way/411", "way/412"]["relation"] == "corner"
    assert relations["way/410", "way/412"]["relation"] == "disjoint"
    assert relations["way/412", "way/413"]["relation"] == "disjoint"
    assert len(key["pairs"]) == 6


def test_adjacency_needs_two_features() -> None:
    with pytest.raises(module["KeyComputationError"], match="at least two"):
        compute_key("adjacency", {"features": ["way/410"]}, LAYERS)


def test_closing_the_only_bridge_disconnects_the_banks() -> None:
    key = compute_key(
        "closure",
        {"from": {"point": ORIGIN}, "to": {"feature_id": "node/501"}, "closed": ["way/202"]},
        LAYERS,
    )
    assert key["before"]["reachable"] is True
    assert key["before"]["walking_m"] == pytest.approx(880, rel=0.01)
    assert key["after"] == {"reachable": False, "walking_m": None, "reason": "not_connected"}
    assert key["disconnected_by_closure"] is True
    assert key["added_m"] is None


def test_closing_a_side_path_adds_no_distance() -> None:
    key = compute_key(
        "closure",
        {"from": {"point": ORIGIN}, "to": {"feature_id": "node/500"}, "closed": ["way/211"]},
        LAYERS,
    )
    assert key["disconnected_by_closure"] is False
    assert key["added_m"] == 0.0


def test_closure_rejects_features_that_are_not_streets_or_paths() -> None:
    with pytest.raises(module["KeyComputationError"], match="not streets or paths"):
        compute_key(
            "closure",
            {"from": {"point": ORIGIN}, "to": {"feature_id": "node/501"}, "closed": ["way/400"]},
            LAYERS,
        )


def _two_buildings(gap_m: float) -> dict[str, gpd.GeoDataFrame]:
    """A 20 m square at x 0..20 and a second whose west wall sits at x = 20 + gap_m."""
    ring_a = [lonlat(x, y) for x, y in [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]]
    x0 = 20 + gap_m
    ring_b = [lonlat(x, y) for x, y in [(x0, 0), (x0 + 20, 0), (x0 + 20, 20), (x0, 20), (x0, 0)]]
    polygons = [Polygon(ring_a), Polygon(ring_b)]
    frame = gpd.GeoDataFrame(
        {"feature_id": ["way/1", "way/2"], "geometry": polygons}, crs="OGC:CRS84"
    )
    return {"buildings": frame}


@pytest.mark.parametrize(
    ("gap_m", "relation"),
    [(0.04, "shared_edge"), (0.06, "disjoint"), (-0.01, "shared_edge"), (-1.0, "overlap")],
)
def test_adjacency_snap_tolerance_is_symmetric(gap_m: float, relation: str) -> None:
    key = compute_key("adjacency", {"features": ["way/1", "way/2"]}, _two_buildings(gap_m))
    (pair,) = key["pairs"]
    assert pair["relation"] == relation
    if relation == "shared_edge":
        assert pair["shared_m"] == pytest.approx(20, abs=0.5)


def test_visibility_uses_heights_and_flags_unknown_ones() -> None:
    key = compute_key(
        "visibility",
        {
            "observer": {"point": VIEWPOINT, "height_m": 1.6},
            "targets": ["way/400", "way/403", "way/405"],
        },
        LAYERS,
    )
    assert key["observer_height_m"] == 1.6
    tower, school, library = (key["targets"][t] for t in ("way/400", "way/403", "way/405"))
    assert tower["visible"] is True and tower["blocked_by"] == []
    assert tower["distance_m"] == pytest.approx(150, rel=0.01)
    assert school["visible"] is False and school["blocked_by"] == ["way/402"]
    assert library["visible"] is None
    assert library["unknown_height_on_path"] == ["way/404"]
    assert library["target_height_m"] == 12.0


def test_visibility_from_a_roof() -> None:
    key = compute_key(
        "visibility",
        {"observer": {"feature_id": "way/402", "height_m": 1.6}, "targets": ["way/403"]},
        LAYERS,
    )
    assert key["observer_height_m"] == 26.6
    assert key["targets"]["way/403"]["visible"] is True


def test_directions_give_turns_landmarks_and_a_misleading_bearing() -> None:
    key = compute_key(
        "direction", {"from": {"point": ORIGIN}, "to": {"feature_id": "node/501"}}, LAYERS
    )
    assert key["bearing_deg"] == 180.0
    assert key["compass"] == "S"
    assert key["walking_m"] == pytest.approx(880, rel=0.01)
    steps = [(s["street"], s["turn"]) for s in key["steps"]]
    assert steps == [
        (None, "start"),
        ("North Street", "right"),
        ("Bridge Road", "right"),
        ("South Street", "right"),
        (None, "right"),
    ]
    assert [round(s["distance_m"] / 10) * 10 for s in key["steps"]] == [40, 300, 200, 300, 40]
    landmarks = [s["landmark"] and s["landmark"]["feature_id"] for s in key["steps"]]
    assert landmarks == [None, None, "node/502", None, "node/504"]


def test_directions_without_a_route_say_why() -> None:
    key = compute_key(
        "direction", {"from": {"point": lonlat(0, 1000)}, "to": {"feature_id": "node/501"}}, LAYERS
    )
    assert key["reachable"] is False
    assert key["reason"] == "too_far_from_network"
    assert key["steps"] == []


def _frame(rows: list[dict]) -> gpd.GeoDataFrame:
    frame = gpd.GeoDataFrame(rows, crs="OGC:CRS84")
    return frame


def _line_layers(lines: list[tuple[str, str | None, list[tuple[float, float]]]]) -> dict:
    streets = _frame(
        [
            {"feature_id": fid, "name": name, "geometry": LineString([lonlat(*p) for p in pts])}
            for fid, name, pts in lines
        ]
    )
    empty = gpd.GeoDataFrame(
        {"feature_id": [], "name": [], "geometry": []}, geometry="geometry", crs="OGC:CRS84"
    )
    return {"streets": streets, "paths": empty, "pois": empty}


def test_bend_in_a_same_named_street_is_a_turn() -> None:
    layers = _line_layers([("way/1", "Elm", [(0, 0), (100, 0), (100, 100)])])
    key = compute_key(
        "direction", {"from": {"point": lonlat(0, 0)}, "to": {"point": lonlat(100, 100)}}, layers
    )
    assert [(s["street"], s["turn"]) for s in key["steps"]] == [("Elm", "start"), ("Elm", "left")]


def test_turn_between_unnamed_paths_is_a_step() -> None:
    layers = _line_layers(
        [("way/1", None, [(0, 0), (100, 0)]), ("way/2", None, [(100, 0), (100, 100)])]
    )
    key = compute_key(
        "direction", {"from": {"point": lonlat(0, 0)}, "to": {"point": lonlat(100, 100)}}, layers
    )
    assert [(s["street"], s["turn"]) for s in key["steps"]] == [(None, "start"), (None, "left")]


def _sight_layers(heights: dict[str, float | None]) -> dict:
    boxes = {
        "way/1": (0, 0),  # observer
        "way/2": (50, 0),  # blocker
        "way/3": (100, 0),  # target
    }
    rows = [
        {
            "feature_id": fid,
            "name": None,
            "height_m": heights[fid],
            "geometry": Polygon(
                [lonlat(x, -5), lonlat(x + 10, -5), lonlat(x + 10, 5), lonlat(x, 5)]
            ),
        }
        for fid, (x, _) in boxes.items()
        if fid in heights
    ]
    buildings = _frame(rows)
    return {"buildings": buildings, "all_features": buildings}


def _visibility(layers: dict, observer: dict) -> dict:
    return compute_key("visibility", {"observer": observer, "targets": ["way/3"]}, layers)


def test_unknown_target_height_is_undecided_when_blocked() -> None:
    layers = _sight_layers({"way/2": 30.0, "way/3": None})
    target = _visibility(layers, {"point": lonlat(-20, 0), "height_m": 1.6})["targets"]["way/3"]
    assert target["visible"] is None and target["target_height_known"] is False
    assert target["blocked_by"] == ["way/2"]


def test_unknown_target_height_is_visible_when_clear() -> None:
    layers = _sight_layers({"way/3": None})
    target = _visibility(layers, {"point": lonlat(-20, 0), "height_m": 1.6})["targets"]["way/3"]
    assert target["visible"] is True and target["target_height_known"] is False


def test_unknown_observer_building_height_is_flagged() -> None:
    layers = _sight_layers({"way/1": None, "way/2": 30.0, "way/3": 12.0})
    key = _visibility(layers, {"feature_id": "way/1", "height_m": 1.6})
    assert key["observer_height_known"] is False and key["observer_height_m"] == 1.6
    assert key["targets"]["way/3"]["visible"] is None


def _town(
    ways: Sequence[tuple[int, Sequence[tuple[float, float]], dict[str, str]]],
    nodes: Sequence[tuple[int, float, float, dict[str, str]]] = (),
) -> dict[str, gpd.GeoDataFrame]:
    """Layers of a small extract laid out in meters on the synthetic city's grid."""
    elements = [
        {"type": "node", "id": id_, "lon": lonlat(x, y)[0], "lat": lonlat(x, y)[1], "tags": tags}
        for id_, x, y, tags in nodes
    ]
    elements += [
        {
            "type": "way",
            "id": id_,
            "geometry": [{"lon": lonlat(x, y)[0], "lat": lonlat(x, y)[1]} for x, y in points],
            "tags": tags,
        }
        for id_, points, tags in ways
    ]
    return convert_extract({"elements": elements})


def test_a_place_beside_a_fragment_joins_the_connected_street() -> None:
    layers = _town(
        [
            (1, [(-100, 0), (0, 0), (100, 0), (200, 0)], {"highway": "residential"}),
            (2, [(0, 23), (5, 23)], {"highway": "footway"}),  # an unconnected 5 m fragment
        ],
        [(9, 100, 0, {"amenity": "pharmacy", "name": "Street Pharmacy"})],
    )
    key = compute_key(
        "proximity", {"from": {"point": lonlat(0, 20)}, "category": {"amenity": "pharmacy"}}, layers
    )
    assert key["unreachable"] == []
    assert key["walking_nearest"] == "node/9"
    assert key["by_walking"][0]["walking_m"] == pytest.approx(120, rel=0.02)
    route = module["WalkGraph"](layers).route(
        module["Point"](*lonlat(0, 20)), module["Point"](*lonlat(100, 0))
    )
    assert route["snap_from_m"] == pytest.approx(20, abs=0.5)
    assert route["snap_to_m"] == pytest.approx(0, abs=0.5)
    assert all(isinstance(node, tuple) and len(node) == 2 for node in route["nodes"])


def _river_town(with_river: bool) -> dict[str, gpd.GeoDataFrame]:
    """North Street 60 m north of the place, a footway 50 m south; they meet 150 m west."""
    ways: list[tuple[int, Sequence[tuple[float, float]], dict[str, str]]] = [
        (1, [(-150, 90), (0, 90), (100, 90)], {"highway": "residential"}),
        (2, [(-150, -20), (0, -20), (50, -20)], {"highway": "footway"}),
        (3, [(-150, 90), (-150, -20)], {"highway": "residential", "bridge": "yes"}),
    ]
    if with_river:
        ways.append((4, [(-200, 0), (200, 0)], {"waterway": "river", "name": "Mill River"}))
    return _town(ways)


@pytest.mark.parametrize(
    ("with_river", "snap_m", "walking_m"), [(False, 50, 100), (True, 60, 60 + 150 + 110 + 200)]
)
def test_a_place_does_not_snap_across_a_river(
    with_river: bool, snap_m: float, walking_m: float
) -> None:
    graph = module["WalkGraph"](_river_town(with_river))
    place = module["Point"](*lonlat(0, 30))
    assert graph.snap(place)[1] == pytest.approx(50, abs=0.5)  # the footway is nearest
    route = graph.route(place, module["Point"](*lonlat(50, -20)))
    assert route["reachable"] is True
    assert route["snap_from_m"] == pytest.approx(snap_m, abs=0.5)
    assert route["walking_m"] == pytest.approx(walking_m, rel=0.02)


def test_a_place_with_only_barred_vertices_is_blocked() -> None:
    layers = _town(
        [
            (1, [(-50, -20), (50, -20)], {"highway": "footway"}),
            (2, [(-200, 0), (200, 0)], {"railway": "rail", "name": "Main Line"}),
        ]
    )
    graph = module["WalkGraph"](layers)
    route = graph.route(module["Point"](*lonlat(0, 30)), module["Point"](*lonlat(50, -20)))
    assert route["reachable"] is False and route["reason"] == "blocked_by_barrier"


def test_a_water_area_is_a_barrier() -> None:
    lake = [(-200, -10), (200, -10), (200, 10), (-200, 10), (-200, -10)]
    layers = _town(
        [
            (1, [(-50, -20), (50, -20)], {"highway": "footway"}),
            (2, lake, {"natural": "water"}),
        ]
    )
    route = module["WalkGraph"](layers).route(
        module["Point"](*lonlat(0, 30)), module["Point"](*lonlat(50, -20))
    )
    assert route["reason"] == "blocked_by_barrier"
