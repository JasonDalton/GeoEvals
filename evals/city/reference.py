"""Reference keys of the graded evals on the city, computed from its layers.

``compute_key(key_type, params, layers)`` returns the key of one task: the facts a correct answer
must agree with. The grader sees the key; the model never does. Keys are computed, never written
by hand (``geoevals evals regenerate``), and are not committed (OpenStreetMap-derived data).

Distances are geodesic meters on WGS 84. Walking distances use the ``streets`` and ``paths``
layers as an undirected graph whose nodes are the lines' shared vertices, densified to
``NETWORK_STEP_M``. A place joins the network by a straight snap leg to one of its nearest
vertices (up to ``MAX_SNAP_CANDIDATES`` within ``MAX_SNAP_M``); a leg that crosses a ``railways``
or ``water`` feature marked ``walk_barrier`` (surface rail, rivers, canals, streams and water
areas; see ``geoevals.graded.city``) is not used, and only the nearest usable vertex of each
connected part of the network is a candidate. The shortest walk picks the best leg at each end,
so a place beside an isolated fragment still joins the connected street behind it. A place with
no vertex within ``MAX_SNAP_M`` is unreachable (``too_far_from_network``), as is one whose every
candidate leg crosses a barrier (``blocked_by_barrier``). Local geometry (shared edges, lines of
sight, distance to a boundary) is measured in an azimuthal equidistant projection centered on the
features involved. Every float in a key is rounded to 0.1 (meters, degrees), so the key and its
hash are the same on every platform.

Key types and their params:

- ``proximity``: ``from`` (a place), ``category`` (one tag, ``{key: value}``), ``top`` (default 3)
- ``containment``: ``points`` (``[{label, point}]``), ``features`` (feature IDs), ``layers``
  (default ``["boundaries"]``), ``boundary_tolerance_m`` (default 1, at most 50)
- ``adjacency``: ``features`` (two or more feature IDs), ``layer`` (default ``buildings``),
  ``edge_min_m`` (default 0.5)
- ``closure``: ``from``, ``to`` (places), ``closed`` (feature IDs of streets or paths)
- ``visibility``: ``observer`` (a place and ``height_m``, the eye height above the ground, or
  above the roof when the place is a building), ``targets`` (building feature IDs)
- ``direction``: ``from``, ``to`` (places), ``landmark_radius_m`` (default 30),
  ``turn_threshold_deg`` (default 30)

A place is ``{"point": [lon, lat]}`` or ``{"feature_id": "way/1"}`` (the feature's
representative point).
"""

import itertools
import json
import math
from collections.abc import Callable, Mapping
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from pyproj import CRS, Geod, Transformer
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

WGS84 = "OGC:CRS84"
GEOD = Geod(ellps="WGS84")
MAX_SNAP_M = 100.0
MAX_SNAP_CANDIDATES = 20
NETWORK_STEP_M = 10.0
NEAR_DEG = 0.001
"""Prefilter: features farther than this (about 70 to 110 m) cannot be within a tolerance."""
NETWORK_LAYERS = ("streets", "paths")
BARRIER_LAYERS = ("railways", "water")
SOURCE, SINK = "source", "sink"
"""The virtual end nodes of a route; network nodes are (lon, lat) tuples."""
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

Layers = Mapping[str, gpd.GeoDataFrame]
Node = tuple[float, float]


class KeyComputationError(ValueError):
    """The params do not describe a computable key (an unknown feature, a bad place)."""


# --- helpers ---------------------------------------------------------------------------------


def _rounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 1) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    return value


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _row(layers: Layers, feature_id: str, layer: str = "all_features") -> Any:
    frame = layers[layer]
    match = frame[frame["feature_id"] == feature_id]
    if match.empty:
        raise KeyComputationError(f"no feature {feature_id!r} in layer {layer!r}")
    return match.iloc[0]


def _place(layers: Layers, place: Mapping[str, Any]) -> Point:
    if "point" in place:
        lon, lat = place["point"]
        return Point(float(lon), float(lat))
    if "feature_id" in place:
        return _row(layers, place["feature_id"]).geometry.representative_point()
    raise KeyComputationError(f"a place needs 'point' or 'feature_id', got {dict(place)!r}")


