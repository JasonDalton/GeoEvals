"""Reference workflow of the ``gis_correctness`` benchmark.

``reference_output(case, benchmark_dir)`` computes the expected output of one case from its
``operation`` and ``inputs``. ``geoevals bench regenerate gis_correctness`` calls it for every
case and writes the result to the case's ``expected``: inline in the case line, or to the JSON
file that ``expected`` names (a path relative to ``benchmark.yaml``).

Fixture files are GeoJSON, so they are in ``OGC:CRS84`` (longitude, latitude) unless a case
states ``source_crs``. Coordinates are always x = easting or longitude first (``always_xy``).

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
from shapely import make_valid, transform, unary_union
from shapely.geometry import mapping, shape
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


OPERATIONS: dict[str, Callable[[Mapping[str, Any], Path], dict[str, Any]]] = {
    "crs_transform": crs_transform,
    "distance": distance,
    "buffer": buffer,
    "validity": validity,
}


def reference_output(case: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """The expected output of ``case`` (a case line without ``expected``)."""
    return OPERATIONS[case["operation"]](case["inputs"], benchmark_dir)
