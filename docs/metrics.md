# Metrics

GeoEvals scores a GIS answer on independent checks: task status, CRS, geometry, validity,
topology, attributes and values. Each check has explicit units and an explicit tolerance. No
metric compares code or text.

Metrics are versioned (semver). A change to any definition in this document is a version bump
of the metric it touches, and run results record the version of every metric they use.

## The output contract

A prediction and its reference are JSON objects:

| Field | Meaning |
| --- | --- |
| `status` | `ok`, `needs_clarification`, `insufficient_data` or `invalid_request` |
| `geometry` | a GeoJSON geometry |
| `features` | a GeoJSON FeatureCollection |
| `value`, `units` | a scalar answer (number, boolean or string) and its units |
| `reason` | a category that explains a `value`, for example why a geometry is invalid |
| `crs` | the CRS of `geometry` or `features`, anything `pyproj.CRS.from_user_input` accepts |

Coordinates are always in traditional GIS order, x = easting or longitude and y = northing or
latitude, whatever axis order the CRS authority defines. GeoJSON uses this order. A document
without `crs` is taken to be in `OGC:CRS84` (WGS 84 longitude/latitude).

## Applicability and aggregation

A check applies to a case only when the **reference** has the field it checks:

| Check | Applies when the reference has |
| --- | --- |
| `status_match` | `status` (inside `task_success`; the registered `status_match` always applies) |
| `crs_match` | `crs` |
| `geometry_match`, `validity_match` | `geometry` or `features` |
| `attribute_match` | `features` |
| `value_abs_error`, `value_rel_error` | a numeric `value` (not a boolean) |
| `reason_match` | `reason` (inside `task_success` only) |

A check that does not apply scores `value: null`, `passed: null`,
`detail: {"applicable": false}`.

Every metric aggregates with the default `Metric.aggregate`
(`geoevals.metrics.base.aggregate_values`): `n` counts the non-null values, `mean` and `median`
are over those, `ci_low`/`ci_high` bound the 95% percentile bootstrap interval of the mean
(2000 resamples, seed 0), and `n_failed` counts the cases with `passed: false`, including those
with a null value. Cases that are not scored (timeout, adapter error, invalid output) have no
metric values and are counted in the run's failure rate instead. For the pass/fail metrics
(value 1.0 or 0.0) the mean is the pass rate over applicable cases.

## Tolerances

Every tolerance is a metric param, is inclusive (`error <= tolerance` passes, so a prediction
exactly at the tolerance passes and one 1e-9 m beyond it fails), and defaults to `0.0`, which
means an exact match. The unit is part of the param name or stated here:

| Param | Units | Used by |
| --- | --- | --- |
| `tol_m` | meters | `geometry_match` (Hausdorff distance) |
| `area_tol_rel` | unitless ratio | `geometry_match` (only when given) |
| `length_tol_rel` | unitless ratio | `geometry_match` (only when given) |
| `float_tol` | each attribute's own units (absolute) | `attribute_match` |
| `abs_tol` | the reference `units` | `value_abs_error` |
| `rel_tol` | unitless ratio | `value_rel_error` |

Other params: `measure_crs` (a projected CRS to measure distances, lengths and areas in),
`topology` (default `true`) and `key` (the feature property that pairs predicted and reference
features; without it features pair by position). `task_success` passes its params to every
check.

The runner builds each metric's params from three places, later ones winning: the spec's
`tolerances` (benchmark-wide defaults), the metric's `params` in the spec, and the case's
`tolerances`. A tolerance is written `{value, units}` in the spec or case, and only its `value`
reaches the metric under the tolerance's name, so name it after the param (`tol_m`, `abs_tol`,
...) and state units that match the table above.

## Measurement frames

Implemented in `geoevals.metrics.spatial`. Every distance is reported in meters.

- **Projected**: when `measure_crs` is given (it must be projected), geometries are transformed
  into it; otherwise, when the reference CRS is projected, they are measured in it. Distances,
  lengths and areas are planar and converted from the CRS's linear unit to meters (for example
  US survey feet: 1200/3937 m).
