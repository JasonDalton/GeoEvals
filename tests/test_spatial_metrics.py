"""Tests for the spatial comparison primitives and the GIS metrics."""

import math

import pytest
from pyproj import Geod, Transformer
from pyproj.exceptions import CRSError
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping

from geoevals.metrics import get_metric, registered_metric_ids
from geoevals.metrics.spatial import (
    area_error_rel,
    area_m2,
    attribute_differences,
    attributes_equal,
    crs_equal,
    detect_axis_swap,
    geometry_equal,
    hausdorff_m,
    is_valid_with_reason,
    length_error_rel,
    length_m,
    topology_equal,
    topology_signature,
)

UTM = "EPSG:32633"  # projected, meters
WGS84 = "EPSG:4326"
SF = (-122.4194, 37.7749)  # lon, lat


def answer(geometry=None, crs=UTM, **fields):
    document = {"status": "ok", "crs": crs, **fields}
    if geometry is not None:
        document["geometry"] = mapping(geometry)
    return document


# Registration


def test_every_story_metric_is_registered():
    expected = {
        "task_success",
        "geometry_match",
        "crs_match",
        "attribute_match",
        "validity_match",
        "status_match",
        "value_abs_error",
        "value_rel_error",
    }
    assert expected <= registered_metric_ids()
    for metric_id in expected:
        metric = get_metric(metric_id)
        assert metric.units
        assert isinstance(metric.higher_is_better, bool)


# Tolerance boundaries


def test_projected_distance_exactly_at_tolerance_passes():
    assert hausdorff_m(Point(0.5, 0), Point(0, 0), UTM) == 0.5
    assert geometry_equal(Point(0.5, 0), Point(0, 0), 0.5, UTM)


def test_projected_distance_tolerance_plus_1e9_m_fails():
    assert not geometry_equal(Point(0.5 + 1e-9, 0), Point(0, 0), 0.5, UTM)


def test_geometry_match_metric_tolerance_boundary():
    metric = get_metric("geometry_match")
    reference = answer(Point(0, 0))
    at = metric.score(answer(Point(0.5, 0)), reference, {"tol_m": 0.5})
    beyond = metric.score(answer(Point(0.5 + 1e-9, 0)), reference, {"tol_m": 0.5})
    assert (at.value, at.passed) == (1.0, True)
    assert (beyond.value, beyond.passed) == (0.0, False)
    assert beyond.detail["hausdorff_m"] > 0.5


def test_geodesic_distance_boundary():
    geod = Geod(ellps="WGS84")
    lon, lat, _ = geod.fwd(*SF, 45.0, 100.0)
    ref, pred = Point(SF), Point(lon, lat)
    distance = hausdorff_m(pred, ref, WGS84)
    _, _, exact = geod.inv(*SF, lon, lat)
    assert distance == pytest.approx(exact, abs=1e-6)
    assert geometry_equal(pred, ref, distance, WGS84)
    assert not geometry_equal(pred, ref, distance - 1e-9, WGS84)


def test_us_survey_feet_are_converted_to_meters():
    # EPSG:2227 (California zone 3) is in US survey feet.
    distance = hausdorff_m(
        Point(6_000_000 + 1, 2_000_000), Point(6_000_000, 2_000_000), "EPSG:2227"
    )
    assert distance == pytest.approx(1200 / 3937)


def test_measure_crs_projects_geographic_input():
    ref = Point(15.0, 0.0)  # central meridian of UTM 33N
    pred = Point(15.0, 0.0001)
    distance = hausdorff_m(pred, ref, WGS84, measure_crs=UTM)
    assert distance == pytest.approx(11.06, abs=0.01)
    with pytest.raises(ValueError, match="not a projected CRS"):
        hausdorff_m(pred, ref, WGS84, measure_crs=WGS84)


# Empty geometry


def test_empty_prediction_vs_non_empty_reference_fails():
    assert hausdorff_m(Point(), Point(0, 0), UTM) == math.inf
    assert not geometry_equal(Point(), Point(0, 0), 1e9, UTM)
    reference = answer(Point(0, 0))
    prediction = answer(geometry=None, crs=UTM)
    prediction["geometry"] = {"type": "Point", "coordinates": []}
    result = get_metric("geometry_match").score(prediction, reference, {"tol_m": 10})
    assert result.passed is False
    assert result.detail["reason"] == "empty_prediction"
    assert result.detail["hausdorff_m"] is None