def _distance_m(a: Point, b: Point) -> float:
    return float(GEOD.inv(a.x, a.y, b.x, b.y)[2])


def _aeqd(center: Point) -> CRS:
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={center.y} +lon_0={center.x} +datum=WGS84 +units=m +no_defs +type=crs"
    )


def _projector(center: Point) -> Callable[[BaseGeometry], BaseGeometry]:
    transformer = Transformer.from_crs(WGS84, _aeqd(center), always_xy=True)

    def project(geometry: BaseGeometry) -> BaseGeometry:
        return shapely.transform(
            geometry, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
        )

    return project


def _lines(geometry: BaseGeometry) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    return []


class WalkGraph:
    """The walking network of the ``streets`` and ``paths`` layers, without ``closed`` features.

    Each edge keeps its geodesic ``length``, its ``feature_id`` and its street ``name``.
    """

    def __init__(self, layers: Layers, closed: frozenset[str] = frozenset()) -> None:
        self.graph = nx.Graph()
        for layer in NETWORK_LAYERS:
            frame = layers[layer]
            for feature_id, name, geometry in zip(
                frame["feature_id"], frame["name"], frame.geometry, strict=True
            ):
                if feature_id in closed:
                    continue
                for line in _lines(geometry):
                    for a, b in itertools.pairwise(line.coords):
                        self._add_segment(a, b, feature_id, _text(name))
        self._nodes: list[Node] = list(self.graph.nodes)
        self._lons = np.array([node[0] for node in self._nodes])
        self._lats = np.array([node[1] for node in self._nodes])
        self._component = {
            node: number
            for number, members in enumerate(nx.connected_components(self.graph))
            for node in members
        }
        barriers = [
            geometry
            for layer in BARRIER_LAYERS
            if layer in layers
            for geometry, barrier in zip(
                layers[layer].geometry, layers[layer]["walk_barrier"], strict=True
            )
            if barrier and geometry is not None and not geometry.is_empty
        ]
        self._barriers = shapely.STRtree(barriers)

    def _add_segment(self, a: Any, b: Any, feature_id: str, name: str | None) -> None:
        """Add the segment a-b, split into pieces of at most ``NETWORK_STEP_M``."""
        total = float(GEOD.inv(a[0], a[1], b[0], b[1])[2])
        if total == 0:
            return
        steps = math.ceil(total / NETWORK_STEP_M)
        inner = GEOD.npts(a[0], a[1], b[0], b[1], steps - 1) if steps > 1 else []
        points: list[Node] = [(a[0], a[1]), *inner, (b[0], b[1])]
        for u, v in itertools.pairwise(points):
            length = float(GEOD.inv(u[0], u[1], v[0], v[1])[2])
            existing = self.graph.get_edge_data(u, v)
            if length > 0 and (existing is None or existing["length"] > length):
                self.graph.add_edge(u, v, length=length, feature_id=feature_id, name=name)

    def _distances(self, point: Point) -> np.ndarray:
        n = len(self._nodes)
        _, _, distances = GEOD.inv(np.full(n, point.x), np.full(n, point.y), self._lons, self._lats)
        return np.asarray(distances)

    def snap(self, point: Point) -> tuple[Node | None, float]:
        """The nearest network vertex and its distance in meters, barriers ignored."""
        if not self._nodes:
            return None, math.inf
        distances = self._distances(point)
        index = int(np.argmin(distances))
        return self._nodes[index], float(distances[index])

    def _crosses_barrier(self, point: Point, node: Node) -> bool:
        """Whether the straight leg from ``point`` to ``node`` crosses a walk barrier."""
        if (point.x, point.y) == node:
            return False
        leg = LineString([(point.x, point.y), node])
        for position in self._barriers.query(leg):
            barrier = self._barriers.geometries[int(position)]
            if barrier.geom_type in ("Polygon", "MultiPolygon"):
                if barrier.relate_pattern(leg, "T********"):  # the leg enters the area
                    return True
            elif leg.relate_pattern(barrier, "T********") or leg.relate_pattern(
                barrier, "*T*******"
            ):  # the leg's interior meets the line
                return True
        return False

    def candidates(self, point: Point) -> tuple[list[tuple[Node, float]], str | None]:
        """The vertices a place can snap to, nearest first, and why there are none.

        At most ``MAX_SNAP_CANDIDATES`` vertices within ``MAX_SNAP_M`` are tried; those whose
        snap leg crosses a barrier are dropped, and of the rest only the nearest vertex of each
        connected part of the network is kept (a straight leg to a farther vertex of the same
        part would cut across the block). The reason is None when a candidate is left, else
        ``too_far_from_network`` or ``blocked_by_barrier``.
        """
        distances = self._distances(point)
        order = sorted(
            (float(d), self._nodes[i]) for i, d in enumerate(distances) if d <= MAX_SNAP_M
        )[:MAX_SNAP_CANDIDATES]
        if not order:
            return [], "too_far_from_network"
        found: dict[int, tuple[Node, float]] = {}
        blocked = True
        for d, node in order:
            component = self._component[node]
            if component in found or self._crosses_barrier(point, node):
                continue
            blocked = False
            found[component] = (node, d)  # the nearest unblocked vertex of each component
        return list(found.values()), "blocked_by_barrier" if blocked else None

    def route(self, start: Point, end: Point) -> dict[str, Any]:
        """The shortest walk from ``start`` to ``end``, snap legs included.

        A virtual source joins every candidate vertex of ``start``, and a virtual sink every
        candidate of ``end``, by edges as long as the snap legs; one shortest path picks the
        best pair. ``snap_from_m`` and ``snap_to_m`` are the legs the walk uses (the nearest
        vertex distances when there is no walk); ``nodes`` is the walk on the network.
        """
        result: dict[str, Any] = {
            "reachable": False,
            "walking_m": None,
            "snap_from_m": None,
            "snap_to_m": None,
            "nodes": [],
        }
        if not self._nodes:
            return {**result, "reason": "no_network"}
        result["snap_from_m"] = self.snap(start)[1]
        result["snap_to_m"] = self.snap(end)[1]
        sources, source_reason = self.candidates(start)
        sinks, sink_reason = self.candidates(end)
        reasons = {source_reason, sink_reason}
        for reason in ("too_far_from_network", "blocked_by_barrier"):
            if reason in reasons:
                return {**result, "reason": reason}
        graph = self.graph  # the virtual ends are removed again below
        graph.add_edges_from((SOURCE, node, {"length": d}) for node, d in sources)
        graph.add_edges_from((node, SINK, {"length": d}) for node, d in sinks)
        try:
            path = nx.shortest_path(graph, SOURCE, SINK, weight="length")
            lengths = [graph.edges[u, v]["length"] for u, v in itertools.pairwise(path)]
        except nx.NetworkXNoPath:
            return {**result, "reason": "not_connected"}
        finally:
            graph.remove_nodes_from((SOURCE, SINK))
        return {
            **result,
            "reachable": True,
            "walking_m": sum(lengths),
            "snap_from_m": lengths[0],
            "snap_to_m": lengths[-1],
            "nodes": path[1:-1],
        }


