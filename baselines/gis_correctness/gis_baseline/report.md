# GeoEvals report: gis_correctness 0.2.0 / gis_baseline

## 1. Summary

| Field | Value |
| --- | --- |
| Run ID | gis_correctness-gis_baseline-20261010T232143Z-1fadf0a0 |
| Benchmark | gis_correctness 0.2.0 |
| Split | test |
| Adapter | gis_baseline 0.1.0 |
| Model | none recorded (the adapter config has no model) |
| Adapter config | {} |
| Metric versions | attribute_match 1.1.0, crs_match 1.0.0, geometry_match 1.1.0, status_match 1.1.0, task_success 1.3.0, validity_match 1.1.0, value_abs_error 1.0.0, value_rel_error 1.0.0 |
| Config hash | 1fadf0a0380009519a4a65492cfd2d1547306df17984ec49975a58dfa39f62fc |
| Dataset manifest hash | 20beb1d10b212eaa1728803d1606fe42ed65c8f75496eced72d0ba5663d2f2ea |
| Run result schema | 1.0.0 |
| Started | 2026-10-10T23:21:43.333784Z |
| Finished | 2026-10-10T23:21:47.790541Z |
| Cases | 56 (56 scored, 0 not scored) |

Comparisons are valid only between runs with the same benchmark version, metric versions, split, and dataset manifest hash.

## 2. Summary metrics

| Metric | Version | Mean | Median | 95% CI | n | n failed |
| --- | --- | --- | --- | --- | --- | --- |
| attribute_match | 1.1.0 | 1 | 1 | [1, 1] | 14 | 0 |
| crs_match | 1.0.0 | 1 | 1 | [1, 1] | 47 | 0 |
| geometry_match | 1.1.0 | 1 | 1 | [1, 1] | 31 | 0 |
| status_match | 1.1.0 | 1 | 1 | [1, 1] | 56 | 0 |
| task_success | 1.3.0 | 1 | 1 | [1, 1] | 56 | 0 |
| validity_match | 1.1.0 | 1 | 1 | [1, 1] | 31 | 0 |
| value_abs_error | 1.0.0 | 1.05479e-11 | 9.09495e-13 | [1.15954e-12, 2.11603e-11] | 9 | 0 |
| value_rel_error | 1.0.0 | 9.42587e-16 | 8.23468e-16 | [5.05969e-16, 1.48754e-15] | 9 | 0 |

The 95% CI is a bootstrap percentile interval of the mean. n counts the cases with a metric value.

## 3. Breakdown by strata

### Abstention

| Reference | Abstained | Answered |
| --- | --- | --- |
| Should abstain | 9 | 0 |
| Should answer | 0 | 47 |

Abstention precision 1, recall 1. A case abstains when its status is needs_clarification, insufficient_data or invalid_request (from the status_match detail of the scored cases).

### abstention

| abstention | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buffer_without_units | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| contradictory_request | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| join_without_crs | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| join_without_predicate | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| missing_attribute | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| missing_features | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| outside_data_extent | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| planar_distance_in_geographic_crs | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 48 | 48 | 1 | 14 | 0 | 1 | 47 | 0 | 1 | 31 | 0 | 1 | 48 | 0 | 1 | 48 | 0 | 1 | 31 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### buffer_kind

| buffer_kind | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cap_style | 2 | 2 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| dissolve | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| line | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| negative_collapse | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| negative_units | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| point_geographic | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 49 | 49 | 1 | 14 | 0 | 1 | 40 | 0 | 1 | 24 | 0 | 1 | 49 | 0 | 1 | 49 | 0 | 1 | 24 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### crs_family

| crs_family | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| datum_shift | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| invalid | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| mercator | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| polar_stereographic | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| state_plane | 1 | 1 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| utm | 3 | 3 | 1 | 1 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| web_mercator | 2 | 2 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 46 | 46 | 1 | 13 | 0 | 1 | 38 | 0 | 1 | 22 | 0 | 1 | 46 | 0 | 1 | 46 | 0 | 1 | 22 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

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
| (not set) | 47 | 47 | 1 | 14 | 0 | 1 | 38 | 0 | 1 | 29 | 0 | 1 | 47 | 0 | 1 | 47 | 0 | 1 | 29 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### expected_status

| expected_status | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| insufficient_data | 4 | 4 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 4 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| invalid_request | 2 | 2 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| needs_clarification | 2 | 2 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 48 | 48 | 1 | 14 | 0 | 1 | 47 | 0 | 1 | 31 | 0 | 1 | 48 | 0 | 1 | 48 | 0 | 1 | 31 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### join

| join | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| crs_mismatch | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| intersects_vs_within | 2 | 2 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| nearest_max_distance | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| one_to_many | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| points_in_polygons | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| shared_boundary | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 49 | 49 | 1 | 7 | 0 | 1 | 40 | 0 | 1 | 24 | 0 | 1 | 49 | 0 | 1 | 49 | 0 | 1 | 24 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### method