- **Geodesic**: when the reference CRS is geographic and no `measure_crs` is given. Lengths and
  areas are computed on the CRS's ellipsoid with `pyproj.Geod` (`geometry_length`,
  `geometry_area_perimeter`; polygon shells and holes are oriented first so the signed areas
  add up). Hausdorff distances are computed in a local azimuthal equidistant (AEQD) projection
  on the same ellipsoid, centered on the reference's centroid. Distances from the center are
  exact geodesic distances, so point-to-point comparisons are exact; for extended geometries
  the error grows with the distance from the center. Edges are straight lines in the
  measurement frame (they are not densified).

## Primitives (`geoevals.metrics.spatial`)

| Function | Result | Units | Frame |
| --- | --- | --- | --- |
| `crs_equal(a, b)` | `pyproj.CRS.equals`; axis order counts (`EPSG:4326` != `OGC:CRS84`) | none | n/a |
| `detect_axis_swap(pred, ref, tol_m, crs)` | true when `crs` is geographic, `pred` misses `ref` by more than `tol_m` and `pred` with x and y exchanged is within `tol_m` | meters | geodesic or projected |
| `geometry_equal(pred, ref, tol_m, crs, measure_crs=None)` | `hausdorff_m <= tol_m` | meters | geodesic or projected |
| `hausdorff_m(pred, ref, crs, measure_crs=None)` | Hausdorff distance (shapely `hausdorff_distance` in the frame) | meters | geodesic (AEQD) or projected |
| `area_m2`, `length_m` | area, length (polygon perimeter) | m², m | geodesic (`Geod`) or projected |
| `area_error_rel(pred, ref, crs)` | `abs(A_pred - A_ref) / A_ref` | ratio | as `area_m2` |
| `length_error_rel(pred, ref, crs)` | `abs(L_pred - L_ref) / L_ref` | ratio | as `length_m` |
| `is_valid_with_reason(geom)` | `(geom.is_valid, explain_validity(geom))` | none | planar in the geometry's coordinates |
| `topology_signature(geom)`, `topology_equal(pred, ref)` | equal geometry type, part count and ring count (shells plus holes) | none | n/a |
| `attributes_equal(pred, ref, float_tol)`, `attribute_differences` | same keys; numbers within `float_tol`; other values equal and of the same type | attribute units | n/a |

Edge cases of the primitives: two empty geometries are 0 m apart; an empty and a non-empty
geometry are infinitely far apart; a coordinate that cannot be projected (for example a latitude
beyond 90 degrees after an axis swap) gives an infinite distance. A reference area or length of
0 gives a relative error of 0 when the prediction's is also 0, else infinity. Two NaN attribute
values are equal; `true` and `1` are not.

## Metrics

Each per-case `detail` explains a failure. A non-finite number in `detail` (an infinite
distance) is written as `null`.

### `task_success`

- **Definition:** 1.0 when every applicable check passes, else 0.0. The checks are
  `status_match`, `crs_match`, `geometry_match`, `validity_match`, `attribute_match`,
  `value_equal` (a non-numeric reference `value` must be equal, type included), `reason_match`
  (a reference `reason` must be equal, exact string; on failure reason `reason_differs` with
  `predicted` and `expected`) and, for a numeric `value`, `value_abs_error` (when `abs_tol` is
  given, or when neither `abs_tol` nor `rel_tol` is) and `value_rel_error` (when `rel_tol` is
  given). A trajectory or tool call never counts toward it.
- **Version:** 1.1.0 added `reason_match`. A reference without `reason` scores as in 1.0.0.
- **Units:** fraction. Higher is better.
- **Implementation:** `geoevals.metrics.gis.TaskSuccess`.
- **Detail:** `checks` maps every applicable check to `{passed, detail}`; `failed` lists the
  failed checks.
- **Edge cases:** a null or non-object output fails every applicable check. A reference with no
  applicable check (no `status` either) gives a null value. An abstention reference
  (`status: invalid_request` and no answer fields) only checks the status, so answering `ok`
  fails.

### `geometry_match`

- **Definition:** 1.0 when `hausdorff_m(pred, ref) <= tol_m`, the topology signatures are equal
  (unless `topology: false`), and, when given, `area_error_rel <= area_tol_rel` and
  `length_error_rel <= length_tol_rel`; else 0.0. With `features`, the feature counts must be
  equal, every feature must pair (by `key` or by position), and every pair must match.
- **Units:** fraction; tolerances in meters and ratios. Higher is better.
- **Frame:** the reference CRS (geodesic when geographic, planar when projected) or
  `measure_crs`. A prediction in another CRS is reprojected into the reference CRS first
  (`detail.reprojected_from`), so a wrong CRS label fails `crs_match` but not this check when
  the coordinates are right. A prediction without `crs` is taken to be in the reference CRS.
