"""Reference workflow of the ``human_context_access`` benchmark.

``reference_output(case, benchmark_dir)`` computes the expected output of one case from its
``operation`` and ``inputs``; ``geoevals bench regenerate human_context_access`` writes it to
every case's ``expected``.

The walking network is built with ``geoevals.metrics.network`` (networkx Dijkstra) from the
synthetic town in ``fixtures/`` (GeoParquet, read with pyarrow and Shapely), following the
rules in ``docs/metrics.md`` and ``docs/human-context.md``: undirected edges weighted by their
stated ``length_m``, points snapped to the nearest node within 25 m, a walking speed of
1.33 m/s unless the case states ``speed_mps``.

The ``access_baseline`` adapter computes the same answers independently with
``scipy.sparse.csgraph`` and GeoPandas; ``tests/test_human_context.py`` checks that the two
agree on every case within 1e-6 s.

Operations (``inputs.params``):

- ``nearest_amenity``: ``origin`` ``[lon, lat]``, ``category``, optional ``speed_mps``. The
  walking time in seconds to the nearest POI of the category, and its ID in ``ids`` (every
  POI at that time, when several are).
- ``amenity_count``: ``origin``, ``category``, ``minutes``, optional ``speed_mps``. The number
  of POIs of the category within ``minutes`` of walking (inclusive), with their ``ids``.
- ``network_detour``: ``origin``, ``destination``. Network distance between the snapped nodes
  divided by the geodesic distance between the points.
- ``open_amenities``: ``origin``, ``category``, ``minutes``, a local instant (``date``
  ``YYYY-MM-DD``, ``time`` ``HH:MM``, IANA ``timezone``), optional ``public_holidays`` (ISO
  dates) and ``speed_mps``. Of the POIs of the category within ``minutes`` of walking, the
  number open at the instant according to their ``opening_hours`` (``geoevals.opening_hours``),
  their ``ids``, and the POIs whose hours are missing or cannot be parsed in ``unknown_ids``.
  When every POI within reach has unknown hours, the data cannot answer: ``insufficient_data``.
- ``abstention``: a request to ``params.operation`` that should not be answered.
"""

import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import shapely

from geoevals import opening_hours
from geoevals.metrics import network


class Abstain(Exception):
    """The request cannot be answered; ``reference_output`` returns ``{"status": status}``.

    - ``needs_clarification``: the request leaves out a choice that changes the answer (the
      amenity category, the time threshold).
    - ``insufficient_data``: the request is clear, but the town data cannot answer it (a point
      that is not on the network, a category with no POIs, no path).
    - ``invalid_request``: the request is impossible or contradicts itself (a threshold or
      speed that is not positive, a detour between coincident points).
    """

    def __init__(self, status: str, why: str) -> None:
        super().__init__(why)
        self.status = status


def _read(path: Path) -> list[dict[str, Any]]:
    """The rows of a GeoParquet file, with the geometry decoded from WKB."""
    rows = pq.read_table(path).to_pylist()
    for row in rows:
        row["geometry"] = shapely.from_wkb(row["geometry"])
    return rows


def _town(inputs: Mapping[str, Any], benchmark_dir: Path) -> tuple[Any, list[dict[str, Any]]]:
    files = inputs["files"]
    nodes = {
        row["node_id"]: (row["geometry"].x, row["geometry"].y)
        for row in _read(benchmark_dir / files["nodes"])
    }
    graph = network.build_walk_graph(nodes, _read(benchmark_dir / files["edges"]))
    return graph, _read(benchmark_dir / files["pois"])


def _point(params: Mapping[str, Any], name: str) -> network.Coordinate:
    value = params.get(name)
    if value is None:
        raise Abstain("needs_clarification", f"no {name}")
    lon, lat = value
    return float(lon), float(lat)


def _positive(params: Mapping[str, Any], name: str, default: float | None = None) -> float:
    value = params.get(name, default)
    if value is None:
        raise Abstain("needs_clarification", f"no {name}")
    number = isinstance(value, int | float) and not isinstance(value, bool)
    if not (number and math.isfinite(value) and value > 0):
        raise Abstain("invalid_request", f"{name} must be a positive number, got {value!r}")
    return float(value)


def _snap(graph: Any, point: network.Coordinate) -> Any:
    node = network.snap_point(graph, point)
    if node is None:
        raise Abstain("insufficient_data", f"{point} is not on the network")
    return node


