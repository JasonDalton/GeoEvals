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
from pyproj.exceptions import CRSError
from shapely import transform
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

GEOJSON_CRS = "OGC:CRS84"

UNITS_IN_M = {"m": 1.0, "km": 1000.0, "ft": 0.3048, "us_ft": 1200 / 3937, "mi": 1609.344}
"""Length units an answer may be requested in, in meters."""


def _geojson(geometry: BaseGeometry) -> dict[str, Any]:
    """GeoJSON of a geometry with lists, not tuples, so it compares equal after a JSON trip."""
    return json.loads(json.dumps(mapping(geometry)))


def _read_features(path: Path) -> list[dict[str, Any]]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    return collection["features"]


def _transformer(source: str, target: str) -> Callable[[BaseGeometry], BaseGeometry]:
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


OPERATIONS: dict[str, Callable[[Mapping[str, Any], Path], dict[str, Any]]] = {
    "crs_transform": crs_transform,
    "distance": distance,
}


def reference_output(case: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """The expected output of ``case`` (a case line without ``expected``)."""
    return OPERATIONS[case["operation"]](case["inputs"], benchmark_dir)
