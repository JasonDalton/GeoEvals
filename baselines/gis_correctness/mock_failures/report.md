# GeoEvals report: gis_correctness 0.3.0 / mock

## 1. Summary

| Field | Value |
| --- | --- |
| Run ID | gis_correctness-mock-20261011T164835Z-fbbb6181 |
| Benchmark | gis_correctness 0.3.0 |
| Split | test |
| Adapter | mock 0.1.0 |
| Model | none recorded (the adapter config has no model) |
| Adapter config | {"cases": {"abstention-001": {"behavior": "wrong", "output": {"crs": "OGC:CRS84", "status": "ok", "units": "m", "value": 1}}, "abstention-002": {"behavior": "wrong", "output": {"status": "needs_clarification"}}, "buffer-001": {"behavior": "sleep", "seconds": 10}, "crs_transform-003": {"behavior": "wrong", "output": {"crs": "EPSG:3857", "geometry": {"coordinates": [0, 0], "type": "Point"}, "status": "ok"}}, "distance-001": {"behavior": "wrong", "output": {"crs": "OGC:CRS84", "status": "ok", "units": "km", "value": 980}}, "distance-002": {"behavior": "raise", "message": "mock adapter failure"}, "overlay-001": {"behavior": "malformed"}, "spatial_join-001": {"behavior": "skip", "message": "mock adapter declines spatial_join cases"}, "validity-001": {"behavior": "fail_then_succeed", "failures": 1, "message": "transient mock failure"}}, "seed": 0, "tokens": {"input": 100, "output": 20}} |
| Metric versions | attribute_match 1.1.0, crs_match 1.1.0, geometry_match 1.1.0, status_match 1.1.0, task_success 1.3.0, validity_match 1.1.0, value_abs_error 1.0.0, value_rel_error 1.0.0 |
| Config hash | fbbb6181df48f103fde9ce99e548adc101738dec0b0804f78c35471edf6b71dc |
| Dataset manifest hash | 20beb1d10b212eaa1728803d1606fe42ed65c8f75496eced72d0ba5663d2f2ea |
| Run result schema | 1.0.0 |
| Started | 2026-10-11T16:48:35.480477Z |
| Finished | 2026-10-11T16:48:40.149103Z |
| Cases | 56 (52 scored, 4 not scored) |

Comparisons are valid only between runs with the same benchmark version, metric versions, split, and dataset manifest hash.

## 2. Summary metrics

| Metric | Version | Mean | Median | 95% CI | n | n failed |
| --- | --- | --- | --- | --- | --- | --- |
| attribute_match | 1.1.0 | 1 | 1 | [1, 1] | 12 | 0 |
| crs_match | 1.1.0 | 1 | 1 | [1, 1] | 43 | 0 |
| geometry_match | 1.1.0 | 1 | 1 | [1, 1] | 28 | 0 |
| status_match | 1.1.0 | 0.942308 | 1 | [0.865385, 1] | 52 | 3 |
| task_success | 1.3.0 | 0.923077 | 1 | [0.846154, 0.980769] | 52 | 4 |
| validity_match | 1.1.0 | 1 | 1 | [1, 1] | 28 | 0 |
| value_abs_error | 1.0.0 | 12.4721 | 0 | [0, 37.4163] | 8 | 1 |
| value_rel_error | 1.0.0 | 0.0141693 | 0 | [0, 0.0425078] | 8 | 1 |

The 95% CI is a bootstrap percentile interval of the mean. n counts the cases with a metric value.

## 3. Breakdown by strata

### Abstention

| Reference | Abstained | Answered |
| --- | --- | --- |
| Should abstain | 7 | 2 |
| Should answer | 0 | 43 |

Abstention precision 1, recall 0.777778. A case abstains when its status is needs_clarification, insufficient_data or invalid_request (from the status_match detail of the scored cases).

### abstention

| abstention | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buffer_without_units | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| contradictory_request | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| join_without_crs | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| join_without_predicate | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| missing_attribute | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| missing_features | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| outside_data_extent | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| planar_distance_in_geographic_crs | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 48 | 44 | 1 | 12 | 0 | 1 | 43 | 0 | 1 | 28 | 0 | 0.977273 | 44 | 1 | 0.954545 | 44 | 2 | 1 | 28 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### buffer_kind

