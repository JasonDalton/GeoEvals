"""Tests for the walking-network computations and the network access metrics.

The hand-built graph has six nodes on and near the equator (lon, lat in degrees):

    D(0, 0.001) --100-- E(0.001, 0.001)
    |                   |  \\
    150                 120  300
    |                   |      \\
    A(0, 0) ----100---- B(0.001, 0) --100-- C(0.002, 0)        F(0.01, 0.01), isolated

Edge lengths are stated in meters. E-B is tagged one-way from E to B, which walking ignores.
A second A-B edge of 500 m and a self-loop at F must not change any path.
"""

import math

import pytest

from geoevals.metrics import get_metric, registered_metric_ids
from geoevals.metrics.network import (
    DEFAULT_SNAP_TOL_M,
    DEFAULT_WALK_SPEED_MPS,
    WEIGHT,
    build_walk_graph,
    component_count,
    connected,
    geodesic_m,
    reachable_count,
    reachable_within,
    route_stretch,
    shortest_path_m,
    shortest_path_time_s,
    snap_point,
    travel_time_s,
)

NODES = {
    "A": (0.0, 0.0),
    "B": (0.001, 0.0),
    "C": (0.002, 0.0),
    "D": (0.0, 0.001),
    "E": (0.001, 0.001),
    "F": (0.01, 0.01),
}
EDGES = [
    {"u": "A", "v": "B", "length_m": 100},
    {"u": "B", "v": "C", "length_m": 100},
    {"u": "A", "v": "D", "length_m": 150},
    {"u": "D", "v": "E", "length_m": 100},
    {"u": "E", "v": "B", "length_m": 120, "oneway": True},
    {"u": "C", "v": "E", "length_m": 300},
    {"u": "A", "v": "B", "length_m": 500},
    {"u": "F", "v": "F", "length_m": 10},
]
POIS = {"p_a": "A", "p_b": "B", "p_b2": "B", "p_c": "C", "p_d": "D", "p_e": "E", "p_f": "F"}

# On the equator the WGS 84 geodesic is an arc of the equator: semi-major axis x longitude.
EQUATOR_M_PER_DEGREE = 6378137 * math.pi / 180


@pytest.fixture
def graph():
    return build_walk_graph(NODES, EDGES)


# Graph construction


def test_graph_is_undirected_and_keeps_the_shortest_parallel_edge(graph):
    assert graph.number_of_nodes() == 6
    assert graph.number_of_edges() == 6
    assert graph.edges["A", "B"][WEIGHT] == 100.0
    assert graph.edges["B", "E"][WEIGHT] == 120.0
    assert not graph.has_edge("F", "F")


def test_edge_length_defaults_to_the_geodesic_distance():
    graph = build_walk_graph({"a": (0.0, 0.0), "b": (0.001, 0.0)}, [{"u": "a", "v": "b"}])
    assert graph.edges["a", "b"][WEIGHT] == pytest.approx(0.001 * EQUATOR_M_PER_DEGREE, rel=1e-12)


@pytest.mark.parametrize(
    "edge",
    [{"u": "A", "v": "Z", "length_m": 1}, {"u": "A", "v": "B", "length_m": -1}],
)
def test_bad_edges_are_rejected(edge):
    with pytest.raises(ValueError):
        build_walk_graph(NODES, [edge])


# Shortest paths


@pytest.mark.parametrize(
    ("origin", "destination", "expected_m"),
    [
        ("A", "A", 0.0),
        ("A", "B", 100.0),
        ("A", "C", 200.0),
        ("A", "E", 220.0),  # A-B-E, against the one-way tag
        ("D", "C", 320.0),  # D-E-B-C, with the one-way tag
        ("C", "D", 320.0),
        ("A", "F", None),
    ],
)
def test_shortest_path_m(graph, origin, destination, expected_m):
    assert shortest_path_m(graph, origin, destination) == expected_m


def test_travel_time(graph):
    assert DEFAULT_WALK_SPEED_MPS == 1.33
    assert shortest_path_time_s(graph, "A", "E") == 220.0 / 1.33
    assert shortest_path_time_s(graph, "A", "E", speed_mps=2.0) == 110.0
    assert shortest_path_time_s(graph, "D", "C", speed_mps=1.0) == 320.0
    assert shortest_path_time_s(graph, "A", "F") is None
    with pytest.raises(ValueError):
        travel_time_s(100.0, 0.0)


