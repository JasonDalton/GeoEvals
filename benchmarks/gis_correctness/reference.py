"""Reference workflow of the ``gis_correctness`` benchmark.

``reference_output(case, benchmark_dir)`` computes the expected output of one case from its
``operation`` and ``inputs``. ``geoevals bench regenerate gis_correctness`` calls it for every
case and writes the result to the case's ``expected``: inline in the case line, or to the JSON
file that ``expected`` names (a path relative to ``benchmark.yaml``).

Fixture files are GeoJSON, so they are in ``OGC:CRS84`` (longitude, latitude) unless a case
states ``source_crs`` or the file has a (pre-RFC 7946) ``crs`` member. Coordinates are always
x = easting or longitude first (``always_xy``).

This workflow uses pyproj and Shapely directly. The ``gis_baseline`` adapter goes through
GeoPandas, so the two are separate implementations of each operation.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import CRS, Geod, Transformer
from pyproj.crs import ProjectedCRS
from pyproj.crs.coordinate_operation import AzimuthalEquidistantConversion
from pyproj.exceptions import CRSError
from shapely import get_parts, make_valid, transform, unary_union
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

GEOJSON_CRS = "OGC:CRS84"

UNITS_IN_M = {"m": 1.0, "km": 1000.0, "ft": 0.3048, "us_ft": 1200 / 3937, "mi": 1609.344}
"""Length units an answer may be requested in, in meters."""

VALIDITY_REASONS = {
    "Valid Geometry": "valid",
    "Self-intersection": "self_intersection",
    "Ring Self-intersection": "self_intersection",
    "Hole lies outside shell": "hole_outside_shell",
    "Holes are nested": "nested_holes",
    "Interior is disconnected": "disconnected_interior",
    "Nested shells": "nested_shells",
    "Duplicate Rings": "duplicate_rings",
    "Too few points in geometry component": "too_few_points",
    "Ring is not closed": "unclosed_ring",
    "Invalid Coordinate": "invalid_coordinate",
}
"""GEOS ``explain_validity`` message (without the ``[x y]`` location) -> reason category."""


def _geojson(geometry: BaseGeometry) -> dict[str, Any]:
    """GeoJSON of a geometry with lists, not tuples, so it compares equal after a JSON trip."""
    return json.loads(json.dumps(mapping(geometry)))


def _read_features(path: Path) -> list[dict[str, Any]]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    return collection["features"]


def _read_layer(path: Path) -> tuple[list[dict[str, Any]], str]:
    """The features of a GeoJSON file and its CRS: the name in its ``crs`` member (written as
    ``AUTHORITY:CODE`` when pyproj knows one), else ``OGC:CRS84``."""
    collection = json.loads(path.read_text(encoding="utf-8"))
    name = collection.get("crs", {}).get("properties", {}).get("name")
    return collection["features"], GEOJSON_CRS if name is None else CRS(name).to_string()


def _transformer(source: str | CRS, target: str | CRS) -> Callable[[BaseGeometry], BaseGeometry]:
    project = Transformer.from_crs(source, target, always_xy=True).transform

    def apply(geometry: BaseGeometry) -> BaseGeometry:
        return transform(geometry, lambda xy: np.column_stack(project(xy[:, 0], xy[:, 1])))

    return apply


def _valid_crs(code: str) -> bool:
    try:
        CRS.from_user_input(code)
    except CRSError:
        return False
    return True


def crs_transform(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """Transform ``params.geometry`` or the features of ``files.source`` from ``source_crs``
    (default ``OGC:CRS84``) to ``target_crs``. An unknown CRS is an ``invalid_request``."""
    params = inputs["params"]
    source = params.get("source_crs", GEOJSON_CRS)
    target = params["target_crs"]
    if not (_valid_crs(source) and _valid_crs(target)):
        return {"status": "invalid_request"}
    apply = _transformer(source, target)
    if "geometry" in params:
        geometry = apply(shape(params["geometry"]))
        return {"status": "ok", "geometry": _geojson(geometry), "crs": target}
    features = [
        {
            "type": "Feature",
            "properties": feature["properties"],
            "geometry": _geojson(apply(shape(feature["geometry"]))),
        }
        for feature in _read_features(benchmark_dir / inputs["files"]["source"])
    ]
    return {
        "status": "ok",
        "features": {"type": "FeatureCollection", "features": features},
        "crs": target,
    }


def distance(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """Distance between the features ``from`` and ``to`` of ``files.layer`` (found by the
    property ``key``) in ``units``. ``method: geodesic`` measures on the WGS 84 ellipsoid with
    ``pyproj.Geod.inv``; ``method: projected`` measures planar distance in ``crs``."""
    params = inputs["params"]
    by_key = {
        feature["properties"][params["key"]]: shape(feature["geometry"])
        for feature in _read_features(benchmark_dir / inputs["files"]["layer"])
    }
    start, end = by_key[params["from"]], by_key[params["to"]]
    if params["method"] == "geodesic":
        _, _, meters = Geod(ellps="WGS84").inv(start.x, start.y, end.x, end.y)
        crs = GEOJSON_CRS
    else:
        crs = params["crs"]
        project = Transformer.from_crs(GEOJSON_CRS, crs, always_xy=True).transform
        (x1, y1), (x2, y2) = project(start.x, start.y), project(end.x, end.y)
        unit_m = CRS(crs).axis_info[0].unit_conversion_factor
        meters = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 * unit_m
    units = params["units"]
    return {"status": "ok", "value": meters / UNITS_IN_M[units], "units": units, "crs": crs}


def _local_crs(source: str, geometry: BaseGeometry) -> CRS:
    """``source`` when it is projected, else an azimuthal equidistant CRS on the source's
    ellipsoid centered on the centroid of ``geometry``, so distances from it are true."""
    crs = CRS(source)
    if crs.is_projected:
        return crs
    center = geometry.centroid
    conversion = AzimuthalEquidistantConversion(
        latitude_natural_origin=center.y, longitude_natural_origin=center.x
    )
    return ProjectedCRS(conversion=conversion, geodetic_crs=crs.geodetic_crs or crs)


def buffer(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """Buffer ``params.geometry``, or every feature of ``files.source`` with ``dissolve: true``
    (the buffers are dissolved into one geometry), by ``distance`` ``units`` (negative shrinks)
    with ``cap_style`` (default ``round``). The buffer is computed in the projected CRS ``crs``
    when given, else in the source CRS when it is projected, else in a local azimuthal
    equidistant CRS. The answer is in the source CRS (``source_crs``, default ``OGC:CRS84``)."""
    params = inputs["params"]
    source = params.get("source_crs", GEOJSON_CRS)
    if "geometry" in params:
        geometries = [shape(params["geometry"])]
    elif params.get("dissolve") is True:
        path = benchmark_dir / inputs["files"]["source"]
        geometries = [shape(feature["geometry"]) for feature in _read_features(path)]
    else:
        raise ValueError("a buffer of a layer needs dissolve: true")
    local = CRS(params["crs"]) if "crs" in params else _local_crs(source, unary_union(geometries))
    to_local, to_source = _transformer(source, local), _transformer(local, source)
    meters = params["distance"] * UNITS_IN_M[params["units"]]
    distance = meters / local.axis_info[0].unit_conversion_factor
    cap_style = params.get("cap_style", "round")
    buffers = [to_local(geometry).buffer(distance, cap_style=cap_style) for geometry in geometries]
    result = to_source(buffers[0] if len(buffers) == 1 else unary_union(buffers))
    return {"status": "ok", "geometry": _geojson(result), "crs": source}


def _ring_reason(geometry: Mapping[str, Any]) -> str | None:
    """``unclosed_ring`` or ``too_few_points`` for a GeoJSON polygon ring that breaks RFC 7946
    (closed, at least four positions), else ``None``. Shapely closes an open ring when it reads
    one, so this is checked on the GeoJSON coordinates."""
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        return None
    for ring in (ring for polygon in polygons for ring in polygon):
        if ring[0] != ring[-1]:
            return "unclosed_ring"
        if len(ring) < 4:
            return "too_few_points"
    return None


def validity(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """``task: detect``: whether ``params.geometry`` is valid (RFC 7946 rings, then OGC validity
    by GEOS), as a boolean ``value`` with a ``reason`` category from ``VALIDITY_REASONS``.
    ``task: repair``: the geometry made valid by ``shapely.make_valid`` (the ``linework``
    method). The answer is in ``source_crs`` (default ``OGC:CRS84``)."""
    params = inputs["params"]
    crs = params.get("source_crs", GEOJSON_CRS)
    geometry = shape(params["geometry"])
    if params["task"] == "repair":
        return {"status": "ok", "geometry": _geojson(make_valid(geometry)), "crs": crs}
    reason = _ring_reason(params["geometry"])
    if reason is None:
        reason = VALIDITY_REASONS[explain_validity(geometry).split("[")[0]]
    return {
        "status": "ok",
        "value": reason == "valid",
        "units": "bool",
        "reason": reason,
        "crs": crs,
    }


JOIN_PREDICATES = ("intersects", "within", "contains")
"""Shapely binary predicates a spatial join may use (``left.<predicate>(right)``), besides
``nearest``. A point on a polygon's boundary ``intersects`` it but is not ``within`` it."""


