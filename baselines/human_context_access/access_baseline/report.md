# GeoEvals report: human_context_access 0.1.0 / access_baseline

## 1. Summary

| Field | Value |
| --- | --- |
| Run ID | human_context_access-access_baseline-20261009T201106Z-1fadf0a0 |
| Benchmark | human_context_access 0.1.0 |
| Split | test |
| Adapter | access_baseline 0.1.0 |
| Model | none recorded (the adapter config has no model) |
| Adapter config | {} |
| Metric versions | reachable_count_error 1.0.0, reachable_set_jaccard 1.0.0, route_stretch_abs_error 1.0.0, status_match 1.1.0, task_success 1.3.0, travel_time_abs_error_s 1.0.0, unknown_set_jaccard 1.0.0 |
| Config hash | 1fadf0a0380009519a4a65492cfd2d1547306df17984ec49975a58dfa39f62fc |
| Dataset manifest hash | f2d344c9051b3956498c04c8da06dd43c1e1ea893b3169052aa52afdaf556b2a |
| Run result schema | 1.0.0 |
| Started | 2026-10-09T20:11:06.085201Z |
| Finished | 2026-10-09T20:11:08.490423Z |
| Cases | 51 (51 scored, 0 not scored) |

Comparisons are valid only between runs with the same benchmark version, metric versions, split, and dataset manifest hash.

## 2. Summary metrics

| Metric | Version | Mean | Median | 95% CI | n | n failed |
| --- | --- | --- | --- | --- | --- | --- |
| reachable_count_error | 1.0.0 | 0 | 0 | [0, 0] | 24 | 0 |
| reachable_set_jaccard | 1.0.0 | 1 | 1 | [1, 1] | 32 | 0 |
| route_stretch_abs_error | 1.0.0 | 2.22045e-15 | 1.66533e-15 | [7.77156e-16, 3.73775e-15] | 6 | 0 |
| status_match | 1.1.0 | 1 | 1 | [1, 1] | 51 | 0 |
| task_success | 1.3.0 | 1 | 1 | [1, 1] | 51 | 0 |
| travel_time_abs_error_s | 1.0.0 | 1.42109e-13 | 5.68434e-14 | [4.9738e-14, 2.4869e-13] | 8 | 0 |
| unknown_set_jaccard | 1.0.0 | 1 | 1 | [1, 1] | 15 | 0 |

The 95% CI is a bootstrap percentile interval of the mean. n counts the cases with a metric value.

## 3. Breakdown by strata

### Abstention

| Reference | Abstained | Answered |
| --- | --- | --- |
| Should abstain | 13 | 0 |
| Should answer | 0 | 38 |

Abstention precision 1, recall 1. A case abstains when its status is needs_clarification, insufficient_data or invalid_request (from the status_match detail of the scored cases).

### abstention

| abstention | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| category_missing | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| category_not_in_data | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| coincident_points | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| destination_off_network | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| hours_missing | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| invalid_date | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| negative_threshold | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| no_path | 2 | 2 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| no_time | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| origin_off_network | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| threshold_missing | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| unknown_timezone | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 38 | 38 | 0 | 24 | 0 | 1 | 32 | 0 | 2.22045e-15 | 6 | 0 | 1 | 38 | 0 | 1 | 38 | 0 | 1.42109e-13 | 8 | 0 | 1 | 15 | 0 |

### amenity_category

| amenity_category | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clinic | 5 | 5 | 0 | 2 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | 1 | 5 | 0 | 1 | 5 | 0 | 1.42109e-13 | 2 | 0 | 1 | 2 | 0 |
| grocery | 11 | 11 | 0 | 7 | 0 | 1 | 9 | 0 | n/a | 0 | 0 | 1 | 11 | 0 | 1 | 11 | 0 | 5.68434e-14 | 2 | 0 | 1 | 4 | 0 |
| library | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| none | 10 | 10 | n/a | 0 | 0 | n/a | 0 | 0 | 2.22045e-15 | 6 | 0 | 1 | 10 | 0 | 1 | 10 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| park | 4 | 4 | 0 | 3 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | 1 | 4 | 0 | 1 | 4 | 0 | 3.41061e-13 | 1 | 0 | 1 | 1 | 0 |
| pharmacy | 8 | 8 | 0 | 4 | 0 | 1 | 5 | 0 | n/a | 0 | 0 | 1 | 8 | 0 | 1 | 8 | 0 | 5.68434e-14 | 1 | 0 | 1 | 3 | 0 |
| school | 4 | 4 | 0 | 3 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | 1 | 4 | 0 | 1 | 4 | 0 | 0 | 1 | 0 | 1 | 1 | 0 |
| transit_stop | 8 | 8 | 0 | 5 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | 1 | 8 | 0 | 1 | 8 | 0 | 3.41061e-13 | 1 | 0 | 1 | 4 | 0 |

