# GeoEvals report: example_distance 1.0.0 / mock

## 1. Summary

| Field | Value |
| --- | --- |
| Run ID | example_distance-mock-20261009T120000Z-be3fe555 |
| Benchmark | example_distance 1.0.0 |
| Split | test |
| Adapter | mock 0.1.0 |
| Adapter config | {"behavior": "reference", "seed": 7} |
| Metric versions | value_abs_error 1.0.0 |
| Config hash | be3fe5552cda5245e16d3639bb82740851ec6a941b9c2f2d532a79c80565a61e |
| Dataset manifest hash | 89333bc71f02c647533ab52e592ad22c609728f12eabff6fda0920109db40401 |
| Run result schema | 1.0.0 |
| Started | 2026-10-09T12:00:00Z |
| Finished | 2026-10-09T12:00:01.250000Z |
| Cases | 4 (2 scored, 2 not scored) |

Comparisons are valid only between runs with the same benchmark version, metric versions, split, and dataset manifest hash.

## 2. Summary metrics

| Metric | Version | Mean | Median | 95% CI | n | n failed |
| --- | --- | --- | --- | --- | --- | --- |
| value_abs_error | 1.0.0 | 2510.65 | 2510.65 | [0, 5021.3] | 2 | 1 |

The 95% CI is a bootstrap percentile interval of the mean. n counts the cases with a metric value.

## 3. Breakdown by strata

### crs_family

| crs_family | Cases | Scored | value_abs_error mean | value_abs_error n | value_abs_error failed |
| --- | --- | --- | --- | --- | --- |
| geographic | 1 | 1 | 5021.3 | 1 | 1 |
| projected | 3 | 1 | 0 | 1 | 0 |

### operation

| operation | Cases | Scored | value_abs_error mean | value_abs_error n | value_abs_error failed |
| --- | --- | --- | --- | --- | --- |
| distance | 4 | 2 | 2510.65 | 2 | 1 |

### region

| region | Cases | Scored | value_abs_error mean | value_abs_error n | value_abs_error failed |
| --- | --- | --- | --- | --- | --- |
| africa | 1 | 1 | 5021.3 | 1 | 1 |
| asia | 2 | 0 | n/a | 0 | 0 |
| europe | 1 | 1 | 0 | 1 | 0 |

### trap

| trap | Cases | Scored | value_abs_error mean | value_abs_error n | value_abs_error failed |
| --- | --- | --- | --- | --- | --- |
| true | 1 | 0 | n/a | 0 | 0 |
| (not set) | 3 | 2 | 2510.65 | 2 | 1 |

## 4. Efficiency

| Measure | Value |
| --- | --- |
| Wall clock (s) | 1.25 |
| Cases | 4 |
| Throughput (cases/s) | 3.2 |
| Latency p50 (s) | 0.0105 |
| Latency p90 (s) | 0.6996 |
| Latency p99 (s) | 0.97 |
| Latency max (s) | 1 |
| Timeout rate | 0.25 |
| Failure rate | 0.5 |
| Retries | 2 |
| Peak RSS (bytes) | 104857600 |
| Input tokens | 120 |
| Output tokens | 15 |
| Cost, total (USD) | 0 |
| Cost per case (USD) | 0 |
| Price table hash | n/a |
| Tool error rate | 0.25 |
| Mean agent steps | 3 |

## 5. Failures

| Case | Status | Metric | Error or detail |
| --- | --- | --- | --- |
| dist_002 | scored | value_abs_error | value 5021.3; detail {"reason": "axis_swap", "units": "m"} |
| dist_003 | adapter_error | - | RuntimeError: mock adapter raised on request |
| dist_004 | timeout | - | TimeoutError: case exceeded timeout_s=1 |

## 6. Agent trajectories

| Case | Status | Result | Tool calls | Tool errors | Agent steps | Agent runtime (s) |
| --- | --- | --- | --- | --- | --- | --- |
| dist_001 | scored | passed | 3 | 1 | 4 | n/a |
| dist_002 | scored | failed | 1 | 0 | 2 | 0.005 |

The result comes from the metrics on the output alone. The trajectory is not scored, so tool calls that succeed do not make a case pass.

### Trajectory of dist_002 (failed)

| Step | Tool | Args | Status | Error | Duration (s) | Tokens |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | transform | {"crs": "EPSG:4326"} | ok | - | 0.004 | n/a |
| 1 | (no tool) | {} | ok | - | 0.001 | n/a |

## 7. Environment

| Key | Value |
| --- | --- |
| git_commit | 0123456789abcdef0123456789abcdef01234567 |
| git_dirty | false |
| os | Darwin |
| python | 3.11.9 |
| uv_lock_sha256 | n/a |

## 8. Provenance and dataset licenses

| Field | Value |
| --- | --- |
| Benchmark license | MIT |
| Authors | GeoEvals contributors |
| Created | 2026-10-09 |
| Notes | Hand-written fixture for the report golden test. |
| Dataset | example_points |

| Asset | License | Attribution | Redistributable | Source |
| --- | --- | --- | --- | --- |
| points | MIT | GeoEvals contributors | true | GeoEvals contributors (2026). Synthetic test points. |
| roads | ODbL-1.0 | OpenStreetMap contributors | false | https://www.openstreetmap.org/ |

## 9. Limitations

- Hand-written example run result for tests; the numbers are not measured.
- Pipe | and <tag> characters stay readable.