| buffer_kind | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cap_style | 2 | 2 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| dissolve | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| line | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| negative_collapse | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| negative_units | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| point_geographic | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 49 | 46 | 1 | 12 | 0 | 1 | 37 | 0 | 1 | 22 | 0 | 0.934783 | 46 | 3 | 0.913043 | 46 | 4 | 1 | 22 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### crs_family

| crs_family | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| datum_shift | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| invalid | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| mercator | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| polar_stereographic | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| state_plane | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| utm | 3 | 3 | 1 | 1 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| web_mercator | 2 | 2 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 46 | 42 | 1 | 11 | 0 | 1 | 34 | 0 | 1 | 19 | 0 | 0.952381 | 42 | 2 | 0.928571 | 42 | 3 | 1 | 19 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### defect

| defect | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bowtie | 2 | 2 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 1 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| duplicate_vertex | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| empty | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| figure_eight | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| hole_outside_shell | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| overlapping_parts | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| unclosed_ring | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| zero_area_sliver | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 47 | 43 | 1 | 12 | 0 | 1 | 34 | 0 | 1 | 26 | 0 | 0.930233 | 43 | 3 | 0.906977 | 43 | 4 | 1 | 26 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### expected_status

| expected_status | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| insufficient_data | 4 | 4 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 0.75 | 4 | 1 | 0.75 | 4 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| invalid_request | 2 | 2 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| needs_clarification | 2 | 2 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 0.5 | 2 | 1 | 0.5 | 2 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 48 | 44 | 1 | 12 | 0 | 1 | 43 | 0 | 1 | 28 | 0 | 0.977273 | 44 | 1 | 0.954545 | 44 | 2 | 1 | 28 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### join

| join | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| crs_mismatch | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| intersects_vs_within | 2 | 2 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| nearest_max_distance | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| one_to_many | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| points_in_polygons | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| shared_boundary | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 49 | 46 | 1 | 6 | 0 | 1 | 37 | 0 | 1 | 22 | 0 | 0.934783 | 46 | 3 | 0.913043 | 46 | 4 | 1 | 22 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### method

| method | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| geodesic | 6 | 6 | n/a | 0 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | 1 | 6 | 0 | 0.833333 | 6 | 1 | n/a | 0 | 0 | 16.6295 | 6 | 1 | 0.0188924 | 6 | 1 |
| projected | 3 | 2 | n/a | 0 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | 0 | 2 | 0 | 0 | 2 | 0 |
| (not set) | 47 | 44 | 1 | 12 | 0 | 1 | 35 | 0 | 1 | 28 | 0 | 0.931818 | 44 | 3 | 0.931818 | 44 | 3 | 1 | 28 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |

### operation

| operation | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| abstention | 8 | 8 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 0.75 | 8 | 2 | 0.75 | 8 | 2 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| buffer | 7 | 6 | n/a | 0 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| crs_transform | 10 | 10 | 1 | 1 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | 0.9 | 10 | 1 | 0.9 | 10 | 1 | 1 | 9 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| distance | 9 | 8 | n/a | 0 | 0 | 1 | 8 | 0 | n/a | 0 | 0 | 1 | 8 | 0 | 0.875 | 8 | 1 | n/a | 0 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |
| overlay | 6 | 5 | 1 | 5 | 0 | 1 | 5 | 0 | 1 | 5 | 0 | 1 | 5 | 0 | 1 | 5 | 0 | 1 | 5 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| spatial_join | 7 | 6 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| validity | 9 | 9 | n/a | 0 | 0 | 1 | 9 | 0 | 1 | 2 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |

### overlay

| overlay | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clip | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| difference | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| intersection | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| mixed_types | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| symmetric_difference | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| union | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 50 | 47 | 1 | 7 | 0 | 1 | 38 | 0 | 1 | 23 | 0 | 0.93617 | 47 | 3 | 0.914894 | 47 | 4 | 1 | 23 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### predicate