# --- proximity -------------------------------------------------------------------------------


def _tagged(layers: Layers, category: Mapping[str, str]) -> list[tuple[str, str | None, Point]]:
    if len(category) != 1:
        raise KeyComputationError("category must hold one tag, as {key: value}")
    ((key, value),) = category.items()
    frame = layers["all_features"]
    needle = json.dumps({key: value}, ensure_ascii=False)[1:-1]  # '"amenity": "pharmacy"'
    candidates = frame[frame["tags"].str.contains(needle, regex=False)]
    found = []
    for feature_id, name, tags, geometry in zip(
        candidates["feature_id"],
        candidates["name"],
        candidates["tags"],
        candidates.geometry,
        strict=True,
    ):
        if json.loads(tags).get(key) == value:
            found.append((feature_id, _text(name), geometry.representative_point()))
    return found


def proximity_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    origin = _place(layers, params["from"])
    candidates = _tagged(layers, params["category"])
    if not candidates:
        raise KeyComputationError(f"no feature tagged {dict(params['category'])}")
    top = int(params.get("top", 3))
    graph = WalkGraph(layers)
    rows = []
    for feature_id, name, point in candidates:
        route = graph.route(origin, point)
        rows.append(
            {
                "feature_id": feature_id,
                "name": name,
                "straight_line_m": _distance_m(origin, point),
                "walking_m": route["walking_m"],
            }
        )
    by_line = sorted(rows, key=lambda r: (r["straight_line_m"], r["feature_id"]))
    by_walk = sorted(
        (r for r in rows if r["walking_m"] is not None),
        key=lambda r: (r["walking_m"], r["feature_id"]),
    )
    return {
        "straight_line_nearest": by_line[0]["feature_id"],
        "walking_nearest": by_walk[0]["feature_id"] if by_walk else None,
        "same_nearest": bool(by_walk) and by_walk[0]["feature_id"] == by_line[0]["feature_id"],
        "by_straight_line": by_line[:top],
        "by_walking": by_walk[:top],
        "unreachable": sorted(r["feature_id"] for r in rows if r["walking_m"] is None),
    }


