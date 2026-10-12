"""A city snapshot from OpenStreetMap as GeoParquet layers, for the graded evals.

``convert_extract`` turns an Overpass JSON extract (``out geom``: tagged nodes, ways, and
multipolygon and local boundary relations of a bounding box) into layers in longitude and
latitude (``OGC:CRS84``):

- ``buildings``: ``building=*`` areas, with ``height_m`` and ``height_source`` (see below)
- ``streets``: ``highway=*`` ways for vehicles (``STREET_HIGHWAYS``)
- ``paths``: ``highway=*`` ways for walking and cycling (``PATH_HIGHWAYS``)
- ``railways``: ``railway=*`` lines (``RAIL_TYPES``), with ``walk_barrier`` (see below)
- ``water``: ``natural=water``, ``waterway=*`` and ``water=*``, with ``walk_barrier``
- ``parks``: parks, gardens, playgrounds, nature reserves (``PARK_LEISURE``)
- ``landuse``: ``landuse=*`` areas
- ``pois``: features with one of ``POI_KEYS``, as points (``category`` is the first such key,
  ``value`` its value)
- ``boundaries``: ``boundary=*`` areas and lines
- ``all_features``: every feature with a geometry and all its tags (JSON in ``tags``)

A feature can be in several layers: a library in a building is in ``buildings`` and ``pois``.
Every row has ``feature_id`` (``node/1``, ``way/2``, ``relation/3``) and ``name``. Rows are in
feature order (nodes, ways, relations; then by ID), so two conversions give the same layers.

Building heights: the ``height`` tag in meters (``12``, ``12 m``, ``40 ft``, ``40'``) when it
parses, else ``building:levels`` x 3 m, else unknown (``height_m`` empty, ``height_source``
``unknown``).

Walk barriers: ``walk_barrier`` is true for a feature a pedestrian cannot cross where no street
or path is mapped. Rail is a barrier when it is ``BARRIER_RAIL_TYPES`` at the surface (not in a
tunnel, on a bridge or ``location=underground``); trams and subways are not. Water is a barrier
when it is a ``BARRIER_WATERWAYS`` line that is not in a tunnel (a culverted stream is tagged
``tunnel=culvert``), or any water area; ditches, drains, culverts and water points are not.

Elements without usable geometry are left out: attic data can lack node positions, and a
relation member can lack its geometry. An invalid geometry is repaired (``make_valid``) keeping
only its area parts, or only its line parts for a line, so a self-intersecting building stays in
``buildings``; a line that collapses to a point is left out. Untagged elements are left out too.
"""

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

CRS = "OGC:CRS84"
LAYERS_DIR = "layers"
LAYERS = (
    "buildings",
    "streets",
    "paths",
    "railways",
    "water",
    "parks",
    "landuse",
    "pois",
    "boundaries",
    "all_features",
)
LAYER_COLUMNS: dict[str, tuple[str, ...]] = {
    "buildings": ("building", "height_m", "height_source"),
    "streets": ("highway",),
    "paths": ("highway",),
    "railways": ("railway", "walk_barrier"),
    "water": ("water_kind", "walk_barrier"),
    "parks": ("leisure",),
    "landuse": ("landuse",),
    "pois": ("category", "value"),
    "boundaries": ("boundary", "admin_level"),
    "all_features": ("tags",),
}
LEVEL_HEIGHT_M = 3.0
FEET_TO_M = 0.3048
STREET_HIGHWAYS = frozenset(
    {
        "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
        "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
        "residential", "living_street", "service", "road",
    }
)  # fmt: skip
PATH_HIGHWAYS = frozenset(
    {"footway", "path", "pedestrian", "steps", "cycleway", "track", "bridleway", "corridor"}
)
RAIL_TYPES = frozenset(
    {"rail", "light_rail", "tram", "subway", "narrow_gauge", "monorail", "funicular"}
)
BARRIER_RAIL_TYPES = frozenset({"rail", "light_rail", "narrow_gauge", "monorail", "funicular"})
BARRIER_WATERWAYS = frozenset({"river", "canal", "stream"})
PARK_LEISURE = frozenset({"park", "garden", "playground", "nature_reserve", "dog_park"})
POI_KEYS = ("amenity", "shop", "tourism", "office", "healthcare", "historic", "craft")
AREA_KEYS = frozenset(
    {"building", "landuse", "leisure", "amenity", "shop", "tourism", "water", "place", "man_made"}
)
LINEAR_NATURAL = frozenset({"coastline", "cliff", "ridge", "tree_row", "arete"})
TYPE_ORDER = {"node": 0, "way": 1, "relation": 2}

_HEIGHT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m|meters?|metres?|ft|feet|')?\s*$", re.IGNORECASE)


class CityError(ValueError):
    """The extract or the layer directory cannot be read."""


