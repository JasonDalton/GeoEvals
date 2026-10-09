"""Walking-network computations for the human-context pillar, built on ``networkx``.

Requires the optional extra ``geoevals[network]``. The scoring metrics that compare answers
(``geoevals.metrics.access``) do not need it; reference workflows and baselines that compute
answers on a network do.

Graph construction rules (also in ``docs/metrics.md``):

- Nodes have WGS 84 longitude/latitude coordinates (``OGC:CRS84``, x = longitude).
- Edges are undirected. A one-way tag is ignored, because walking is allowed both ways.
- The edge weight ``length_m`` is in meters: the edge's stated length, or else the geodesic
  distance between its end nodes on the WGS 84 ellipsoid. Parallel edges keep the shortest
  length; self-loops are dropped (they never shorten a path).
- A point snaps to the nearest node by geodesic distance when that distance is at most
  ``snap_tol_m`` (inclusive, default ``DEFAULT_SNAP_TOL_M``); otherwise it is not on the
  network.
- Travel time is the shortest-path length divided by the walking speed in m/s (default
  ``DEFAULT_WALK_SPEED_MPS``).
"""

from collections.abc import Hashable, Iterable, Mapping
from typing import Any, TypeVar

import networkx as nx
from pyproj import Geod

DEFAULT_WALK_SPEED_MPS = 1.33
"""Walking speed in meters per second (about 4.8 km/h), as in ``docs/human-context.md``."""

DEFAULT_SNAP_TOL_M = 25.0
"""Largest geodesic distance, in meters, at which a point snaps to a network node."""

WEIGHT = "length_m"
"""Edge attribute holding the edge length in meters."""

_GEOD = Geod(ellps="WGS84")

Coordinate = tuple[float, float]
"""``(longitude, latitude)`` in degrees."""

DestinationId = TypeVar("DestinationId", bound=Hashable)


def geodesic_m(a: Coordinate, b: Coordinate) -> float:
    """Geodesic distance in meters between two lon/lat points on the WGS 84 ellipsoid."""
    _, _, distance = _GEOD.inv(a[0], a[1], b[0], b[1])
    return float(distance)


def build_walk_graph(
    nodes: Mapping[Any, Coordinate], edges: Iterable[Mapping[str, Any]]
) -> nx.Graph:
    """Build the undirected walking graph.

    ``nodes`` maps a node ID to its ``(lon, lat)``. Each edge is a mapping with ``u`` and ``v``
    (node IDs), optional ``length_m`` (meters; default the geodesic distance between the
    nodes) and optional ``oneway``, which is ignored for walking. Node coordinates are stored
    as the node attribute ``xy``. Raises ``ValueError`` for an edge whose node is unknown or
    whose length is negative or not finite.
    """
    graph = nx.Graph()
    for node, (lon, lat) in nodes.items():
        graph.add_node(node, xy=(float(lon), float(lat)))
    for edge in edges:
        u, v = edge["u"], edge["v"]
        for node in (u, v):
            if node not in graph:
                raise ValueError(f"edge {u!r}-{v!r} refers to unknown node {node!r}")
        if u == v:
            continue
        length = edge.get("length_m")
        if length is None:
            length = geodesic_m(graph.nodes[u]["xy"], graph.nodes[v]["xy"])
        length = float(length)
        if not 0 <= length < float("inf"):
            raise ValueError(f"edge {u!r}-{v!r} has invalid length_m {length!r}")
        if not graph.has_edge(u, v) or length < graph.edges[u, v][WEIGHT]:
            graph.add_edge(u, v, **{WEIGHT: length})
    return graph


def snap_point(
    graph: nx.Graph, point: Coordinate, *, snap_tol_m: float = DEFAULT_SNAP_TOL_M
) -> Hashable | None:
    """The nearest node to ``point`` within ``snap_tol_m`` meters, or ``None``.

    Ties go to the node added to the graph first.
    """
    best: tuple[float, Hashable] | None = None
    for node, data in graph.nodes(data=True):
        distance = geodesic_m(point, data["xy"])
        if best is None or distance < best[0]:
            best = (distance, node)
    if best is None or best[0] > snap_tol_m:
        return None
    return best[1]


def shortest_path_m(graph: nx.Graph, origin: Hashable, destination: Hashable) -> float | None:
    """Shortest-path length in meters between two nodes, ``None`` when no path connects them."""
    try:
        return float(nx.dijkstra_path_length(graph, origin, destination, weight=WEIGHT))
    except nx.NetworkXNoPath:
        return None


def travel_time_s(distance_m: float, speed_mps: float = DEFAULT_WALK_SPEED_MPS) -> float:
    """Walking time in seconds for ``distance_m`` meters at ``speed_mps``."""
    if speed_mps <= 0:
        raise ValueError(f"walking speed must be positive, got {speed_mps!r}")
    return distance_m / speed_mps


def shortest_path_time_s(
    graph: nx.Graph,
    origin: Hashable,
    destination: Hashable,
    speed_mps: float = DEFAULT_WALK_SPEED_MPS,
) -> float | None:
    """Walking time in seconds of the shortest path, ``None`` when no path connects the nodes."""
    distance = shortest_path_m(graph, origin, destination)
    return None if distance is None else travel_time_s(distance, speed_mps)


def reachable_within(
    graph: nx.Graph,
    origin: Hashable,
    destinations: Mapping[DestinationId, Hashable],
    minutes: float,
    speed_mps: float = DEFAULT_WALK_SPEED_MPS,
) -> set[DestinationId]:
    """IDs of the destinations whose walking time from ``origin`` is at most ``minutes``.

    ``destinations`` maps a destination ID (a point of interest) to its snapped node. Each
    destination counts once, and destinations that share a node each count. The boundary is
    inclusive: travel time <= ``minutes * 60`` seconds.
    """
    limit_s = minutes * 60
    lengths = nx.single_source_dijkstra_path_length(graph, origin, weight=WEIGHT)
    return {
        destination
        for destination, node in destinations.items()
        if node in lengths and travel_time_s(lengths[node], speed_mps) <= limit_s
    }


def reachable_count(
    graph: nx.Graph,
    origin: Hashable,
    destinations: Mapping[Any, Hashable],
    minutes: float,
    speed_mps: float = DEFAULT_WALK_SPEED_MPS,
) -> int:
    """Number of destinations reachable within ``minutes`` (see ``reachable_within``)."""
    return len(reachable_within(graph, origin, destinations, minutes, speed_mps))


def route_stretch(
    graph: nx.Graph,
    origin: Coordinate,
    destination: Coordinate,
    *,
    snap_tol_m: float = DEFAULT_SNAP_TOL_M,
) -> float | None:
    """Network detour ratio: shortest-path length between the snapped nodes divided by the
    geodesic distance between the original points.

    ``None`` when a point does not snap, no path connects the nodes, or the points coincide.
    """
    origin_node = snap_point(graph, origin, snap_tol_m=snap_tol_m)
    destination_node = snap_point(graph, destination, snap_tol_m=snap_tol_m)
    if origin_node is None or destination_node is None:
        return None
    network = shortest_path_m(graph, origin_node, destination_node)
    straight = geodesic_m(origin, destination)
    if network is None or straight == 0:
        return None
    return network / straight


def component_count(graph: nx.Graph) -> int:
    """Number of connected components (an isolated node is a component)."""
    return nx.number_connected_components(graph)


def connected(graph: nx.Graph, a: Hashable, b: Hashable) -> bool:
    """True when a path connects nodes ``a`` and ``b``."""
    return nx.has_path(graph, a, b)