# Reachability


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, {"p_a"}),
        (2, {"p_a", "p_b", "p_b2"}),  # 120 s: A 0 s, B 100 s
        (2.5, {"p_a", "p_b", "p_b2", "p_d"}),  # D at exactly 150 s is inside
        (4, {"p_a", "p_b", "p_b2", "p_c", "p_d", "p_e"}),  # C 200 s, E 220 s; F never
    ],
)
def test_reachable_within(graph, minutes, expected):
    assert reachable_within(graph, "A", POIS, minutes, speed_mps=1.0) == expected
    assert reachable_count(graph, "A", POIS, minutes, speed_mps=1.0) == len(expected)


def test_reachable_at_the_default_speed(graph):
    # 2.5 min = 150 s covers 199.5 m: A, B and D (150 m), not C (200 m).
    assert reachable_within(graph, "A", POIS, 2.5) == {"p_a", "p_b", "p_b2", "p_d"}


# Snapping and route stretch


def test_snap_point(graph):
    assert DEFAULT_SNAP_TOL_M == 25.0
    near_a = (0.0001, 0.0)  # 11.13 m east of A
    assert snap_point(graph, near_a) == "A"
    assert snap_point(graph, near_a, snap_tol_m=11.0) is None
    halfway = (0.0005, 0.0)  # 55.66 m from both A and B
    assert snap_point(graph, halfway) is None
    assert snap_point(graph, halfway, snap_tol_m=60.0) == "A"  # tie: first node added


def test_route_stretch(graph):
    straight = 0.002 * EQUATOR_M_PER_DEGREE
    assert geodesic_m(NODES["A"], NODES["C"]) == pytest.approx(straight, rel=1e-12)
    assert route_stretch(graph, NODES["A"], NODES["C"]) == pytest.approx(200 / straight, rel=1e-12)
    # The network distance uses the snapped nodes, the straight line the original points.
    near_a = (0.0001, 0.0)
    assert route_stretch(graph, near_a, NODES["C"]) == pytest.approx(
        200 / (0.0019 * EQUATOR_M_PER_DEGREE), rel=1e-12
    )
    assert route_stretch(graph, NODES["A"], NODES["F"]) is None  # no path
    assert route_stretch(graph, NODES["A"], (0.0005, 0.0)) is None  # does not snap
    assert route_stretch(graph, NODES["A"], NODES["A"]) is None  # coincident points


def test_connectivity(graph):
    assert component_count(graph) == 2
    assert connected(graph, "A", "E")
    assert not connected(graph, "A", "F")


# Metrics


def test_access_metrics_are_registered():
    ids = {
        "travel_time_abs_error_s",
        "reachable_count_error",
        "reachable_set_jaccard",
        "route_stretch_abs_error",
    }
    assert ids <= registered_metric_ids()
    assert get_metric("travel_time_abs_error_s").units == "s"
    assert get_metric("reachable_set_jaccard").higher_is_better is True


def answer(value, units, **fields):
    return {"status": "ok", "value": value, "units": units, **fields}


def test_travel_time_abs_error_s():
    metric = get_metric("travel_time_abs_error_s")
    reference = answer(220.0, "s")
    result = metric.score(answer(230.0, "s"), reference, {"time_tol_s": 10.0})
    assert (result.value, result.passed) == (10.0, True)
    assert result.detail == {"signed_error": 10.0}
    result = metric.score(answer(210.0, "s"), reference, {"time_tol_s": 5.0})
    assert (result.value, result.passed) == (10.0, False)
    assert result.detail["signed_error"] == -10.0
    result = metric.score(answer(220.0, "min"), reference, {})
    assert (result.value, result.passed, result.detail["reason"]) == (None, False, "units_mismatch")
    result = metric.score({"status": "insufficient_data"}, reference, {})
    assert (result.value, result.passed, result.detail["reason"]) == (None, False, "missing_value")
    for not_time in (answer(3, "count"), {"status": "insufficient_data"}):
        assert metric.score(answer(3, "count"), not_time, {}).detail == {"applicable": False}