| predicate | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| contains | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| intersects | 2 | 2 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| nearest | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| within | 3 | 2 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 49 | 46 | 1 | 6 | 0 | 1 | 37 | 0 | 1 | 22 | 0 | 0.934783 | 46 | 3 | 0.913043 | 46 | 4 | 1 | 22 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### request_operation

| request_operation | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buffer | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| distance | 3 | 3 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| spatial_join | 4 | 4 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 0.75 | 4 | 1 | 0.75 | 4 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 48 | 44 | 1 | 12 | 0 | 1 | 43 | 0 | 1 | 28 | 0 | 0.977273 | 44 | 1 | 0.954545 | 44 | 2 | 1 | 28 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### task

| task | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| detect | 7 | 7 | n/a | 0 | 0 | 1 | 7 | 0 | n/a | 0 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| repair | 2 | 2 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 47 | 43 | 1 | 12 | 0 | 1 | 34 | 0 | 1 | 26 | 0 | 0.930233 | 43 | 3 | 0.906977 | 43 | 4 | 1 | 26 | 0 | 12.4721 | 8 | 1 | 0.0141693 | 8 | 1 |

### trap

| trap | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| false | 21 | 18 | 1 | 6 | 0 | 1 | 18 | 0 | 1 | 11 | 0 | 1 | 18 | 0 | 0.944444 | 18 | 1 | 1 | 11 | 0 | 19.9554 | 5 | 1 | 0.0226708 | 5 | 1 |
| true | 35 | 34 | 1 | 6 | 0 | 1 | 25 | 0 | 1 | 17 | 0 | 0.911765 | 34 | 3 | 0.911765 | 34 | 3 | 1 | 17 | 0 | 0 | 3 | 0 | 0 | 3 | 0 |

## 4. Efficiency

| Measure | Value |
| --- | --- |
| Wall clock (s) | 4.66691 |
| Cases | 56 |
| Throughput (cases/s) | 11.9994 |
| Latency p50 (s) | 4.95415e-05 |
| Latency p90 (s) | 0.000199021 |
| Latency p99 (s) | 0.901139 |
| Latency max (s) | 2.00173 |
| Timeout rate | 0.0178571 |
| Failure rate | 0.0714286 |
| Retries | 2 |
| Peak RSS (bytes) | 160088064 |
| Input tokens | 5300 |
| Output tokens | 1060 |
| Cost, total (USD) | 0 |
| Cost per case (USD) | 0 |
| Price table hash | bac82dab3dacce874bb244d6293734dafcf129d683e7c78cc207567177435b87 |
| Tool error rate | n/a |
| Mean agent steps | n/a |

## 5. Failures

| Case | Status | Metric | Error or detail |
| --- | --- | --- | --- |
| abstention-001 | scored | status_match | value 0; detail {"expected": "needs_clarification", "predicted": "ok", "reason": "answered_when_should_abstain"} |
| abstention-001 | scored | task_success | value 0; detail {"checks": {"status_match": {"detail": {"expected": "needs_clarification", "predicted": "ok", "reason": "answered_when_should_abstain"}, "passed": false}}, "failed": ["status_match"]} |
| abstention-002 | scored | status_match | value 0; detail {"expected": "insufficient_data", "predicted": "needs_clarification", "reason": "wrong_abstention_status"} |
| abstention-002 | scored | task_success | value 0; detail {"checks": {"status_match": {"detail": {"expected": "insufficient_data", "predicted": "needs_clarification", "reason": "wrong_abstention_status"}, "passed": false}}, "failed": ["status_match"]} |
| buffer-001 | timeout | - | TimeoutError: case exceeded timeout_s=2 |
| crs_transform-003 | scored | status_match | value 0; detail {"expected": "invalid_request", "predicted": "ok", "reason": "answered_when_should_abstain"} |
| crs_transform-003 | scored | task_success | value 0; detail {"checks": {"status_match": {"detail": {"expected": "invalid_request", "predicted": "ok", "reason": "answered_when_should_abstain"}, "passed": false}}, "failed": ["status_match"]} |
| distance-001 | scored | task_success | value 0; detail {"checks": {"crs_match": {"detail": {}, "passed": true}, "status_match": {"detail": {"expected": "ok", "predicted": "ok"}, "passed": true}, "value_abs_error": {"detail": {"abs_tol": 0.001, "expected": 880.223093784306, "predicted": 980.0}, "passed": false}, "value_rel_error": {"detail": {"expected": 880.223093784306, "predicted": 980.0, "rel_tol": 1e-06}, "passed": false}}, "failed": ["value_abs_error", "value_rel_error"]} |
| distance-001 | scored | value_abs_error | value 99.7769; detail {"abs_tol": 0.001, "expected": 880.223093784306, "predicted": 980.0} |
| distance-001 | scored | value_rel_error | value 0.113354; detail {"expected": 880.223093784306, "predicted": 980.0, "rel_tol": 1e-06} |
| distance-002 | adapter_error | - | MockAdapterError: mock adapter failure |
| overlay-001 | invalid_output | - | InvalidOutput: <root>: 'crs' is a required property; <root>: 'status' is a required property; <root>: {'mock_malformed_output': True} is not valid under any of the given schemas |
| spatial_join-001 | skipped | - | SkipCase: mock adapter declines spatial_join cases |

