"""Metrics for the GIS output contract, built on ``geoevals.metrics.spatial``.

A prediction and its reference are mappings with ``status`` and, for an answer, one of
``geometry`` (a GeoJSON geometry), ``features`` (a GeoJSON FeatureCollection) or ``value`` (with
optional ``units``), plus ``crs``. Each metric is one independent check. It applies to a case
only when the reference has the field it checks; otherwise it scores ``value = None`` and
``passed = None`` with ``detail = {"applicable": False}``, so the case is left out of the
metric's aggregate. ``task_success`` passes only when every applicable check passes.

Tolerance params (all inclusive, default 0.0, which means exact): ``tol_m`` (meters),
``area_tol_rel`` and ``length_tol_rel`` (unitless, checked only when given), ``float_tol``
(absolute, in each attribute's units), ``abs_tol`` (the reference value's units) and
``rel_tol`` (unitless). Other params: ``measure_crs`` (a projected CRS to measure in instead of
the reference CRS), ``topology`` (compare type, part and ring counts; default true) and ``key``
(the feature property that pairs predicted and reference features; by default features pair
by position). The full definitions are in ``docs/metrics.md``.
"""

import math
from collections.abc import Callable, Mapping
from typing import Any, TypeGuard

from pyproj import Transformer
from pyproj.exceptions import CRSError
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from geoevals.metrics.base import Metric, MetricValue
from geoevals.metrics.spatial import (
    area_error_rel,
    attribute_differences,
    crs_equal,
    detect_axis_swap,
    hausdorff_m,
    is_valid_with_reason,
    length_error_rel,
    reproject,
    to_crs,
    topology_signature,
)
from geoevals.metrics.status import StatusMatch

DEFAULT_CRS = "OGC:CRS84"
"""CRS of a geometry whose document has no ``crs``: WGS 84 longitude/latitude, as in GeoJSON."""

Check = Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], MetricValue | None]
"""A check returns ``None`` when it does not apply to the reference."""


def _document(value: Any) -> Mapping[str, Any]:
    """A prediction that is not a mapping (for example a null output) has no fields."""
    return value if isinstance(value, Mapping) else {}


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _verdict(passed: bool, detail: dict[str, Any]) -> MetricValue:
    return MetricValue(value=1.0 if passed else 0.0, passed=passed, detail=detail)


def _failed(reason: str, **detail: Any) -> MetricValue:
    return _verdict(False, {"reason": reason, **detail})


def _parse_geometry(value: Any) -> BaseGeometry | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return shape(dict(value))
    except Exception:
        return None


