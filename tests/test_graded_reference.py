from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

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