# --- containment -----------------------------------------------------------------------------


def _polygons(layers: Layers, names: list[str]) -> list[tuple[str, BaseGeometry]]:
    found = []
    for name in names:
        frame = layers[name]
        for feature_id, geometry in zip(frame["feature_id"], frame.geometry, strict=True):
            if geometry.geom_type in ("Polygon", "MultiPolygon"):
                found.append((feature_id, geometry))
    return found


def containment_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    tolerance = float(params.get("boundary_tolerance_m", 1.0))
    if tolerance > 50:
        raise KeyComputationError("boundary_tolerance_m must be at most 50")
    polygons = _polygons(layers, list(params.get("layers", ["boundaries"])))
    points: dict[str, Any] = {}
    for entry in params.get("points", []):
        point = Point(*map(float, entry["point"]))
        project = _projector(point)
        local_point = project(point)
        inside, on_boundary = [], []
        for feature_id, polygon in polygons:
            if polygon.distance(point) > NEAR_DEG:
                continue
            local = project(polygon)
            if local.boundary.distance(local_point) <= tolerance:
                on_boundary.append(feature_id)
            elif local.contains(local_point):
                inside.append(feature_id)
        points[entry["label"]] = {"inside": sorted(inside), "on_boundary": sorted(on_boundary)}
    features: dict[str, Any] = {}
    for feature_id in params.get("features", []):
        geometry = _row(layers, feature_id).geometry
        within, overlaps, touches = [], [], []
        for other_id, polygon in polygons:
            if other_id == feature_id or not polygon.intersects(geometry):
                continue
            if polygon.covers(geometry):
                within.append(other_id)
            elif polygon.relate_pattern(geometry, "T********"):
                overlaps.append(other_id)
            else:
                touches.append(other_id)
        features[feature_id] = {
            "within": sorted(within),
            "overlaps": sorted(overlaps),
            "touches": sorted(touches),
        }
    return {"points": points, "features": features}


# --- adjacency -------------------------------------------------------------------------------

SNAP_M = 0.05
"""Walls drawn up to 5 cm apart, or overlapping by up to 5 cm, count as touching."""


def adjacency_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    layer = params.get("layer", "buildings")
    edge_min = float(params.get("edge_min_m", 0.5))
    ids = list(params["features"])
    if len(ids) < 2:
        raise KeyComputationError("adjacency needs at least two features")
    geometries = {feature_id: _row(layers, feature_id, layer).geometry for feature_id in ids}
    project = _projector(shapely.union_all(list(geometries.values())).centroid)
    local = {feature_id: project(geometry) for feature_id, geometry in geometries.items()}
    pairs = []
    for a, b in itertools.combinations(ids, 2):
        ga, gb = local[a], local[b]
        # the buffer adds SNAP_M of boundary at each end of a shared wall
        shared = max(0.0, ga.boundary.intersection(gb.buffer(SNAP_M)).length - 2 * SNAP_M)
        if ga.buffer(-SNAP_M).intersects(gb) or gb.buffer(-SNAP_M).intersects(ga):
            relation = "overlap"
        elif ga.distance(gb) > SNAP_M:
            relation = "disjoint"
        elif shared >= edge_min:
            relation = "shared_edge"
        else:
            relation = "corner"
        pairs.append({"a": a, "b": b, "relation": relation, "shared_m": shared})
    return {"pairs": pairs}