def test_two_empty_geometries_match():
    assert hausdorff_m(Polygon(), Polygon(), UTM) == 0.0
    assert geometry_equal(Polygon(), Polygon(), 0.0, UTM)


# Axis order


def test_axis_swapped_point_is_detected():
    ref = Point(SF)
    swapped = Point(SF[1], SF[0])
    assert detect_axis_swap(swapped, ref, 1.0, WGS84)
    assert not detect_axis_swap(ref, ref, 1.0, WGS84)
    assert not detect_axis_swap(Point(0, 0), ref, 1.0, WGS84)
    assert not detect_axis_swap(Point(2, 1), Point(1, 2), 1.0, UTM)


def test_axis_swapped_point_is_reported_in_detail():
    reference = answer(Point(SF), crs=WGS84)
    prediction = answer(Point(SF[1], SF[0]), crs=WGS84)
    result = get_metric("geometry_match").score(prediction, reference, {"tol_m": 1.0})
    assert result.passed is False
    assert result.detail["axis_swapped"] is True
    assert result.detail["reason"] == "axis_order_swapped"
    success = get_metric("task_success").score(prediction, reference, {"tol_m": 1.0})
    assert success.value == 0.0
    assert success.detail["failed"] == ["geometry_match"]
    assert success.detail["checks"]["geometry_match"]["detail"]["axis_swapped"] is True


# CRS


def test_crs_equal():
    assert crs_equal("EPSG:4326", "epsg:4326")
    assert crs_equal("EPSG:32633", "+proj=utm +zone=33 +datum=WGS84 +units=m +no_defs +type=crs")
    assert not crs_equal("EPSG:4326", "EPSG:3857")
    assert not crs_equal("EPSG:4326", "OGC:CRS84")  # axis order differs
    assert crs_equal("EPSG:4326", "OGC:CRS84", ignore_axis_order=True)
    assert not crs_equal("EPSG:4258", "OGC:CRS84", ignore_axis_order=True)  # another datum
    with pytest.raises(CRSError):
        crs_equal("EPSG:999999", "EPSG:4326")


def test_crs_match_metric():
    metric = get_metric("crs_match")
    assert metric.score({"crs": "EPSG:4326"}, {"crs": "EPSG:4326"}, {}).passed is True
    wrong = metric.score({"crs": "EPSG:3857"}, {"crs": "EPSG:4326"}, {})
    assert wrong.passed is False
    assert wrong.detail["reason"] == "crs_differs"
    assert metric.score({}, {"crs": "EPSG:4326"}, {}).detail["reason"] == "missing_crs"
    bad = metric.score({"crs": "EPSG:999999"}, {"crs": "EPSG:4326"}, {})
    assert bad.detail["reason"] == "unreadable_crs"


def test_crs_match_ignores_axis_order():
    # Coordinates are always (x, y); geometry_match catches a swap, not the label.
    metric = get_metric("crs_match")
    assert metric.version == "1.1.0"
    assert metric.score({"crs": "EPSG:4326"}, {"crs": "OGC:CRS84"}, {}).passed is True
    assert metric.score({"crs": "OGC:CRS84"}, {"crs": "EPSG:4326"}, {}).passed is True
    other_datum = metric.score({"crs": "EPSG:4258"}, {"crs": "OGC:CRS84"}, {})
    assert other_datum.detail["reason"] == "crs_differs"


def test_geometry_match_reprojects_a_prediction_in_another_crs():
    reference = answer(Point(15.0, 10.0), crs=WGS84)
    x, y = Transformer.from_crs(WGS84, UTM, always_xy=True).transform(15.0, 10.0)
    prediction = {"crs": UTM, "geometry": {"type": "Point", "coordinates": [x, y]}}
    result = get_metric("geometry_match").score(prediction, reference, {"tol_m": 0.1})
    assert result.passed is True
    assert result.detail["reprojected_from"] == UTM


# Area, length, validity, topology


