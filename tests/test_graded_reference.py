from pathlib import Path

import pytest

from geoevals.graded.city import convert_extract
from geoevals.graded.reference import load_reference
from geoevals.validation import load_eval_spec
from graded_city import ORIGIN, lonlat, overpass_document

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
