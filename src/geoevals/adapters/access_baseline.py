"""Deterministic access baseline: answers ``human_context_access`` cases with
``scipy.sparse.csgraph`` shortest paths on the walking network.

It is written independently of the benchmark's reference workflow (networkx, via
``geoevals.metrics.network``) but follows the same rules (``docs/metrics.md``): undirected
edges weighted by their stated ``length_m`` (the shortest of parallel edges, no self-loops),
points snapped to the nearest node by WGS 84 geodesic distance within ``SNAP_TOL_M`` (ties go
to the first node in the file), and a walking speed of ``WALK_SPEED_MPS`` unless the case
states ``speed_mps``.

``predict`` dispatches on the case's ``operation`` (``OPERATIONS``); the case ``inputs`` hold
``files`` (``nodes``, ``edges``, ``pois``: GeoParquet paths relative to the benchmark
directory) and ``params``. A request that should not be answered raises ``Abstain`` inside the
operation, and ``predict`` answers ``{"status": <status>}``.

Requires the optional extra ``geoevals[network]`` (scipy). The adapter takes no config, makes
no paid calls (``deterministic = True``) and keeps no state between cases.
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Geod

from geoevals.adapters.base import AdapterResponse

WALK_SPEED_MPS = 1.33
SNAP_TOL_M = 25.0

_GEOD = Geod(ellps="WGS84")

Operation = Callable[[Mapping[str, Any], Path], dict[str, Any]]


class UnsupportedAccessOperation(ValueError):
    """The case's ``operation`` has no implementation in the baseline."""


class Abstain(Exception):
    """The request cannot be answered: ``needs_clarification`` (a category or threshold is
    missing), ``insufficient_data`` (the town data cannot answer it) or ``invalid_request``
    (it is impossible or contradicts itself)."""

    def __init__(self, status: str, why: str) -> None:
        super().__init__(why)
        self.status = status


@dataclass(frozen=True)
class _Network:
    lon: np.ndarray
    lat: np.ndarray
    matrix: Any
    """Symmetric ``scipy.sparse.csr_matrix`` of edge lengths in meters."""

    def snap(self, point: tuple[float, float]) -> int:
        """Index of the nearest node within ``SNAP_TOL_M``; raises ``Abstain`` otherwise."""
        count = len(self.lon)
        _, _, distances = _GEOD.inv(
            np.full(count, point[0]), np.full(count, point[1]), self.lon, self.lat
        )
        index = int(np.argmin(distances))
        if distances[index] > SNAP_TOL_M:
            raise Abstain("insufficient_data", f"{point} is not on the network")
        return index

    def distances_from(self, index: int) -> np.ndarray:
        """Shortest-path length in meters from node ``index`` to every node (inf: no path)."""
        from scipy.sparse.csgraph import shortest_path

        return shortest_path(self.matrix, method="D", directed=False, indices=index)


def _network(inputs: Mapping[str, Any], base: Path) -> tuple[_Network, Any]:
    # Imported here: geopandas and scipy are slow to import, and the adapters package is
    # imported by every CLI command and runner worker.
    import geopandas
    from scipy.sparse import csr_matrix

    files = inputs["files"]
    nodes = geopandas.read_parquet(base / files["nodes"])
    edges = geopandas.read_parquet(base / files["edges"])
    pois = geopandas.read_parquet(base / files["pois"])
    index = {int(node_id): i for i, node_id in enumerate(nodes["node_id"])}
    lengths: dict[tuple[int, int], float] = {}
    for u, v, length in zip(edges["u"], edges["v"], edges["length_m"], strict=True):
        a, b = sorted((index[int(u)], index[int(v)]))
        if a != b:
            lengths[a, b] = min(float(length), lengths.get((a, b), math.inf))
    pairs = list(lengths)
    rows = [a for a, _ in pairs] + [b for _, b in pairs]
    cols = [b for _, b in pairs] + [a for a, _ in pairs]
    data = list(lengths.values()) * 2
    count = len(nodes)
    matrix = csr_matrix((data, (rows, cols)), shape=(count, count))
    net = _Network(nodes.geometry.x.to_numpy(), nodes.geometry.y.to_numpy(), matrix)
    return net, pois


def _point(params: Mapping[str, Any], name: str) -> tuple[float, float]:
    if params.get(name) is None:
        raise Abstain("needs_clarification", f"no {name}")
    lon, lat = params[name]
    return float(lon), float(lat)


