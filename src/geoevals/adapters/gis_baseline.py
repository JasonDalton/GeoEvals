"""Deterministic GIS baseline: answers ``gis_correctness`` cases with GeoPandas, Shapely and pyproj.

``predict`` dispatches on the case's ``operation`` to one function per operation in
``OPERATIONS``. Each function takes the case ``inputs`` (``files``: name -> path relative to
the benchmark directory, ``params``: the operation's parameters) and the benchmark directory,
and returns an output in the benchmark's output contract. An operation that is not in
``OPERATIONS`` raises ``UnsupportedOperation``, which the runner records as ``adapter_error``.

Fixture files are read with GeoPandas. A file without a CRS (GeoJSON) is taken to be in
``OGC:CRS84`` unless the case states ``source_crs``. Coordinates are x = easting or longitude
first, as everywhere in GeoEvals.

The adapter takes no config, makes no paid calls (``deterministic = True``) and keeps no state
between cases.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry import mapping, shape

from geoevals.adapters.base import AdapterResponse

if TYPE_CHECKING:
    import geopandas

GEOJSON_CRS = "OGC:CRS84"

UNITS_IN_M = {"m": 1.0, "km": 1000.0, "ft": 0.3048, "us_ft": 1200 / 3937, "mi": 1609.344}
"""Length units an answer may be requested in, in meters."""

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

    frame = geopandas.read_file(base / inputs["files"][name])
    source = inputs["params"].get("source_crs")
    if source is not None:
        return frame.set_crs(source, allow_override=True)
    return frame if frame.crs is not None else frame.set_crs(GEOJSON_CRS)


def _geojson(value: Any) -> Any:
    """Plain JSON (lists, not tuples) of a ``__geo_interface__`` mapping."""
    return json.loads(json.dumps(value))


def _feature_collection(frame: "geopandas.GeoDataFrame") -> dict[str, Any]:
    properties = frame.drop(columns=frame.geometry.name).to_dict(orient="records")
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


OPERATIONS: dict[str, Operation] = {
    "crs_transform": crs_transform,
    "distance": distance,
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