# --- closures --------------------------------------------------------------------------------


def _route_summary(route: Mapping[str, Any]) -> dict[str, Any]:
    summary = {"reachable": route["reachable"], "walking_m": route["walking_m"]}
    if "reason" in route:
        summary["reason"] = route["reason"]
    return summary


def closure_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    start, end = _place(layers, params["from"]), _place(layers, params["to"])
    closed = frozenset(params["closed"])
    network = set(layers["streets"]["feature_id"]) | set(layers["paths"]["feature_id"])
    unknown = sorted(closed - network)
    if unknown:
        raise KeyComputationError(f"closed features are not streets or paths: {unknown}")
    before = WalkGraph(layers).route(start, end)
    after = WalkGraph(layers, closed).route(start, end)
    both = before["reachable"] and after["reachable"]
    return {
        "closed": sorted(closed),
        "before": _route_summary(before),
        "after": _route_summary(after),
        "disconnected_by_closure": before["reachable"] and not after["reachable"],
        "added_m": after["walking_m"] - before["walking_m"] if both else None,
    }


# --- visibility ------------------------------------------------------------------------------


def _height(row: Any) -> float | None:
    value = row["height_m"]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def _coordinates(geometry: BaseGeometry) -> list[tuple[float, ...]]:
    if hasattr(geometry, "geoms"):
        return [c for part in geometry.geoms for c in _coordinates(part)]
    return list(geometry.coords)


def visibility_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    """Lines of sight from an eye point to the top of each target building.

    A building on the line blocks it when its height exceeds the line's height where the line
    crosses it (the lower of the entry and exit heights, as the line is straight). A building of
    unknown height on the line leaves the target undecided (``visible`` null). A target of
    unknown height is sighted at ground level (``target_height_known`` false): a clear line is
    still ``visible`` (a taller target only raises the line), but a blocked one is undecided
    (null), with the blockers still listed. An observer building of unknown height is taken at
    eye height above the ground (``observer_height_known`` false): targets visible from there stay
    visible, targets blocked from there are undecided. A building that contains the observer point
    never blocks (the observer looks out of it).
    """
    observer = params["observer"]
    eye = float(observer.get("height_m", 1.6))
    observer_id = observer.get("feature_id")
    origin = _place(layers, observer)
    observer_height = eye
    observer_known = True
    if observer_id is not None:
        roof = _height(_row(layers, observer_id, "buildings"))
        observer_known = roof is not None
        observer_height += roof or 0.0
    project = _projector(origin)
    buildings = layers["buildings"].to_crs(_aeqd(origin))
    index = buildings.sindex
    eye_point = project(origin)
    # an observer standing in a building looks out of it: that building never blocks
    around = {
        buildings.iloc[int(position)]["feature_id"]
        for position in index.query(eye_point, predicate="within")
    }
    targets: dict[str, Any] = {}
    for target_id in params["targets"]:
        target = _row(layers, target_id, "buildings")
        target_height = _height(target)
        top = target_height if target_height is not None else 0.0
        sight = LineString([eye_point, project(target.geometry.representative_point())])
        length = sight.length
        blocked, unknown = [], []
        for position in index.query(sight, predicate="intersects"):
            other = buildings.iloc[int(position)]
            if other["feature_id"] in (target_id, observer_id) or other["feature_id"] in around:
                continue
            crossing = other.geometry.intersection(sight)
            if crossing.is_empty:
                continue
            along = [sight.project(Point(c[0], c[1])) for c in _coordinates(crossing)]
            lowest = min(
                observer_height + (top - observer_height) * d / length
                for d in (min(along), max(along))
            )
            height = _height(other)
            if height is None:
                unknown.append(other["feature_id"])
            elif height > lowest:
                blocked.append(other["feature_id"])
        if unknown:
            visible = None
        elif blocked:
            visible = False if observer_known and target_height is not None else None
        else:
            visible = True
        targets[target_id] = {
            "visible": visible,
            "distance_m": length,
            "target_height_m": target_height,
            "target_height_known": target_height is not None,
            "blocked_by": sorted(blocked),
            "unknown_height_on_path": sorted(unknown),
        }
    return {
        "observer_height_m": observer_height,
        "observer_height_known": observer_known,
        "targets": targets,
    }