def _layer_in(
    inputs: Mapping[str, Any], benchmark_dir: Path, name: str, crs: str
) -> list[tuple[dict[str, Any], BaseGeometry]]:
    """The properties and geometries of the layer ``files.<name>``, transformed into ``crs``."""
    features, source = _read_layer(benchmark_dir / inputs["files"][name])
    geometries = [shape(feature["geometry"]) for feature in features]
    if not CRS(source).equals(CRS(crs)):
        geometries = [_transformer(source, crs)(geometry) for geometry in geometries]
    return [(feature["properties"], g) for feature, g in zip(features, geometries, strict=True)]


def spatial_join(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """Join the attributes of ``files.right`` to the features of ``files.left``.

    ``predicate`` is one of ``JOIN_PREDICATES`` or ``nearest``. Every left feature gets one
    output feature per matching right feature (so one left feature can give several, and a
    point on a shared boundary ``intersects`` both polygons), with the left geometry and the
    left plus right properties. ``how: left`` keeps unmatched left features with null right
    properties; ``how: inner`` (default) drops them. ``nearest`` matches the closest right
    feature (all of them on a tie) within ``max_distance`` ``units``, measured planar in the
    projected CRS ``crs``, and adds its distance in meters as ``distance_m``. A right layer in
    another CRS is transformed into the left layer's CRS first; the answer is in that CRS.
    """
    params = inputs["params"]
    left, crs = _read_layer(benchmark_dir / inputs["files"]["left"])
    right = _layer_in(inputs, benchmark_dir, "right", crs)
    right_names = list(dict.fromkeys(name for properties, _ in right for name in properties))
    predicate = params["predicate"]
    if predicate == "nearest":
        to_measure = _transformer(crs, params["crs"])
        unit_m = CRS(params["crs"]).axis_info[0].unit_conversion_factor
        right_measured = [to_measure(geometry) for _, geometry in right]
        max_m = params["max_distance"] * UNITS_IN_M[params["units"]]
    elif predicate not in JOIN_PREDICATES:
        raise ValueError(f"unknown join predicate {predicate!r}")
    features = []
    for feature in left:
        geometry = shape(feature["geometry"])
        if predicate == "nearest":
            measured = to_measure(geometry)
            distances = [measured.distance(other) * unit_m for other in right_measured]
            closest = min(distances)
            matches = [
                (properties, {"distance_m": d})
                for (properties, _), d in zip(right, distances, strict=True)
                if d == closest and d <= max_m
            ]
            unmatched = {"distance_m": None}
        else:
            test = getattr(geometry, predicate)
            matches = [(properties, {}) for properties, other in right if test(other)]
            unmatched = {}
        if not matches and params.get("how", "inner") == "left":
            matches = [(dict.fromkeys(right_names), unmatched)]
        features.extend(
            {
                "type": "Feature",
                "properties": {**feature["properties"], **properties, **extra},
                "geometry": feature["geometry"],
            }
            for properties, extra in matches
        )
    return {
        "status": "ok",
        "features": {"type": "FeatureCollection", "features": features},
        "crs": crs,
    }


def _keep_polygons(geometry: BaseGeometry) -> BaseGeometry | None:
    """The polygonal part of an overlay result (``keep_geom_type``), or ``None`` when it has
    none. Points and lines where polygons only touch are dropped."""
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        return geometry
    polygons = [part for part in get_parts(geometry) if isinstance(part, Polygon)]
    if not polygons:
        return None
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


def overlay(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """Overlay the polygon layers ``files.a`` and ``files.b`` (transformed into the CRS of
    ``a``) with ``how``:

    - ``intersection``: ``a & b`` for every pair, with the properties of both.
    - ``difference``: each ``a`` minus all of ``b``, with the ``a`` properties.
    - ``symmetric_difference``: the difference both ways; the other layer's properties are null.
    - ``union``: the intersection plus the symmetric difference.
    - ``clip``: each ``a`` cut to all of ``b`` (the mask), with the ``a`` properties only.

    Empty results are dropped. With ``keep_geom_type`` (default true) only the polygonal part of
    each result is kept; with ``false`` the full result is kept, so polygons that overlap in an
    area and touch along an edge give a GeometryCollection of a polygon and a line. The answer
    is in the CRS of ``a``.
    """
    params = inputs["params"]
    _, crs = _read_layer(benchmark_dir / inputs["files"]["a"])
    a = _layer_in(inputs, benchmark_dir, "a", crs)
    b = _layer_in(inputs, benchmark_dir, "b", crs)
    keep_polygons = params.get("keep_geom_type", True)
    results: list[tuple[dict[str, Any], BaseGeometry]] = []

    def add(properties: dict[str, Any], geometry: BaseGeometry) -> None:
        kept = _keep_polygons(geometry) if keep_polygons else geometry
        if kept is not None and not kept.is_empty:
            results.append((properties, kept))

    def difference(
        layer: list[tuple[dict[str, Any], BaseGeometry]],
        other: list[tuple[dict[str, Any], BaseGeometry]],
        null_other: bool,
    ) -> None:
        mask = unary_union([geometry for _, geometry in other])
        nulls = dict.fromkeys(name for properties, _ in other for name in properties)
        for properties, geometry in layer:
            add({**properties, **nulls} if null_other else properties, geometry.difference(mask))

    how = params["how"]
    if how in ("intersection", "union"):
        for a_properties, a_geometry in a:
            for b_properties, b_geometry in b:
                add({**a_properties, **b_properties}, a_geometry.intersection(b_geometry))
    if how in ("symmetric_difference", "union"):
        difference(a, b, null_other=True)
        difference(b, a, null_other=True)
    elif how == "difference":
        difference(a, b, null_other=False)
    elif how == "clip":
        mask = unary_union([geometry for _, geometry in b])
        for properties, geometry in a:
            add(properties, geometry.intersection(mask))
    elif how != "intersection":
        raise ValueError(f"unknown overlay {how!r}")
    features = [
        {"type": "Feature", "properties": properties, "geometry": _geojson(geometry)}
        for properties, geometry in results
    ]
    return {
        "status": "ok",
        "features": {"type": "FeatureCollection", "features": features},
        "crs": crs,
    }


OPERATIONS: dict[str, Callable[[Mapping[str, Any], Path], dict[str, Any]]] = {
    "crs_transform": crs_transform,
    "distance": distance,
    "buffer": buffer,
    "validity": validity,
    "spatial_join": spatial_join,
    "overlay": overlay,
}


def reference_output(case: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """The expected output of ``case`` (a case line without ``expected``)."""
    return OPERATIONS[case["operation"]](case["inputs"], benchmark_dir)