def test_reachable_count_error():
    metric = get_metric("reachable_count_error")
    reference = answer(6, "count")
    assert metric.score(answer(6, "count"), reference, {}).value == 0.0
    result = metric.score(answer(4, "count"), reference, {})
    assert (result.value, result.passed, result.detail["signed_error"]) == (2.0, False, -2.0)
    assert metric.score(answer(5, "count"), reference, {"count_tol": 1}).passed is True
    assert metric.score(answer(6, "count"), answer(220.0, "s"), {}).passed is None


def test_route_stretch_abs_error():
    metric = get_metric("route_stretch_abs_error")
    result = metric.score(answer(1.25, "ratio"), answer(1.5, "ratio"), {"stretch_tol": 0.25})
    assert (result.value, result.passed) == (0.25, True)
    assert metric.score(answer(1.25, "ratio"), answer(1.5, "ratio"), {}).passed is False


def test_reachable_set_jaccard():
    metric = get_metric("reachable_set_jaccard")
    reference = answer(4, "count", ids=["p_a", "p_b", "p_b2", "p_d"])
    exact = metric.score(answer(4, "count", ids=["p_d", "p_b2", "p_b", "p_a"]), reference, {})
    assert (exact.value, exact.passed, exact.detail) == (1.0, True, {})
    # 3 shared of 5 distinct IDs.
    partial = metric.score(answer(4, "count", ids=["p_a", "p_b", "p_d", "p_c"]), reference, {})
    assert (partial.value, partial.passed) == (0.6, False)
    assert partial.detail == {"missing": ["p_b2"], "extra": ["p_c"], "min_jaccard": 1.0}
    assert (
        metric.score(
            answer(4, "count", ids=["p_a", "p_b", "p_d", "p_c"]), reference, {"min_jaccard": 0.6}
        ).passed
        is True
    )
    empty = metric.score(answer(0, "count", ids=[]), answer(0, "count", ids=[]), {})
    assert (empty.value, empty.passed) == (1.0, True)
    missing = metric.score(answer(4, "count"), reference, {})
    assert (missing.value, missing.passed, missing.detail["reason"]) == (None, False, "missing_ids")
    assert metric.score(answer(4, "count", ids=[True]), reference, {}).passed is False
    assert metric.score(answer(4, "count"), answer(4, "count"), {}).passed is None


def test_metrics_score_answers_on_the_hand_built_graph(graph):
    """An answer that respects the one-way tag (A-D-E, 250 m, instead of A-B-E, 220 m) is
    caught by every metric."""
    speed = 1.0
    reference_ids = sorted(reachable_within(graph, "A", POIS, 3.75, speed_mps=speed))
    assert reference_ids == ["p_a", "p_b", "p_b2", "p_c", "p_d", "p_e"]  # 225 s; E at 220 s
    reference_time = answer(shortest_path_time_s(graph, "A", "E", speed_mps=speed), "s")
    wrong_time = answer(250.0, "s")
    result = get_metric("travel_time_abs_error_s").score(wrong_time, reference_time, {})
    assert (result.value, result.passed) == (30.0, False)

    reference_set = answer(len(reference_ids), "count", ids=reference_ids)
    wrong_set = answer(5, "count", ids=["p_a", "p_b", "p_b2", "p_c", "p_d"])
    count = get_metric("reachable_count_error").score(wrong_set, reference_set, {})
    assert (count.value, count.passed) == (1.0, False)
    jaccard = get_metric("reachable_set_jaccard").score(wrong_set, reference_set, {})
    assert (jaccard.value, jaccard.passed, jaccard.detail["missing"]) == (5 / 6, False, ["p_e"])

    stretch = route_stretch(graph, NODES["A"], NODES["E"])
    assert stretch is not None
    straight = geodesic_m(NODES["A"], NODES["E"])
    result = get_metric("route_stretch_abs_error").score(
        answer(250 / straight, "ratio"), answer(stretch, "ratio"), {}
    )
    assert result.value == pytest.approx(30 / straight, rel=1e-12)
    assert result.passed is False