| method | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| geodesic | 6 | 6 | n/a | 0 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | 7.93913e-12 | 6 | 0 | 5.92804e-16 | 6 | 0 |
| projected | 3 | 3 | n/a | 0 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1.57653e-11 | 3 | 0 | 1.64215e-15 | 3 | 0 |
| (not set) | 47 | 47 | 1 | 14 | 0 | 1 | 38 | 0 | 1 | 31 | 0 | 1 | 47 | 0 | 1 | 47 | 0 | 1 | 31 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |

### operation

| operation | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| abstention | 8 | 8 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 8 | 0 | 1 | 8 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| buffer | 7 | 7 | n/a | 0 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| crs_transform | 10 | 10 | 1 | 1 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | 1 | 10 | 0 | 1 | 10 | 0 | 1 | 9 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| distance | 9 | 9 | n/a | 0 | 0 | 1 | 9 | 0 | n/a | 0 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | n/a | 0 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |
| overlay | 6 | 6 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| spatial_join | 7 | 7 | 1 | 7 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| validity | 9 | 9 | n/a | 0 | 0 | 1 | 9 | 0 | 1 | 2 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |

### overlay

| overlay | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clip | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| difference | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| intersection | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| mixed_types | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| symmetric_difference | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| union | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 50 | 50 | 1 | 8 | 0 | 1 | 41 | 0 | 1 | 25 | 0 | 1 | 50 | 0 | 1 | 50 | 0 | 1 | 25 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### predicate

| predicate | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| contains | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| intersects | 2 | 2 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| nearest | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| within | 3 | 3 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 49 | 49 | 1 | 7 | 0 | 1 | 40 | 0 | 1 | 24 | 0 | 1 | 49 | 0 | 1 | 49 | 0 | 1 | 24 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### request_operation

| request_operation | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buffer | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| distance | 3 | 3 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| spatial_join | 4 | 4 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 4 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 48 | 48 | 1 | 14 | 0 | 1 | 47 | 0 | 1 | 31 | 0 | 1 | 48 | 0 | 1 | 48 | 0 | 1 | 31 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### task

| task | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| detect | 7 | 7 | n/a | 0 | 0 | 1 | 7 | 0 | n/a | 0 | 0 | 1 | 7 | 0 | 1 | 7 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| repair | 2 | 2 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 47 | 47 | 1 | 14 | 0 | 1 | 38 | 0 | 1 | 29 | 0 | 1 | 47 | 0 | 1 | 47 | 0 | 1 | 29 | 0 | 1.05479e-11 | 9 | 0 | 9.42587e-16 | 9 | 0 |

### trap

| trap | Cases | Scored | attribute_match mean | attribute_match n | attribute_match failed | crs_match mean | crs_match n | crs_match failed | geometry_match mean | geometry_match n | geometry_match failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | validity_match mean | validity_match n | validity_match failed | value_abs_error mean | value_abs_error n | value_abs_error failed | value_rel_error mean | value_rel_error n | value_rel_error failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| false | 21 | 21 | 1 | 8 | 0 | 1 | 21 | 0 | 1 | 13 | 0 | 1 | 21 | 0 | 1 | 21 | 0 | 1 | 13 | 0 | 1.23164e-11 | 6 | 0 | 9.46206e-16 | 6 | 0 |
| true | 35 | 35 | 1 | 6 | 0 | 1 | 26 | 0 | 1 | 18 | 0 | 1 | 35 | 0 | 1 | 35 | 0 | 1 | 18 | 0 | 7.01069e-12 | 3 | 0 | 9.3535e-16 | 3 | 0 |

## 4. Efficiency

| Measure | Value |
| --- | --- |
| Wall clock (s) | 4.45574 |
| Cases | 56 |
| Throughput (cases/s) | 12.5681 |
| Latency p50 (s) | 0.00627617 |
| Latency p90 (s) | 0.0399228 |
| Latency p99 (s) | 0.407021 |
| Latency max (s) | 0.764896 |
| Timeout rate | 0 |
| Failure rate | 0 |
| Retries | 0 |
| Peak RSS (bytes) | 264404992 |
| Input tokens | 0 |
| Output tokens | 0 |
| Cost, total (USD) | 0 |
| Cost per case (USD) | 0 |
| Price table hash | bac82dab3dacce874bb244d6293734dafcf129d683e7c78cc207567177435b87 |
| Tool error rate | n/a |
| Mean agent steps | n/a |

## 5. Failures

Every case was scored and no metric failed.

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
| git_commit | cb6b336e3ee1a3bb0142f14e3ce3a4bc48ad1a27 |
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
