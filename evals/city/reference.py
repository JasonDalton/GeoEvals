"""Reference keys of the graded evals on the city, computed from its layers.

``compute_key(key_type, params, layers)`` returns the key of one task: the facts a correct answer
must agree with. The grader sees the key; the model never does. Keys are computed, never written
by hand (``geoevals evals regenerate``), and are not committed (OpenStreetMap-derived data).

Distances are geodesic meters on WGS 84. Walking distances use the ``streets`` and ``paths``
layers as an undirected graph whose nodes are the lines' shared vertices; a place joins the
network at its nearest vertex, and a place more than ``MAX_SNAP_M`` from every vertex is
unreachable. Local geometry (shared edges, lines of sight, distance to a boundary) is measured in
an azimuthal equidistant projection centered on the features involved. Every float in a key is
rounded to 0.1 (meters, degrees), so the key and its hash are the same on every platform.

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
NEAR_DEG = 0.001
"""Prefilter: features farther than this (about 70 to 110 m) cannot be within a tolerance."""
NETWORK_LAYERS = ("streets", "paths")
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
                        length = float(GEOD.inv(a[0], a[1], b[0], b[1])[2])
                        if length == 0:
                            continue
                        u, v = (a[0], a[1]), (b[0], b[1])
                        existing = self.graph.get_edge_data(u, v)
                        if existing is None or existing["length"] > length:
                            self.graph.add_edge(
                                u, v, length=length, feature_id=feature_id, name=_text(name)
                            )
        self._nodes: list[Node] = list(self.graph.nodes)
        self._lons = np.array([node[0] for node in self._nodes])
        self._lats = np.array([node[1] for node in self._nodes])

    def snap(self, point: Point) -> tuple[Node | None, float]:
        """The nearest network vertex and its distance in meters."""
        if not self._nodes:
            return None, math.inf
        n = len(self._nodes)
        _, _, distances = GEOD.inv(np.full(n, point.x), np.full(n, point.y), self._lons, self._lats)
        index = int(np.argmin(distances))
        return self._nodes[index], float(distances[index])

    def route(self, start: Point, end: Point) -> dict[str, Any]:
        """The shortest walk from ``start`` to ``end``, snap distances included."""
        a, snap_a = self.snap(start)
        b, snap_b = self.snap(end)
        result: dict[str, Any] = {
            "reachable": False,
            "walking_m": None,
            "snap_from_m": snap_a if math.isfinite(snap_a) else None,
            "snap_to_m": snap_b if math.isfinite(snap_b) else None,
            "nodes": [],
        }
        if a is None or b is None:
            return {**result, "reason": "no_network"}
        if snap_a > MAX_SNAP_M or snap_b > MAX_SNAP_M:
            return {**result, "reason": "too_far_from_network"}
        try:
            nodes = nx.shortest_path(self.graph, a, b, weight="length")
        except nx.NetworkXNoPath:
            return {**result, "reason": "not_connected"}
        length = sum(self.graph.edges[u, v]["length"] for u, v in itertools.pairwise(nodes))
        return {**result, "reachable": True, "walking_m": snap_a + length + snap_b, "nodes": nodes}


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


# --- dispatch --------------------------------------------------------------------------------

KEY_FUNCTIONS: dict[str, Callable[[Mapping[str, Any], Layers], dict[str, Any]]] = {
    "proximity": proximity_key,
    "containment": containment_key,
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