def _positive(params: Mapping[str, Any], name: str, default: float | None = None) -> float:
    value = params.get(name, default)
    if value is None:
        raise Abstain("needs_clarification", f"no {name}")
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise Abstain("invalid_request", f"{name} must be a positive number")
    if not math.isfinite(value):
        raise Abstain("invalid_request", f"{name} must be finite")
    return float(value)


def _times(inputs: Mapping[str, Any], base: Path, speed: float) -> dict[str, float]:
    """POI ID -> walking time in seconds from the origin, for the reachable POIs of
    ``params.category``."""
    params = inputs["params"]
    category = params.get("category")
    if category is None:
        raise Abstain("needs_clarification", "no amenity category")
    net, pois = _network(inputs, base)
    of_category = pois[pois["amenity_category"] == category]
    if of_category.empty:
        raise Abstain("insufficient_data", f"no POIs of category {category!r}")
    destinations = {}
    for poi_id, geometry in zip(of_category["poi_id"], of_category.geometry, strict=True):
        try:
            destinations[str(poi_id)] = net.snap((geometry.x, geometry.y))
        except Abstain:
            continue
    distances = net.distances_from(net.snap(_point(params, "origin")))
    return {
        poi_id: float(distances[node]) / speed
        for poi_id, node in destinations.items()
        if math.isfinite(distances[node])
    }


def nearest_amenity(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Walking time in seconds to the nearest POI of ``category``, with its ID."""
    speed = _positive(inputs["params"], "speed_mps", WALK_SPEED_MPS)
    times = _times(inputs, base, speed)
    if not times:
        raise Abstain("insufficient_data", "no POI of the category is reachable")
    best = min(times.values())
    ids = sorted(poi_id for poi_id, seconds in times.items() if seconds == best)
    return {"status": "ok", "value": best, "units": "s", "ids": ids}


def amenity_count(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Number (and IDs) of POIs of ``category`` within ``minutes`` of walking, inclusive."""
    params = inputs["params"]
    limit_s = _positive(params, "minutes") * 60
    speed = _positive(params, "speed_mps", WALK_SPEED_MPS)
    times = _times(inputs, base, speed)
    ids = sorted(poi_id for poi_id, seconds in times.items() if seconds <= limit_s)
    return {"status": "ok", "value": len(ids), "units": "count", "ids": ids}


def network_detour(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Network distance between the snapped nodes / geodesic distance between the points."""
    params = inputs["params"]
    origin, destination = _point(params, "origin"), _point(params, "destination")
    _, _, straight = _GEOD.inv(origin[0], origin[1], destination[0], destination[1])
    if straight == 0:
        raise Abstain("invalid_request", "origin and destination coincide")
    net, _ = _network(inputs, base)
    a, b = net.snap(origin), net.snap(destination)
    length = float(net.distances_from(a)[b])
    if not math.isfinite(length):
        raise Abstain("insufficient_data", "no path connects origin and destination")
    return {"status": "ok", "value": length / float(straight), "units": "ratio"}


def abstention(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Run ``params.operation`` with the other params; the operation raises ``Abstain``."""
    params = dict(inputs["params"])
    operation = params.pop("operation")
    return OPERATIONS[operation]({"files": inputs["files"], "params": params}, base)


OPERATIONS: dict[str, Operation] = {
    "nearest_amenity": nearest_amenity,
    "amenity_count": amenity_count,
    "network_detour": network_detour,
    "abstention": abstention,
}
"""Operation name (the case ``operation``) -> its implementation."""


class AccessBaselineAdapter:
    """Answers every ``human_context_access`` operation deterministically."""

    name = "access_baseline"
    version = "0.1.0"
    deterministic = True

    def setup(self, config: Mapping[str, Any]) -> None:
        if config:
            raise ValueError(f"access_baseline takes no config, got keys {sorted(config)}")

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        operation = case_input.get("operation")
        handler = OPERATIONS.get(operation) if isinstance(operation, str) else None
        if handler is None:
            known = ", ".join(sorted(OPERATIONS))
            raise UnsupportedAccessOperation(
                f"unsupported operation {operation!r} (supported: {known})"
            )
        base = Path(case_input.get("benchmark_dir", "."))
        try:
            return AdapterResponse(output=handler(case_input["inputs"], base))
        except Abstain as abstain:
            return AdapterResponse(output={"status": abstain.status})

    def teardown(self) -> None:
        pass