- **Implementation:** `geoevals.metrics.gis.check_geometry`, `compare_geometries`.
- **Detail:** `hausdorff_m`, `tol_m`, and when they apply `reason`, `axis_swapped`, `topology`
  (`{predicted, expected}` signatures), `area_error_rel`, `length_error_rel`; with features
  `feature_count`, `missing`, `extra`, `duplicate` and per-feature `features`.
- **Reasons:** `missing_geometry`, `unreadable_geometry`, `unreadable_crs`, `missing_features`,
  `empty_prediction`, `empty_reference`, `axis_order_swapped` (also `axis_swapped: true`).
- **Edge cases:** empty prediction vs. non-empty reference fails (`hausdorff_m: null`); two
  empty geometries pass. Mixed geometry types are compared as a GeometryCollection: the
  Hausdorff distance covers all members, and the signature compares the collection type and its
  part count, so a Point cannot stand in for a GeometryCollection. A reference with duplicate
  `key` values is a benchmark error and raises (recorded as `scoring_error`).

### `crs_match`

- **Definition:** 1.0 when `crs_equal(pred.crs, ref.crs)`, else 0.0.
- **Units:** fraction. Higher is better.
- **Implementation:** `geoevals.metrics.gis.check_crs`.
- **Reasons:** `missing_crs`, `unreadable_crs` (with the pyproj `error`), `crs_differs` (with
  `predicted`, `expected`).
- **Edge cases:** axis order counts, so `EPSG:4326` and `OGC:CRS84` differ. Spelling does not
  (`epsg:4326` equals `EPSG:4326`, and a PROJ string equals its EPSG code when pyproj says so).

### `attribute_match`

- **Definition:** 1.0 when every reference feature pairs with a predicted feature and the
  properties of every pair are equal under `attributes_equal(pred, ref, float_tol)`; else 0.0.
- **Units:** fraction; `float_tol` in each attribute's units. Higher is better.
- **Implementation:** `geoevals.metrics.gis.check_attributes`.
- **Detail:** pairing problems as for `geometry_match`; `features` lists each failing pair with
  its `differences` (`{attribute, predicted, expected}`).
- **Edge cases:** a missing or null `properties` is an empty mapping; an attribute present on
  one side only is a difference.

### `validity_match`

- **Definition:** 1.0 when the predicted geometry is OGC-valid exactly when the reference is
  (`is_valid_with_reason`); with `features`, for every pair. Else 0.0.
- **Units:** fraction. Higher is better. Planar in the geometries' own coordinates.
- **Implementation:** `geoevals.metrics.gis.check_validity`.
- **Detail:** on failure `predicted` and `expected` as `{valid, reason}`, where `reason` is the
  `explain_validity` text.
- **Edge cases:** an empty geometry is valid. A missing or unreadable predicted geometry fails.

### `status_match`

- **Definition:** 1.0 when `pred.status == ref.status` (exact string), else 0.0.
- **Units:** fraction. Higher is better.
- **Implementation:** `geoevals.metrics.status.StatusMatch`.
- **Detail:** `predicted`, `expected` on mismatch.
- **Edge cases:** a missing status, or a prediction that is not an object, counts as null; null
  equals only null. Unlike the other checks it always applies.

### `value_abs_error`

- **Definition:** `abs(pred.value - ref.value)`; passed when `<= abs_tol`.
- **Units:** the reference `units`. Lower is better.
- **Implementation:** `geoevals.metrics.gis.check_value_abs`.
- **Edge cases:** a missing, non-numeric or non-finite predicted value gives value null, failed,
  reason `missing_value`. When the reference has `units`, the prediction must state the same
  string; otherwise value null, failed, reason `units_mismatch` (no unit conversion is done, so
  an answer in the wrong units fails). Booleans are not numbers.

### `value_rel_error`

- **Definition:** `abs(pred.value - ref.value) / abs(ref.value)`; passed when `<= rel_tol`.
- **Units:** unitless ratio. Lower is better.
- **Implementation:** `geoevals.metrics.gis.check_value_rel`.
- **Edge cases:** as `value_abs_error`; a reference of 0 gives 0.0 when the prediction is also
  0, else value null, failed, reason `zero_reference`.