### day_type

| day_type | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| invalid | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| public_holiday | 3 | 3 | 0 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 3 | 0 |
| weekday | 6 | 6 | 0 | 5 | 0 | 1 | 5 | 0 | n/a | 0 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | 1 | 5 | 0 |
| weekend | 9 | 9 | 0 | 7 | 0 | 1 | 7 | 0 | n/a | 0 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | n/a | 0 | 0 | 1 | 7 | 0 |
| (not set) | 32 | 32 | 0 | 9 | 0 | 1 | 17 | 0 | 2.22045e-15 | 6 | 0 | 1 | 32 | 0 | 1 | 32 | 0 | 1.42109e-13 | 8 | 0 | n/a | 0 | 0 |

### expected_status

| expected_status | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| insufficient_data | 6 | 6 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| invalid_request | 4 | 4 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 4 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| needs_clarification | 3 | 3 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 38 | 38 | 0 | 24 | 0 | 1 | 32 | 0 | 2.22045e-15 | 6 | 0 | 1 | 38 | 0 | 1 | 38 | 0 | 1.42109e-13 | 8 | 0 | 1 | 15 | 0 |

### hours_feature

| hours_feature | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 24_7 | 2 | 2 | 0 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | 1 | 2 | 0 |
| boundary | 2 | 2 | 0 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | 1 | 2 | 0 |
| missing_hours | 2 | 2 | 0 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | 1 | 1 | 0 |
| overnight | 4 | 4 | 0 | 4 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | 1 | 4 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | 1 | 4 | 0 |
| public_holiday | 3 | 3 | 0 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 3 | 0 |
| regular | 6 | 6 | 0 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | 1 | 3 | 0 |
| (not set) | 32 | 32 | 0 | 9 | 0 | 1 | 17 | 0 | 2.22045e-15 | 6 | 0 | 1 | 32 | 0 | 1 | 32 | 0 | 1.42109e-13 | 8 | 0 | n/a | 0 | 0 |

### neighborhood_type

| neighborhood_type | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cul_de_sac_suburban | 8 | 8 | 0 | 3 | 0 | 1 | 5 | 0 | 2.44249e-15 | 2 | 0 | 1 | 8 | 0 | 1 | 8 | 0 | 2.84217e-14 | 2 | 0 | 1 | 1 | 0 |
| grid | 18 | 18 | 0 | 8 | 0 | 1 | 10 | 0 | 3.21965e-15 | 2 | 0 | 1 | 18 | 0 | 1 | 18 | 0 | 5.68434e-14 | 2 | 0 | 1 | 5 | 0 |
| mixed_use_core | 15 | 15 | 0 | 10 | 0 | 1 | 12 | 0 | 1.55431e-15 | 1 | 0 | 1 | 15 | 0 | 1 | 15 | 0 | 3.12639e-13 | 2 | 0 | 1 | 8 | 0 |
| outside_network | 1 | 1 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| rural_fringe | 9 | 9 | 0 | 3 | 0 | 1 | 5 | 0 | 4.44089e-16 | 1 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | 1.7053e-13 | 2 | 0 | 1 | 1 | 0 |

### operation

| operation | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| abstention | 13 | 13 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 13 | 0 | 1 | 13 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| amenity_count | 9 | 9 | 0 | 9 | 0 | 1 | 9 | 0 | n/a | 0 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| nearest_amenity | 8 | 8 | n/a | 0 | 0 | 1 | 8 | 0 | n/a | 0 | 0 | 1 | 8 | 0 | 1 | 8 | 0 | 1.42109e-13 | 8 | 0 | n/a | 0 | 0 |
| network_detour | 6 | 6 | n/a | 0 | 0 | n/a | 0 | 0 | 2.22045e-15 | 6 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| open_amenities | 15 | 15 | 0 | 15 | 0 | 1 | 15 | 0 | n/a | 0 | 0 | 1 | 15 | 0 | 1 | 15 | 0 | n/a | 0 | 0 | 1 | 15 | 0 |

### request_operation

| request_operation | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| amenity_count | 4 | 4 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 4 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| nearest_amenity | 2 | 2 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| network_detour | 3 | 3 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| open_amenities | 4 | 4 | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 | 1 | 4 | 0 | 1 | 4 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| (not set) | 38 | 38 | 0 | 24 | 0 | 1 | 32 | 0 | 2.22045e-15 | 6 | 0 | 1 | 38 | 0 | 1 | 38 | 0 | 1.42109e-13 | 8 | 0 | 1 | 15 | 0 |