def _destinations(graph: Any, pois: list[dict[str, Any]], params: Mapping[str, Any]) -> dict:
    """POI ID -> snapped node, for the POIs of ``params.category`` that snap."""
    category = params.get("category")
    if category is None:
        raise Abstain("needs_clarification", "no amenity category")
    of_category = [poi for poi in pois if poi["amenity_category"] == category]
    if not of_category:
        raise Abstain("insufficient_data", f"no POIs of category {category!r}")
    destinations = {}
    for poi in of_category:
        node = network.snap_point(graph, (poi["geometry"].x, poi["geometry"].y))
        if node is not None:
            destinations[poi["poi_id"]] = node
    return destinations


def nearest_amenity(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    params = inputs["params"]
    speed = _positive(params, "speed_mps", network.DEFAULT_WALK_SPEED_MPS)
    graph, pois = _town(inputs, benchmark_dir)
    destinations = _destinations(graph, pois, params)
    origin = _snap(graph, _point(params, "origin"))
    times = {}
    for poi_id, node in destinations.items():
        seconds = network.shortest_path_time_s(graph, origin, node, speed)
        if seconds is not None:
            times[poi_id] = seconds
    if not times:
        raise Abstain("insufficient_data", "no POI of the category is reachable")
    best = min(times.values())
    ids = sorted(poi_id for poi_id, seconds in times.items() if seconds == best)
    return {"status": "ok", "value": best, "units": "s", "ids": ids}


def amenity_count(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    params = inputs["params"]
    minutes = _positive(params, "minutes")
    speed = _positive(params, "speed_mps", network.DEFAULT_WALK_SPEED_MPS)
    graph, pois = _town(inputs, benchmark_dir)
    destinations = _destinations(graph, pois, params)
    origin = _snap(graph, _point(params, "origin"))
    ids = sorted(network.reachable_within(graph, origin, destinations, minutes, speed))
    return {"status": "ok", "value": len(ids), "units": "count", "ids": ids}


def network_detour(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    params = inputs["params"]
    origin, destination = _point(params, "origin"), _point(params, "destination")
    if network.geodesic_m(origin, destination) == 0:
        raise Abstain("invalid_request", "origin and destination coincide")
    graph, _ = _town(inputs, benchmark_dir)
    origin_node, destination_node = _snap(graph, origin), _snap(graph, destination)
    if not network.connected(graph, origin_node, destination_node):
        raise Abstain("insufficient_data", "no path connects origin and destination")
    stretch = network.route_stretch(graph, origin, destination)
    assert stretch is not None
    return {"status": "ok", "value": stretch, "units": "ratio"}


def _instant(params: Mapping[str, Any]) -> tuple[Any, frozenset[Any]]:
    """The case's local instant and public holidays."""
    for name in ("date", "time", "timezone"):
        if params.get(name) is None:
            raise Abstain("needs_clarification", f"no {name}")
    try:
        when = opening_hours.local_instant(params["date"], params["time"], params["timezone"])
        holidays = opening_hours.holiday_dates(params.get("public_holidays", []))
    except ValueError as error:
        raise Abstain("invalid_request", str(error)) from error
    return when, holidays


def open_amenities(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    params = inputs["params"]
    minutes = _positive(params, "minutes")
    speed = _positive(params, "speed_mps", network.DEFAULT_WALK_SPEED_MPS)
    when, holidays = _instant(params)
    graph, pois = _town(inputs, benchmark_dir)
    destinations = _destinations(graph, pois, params)
    origin = _snap(graph, _point(params, "origin"))
    reachable = network.reachable_within(graph, origin, destinations, minutes, speed)
    hours = {poi["poi_id"]: poi["opening_hours"] for poi in pois}
    states = {
        poi_id: opening_hours.open_state(hours[poi_id], when, holidays) for poi_id in reachable
    }
    if states and all(state is None for state in states.values()):
        raise Abstain("insufficient_data", "every POI within reach has unknown opening hours")
    ids = sorted(poi_id for poi_id, state in states.items() if state is True)
    unknown = sorted(poi_id for poi_id, state in states.items() if state is None)
    return {"status": "ok", "value": len(ids), "units": "count", "ids": ids, "unknown_ids": unknown}


def abstention(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """A request to the operation ``params.operation`` (with the other params) that should not
    be answered. The operation itself raises ``Abstain``; this only dispatches."""
    params = dict(inputs["params"])
    operation = params.pop("operation")
    return OPERATIONS[operation]({"files": inputs["files"], "params": params}, benchmark_dir)


OPERATIONS: dict[str, Callable[[Mapping[str, Any], Path], dict[str, Any]]] = {
    "nearest_amenity": nearest_amenity,
    "amenity_count": amenity_count,
    "network_detour": network_detour,
    "open_amenities": open_amenities,
    "abstention": abstention,
}


def reference_output(case: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """The expected output of ``case`` (a case line without ``expected``)."""
    try:
        return OPERATIONS[case["operation"]](case["inputs"], benchmark_dir)
    except Abstain as abstain:
        return {"status": abstain.status}