def test_area_and_length_errors():
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    larger = Polygon([(0, 0), (101, 0), (101, 100), (0, 100)])
    assert area_m2(square, UTM) == 10_000
    assert area_error_rel(larger, square, UTM) == pytest.approx(0.01)
    assert length_error_rel(
        LineString([(0, 0), (110, 0)]), LineString([(0, 0), (100, 0)]), UTM
    ) == (pytest.approx(0.1))
    assert area_error_rel(Polygon(), Polygon(), UTM) == 0.0
    assert area_error_rel(square, Polygon(), UTM) == math.inf


def test_geodesic_area_and_length():
    # 1 x 1 degree cell at the equator; its geodesic area is about 12,308 km^2.
    cell = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    assert area_m2(cell, WGS84) == pytest.approx(12_308e6, rel=1e-3)
    # Clockwise orientation gives the same (positive) area.
    assert area_m2(Polygon(list(cell.exterior.coords)[::-1]), WGS84) == area_m2(cell, WGS84)
    assert length_m(LineString([(0, 0), (1, 0)]), WGS84) == pytest.approx(111_319.49, abs=0.01)


def test_geometry_match_area_tolerance():
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    larger = Polygon([(0, 0), (101, 0), (101, 100), (0, 100)])
    metric = get_metric("geometry_match")
    params = {"tol_m": 1.0, "area_tol_rel": 0.005}
    result = metric.score(answer(larger), answer(square), params)
    assert result.passed is False
    assert result.detail["area_error_rel"] == pytest.approx(0.01)
    assert metric.score(answer(larger), answer(square), {**params, "area_tol_rel": 0.01}).passed


def test_is_valid_with_reason():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    valid, reason = is_valid_with_reason(bowtie)
    assert not valid
    assert reason.startswith("Self-intersection")
    assert is_valid_with_reason(Point(0, 0)) == (True, "Valid Geometry")


def test_validity_match_metric():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    metric = get_metric("validity_match")
    assert metric.score(answer(square), answer(square), {}).passed is True
    result = metric.score(answer(bowtie), answer(square), {})
    assert result.passed is False
    assert result.detail["predicted"]["valid"] is False


def test_topology():
    square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    holed = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(2, 2), (3, 2), (3, 3), (2, 3)]])
    assert topology_signature(holed) == {"type": "Polygon", "parts": 1, "rings": 2}
    assert topology_signature(MultiPolygon([square, holed])) == {
        "type": "MultiPolygon",
        "parts": 2,
        "rings": 3,
    }
    assert topology_equal(square, Polygon([(5, 5), (6, 5), (6, 6)]))
    assert not topology_equal(square, MultiPolygon([square]))
    assert not topology_equal(square, holed)
    result = get_metric("geometry_match").score(
        answer(MultiPolygon([square])), answer(square), {"tol_m": 0}
    )
    assert result.passed is False
    assert result.detail["topology"]["expected"]["type"] == "Polygon"
    assert (
        get_metric("geometry_match")
        .score(answer(MultiPolygon([square])), answer(square), {"tol_m": 0, "topology": False})
        .passed
    )


# Attributes and features


def test_attributes_equal():
    assert attributes_equal({"a": 1.0, "b": "x"}, {"a": 1.0 + 1e-10, "b": "x"}, 1e-9)
    assert not attributes_equal({"a": 1.0}, {"a": 1.1}, 1e-9)
    assert attributes_equal({"a": math.nan}, {"a": math.nan}, 0.0)
    assert not attributes_equal({"a": True}, {"a": 1}, 0.0)
    assert attribute_differences({"a": 1}, {"b": 1}, 0.0) == [
        {"attribute": "a", "predicted": 1, "expected": None},
        {"attribute": "b", "predicted": None, "expected": 1},
    ]


def _collection(*features):
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": mapping(g), "properties": p} for g, p in features
        ],
    }


