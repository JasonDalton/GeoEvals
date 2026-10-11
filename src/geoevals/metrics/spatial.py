"""Tolerance-aware spatial comparison primitives.

Every distance is in meters, every area comparison is relative (unitless), and every function
states the frame it measures in:

- **Geodesic** (the geometries' CRS is geographic): lengths and areas are computed on the CRS's
  ellipsoid with ``pyproj.Geod``. Distances between geometries (Hausdorff) are computed in a
  local azimuthal equidistant (AEQD) projection on the same ellipsoid, centered on the
  reference's centroid. AEQD distances from the center are exact geodesic distances, so the
  distance between two points is exact; for extended geometries the distortion grows with the
  distance from the center.
- **Projected** (the geometries' CRS is projected, or ``measure_crs`` names a projected CRS):
  planar distances, lengths and areas in that CRS, converted from its linear unit to meters
  (for example US survey feet).

Coordinates are always in traditional GIS order, x = easting or longitude and y = northing or
latitude, whatever the CRS authority's axis order (``always_xy``). GeoJSON uses this order, so a
point written as (lat, lon) is an axis swap; ``detect_axis_swap`` finds it.
"""

import math
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import shapely
from pyproj import CRS, Geod, Transformer
from pyproj.crs import ProjectedCRS
from pyproj.crs.coordinate_operation import AzimuthalEquidistantConversion
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

CRSLike = Any
"""Anything ``pyproj.CRS.from_user_input`` accepts: ``"EPSG:4326"``, WKT, a ``CRS``, ..."""

VALID_REASON = "Valid Geometry"
"""``explain_validity`` reason of a valid geometry."""


def to_crs(value: CRSLike) -> CRS:
    """Parse ``value`` into a ``pyproj.CRS``. Raises ``pyproj.exceptions.CRSError`` if invalid."""
    return CRS.from_user_input(value)


def crs_equal(a: CRSLike, b: CRSLike, *, ignore_axis_order: bool = False) -> bool:
    """Whether two CRSs are the same, by ``pyproj.CRS.equals``.

    Unitless. Axis order counts unless ``ignore_axis_order``: ``EPSG:4326`` (lat, lon) does not
    equal ``OGC:CRS84`` (lon, lat). Raises ``pyproj.exceptions.CRSError`` if either CRS cannot
    be parsed.
    """
    return to_crs(a).equals(to_crs(b), ignore_axis_order=ignore_axis_order)


def swap_axes(geometry: BaseGeometry) -> BaseGeometry:
    """Return ``geometry`` with x and y exchanged in every coordinate."""
    return shapely.transform(geometry, lambda xy: xy[:, ::-1])