def _features(document: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    collection = document.get("features")
    if not isinstance(collection, Mapping):
        return None
    features = collection.get("features")
    if not isinstance(features, list) or not all(isinstance(f, Mapping) for f in features):
        return None
    return features


def _properties(feature: Mapping[str, Any]) -> Mapping[str, Any]:
    properties = feature.get("properties")
    return properties if isinstance(properties, Mapping) else {}


def _pair_features(
    pred: list[Mapping[str, Any]], ref: list[Mapping[str, Any]], key: str | None
) -> tuple[list[tuple[Any, Mapping[str, Any], Mapping[str, Any]]], dict[str, Any]]:
    """Pair features by ``key`` (or by position). Returns the pairs, each labeled by its key
    value or index, and the pairing problems (empty when every feature pairs exactly once)."""
    problems: dict[str, Any] = {}
    if len(pred) != len(ref):
        problems["feature_count"] = {"predicted": len(pred), "expected": len(ref)}
    if key is None:
        n = min(len(pred), len(ref))
        pairs = [(i, pred[i], ref[i]) for i in range(n)]
        if len(ref) > n:
            problems["missing"] = list(range(n, len(ref)))
        if len(pred) > n:
            problems["extra"] = list(range(n, len(pred)))
        return pairs, problems

    def index(features: list[Mapping[str, Any]]) -> tuple[dict[str, Any], list[Any]]:
        by_key: dict[str, Any] = {}
        duplicates = []
        for feature in features:
            value = _properties(feature).get(key)
            label = repr(value)
            if label in by_key:
                duplicates.append(value)
            by_key[label] = (value, feature)
        return by_key, duplicates

    ref_index, ref_duplicates = index(ref)
    if ref_duplicates:
        raise ValueError(f"reference features repeat key {key!r} values {ref_duplicates}")
    pred_index, pred_duplicates = index(pred)
    if pred_duplicates:
        problems["duplicate"] = pred_duplicates
    pairs = [
        (value, pred_index[label][1], feature)
        for label, (value, feature) in ref_index.items()
        if label in pred_index
    ]
    missing = [value for label, (value, _) in ref_index.items() if label not in pred_index]
    extra = [value for label, (value, _) in pred_index.items() if label not in ref_index]
    if missing:
        problems["missing"] = missing
    if extra:
        problems["extra"] = extra
    return pairs, problems


def _check_pairs(
    pred: Mapping[str, Any],
    ref: Mapping[str, Any],
    params: Mapping[str, Any],
    compare: Callable[[Mapping[str, Any], Mapping[str, Any]], tuple[bool, dict[str, Any]]],
) -> MetricValue:
    """Run ``compare(pred_feature, ref_feature)`` on every feature pair."""
    ref_features = _features(ref)
    assert ref_features is not None
    pred_features = _features(pred)
    if pred_features is None:
        return _failed("missing_features")
    pairs, problems = _pair_features(pred_features, ref_features, params.get("key"))
    failures = []
    for label, pred_feature, ref_feature in pairs:
        passed, detail = compare(pred_feature, ref_feature)
        if not passed:
            failures.append({"feature": label, **detail})
    detail = dict(problems)
    if failures:
        detail["features"] = failures
    return _verdict(not problems and not failures, detail)


# Geometry


def _crs_pair(
    pred: Mapping[str, Any], ref: Mapping[str, Any]
) -> tuple[Any, Callable[[BaseGeometry], BaseGeometry], dict[str, Any]]:
    """The reference CRS, a function that moves predicted geometries into it, and detail.

    A prediction without ``crs`` is taken to be in the reference CRS. A prediction in another
    CRS is reprojected, so ``geometry_match`` stays independent of ``crs_match``. Raises
    ``CRSError`` when the predicted CRS cannot be parsed.
    """
    ref_crs = ref.get("crs") or DEFAULT_CRS
    pred_crs = pred.get("crs")
    if pred_crs is None or crs_equal(pred_crs, ref_crs):
        return ref_crs, lambda g: g, {}
    transformer = Transformer.from_crs(to_crs(pred_crs), to_crs(ref_crs), always_xy=True)
    return ref_crs, lambda g: reproject(g, transformer), {"reprojected_from": pred_crs}


def compare_geometries(
    pred: BaseGeometry, ref: BaseGeometry, crs: Any, params: Mapping[str, Any]
) -> tuple[bool, dict[str, Any]]:
    """Compare two geometries in ``crs`` under the ``geometry_match`` params.

    Returns whether they match and the detail: ``hausdorff_m`` (null when infinite), ``tol_m``,
    and, when they apply, ``reason``, ``axis_swapped``, ``topology``, ``area_error_rel`` and
    ``length_error_rel``.
    """
    tol_m = float(params.get("tol_m", 0.0))
    measure_crs = params.get("measure_crs")
    distance = hausdorff_m(pred, ref, crs, measure_crs=measure_crs)
    passed = distance <= tol_m
    detail: dict[str, Any] = {"hausdorff_m": _finite(distance), "tol_m": tol_m}
    if pred.is_empty != ref.is_empty:
        detail["reason"] = "empty_prediction" if pred.is_empty else "empty_reference"
    elif not passed and detect_axis_swap(pred, ref, tol_m, crs, measure_crs=measure_crs):
        detail["reason"] = "axis_order_swapped"
        detail["axis_swapped"] = True
    if params.get("topology", True):
        predicted, expected = topology_signature(pred), topology_signature(ref)
        if predicted != expected:
            passed = False
            detail["topology"] = {"predicted": predicted, "expected": expected}
    for name, error in (("area", area_error_rel), ("length", length_error_rel)):
        tolerance = params.get(f"{name}_tol_rel")
        if tolerance is not None:
            value = error(pred, ref, crs, measure_crs=measure_crs)
            passed = passed and value <= float(tolerance)
            detail[f"{name}_error_rel"] = _finite(value)
            detail[f"{name}_tol_rel"] = float(tolerance)
    return passed, detail


def check_geometry(
    pred: Mapping[str, Any], ref: Mapping[str, Any], params: Mapping[str, Any]
) -> MetricValue | None:
    """``geometry_match``: geometries match within ``tol_m`` meters (see ``compare_geometries``)."""
    if ref.get("geometry") is None and _features(ref) is None:
        return None
    try:
        crs, reproject, crs_detail = _crs_pair(pred, ref)
    except CRSError as error:
        return _failed("unreadable_crs", error=str(error))

    def compare(pred_geometry: Any, ref_geometry: Any) -> tuple[bool, dict[str, Any]]:
        expected = _parse_geometry(ref_geometry)
        if expected is None:
            raise ValueError(f"reference geometry is not GeoJSON: {ref_geometry!r}")
        if pred_geometry is None:
            return False, {"reason": "missing_geometry"}
        predicted = _parse_geometry(pred_geometry)
        if predicted is None:
            return False, {"reason": "unreadable_geometry"}
        return compare_geometries(reproject(predicted), expected, crs, params)

    if ref.get("geometry") is not None:
        passed, detail = compare(pred.get("geometry"), ref["geometry"])
        return _verdict(passed, {**crs_detail, **detail})
    result = _check_pairs(
        pred, ref, params, lambda p, r: compare(p.get("geometry"), r.get("geometry"))
    )
    return MetricValue(result.value, result.passed, {**crs_detail, **result.detail})


# CRS


def check_crs(
    pred: Mapping[str, Any], ref: Mapping[str, Any], params: Mapping[str, Any]
) -> MetricValue | None:
    """``crs_match``: the predicted ``crs`` equals the reference ``crs`` (``crs_equal``)."""
    if ref.get("crs") is None:
        return None
    expected = ref["crs"]
    predicted = pred.get("crs")
    if predicted is None:
        return _failed("missing_crs", expected=expected)
    try:
        equal = crs_equal(predicted, expected)
    except CRSError as error:
        return _failed("unreadable_crs", predicted=predicted, expected=expected, error=str(error))
    if equal:
        return _verdict(True, {})
    return _failed("crs_differs", predicted=predicted, expected=expected)


# Attributes


def check_attributes(
    pred: Mapping[str, Any], ref: Mapping[str, Any], params: Mapping[str, Any]
) -> MetricValue | None:
    """``attribute_match``: paired features have the same properties within ``float_tol``."""
    if _features(ref) is None:
        return None
    float_tol = float(params.get("float_tol", 0.0))

    def compare(p: Mapping[str, Any], r: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
        differences = attribute_differences(_properties(p), _properties(r), float_tol)
        return not differences, {"differences": differences}

    return _check_pairs(pred, ref, params, compare)


# Validity


def check_validity(
    pred: Mapping[str, Any], ref: Mapping[str, Any], params: Mapping[str, Any]
) -> MetricValue | None:
    """``validity_match``: the predicted geometry is valid exactly when the reference is."""
    if ref.get("geometry") is None and _features(ref) is None:
        return None

    def compare(pred_geometry: Any, ref_geometry: Any) -> tuple[bool, dict[str, Any]]:
        expected = _parse_geometry(ref_geometry)
        if expected is None:
            raise ValueError(f"reference geometry is not GeoJSON: {ref_geometry!r}")
        predicted = _parse_geometry(pred_geometry)
        if predicted is None:
            return False, {"reason": "missing_geometry"}
        (pred_valid, pred_reason), (ref_valid, ref_reason) = (
            is_valid_with_reason(predicted),
            is_valid_with_reason(expected),
        )
        detail = {
            "predicted": {"valid": pred_valid, "reason": pred_reason},
            "expected": {"valid": ref_valid, "reason": ref_reason},
        }
        return pred_valid == ref_valid, detail

    if ref.get("geometry") is not None:
        passed, detail = compare(pred.get("geometry"), ref["geometry"])
        return _verdict(passed, detail if not passed else {})
    return _check_pairs(
        pred, ref, params, lambda p, r: compare(p.get("geometry"), r.get("geometry"))
    )


# Values


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _value_pair(
    pred: Mapping[str, Any], ref: Mapping[str, Any]
) -> tuple[float, float] | MetricValue | None:
    """The predicted and reference numbers, a failed ``MetricValue`` (null value), or ``None``
    when the reference has no numeric value."""
    expected = ref.get("value")
    if not _is_number(expected):
        return None
    predicted = pred.get("value")
    detail: dict[str, Any] = {"predicted": predicted, "expected": expected}
    if not _is_number(predicted) or not math.isfinite(predicted):
        return MetricValue(None, False, {"reason": "missing_value", **detail})
    if "units" in ref and pred.get("units") != ref["units"]:
        detail.update(predicted_units=pred.get("units"), expected_units=ref["units"])
        return MetricValue(None, False, {"reason": "units_mismatch", **detail})
    return float(predicted), float(expected)


def check_value_abs(
    pred: Mapping[str, Any], ref: Mapping[str, Any], params: Mapping[str, Any]
) -> MetricValue | None:
    """``value_abs_error``: ``|pred - ref|`` in the reference units, passed when <= ``abs_tol``."""
    pair = _value_pair(pred, ref)
    if not isinstance(pair, tuple):
        return pair
    error = abs(pair[0] - pair[1])
    tolerance = float(params.get("abs_tol", 0.0))
    passed = error <= tolerance
    detail = {} if passed else {"predicted": pair[0], "expected": pair[1], "abs_tol": tolerance}
    return MetricValue(error, passed, detail)


def check_value_rel(
    pred: Mapping[str, Any], ref: Mapping[str, Any], params: Mapping[str, Any]
) -> MetricValue | None:
    """``value_rel_error``: ``|pred - ref| / |ref|`` (unitless), passed when <= ``rel_tol``.

    A reference of zero gives 0.0 when the prediction is also zero; otherwise the relative
    error is undefined: null value, failed, reason ``zero_reference``.
    """
    pair = _value_pair(pred, ref)
    if not isinstance(pair, tuple):
        return pair
    predicted, expected = pair
    if expected == 0 and predicted != 0:
        return MetricValue(
            None, False, {"reason": "zero_reference", "predicted": predicted, "expected": 0.0}
        )
    error = 0.0 if expected == 0 else abs(predicted - expected) / abs(expected)
    tolerance = float(params.get("rel_tol", 0.0))
    passed = error <= tolerance
    detail = {} if passed else {"predicted": predicted, "expected": expected, "rel_tol": tolerance}
    return MetricValue(error, passed, detail)


def check_value_equal(
    pred: Mapping[str, Any], ref: Mapping[str, Any], params: Mapping[str, Any]
) -> MetricValue | None:
    """A non-numeric reference ``value`` (for example a boolean) must be equal, type included."""
    if "value" not in ref or _is_number(ref["value"]):
        return None
    expected, predicted = ref["value"], pred.get("value")
    if type(predicted) is type(expected) and predicted == expected:
        return _verdict(True, {})
    return _failed("value_differs", predicted=predicted, expected=expected)


def check_status(
    pred: Mapping[str, Any], ref: Mapping[str, Any], params: Mapping[str, Any]
) -> MetricValue | None:
    """``status_match``, applicable when the reference has a ``status``."""
    if "status" not in ref:
        return None
    return StatusMatch().score(pred, ref, params)


# Registered metrics

NOT_APPLICABLE = MetricValue(value=None, passed=None, detail={"applicable": False})


class _CheckMetric(Metric):
    check: Check

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        result = type(self).check(_document(prediction), _document(reference), params)
        return NOT_APPLICABLE if result is None else result


class GeometryMatch(_CheckMetric):
    """1.0 when the geometry (or every paired feature geometry) matches within ``tol_m``
    meters, with topology and, when given, relative area and length checks."""

    id = "geometry_match"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True
    check = staticmethod(check_geometry)


class CrsMatch(_CheckMetric):
    """1.0 when the predicted CRS equals the reference CRS (``pyproj.CRS.equals``)."""

    id = "crs_match"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True
    check = staticmethod(check_crs)


class AttributeMatch(_CheckMetric):
    """1.0 when every paired feature has the reference properties within ``float_tol``."""

    id = "attribute_match"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True
    check = staticmethod(check_attributes)


class ValidityMatch(_CheckMetric):
    """1.0 when the predicted geometry's OGC validity equals the reference's."""

    id = "validity_match"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True
    check = staticmethod(check_validity)


class ValueAbsError(_CheckMetric):
    """Absolute error of a numeric ``value``, in the reference ``units``."""

    id = "value_abs_error"
    version = "1.0.0"
    units = "reference units"
    higher_is_better = False
    check = staticmethod(check_value_abs)


class ValueRelError(_CheckMetric):
    """Relative error of a numeric ``value`` (unitless)."""

    id = "value_rel_error"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = False
    check = staticmethod(check_value_rel)


def _task_checks(params: Mapping[str, Any]) -> list[tuple[str, Check]]:
    checks: list[tuple[str, Check]] = [
        ("status_match", check_status),
        ("crs_match", check_crs),
        ("geometry_match", check_geometry),
        ("validity_match", check_validity),
        ("attribute_match", check_attributes),
        ("value_equal", check_value_equal),
    ]
    if "abs_tol" in params or "rel_tol" not in params:
        checks.append(("value_abs_error", check_value_abs))
    if "rel_tol" in params:
        checks.append(("value_rel_error", check_value_rel))
    return checks


class TaskSuccess(Metric):
    """1.0 when every check that applies to the reference passes, else 0.0.

    The checks are ``status_match``, ``crs_match``, ``geometry_match``, ``validity_match``,
    ``attribute_match``, ``value_equal`` (non-numeric values) and, for a numeric value,
    ``value_abs_error`` (when ``abs_tol`` is given, or when neither ``abs_tol`` nor ``rel_tol``
    is) and ``value_rel_error`` (when ``rel_tol`` is given). All take this metric's params.
    ``detail.checks`` holds every applicable check's ``passed`` and ``detail``;
    ``detail.failed`` lists the failed checks.
    """

    id = "task_success"
    version = "1.0.0"
    units = "fraction"
    higher_is_better = True

    def score(self, prediction: Any, reference: Any, params: Mapping[str, Any]) -> MetricValue:
        pred, ref = _document(prediction), _document(reference)
        checks: dict[str, Any] = {}
        for name, check in _task_checks(params):
            result = check(pred, ref, params)
            if result is not None:
                checks[name] = {"passed": result.passed, "detail": result.detail}
        if not checks:
            return NOT_APPLICABLE
        failed = [name for name, check in checks.items() if check["passed"] is not True]
        detail: dict[str, Any] = {"checks": checks}
        if failed:
            detail["failed"] = failed
        return _verdict(not failed, detail)


SPATIAL_METRICS: tuple[Metric, ...] = (
    TaskSuccess(),
    GeometryMatch(),
    CrsMatch(),
    AttributeMatch(),
    ValidityMatch(),
    ValueAbsError(),
    ValueRelError(),
)
"""The GIS metrics registered in ``geoevals.metrics`` (``status_match`` is registered there
too)."""
