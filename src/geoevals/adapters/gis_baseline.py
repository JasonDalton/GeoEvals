"""Deterministic GIS baseline: answers ``gis_correctness`` cases with GeoPandas, Shapely and pyproj.

``predict`` dispatches on the case's ``operation`` to one function per operation in
``OPERATIONS``. Each function takes the case ``inputs`` (``files``: name -> path relative to
the benchmark directory, ``params``: the operation's parameters) and the benchmark directory,
and returns an output in the benchmark's output contract. An operation that is not in
``OPERATIONS`` raises ``UnsupportedOperation``, which the runner records as ``adapter_error``.

Fixture files are read with GeoPandas. A file without a CRS (GeoJSON without a ``crs`` member)
is taken to be in ``OGC:CRS84`` unless the case states ``source_crs``. Coordinates are
x = easting or longitude first, as everywhere in GeoEvals.

The adapter takes no config, makes no paid calls (``deterministic = True``) and keeps no state
between cases.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry import mapping, shape

from geoevals.adapters.base import AdapterResponse

if TYPE_CHECKING:
    import geopandas

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
"""GEOS validity message (without the ``[x y]`` location) -> reason category."""

Operation = Callable[[Mapping[str, Any], Path], dict[str, Any]]


class UnsupportedOperation(ValueError):
    """The case's ``operation`` has no implementation in the baseline."""


def _parse_crs(value: Any) -> CRS | None:
    try:
        return CRS.from_user_input(value)
    except CRSError:
        return None


def _read(inputs: Mapping[str, Any], name: str, base: Path) -> "geopandas.GeoDataFrame":
    # Imported here: geopandas is slow to import, and the adapters package is imported by
    # every CLI command and runner worker.
    import geopandas

    path = base / inputs["files"][name]
    frame = geopandas.read_file(path)
    source = inputs["params"].get("source_crs")
    if source is not None:
        return frame.set_crs(source, allow_override=True)
    # GDAL labels a GeoJSON file without a ``crs`` member EPSG:4326 (latitude first), but
    # RFC 7946 coordinates are longitude, latitude: OGC:CRS84.
    if frame.crs is None or (
        path.suffix == ".geojson" and "crs" not in json.loads(path.read_text(encoding="utf-8"))
    ):
        return frame.set_crs(GEOJSON_CRS, allow_override=True)
    return frame


def _geojson(value: Any) -> Any:
    """Plain JSON (lists, not tuples) of a ``__geo_interface__`` mapping."""
    return json.loads(json.dumps(value))


def _feature_collection(frame: "geopandas.GeoDataFrame") -> dict[str, Any]:
    """The frame as a FeatureCollection; missing attribute values (NaN) become null."""
    columns = frame.drop(columns=frame.geometry.name).astype(object)
    properties = columns.where(columns.notna(), None).to_dict(orient="records")
    features = [
        {"type": "Feature", "properties": props, "geometry": _geojson(mapping(geometry))}
        for props, geometry in zip(properties, frame.geometry, strict=True)
    ]
    return {"type": "FeatureCollection", "features": features}