def reproject(geometry: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    """Apply a pyproj ``Transformer`` (built with ``always_xy=True``) to every coordinate."""
    return shapely.transform(
        geometry, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
    )


def _meters_per_unit(crs: CRS) -> float:
    return crs.axis_info[0].unit_conversion_factor


def _aeqd(geodetic: CRS, center: BaseGeometry) -> CRS:
    point = center.centroid
    conversion = AzimuthalEquidistantConversion(
        latitude_natural_origin=point.y, longitude_natural_origin=point.x
    )
    return ProjectedCRS(conversion=conversion, geodetic_crs=geodetic)


def _projector(
    crs: CRSLike, center: BaseGeometry, measure_crs: CRSLike | None
) -> tuple[Callable[[BaseGeometry], BaseGeometry], float]:
    """Return a function that maps geometries in ``crs`` to the measurement frame, and the
    frame's meters per unit."""
    source = to_crs(crs)
    if measure_crs is not None:
        target = to_crs(measure_crs)
        if not target.is_projected:
            raise ValueError(f"measure_crs {target.to_string()!r} is not a projected CRS")
    elif source.is_geographic:
        target = _aeqd(source.geodetic_crs or source, center)
    else:
        return (lambda g: g), _meters_per_unit(source)
    transformer = Transformer.from_crs(source, target, always_xy=True)
    return (lambda g: reproject(g, transformer)), _meters_per_unit(target)


def hausdorff_m(
    pred: BaseGeometry, ref: BaseGeometry, crs: CRSLike, *, measure_crs: CRSLike | None = None
) -> float:
    """Hausdorff distance between ``pred`` and ``ref``, in meters.

    Both geometries are in ``crs``. The distance is measured in ``measure_crs`` when given (it
    must be projected), else planar in ``crs`` when it is projected, else geodesically (local
    AEQD; see the module docstring). Two empty geometries are 0.0 apart; an empty and a
    non-empty geometry are ``math.inf`` apart. A coordinate that cannot be projected (for
    example a latitude beyond 90 degrees) also gives ``math.inf``.
    """
    if pred.is_empty and ref.is_empty:
        return 0.0
    if pred.is_empty or ref.is_empty:
        return math.inf
    project, meters = _projector(crs, ref, measure_crs)
    distance = project(pred).hausdorff_distance(project(ref)) * meters
    return distance if math.isfinite(distance) else math.inf


def geometry_equal(
    pred: BaseGeometry,
    ref: BaseGeometry,
    tol_m: float,
    crs: CRSLike,
    *,
    measure_crs: CRSLike | None = None,
) -> bool:
    """Whether ``hausdorff_m(pred, ref) <= tol_m``; the tolerance is in meters and inclusive.

    Measured in ``measure_crs`` (projected) when given, else in ``crs`` when it is projected,
    else geodesically. An empty geometry equals only an empty geometry.
    """
    return hausdorff_m(pred, ref, crs, measure_crs=measure_crs) <= tol_m


def detect_axis_swap(
    pred: BaseGeometry,
    ref: BaseGeometry,
    tol_m: float,
    crs: CRSLike,
    *,
    measure_crs: CRSLike | None = None,
) -> bool:
    """Whether ``pred`` is ``ref`` with latitude and longitude exchanged.

    True only when ``crs`` is geographic (for example EPSG:4326), ``pred`` does not match
    ``ref`` within ``tol_m`` meters, and ``pred`` with its axes swapped does. Measured like
    ``geometry_equal``.
    """
    if not to_crs(crs).is_geographic or pred.is_empty:
        return False
    if geometry_equal(pred, ref, tol_m, crs, measure_crs=measure_crs):
        return False
    return geometry_equal(swap_axes(pred), ref, tol_m, crs, measure_crs=measure_crs)


def _oriented(geometry: BaseGeometry) -> BaseGeometry:
    # Geod sums signed ring areas: shells counterclockwise, holes clockwise.
    return shapely.orient_polygons(geometry, exterior_cw=False)


def area_m2(geometry: BaseGeometry, crs: CRSLike, *, measure_crs: CRSLike | None = None) -> float:
    """Area in square meters: geodesic on the ellipsoid when ``crs`` is geographic and no
    ``measure_crs`` is given, else planar in the projected CRS."""
    if geometry.is_empty:
        return 0.0
    source = to_crs(crs)
    if measure_crs is None and source.is_geographic:
        area, _ = source.get_geod().geometry_area_perimeter(_oriented(geometry))  # type: ignore[union-attr]
        return abs(area)
    project, meters = _projector(source, geometry, measure_crs)
    return project(geometry).area * meters**2


def length_m(geometry: BaseGeometry, crs: CRSLike, *, measure_crs: CRSLike | None = None) -> float:
    """Length in meters (perimeter for polygons): geodesic on the ellipsoid when ``crs`` is
    geographic and no ``measure_crs`` is given, else planar in the projected CRS."""
    if geometry.is_empty:
        return 0.0
    source = to_crs(crs)
    if measure_crs is None and source.is_geographic:
        geod: Geod = source.get_geod()  # type: ignore[assignment]
        return geod.geometry_length(geometry)
    project, meters = _projector(source, geometry, measure_crs)
    return project(geometry).length * meters


def _relative_error(predicted: float, reference: float) -> float:
    if reference == 0:
        return 0.0 if predicted == 0 else math.inf
    return abs(predicted - reference) / abs(reference)


def area_error_rel(
    pred: BaseGeometry, ref: BaseGeometry, crs: CRSLike, *, measure_crs: CRSLike | None = None
) -> float:
    """Relative area error ``|A_pred - A_ref| / A_ref`` (unitless), areas from ``area_m2``.

    A reference area of zero gives 0.0 when the predicted area is also zero, else ``math.inf``.
    """
    return _relative_error(
        area_m2(pred, crs, measure_crs=measure_crs), area_m2(ref, crs, measure_crs=measure_crs)
    )


def length_error_rel(
    pred: BaseGeometry, ref: BaseGeometry, crs: CRSLike, *, measure_crs: CRSLike | None = None
) -> float:
    """Relative length error ``|L_pred - L_ref| / L_ref`` (unitless), lengths from
    ``length_m``. A reference length of zero gives 0.0 when the predicted length is also zero,
    else ``math.inf``."""
    return _relative_error(
        length_m(pred, crs, measure_crs=measure_crs), length_m(ref, crs, measure_crs=measure_crs)
    )


def is_valid_with_reason(geometry: BaseGeometry) -> tuple[bool, str]:
    """OGC validity and the reason from ``shapely.validation.explain_validity``.

    Unitless and CRS-independent (planar in the geometry's own coordinates). A valid geometry,
    including an empty one, gives ``(True, "Valid Geometry")``.
    """
    return bool(geometry.is_valid), explain_validity(geometry)


def topology_signature(geometry: BaseGeometry) -> dict[str, Any]:
    """``{"type", "parts", "rings"}`` of a geometry.

    ``parts`` counts the members of a multi-part geometry or collection (1 for a single
    non-empty geometry, 0 for an empty one). ``rings`` counts polygon shells and holes over all
    parts (0 for points and lines).
    """
    if geometry.is_empty:
        parts = []
    elif hasattr(geometry, "geoms"):
        parts = list(geometry.geoms)  # type: ignore[attr-defined]
    else:
        parts = [geometry]
    rings = 0
    for part in parts:
        if part.geom_type == "Polygon":
            rings += 1 + len(part.interiors)  # type: ignore[attr-defined]
        elif hasattr(part, "geoms"):
            rings += topology_signature(part)["rings"]
    return {"type": geometry.geom_type, "parts": len(parts), "rings": rings}


def topology_equal(pred: BaseGeometry, ref: BaseGeometry) -> bool:
    """Whether both geometries have the same type, part count and ring count.

    Unitless and CRS-independent; coordinates are not compared (see ``geometry_equal``).
    """
    return topology_signature(pred) == topology_signature(ref)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def attribute_differences(
    pred: Mapping[str, Any], ref: Mapping[str, Any], float_tol: float
) -> list[dict[str, Any]]:
    """Attributes that differ, as ``{"attribute", "predicted", "expected"}`` (sorted by name).

    Numbers (not booleans) match when ``|pred - ref| <= float_tol``, an absolute tolerance in
    the attribute's own units; two NaNs match. Every other value must be equal. An attribute
    present on one side only differs (the missing side is reported as null).
    """
    differences = []
    for name in sorted(set(pred) | set(ref), key=str):
        if name not in pred or name not in ref:
            differences.append(
                {"attribute": name, "predicted": pred.get(name), "expected": ref.get(name)}
            )
            continue
        a, b = pred[name], ref[name]
        if _is_number(a) and _is_number(b):
            same = (math.isnan(a) and math.isnan(b)) or abs(a - b) <= float_tol
        else:
            same = type(a) is type(b) and a == b
        if not same:
            differences.append({"attribute": name, "predicted": a, "expected": b})
    return differences


def attributes_equal(pred: Mapping[str, Any], ref: Mapping[str, Any], float_tol: float) -> bool:
    """Whether two attribute mappings match (see ``attribute_differences``)."""
    return not attribute_differences(pred, ref, float_tol)