### threshold_min

| threshold_min | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 19 | 19 | 0 | 16 | 0 | 1 | 16 | 0 | n/a | 0 | 0 | 1 | 19 | 0 | 1 | 19 | 0 | n/a | 0 | 0 | 1 | 11 | 0 |
| 15 | 9 | 9 | 0 | 8 | 0 | 1 | 8 | 0 | n/a | 0 | 0 | 1 | 9 | 0 | 1 | 9 | 0 | n/a | 0 | 0 | 1 | 4 | 0 |
| (not set) | 23 | 23 | n/a | 0 | 0 | 1 | 8 | 0 | 2.22045e-15 | 6 | 0 | 1 | 23 | 0 | 1 | 23 | 0 | 1.42109e-13 | 8 | 0 | n/a | 0 | 0 |

### time_of_day

| time_of_day | Cases | Scored | reachable_count_error mean | reachable_count_error n | reachable_count_error failed | reachable_set_jaccard mean | reachable_set_jaccard n | reachable_set_jaccard failed | route_stretch_abs_error mean | route_stretch_abs_error n | route_stretch_abs_error failed | status_match mean | status_match n | status_match failed | task_success mean | task_success n | task_success failed | travel_time_abs_error_s mean | travel_time_abs_error_s n | travel_time_abs_error_s failed | unknown_set_jaccard mean | unknown_set_jaccard n | unknown_set_jaccard failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| afternoon | 3 | 3 | 0 | 2 | 0 | 1 | 2 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 2 | 0 |
| evening | 6 | 6 | 0 | 5 | 0 | 1 | 5 | 0 | n/a | 0 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | 1 | 5 | 0 |
| morning | 3 | 3 | 0 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 3 | 0 | 1 | 3 | 0 | n/a | 0 | 0 | 1 | 3 | 0 |
| night | 6 | 6 | 0 | 5 | 0 | 1 | 5 | 0 | n/a | 0 | 0 | 1 | 6 | 0 | 1 | 6 | 0 | n/a | 0 | 0 | 1 | 5 | 0 |
| none | 33 | 33 | 0 | 9 | 0 | 1 | 17 | 0 | 2.22045e-15 | 6 | 0 | 1 | 33 | 0 | 1 | 33 | 0 | 1.42109e-13 | 8 | 0 | n/a | 0 | 0 |

## 4. Efficiency

| Measure | Value |
| --- | --- |
| Wall clock (s) | 2.40444 |
| Cases | 51 |
| Throughput (cases/s) | 21.2107 |
| Latency p50 (s) | 0.0160062 |
| Latency p90 (s) | 0.0167536 |
| Latency p99 (s) | 0.672888 |
| Latency max (s) | 1.11382 |
| Timeout rate | 0 |
| Failure rate | 0 |
| Retries | 0 |
| Peak RSS (bytes) | 266649600 |
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
| geoevals_version | 0.1.0.dev0 |
| geopandas_version | 1.2.0 |
| geos_version | 3.14.1 |
| git_commit | 66bd8037e31a4264c531e91bf54429cdfc11af4e |
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
| uv_lock_sha256 | 70ba69c80197dc92ae3a9d4c6a24c2f950263e532793f7f9122f8a427620ffeb |

## 8. Provenance and dataset licenses

| Field | Value |
| --- | --- |
| Benchmark license | MIT |
| Authors | GeoEvals contributors |
| Created | 2026-10-09 |
| Reference workflow | reference.py |
| Notes | The town is generated by make_fixture.py (seeded). Every expected output is computed by reference.py with networkx Dijkstra; regenerate them with `geoevals bench regenerate human_context_access`. The tests check every expected output against an independent scipy.sparse.csgraph implementation (the access_baseline adapter). |
| Dataset | human_context_access |

| Asset | License | Attribution | Redistributable | Source |
| --- | --- | --- | --- | --- |
| town_nodes | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic town nodes for the human-context access benchmark. |
| town_edges | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic town edges for the human-context access benchmark. |
| town_pois | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic town pois for the human-context access benchmark. |
| town_neighborhoods | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic town neighborhoods for the human-context access benchmark. |

## 9. Limitations

- One small synthetic town; it tests access computations, not scale or real-world data quality.
- Walking is modeled as a constant speed on mapped street lengths; crossings, slope, signals and personal mobility are not modeled.
- Opening hours are evaluated with a documented subset of the OpenStreetMap syntax (docs/human-context.md); values outside it count as unknown. Travel time is not added to the instant.
- Tolerances are tight because the network, lengths and speed are all given; they absorb only floating-point summation order.