def test_features_are_paired_by_key():
    reference = {
        "crs": UTM,
        "features": _collection(
            (Point(0, 0), {"id": 1, "count": 2}), (Point(10, 0), {"id": 2, "count": 5})
        ),
    }
    prediction = {
        "crs": UTM,
        "features": _collection(
            (Point(10, 0), {"id": 2, "count": 5}), (Point(0, 0.5), {"id": 1, "count": 3})
        ),
    }
    params = {"key": "id", "tol_m": 1.0}
    assert get_metric("geometry_match").score(prediction, reference, params).passed is True
    attributes = get_metric("attribute_match").score(prediction, reference, params)
    assert attributes.passed is False
    assert attributes.detail["features"] == [
        {"feature": 1, "differences": [{"attribute": "count", "predicted": 3, "expected": 2}]}
    ]
    # Pairing by position fails the geometry check.
    assert get_metric("geometry_match").score(prediction, reference, {"tol_m": 1.0}).passed is False


def test_missing_and_extra_features_fail():
    reference = {"crs": UTM, "features": _collection((Point(0, 0), {"id": 1}))}
    prediction = {"crs": UTM, "features": _collection((Point(0, 0), {"id": 9}))}
    result = get_metric("geometry_match").score(prediction, reference, {"key": "id"})
    assert result.passed is False
    assert result.detail["missing"] == [1]
    assert result.detail["extra"] == [9]


def test_features_are_paired_by_a_composite_key():
    # A one-to-many join: point 1 is in two zones, so no single property is unique.
    reference = {
        "crs": UTM,
        "features": _collection(
            (Point(0, 0), {"point": 1, "zone": "a"}),
            (Point(0, 0), {"point": 1, "zone": "b"}),
            (Point(5, 0), {"point": 2, "zone": "a"}),
        ),
    }
    prediction = {
        "crs": UTM,
        "features": _collection(
            (Point(5, 0), {"point": 2, "zone": "a"}),
            (Point(0, 0), {"point": 1, "zone": "b"}),
            (Point(0, 0), {"point": 1, "zone": "c"}),
        ),
    }
    params = {"key": ["point", "zone"]}
    result = get_metric("geometry_match").score(prediction, reference, params)
    assert result.passed is False
    assert (result.detail["missing"], result.detail["extra"]) == ([[1, "a"]], [[1, "c"]])
    assert get_metric("attribute_match").score(reference, reference, params).passed is True
    with pytest.raises(ValueError, match="repeat key 'point'"):
        get_metric("geometry_match").score(reference, reference, {"key": "point"})


def test_task_success_checks_the_feature_count_on_its_own():
    reference = {
        "status": "ok",
        "crs": UTM,
        "features": _collection((Point(0, 0), {"id": 1}), (Point(5, 0), {"id": 2})),
    }
    metric = get_metric("task_success")
    passed = metric.score(reference, reference, {"key": "id"})
    assert passed.detail["checks"]["feature_count"] == {
        "passed": True,
        "detail": {"predicted": 2, "expected": 2},
    }
    # Same count, wrong pairing: only the pairing checks fail.
    relabeled = {
        **reference,
        "features": _collection((Point(0, 0), {"id": 1}), (Point(5, 0), {"id": 3})),
    }
    result = metric.score(relabeled, reference, {"key": "id"})
    assert result.detail["failed"] == ["geometry_match", "validity_match", "attribute_match"]
    short = {**reference, "features": _collection((Point(0, 0), {"id": 1}))}
    result = metric.score(short, reference, {"key": "id"})
    assert result.detail["checks"]["feature_count"]["detail"] == {
        "reason": "feature_count_differs",
        "predicted": 1,
        "expected": 2,
    }
    assert "feature_count" in result.detail["failed"]
    missing = metric.score({"status": "ok", "crs": UTM}, reference, {})
    assert missing.detail["checks"]["feature_count"]["detail"] == {
        "reason": "missing_features",
        "expected": 2,
    }
    assert (
        "feature_count"
        not in metric.score(answer(Point(0, 0)), answer(Point(0, 0)), {}).detail["checks"]
    )


def test_mixed_geometry_types_compare_as_collections():
    collection = {
        "type": "GeometryCollection",
        "geometries": [mapping(Point(0, 0)), mapping(LineString([(0, 0), (1, 1)]))],
    }
    reference = {"crs": UTM, "geometry": collection}
    assert get_metric("geometry_match").score(reference, reference, {}).passed is True
    other = {"crs": UTM, "geometry": mapping(Point(0, 0))}
    result = get_metric("geometry_match").score(other, reference, {"tol_m": 10})
    assert result.passed is False
    assert result.detail["topology"]["expected"]["type"] == "GeometryCollection"