# --- directions ------------------------------------------------------------------------------


def _bearing(a: Node, b: Node) -> float:
    return float(GEOD.inv(a[0], a[1], b[0], b[1])[0]) % 360


def _turn(before: float, after: float, threshold: float) -> str:
    delta = (after - before + 540) % 360 - 180
    if delta > threshold:
        return "right"
    if delta < -threshold:
        return "left"
    return "straight"


def _landmark(pois: gpd.GeoDataFrame, node: Point, radius: float) -> dict[str, Any] | None:
    best: tuple[float, str, str | None] | None = None
    for feature_id, name, geometry in zip(
        pois["feature_id"], pois["name"], pois.geometry, strict=True
    ):
        if geometry.distance(node) > NEAR_DEG:
            continue
        distance = _distance_m(node, geometry)
        if distance <= radius and (best is None or (distance, feature_id) < best[:2]):
            best = (distance, feature_id, _text(name))
    if best is None:
        return None
    return {"feature_id": best[1], "name": best[2], "distance_m": best[0]}


def direction_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    """Turn-by-turn directions along the shortest walk, with the nearest landmark (a POI within
    ``landmark_radius_m``) where each step after the first begins, and the straight-line bearing
    from start to end."""
    start, end = _place(layers, params["from"]), _place(layers, params["to"])
    radius = float(params.get("landmark_radius_m", 30.0))
    threshold = float(params.get("turn_threshold_deg", 30.0))
    graph = WalkGraph(layers)
    route = graph.route(start, end)
    azimuth = float(GEOD.inv(start.x, start.y, end.x, end.y)[0]) % 360
    result: dict[str, Any] = {
        "bearing_deg": azimuth,
        "compass": COMPASS[round(azimuth / 45) % 8],
        "straight_line_m": _distance_m(start, end),
        "reachable": route["reachable"],
        "walking_m": route["walking_m"],
        "steps": [],
    }
    if not route["reachable"]:
        return {**result, "reason": route["reason"]}
    steps: list[dict[str, Any]] = []
    last_bearing = 0.0
    last_group: tuple[str, Any] | None = None
    for u, v in itertools.pairwise(route["nodes"]):
        edge = graph.graph.edges[u, v]
        bearing = _bearing(u, v)
        # a step is one named street, or one unnamed way, without a turn beyond the threshold
        group = ("name", edge["name"]) if edge["name"] else ("way", edge["feature_id"])
        bend = steps and _turn(last_bearing, bearing, threshold) != "straight"
        if steps and group == last_group and not bend:
            steps[-1]["distance_m"] += edge["length"]
        else:
            turn = "start" if not steps else _turn(last_bearing, bearing, threshold)
            steps.append(
                {"street": edge["name"], "distance_m": edge["length"], "turn": turn, "_at": u}
            )
        last_group, last_bearing = group, bearing
    pois = layers["pois"]
    for number, step in enumerate(steps):
        at = step.pop("_at")
        step["landmark"] = _landmark(pois, Point(at), radius) if number else None
    return {**result, "steps": steps}


# --- dispatch --------------------------------------------------------------------------------

KEY_FUNCTIONS: dict[str, Callable[[Mapping[str, Any], Layers], dict[str, Any]]] = {
    "proximity": proximity_key,
    "containment": containment_key,
    "adjacency": adjacency_key,
    "closure": closure_key,
    "visibility": visibility_key,
    "direction": direction_key,
}


def compute_key(key_type: str, params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    """The key of one task, floats rounded to 0.1. Raises ``KeyComputationError``."""
    function = KEY_FUNCTIONS.get(key_type)
    if function is None:
        known = ", ".join(sorted(KEY_FUNCTIONS))
        raise KeyComputationError(f"unknown key type {key_type!r} (known: {known})")
    try:
        return _rounded(function(params, layers))
    except KeyError as exc:
        raise KeyComputationError(f"{key_type} params lack {exc}") from exc