## 6. Agent trajectories

No case recorded an agent trajectory.

## 7. Environment

| Key | Value |
| --- | --- |
| cpu_count_logical | 8 |
| cpu_model | Apple M1 Pro |
| geoevals_version | 0.1.0 |
| geopandas_version | 1.2.0 |
| geos_version | 3.14.1 |
| git_commit | 4ea674eb0ffc18aac87393e382af46744bbc925d |
| git_dirty | true |
| machine | arm64 |
| os | Darwin |
| os_release | 25.5.0 |
| platform | macOS-26.5.2-arm64-arm-64bit |
| proj_version | 9.5.1 |
| pyproj_version | 3.7.2 |
| python | 3.11.6 |
| python_implementation | CPython |
| ram_total_bytes | 17179869184 |
| shapely_version | 2.2.0 |
| uv_lock_sha256 | ef03eb7ea7f6e758d17061ad5a3ff9951aa2bad73105153027dff22b9a028a55 |

## 8. Provenance and dataset licenses

| Field | Value |
| --- | --- |
| Benchmark license | MIT |
| Authors | GeoEvals contributors |
| Created | 2026-10-09 |
| Reference workflow | reference.py |
| Notes | Every expected output is computed by reference.py; regenerate them with `geoevals bench regenerate gis_correctness`. |
| Dataset | gis_correctness |

| Asset | License | Attribution | Redistributable | Source |
| --- | --- | --- | --- | --- |
| places | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic places fixture for the GIS correctness benchmark. |
| distance_points | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic distance points fixture for the GIS correctness benchmark. |
| buffer_sites | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic buffer sites fixture for the GIS correctness benchmark. |
| join_points | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic join points fixture for the GIS correctness benchmark. |
| join_zones | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic join zones fixture for the GIS correctness benchmark. |
| join_lots | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic join lots fixture for the GIS correctness benchmark. |
| join_stations | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic join stations fixture for the GIS correctness benchmark. |
| join_points_utm | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic UTM join points fixture for the GIS correctness benchmark. |
| abstain_points_nocrs | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic points without CRS information for the GIS correctness benchmark. |
| abstain_zones_paris | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic Paris zones fixture for the GIS correctness benchmark. |
| overlay_parcels | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic overlay parcels fixture for the GIS correctness benchmark. |
| overlay_flood | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic overlay flood zones fixture for the GIS correctness benchmark. |
| overlay_works | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic overlay works areas fixture for the GIS correctness benchmark. |

## 9. Limitations

- Small synthetic fixtures; they test operation correctness, not scale or real-world data quality.
- Expected outputs come from one reference workflow (Shapely, pyproj, GEOS, PROJ); an error shared by those libraries would not be caught.
- Tolerances are set per case and stated in explicit units, sized to catch the smallest error of the mistake each case targets; none is tighter than a correct answer given to 5 decimal places needs.