def parse_height(value: str | None) -> float | None:
    """A ``height`` tag in meters, or None when it does not parse or is not positive."""
    if value is None:
        return None
    match = _HEIGHT.match(value)
    if match is None:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "m").lower()
    meters = number * FEET_TO_M if unit in ("ft", "feet", "'") else number
    return meters if meters > 0 else None


def building_height(tags: Mapping[str, str]) -> tuple[float | None, str]:
    """The building's height in meters and its source: ``height``, ``levels`` or ``unknown``."""
    height = parse_height(tags.get("height"))
    if height is not None:
        return height, "height"
    try:
        levels = float(tags.get("building:levels", ""))
    except ValueError:
        levels = 0.0
    if math.isfinite(levels) and levels > 0:
        return levels * LEVEL_HEIGHT_M, "levels"
    return None, "unknown"


def feature_id(element: Mapping[str, Any]) -> str:
    return f"{element['type']}/{element['id']}"


def _coords(points: Iterable[Any]) -> list[tuple[float, float]]:
    return [
        (float(p["lon"]), float(p["lat"]))
        for p in points
        if isinstance(p, dict) and "lon" in p and "lat" in p
    ]


def _is_area(tags: Mapping[str, str]) -> bool:
    if tags.get("area") == "no":
        return False
    if tags.get("area") == "yes" or tags.get("waterway") == "riverbank":
        return True
    if "highway" in tags or "barrier" in tags or "railway" in tags:
        return False
    if "natural" in tags:
        return tags["natural"] not in LINEAR_NATURAL
    return any(key in tags for key in AREA_KEYS)


def _relation_geometry(members: Iterable[Any]) -> BaseGeometry | None:
    rings: dict[str, list[LineString]] = {"outer": [], "inner": []}
    for member in members:
        if not isinstance(member, dict) or member.get("type") != "way":
            continue
        coords = _coords(member.get("geometry") or [])
        if len(coords) >= 2:
            role = "inner" if member.get("role") == "inner" else "outer"
            rings[role].append(LineString(coords))
    if not rings["outer"]:
        return None
    outer = unary_union(list(polygonize(unary_union(rings["outer"]))))
    if outer.is_empty:
        return unary_union(rings["outer"])
    if rings["inner"]:
        outer = outer.difference(unary_union(list(polygonize(unary_union(rings["inner"])))))
    return outer


def element_geometry(element: Mapping[str, Any]) -> BaseGeometry | None:
    """The element's geometry in longitude and latitude, or None when it has none."""
    tags = element.get("tags") or {}
    kind = element.get("type")
    if kind == "node":
        if "lon" not in element or "lat" not in element:
            return None
        return Point(float(element["lon"]), float(element["lat"]))
    if kind == "way":
        coords = _coords(element.get("geometry") or [])
        if len(coords) < 2:
            return None
        if len(coords) >= 4 and coords[0] == coords[-1] and _is_area(tags):
            return Polygon(coords)
        return LineString(coords)
    if kind == "relation" and tags.get("type") in ("multipolygon", "boundary"):
        return _relation_geometry(element.get("members") or [])
    return None


def _passes_over_or_under(tags: Mapping[str, str]) -> bool:
    """Whether the feature is in a tunnel, on a bridge or underground, off the walking level."""
    return (
        tags.get("tunnel", "no") != "no"
        or tags.get("bridge", "no") != "no"
        or tags.get("location") == "underground"
    )


def walk_barrier(layer: str, tags: Mapping[str, str], geometry: BaseGeometry) -> bool:
    """Whether a ``railways`` or ``water`` feature bars walking; see the module docstring."""
    if layer == "railways":
        return tags.get("railway") in BARRIER_RAIL_TYPES and not _passes_over_or_under(tags)
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        return True
    linear = geometry.geom_type in ("LineString", "MultiLineString")
    return linear and tags.get("waterway") in BARRIER_WATERWAYS and not _passes_over_or_under(tags)


def _layers_of(tags: Mapping[str, str], geometry: BaseGeometry) -> list[str]:
    polygonal = geometry.geom_type in ("Polygon", "MultiPolygon")
    linear = geometry.geom_type in ("LineString", "MultiLineString")
    highway = tags.get("highway")
    layers = []
    if "building" in tags and polygonal:
        layers.append("buildings")
    if highway in STREET_HIGHWAYS and linear:
        layers.append("streets")
    if highway in PATH_HIGHWAYS and linear:
        layers.append("paths")
    if tags.get("railway") in RAIL_TYPES and linear:
        layers.append("railways")
    if tags.get("natural") == "water" or "waterway" in tags or "water" in tags:
        layers.append("water")
    if tags.get("leisure") in PARK_LEISURE and polygonal:
        layers.append("parks")
    if "landuse" in tags and polygonal:
        layers.append("landuse")
    if any(key in tags for key in POI_KEYS):
        layers.append("pois")
    if "boundary" in tags and (polygonal or linear):
        layers.append("boundaries")
    return layers