def crs_transform(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Reproject ``params.geometry`` (in ``source_crs``, default ``OGC:CRS84``) or the layer
    ``files.source`` to ``target_crs``. An unknown CRS gives ``invalid_request``."""
    params = inputs["params"]
    source = _parse_crs(params.get("source_crs", GEOJSON_CRS))
    target = _parse_crs(params["target_crs"])
    if source is None or target is None:
        return {"status": "invalid_request"}
    if "geometry" in params:
        import geopandas

        series = geopandas.GeoSeries([shape(params["geometry"])], crs=source).to_crs(target)
        geometry = _geojson(mapping(series.iloc[0]))
        return {"status": "ok", "geometry": geometry, "crs": params["target_crs"]}
    frame = _read(inputs, "source", base).to_crs(target)
    return {"status": "ok", "features": _feature_collection(frame), "crs": params["target_crs"]}


def distance(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Distance between the features ``from`` and ``to`` of ``files.layer`` (matched on the
    property ``key``) in ``units``: geodesic on the layer CRS's ellipsoid (``method:
    geodesic``) or planar in ``crs`` (``method: projected``)."""
    params = inputs["params"]
    frame = _read(inputs, "layer", base)
    layer_crs = CRS.from_user_input(frame.crs)
    if params["method"] == "geodesic":
        if layer_crs.is_projected:
            layer_crs = layer_crs.geodetic_crs
            assert layer_crs is not None
            frame = frame.to_crs(layer_crs)
        crs = params.get("source_crs", GEOJSON_CRS)
    else:
        crs = params["crs"]
        layer_crs = CRS.from_user_input(crs)
        frame = frame.to_crs(layer_crs)
    by_key = frame.set_index(params["key"]).geometry
    start, end = by_key[params["from"]], by_key[params["to"]]
    if params["method"] == "geodesic":
        geod = layer_crs.get_geod()
        assert geod is not None, "a geodesic distance needs a CRS with an ellipsoid"
        meters = geod.line_length([start.x, end.x], [start.y, end.y])
    else:
        meters = start.distance(end) * layer_crs.axis_info[0].unit_conversion_factor
    units = params["units"]
    return {"status": "ok", "value": meters / UNITS_IN_M[units], "units": units, "crs": crs}


def buffer(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Buffer ``params.geometry`` or the layer ``files.source`` (with ``dissolve: true``, the
    buffers are dissolved into one geometry) by ``distance`` ``units`` with ``cap_style``. The
    buffer is computed in ``crs`` when given, else in the source CRS when it is projected, else
    in the UTM zone GeoPandas estimates; the answer is in the source CRS."""
    import geopandas

    params = inputs["params"]
    if "geometry" in params:
        source = params.get("source_crs", GEOJSON_CRS)
        series = geopandas.GeoSeries([shape(params["geometry"])], crs=source)
    elif params.get("dissolve") is True:
        series = _read(inputs, "source", base).geometry
    else:
        raise ValueError("a buffer of a layer needs dissolve: true")
    source_crs = CRS.from_user_input(series.crs)
    if "crs" in params:
        local = CRS.from_user_input(params["crs"])
    else:
        local = series.estimate_utm_crs() if source_crs.is_geographic else source_crs
    meters = params["distance"] * UNITS_IN_M[params["units"]]
    distance = meters / local.axis_info[0].unit_conversion_factor
    buffers = series.to_crs(local).buffer(distance, cap_style=params.get("cap_style", "round"))
    if len(buffers) > 1:
        buffers = geopandas.GeoSeries([buffers.union_all()], crs=local)
    geometry = _geojson(mapping(buffers.to_crs(source_crs).iloc[0]))
    return {"status": "ok", "geometry": geometry, "crs": params.get("source_crs", GEOJSON_CRS)}


def _rings(geometry: Mapping[str, Any]) -> list[list[Any]]:
    """The rings of a GeoJSON Polygon or MultiPolygon as written (none for other types)."""
    if geometry["type"] == "Polygon":
        return list(geometry["coordinates"])
    if geometry["type"] == "MultiPolygon":
        return [ring for polygon in geometry["coordinates"] for ring in polygon]
    return []


def validity(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Detect (``task: detect``) or repair (``task: repair``) the validity of
    ``params.geometry``. Detection checks the GeoJSON rings first (RFC 7946: closed, at least
    four positions; Shapely would silently close an open ring), then GEOS validity, and answers
    a boolean ``value`` with a ``reason`` category. Repair uses GeoPandas ``make_valid``."""
    import geopandas

    params = inputs["params"]
    crs = params.get("source_crs", GEOJSON_CRS)
    series = geopandas.GeoSeries([shape(params["geometry"])], crs=crs)
    if params["task"] == "repair":
        geometry = _geojson(mapping(series.make_valid().iloc[0]))
        return {"status": "ok", "geometry": geometry, "crs": crs}
    rings = _rings(params["geometry"])
    if any(ring[0] != ring[-1] for ring in rings):
        reason = "unclosed_ring"
    elif any(len(ring) < 4 for ring in rings):
        reason = "too_few_points"
    else:
        message = series.is_valid_reason().iloc[0]
        reason = VALIDITY_REASONS[message.partition("[")[0]]
    return {
        "status": "ok",
        "value": reason == "valid",
        "units": "bool",
        "reason": reason,
        "crs": crs,
    }


def _layers(
    inputs: Mapping[str, Any], base: Path, first: str, second: str
) -> tuple["geopandas.GeoDataFrame", "geopandas.GeoDataFrame"]:
    """The layers ``files.<first>`` and ``files.<second>``, the second in the first's CRS."""
    one, two = _read(inputs, first, base), _read(inputs, second, base)
    assert one.crs is not None, "_read always sets a CRS"
    return one, two if two.crs == one.crs else two.to_crs(one.crs)


def _crs_name(frame: "geopandas.GeoDataFrame") -> str:
    return CRS.from_user_input(frame.crs).to_string()


def spatial_join(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Join ``files.right`` to ``files.left`` with GeoPandas ``sjoin`` (``predicate``
    intersects, within or contains) or ``sjoin_nearest`` (``predicate: nearest``, within
    ``max_distance`` ``units`` in the projected CRS ``crs``, distance in meters as
    ``distance_m``), ``how`` inner (default) or left. The right layer is reprojected to the left
    layer's CRS first (``sjoin`` would only warn about a mismatch); the answer keeps the left
    geometries and CRS."""
    import geopandas

    params = inputs["params"]
    left, right = _layers(inputs, base, "left", "right")
    how = params.get("how", "inner")
    if params["predicate"] == "nearest":
        crs = CRS.from_user_input(params["crs"])
        unit_m = crs.axis_info[0].unit_conversion_factor
        max_distance = params["max_distance"] * UNITS_IN_M[params["units"]] / unit_m
        joined = geopandas.sjoin_nearest(
            left.to_crs(crs),
            right.to_crs(crs),
            how=how,
            max_distance=max_distance,
            distance_col="distance_m",
        )
        joined["distance_m"] = joined["distance_m"] * unit_m
        joined = joined.set_geometry(left.geometry.loc[joined.index].values, crs=left.crs)
    else:
        joined = geopandas.sjoin(left, right, how=how, predicate=params["predicate"])
    joined = cast("geopandas.GeoDataFrame", joined.drop(columns="index_right"))
    return {"status": "ok", "features": _feature_collection(joined), "crs": _crs_name(left)}


def overlay(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Overlay ``files.a`` with ``files.b`` (reprojected to the CRS of ``a``): GeoPandas
    ``overlay`` for ``how`` intersection, union, difference or symmetric_difference, and
    ``clip`` (``b`` is the mask) for ``how: clip``, with ``keep_geom_type`` (default true)."""
    import geopandas

    params = inputs["params"]
    a, b = _layers(inputs, base, "a", "b")
    keep_geom_type = params.get("keep_geom_type", True)
    if params["how"] == "clip":
        result = geopandas.clip(a, b, keep_geom_type=keep_geom_type)
    else:
        result = geopandas.overlay(a, b, how=params["how"], keep_geom_type=keep_geom_type)
    return {"status": "ok", "features": _feature_collection(result), "crs": _crs_name(a)}


OPERATIONS: dict[str, Operation] = {
    "crs_transform": crs_transform,
    "distance": distance,
    "buffer": buffer,
    "validity": validity,
    "spatial_join": spatial_join,
    "overlay": overlay,
}
"""Operation name (the case ``operation``) -> its implementation."""


class GisBaselineAdapter:
    """Answers every supported ``gis_correctness`` operation deterministically."""

    name = "gis_baseline"
    version = "0.1.0"
    deterministic = True

    def setup(self, config: Mapping[str, Any]) -> None:
        if config:
            raise ValueError(f"gis_baseline takes no config, got keys {sorted(config)}")

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        operation = case_input.get("operation")
        handler = OPERATIONS.get(operation) if isinstance(operation, str) else None
        if handler is None:
            known = ", ".join(sorted(OPERATIONS))
            raise UnsupportedOperation(f"unsupported operation {operation!r} (supported: {known})")
        base = Path(case_input.get("benchmark_dir", "."))
        return AdapterResponse(output=handler(case_input["inputs"], base))

    def teardown(self) -> None:
        pass