# Values


def test_value_metrics():
    reference = {"status": "ok", "value": 100.0, "units": "m"}
    absolute, relative = get_metric("value_abs_error"), get_metric("value_rel_error")
    result = absolute.score({"value": 101.0, "units": "m"}, reference, {"abs_tol": 1.0})
    assert (result.value, result.passed) == (1.0, True)
    assert (
        absolute.score({"value": 101.0, "units": "m"}, reference, {"abs_tol": 0.5}).passed is False
    )
    result = relative.score({"value": 101.0, "units": "m"}, reference, {"rel_tol": 0.01})
    assert result.value == pytest.approx(0.01)
    mismatch = absolute.score({"value": 328.084, "units": "ft"}, reference, {"abs_tol": 1})
    assert (mismatch.value, mismatch.passed, mismatch.detail["reason"]) == (
        None,
        False,
        "units_mismatch",
    )
    zero = relative.score({"value": 1.0}, {"value": 0}, {})
    assert (zero.value, zero.passed, zero.detail["reason"]) == (None, False, "zero_reference")
    assert relative.score({"value": 0.0}, {"value": 0}, {}).value == 0.0


# Applicability, null output, task_success


def test_metrics_that_do_not_apply_return_null():
    reference = {"status": "invalid_request"}
    for metric_id in ("geometry_match", "crs_match", "attribute_match", "value_abs_error"):
        result = get_metric(metric_id).score({"status": "ok"}, reference, {})
        assert (result.value, result.passed) == (None, None)
        assert result.detail == {"applicable": False}


def test_null_output_fails_every_applicable_check():
    reference = answer(Point(0, 0))
    result = get_metric("task_success").score(None, reference, {"tol_m": 1})
    assert result.value == 0.0
    assert result.detail["failed"] == [
        "status_match",
        "crs_match",
        "geometry_match",
        "validity_match",
    ]
    assert get_metric("geometry_match").score(None, reference, {}).detail["reason"] == (
        "missing_geometry"
    )


def test_task_success_passes_when_every_check_passes():
    reference = answer(Point(0, 0))
    result = get_metric("task_success").score(answer(Point(0.2, 0)), reference, {"tol_m": 0.5})
    assert (result.value, result.passed) == (1.0, True)
    assert set(result.detail["checks"]) == {
        "status_match",
        "crs_match",
        "geometry_match",
        "validity_match",
    }
    assert "failed" not in result.detail


def test_task_success_on_an_abstention_case():
    metric = get_metric("task_success")
    reference = {"status": "invalid_request"}
    assert metric.score({"status": "invalid_request"}, reference, {}).passed is True
    answered = metric.score(answer(Point(0, 0)), reference, {})
    assert answered.passed is False
    assert answered.detail["failed"] == ["status_match"]


def test_task_success_value_checks():
    metric = get_metric("task_success")
    reference = {"status": "ok", "value": 100.0, "units": "m"}
    prediction = {"status": "ok", "value": 100.5, "units": "m"}
    assert metric.score(prediction, reference, {}).passed is False  # exact by default
    assert metric.score(prediction, reference, {"rel_tol": 0.01}).passed is True
    assert metric.score(prediction, reference, {"abs_tol": 0.1, "rel_tol": 0.01}).passed is False
    boolean = {"status": "ok", "value": False}
    assert metric.score({"status": "ok", "value": False}, boolean, {}).passed is True
    assert metric.score({"status": "ok", "value": 0}, boolean, {}).passed is False


def test_task_success_reason_match():
    metric = get_metric("task_success")
    reference = {"status": "ok", "value": False, "reason": "self_intersection"}
    assert metric.score(reference, reference, {}).passed is True
    wrong = metric.score({**reference, "reason": "unclosed_ring"}, reference, {})
    assert wrong.detail["failed"] == ["reason_match"]
    assert wrong.detail["checks"]["reason_match"]["detail"] == {
        "reason": "reason_differs",
        "predicted": "unclosed_ring",
        "expected": "self_intersection",
    }
    without_reason = {"status": "ok", "value": False}
    assert set(metric.score(reference, without_reason, {}).detail["checks"]) == {
        "status_match",
        "value_equal",
    }