def _columns(layer: str, tags: Mapping[str, str], geometry: BaseGeometry) -> dict[str, Any]:
    if layer == "buildings":
        height, source = building_height(tags)
        return {"building": tags["building"], "height_m": height, "height_source": source}
    if layer in ("streets", "paths"):
        return {"highway": tags["highway"]}
    if layer == "railways":
        return {"railway": tags["railway"], "walk_barrier": walk_barrier(layer, tags, geometry)}
    if layer == "water":
        return {
            "water_kind": tags.get("waterway") or tags.get("water") or tags.get("natural"),
            "walk_barrier": walk_barrier(layer, tags, geometry),
        }
    if layer == "parks":
        return {"leisure": tags["leisure"]}
    if layer == "landuse":
        return {"landuse": tags["landuse"]}
    if layer == "pois":
        category = next(key for key in POI_KEYS if key in tags)
        return {"category": category, "value": tags[category]}
    if layer == "boundaries":
        return {"boundary": tags["boundary"], "admin_level": tags.get("admin_level")}
    return {"tags": json.dumps(dict(tags), sort_keys=True, ensure_ascii=False)}


def _order(element: Mapping[str, Any]) -> tuple[int, int]:
    return TYPE_ORDER.get(str(element.get("type")), 3), int(element.get("id", 0))


def _frame(layer: str, rows: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    columns = ["feature_id", "name", *LAYER_COLUMNS[layer]]
    if not rows:
        empty = {column: [] for column in columns}
        return gpd.GeoDataFrame(empty, geometry=gpd.GeoSeries([], crs=CRS), crs=CRS)
    return gpd.GeoDataFrame(rows, columns=[*columns, "geometry"], geometry="geometry", crs=CRS)


def _repaired(geometry: BaseGeometry) -> BaseGeometry:
    """A valid geometry of the same kind: ``make_valid`` can add stray lines to an area (a ring
    with a spike) or collapse a line to a point, so only the area or line parts are kept."""
    polygonal = geometry.geom_type in ("Polygon", "MultiPolygon")
    kinds = ("Polygon", "MultiPolygon") if polygonal else ("LineString", "MultiLineString")
    parts = [
        part for part in shapely.get_parts(shapely.make_valid(geometry)) if part.geom_type in kinds
    ]
    return unary_union(parts) if parts else Polygon()


def convert_extract(document: Mapping[str, Any]) -> dict[str, gpd.GeoDataFrame]:
    """The layers of an Overpass extract; see the module docstring."""
    elements = document.get("elements")
    if not isinstance(elements, list):
        raise CityError("the extract has no elements list")
    rows: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
    for element in sorted((e for e in elements if isinstance(e, dict)), key=_order):
        tags = element.get("tags") or {}
        if not tags:
            continue
        geometry = element_geometry(element)
        if geometry is None or geometry.is_empty:
            continue
        if not geometry.is_valid:
            geometry = _repaired(geometry)
            if geometry.is_empty:
                continue
        base = {"feature_id": feature_id(element), "name": tags.get("name")}
        for layer in _layers_of(tags, geometry):
            point_only = layer == "pois" and geometry.geom_type != "Point"
            shape = geometry.representative_point() if point_only else geometry
            rows[layer].append({**base, **_columns(layer, tags, geometry), "geometry": shape})
        rows["all_features"].append(
            {**base, **_columns("all_features", tags, geometry), "geometry": geometry}
        )
    return {layer: _frame(layer, rows[layer]) for layer in LAYERS}


def write_layers(layers: Mapping[str, gpd.GeoDataFrame], out_dir: Path) -> list[Path]:
    """Write each layer to ``out_dir/<layer>.parquet``; return the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in LAYERS:
        path = out_dir / f"{name}.parquet"
        layers[name].to_parquet(path, index=False)
        written.append(path)
    return written


def load_layers(directory: Path) -> dict[str, gpd.GeoDataFrame]:
    """Read every layer from ``directory``. Raises ``CityError`` naming missing layers."""
    missing = [name for name in LAYERS if not (directory / f"{name}.parquet").is_file()]
    if missing:
        raise CityError(f"{directory}: missing layer(s) {', '.join(missing)}")
    return {name: gpd.read_parquet(directory / f"{name}.parquet") for name in LAYERS}


def layers_sha256(directory: Path) -> str:
    """SHA-256 over the layer files' names and bytes, in layer order.

    Runs and grades of one eval must use the same layers; this hash, recorded in the result,
    says whether they did. It depends on the GeoParquet writer, so it is compared only between
    runs made from the same layer files.
    """
    digest = hashlib.sha256()
    for name in LAYERS:
        path = directory / f"{name}.parquet"
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
