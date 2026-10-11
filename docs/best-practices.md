# Best practices

This document lists the minimum standards for a GeoEvals benchmark and for the people who run
it and report its results. Each standard says what is required and which part of GeoEvals
supports it. Benchmark authors should also read
[`benchmark-authoring.md`](benchmark-authoring.md).

## Standards for benchmarks

| Standard | Minimum requirement | Support in GeoEvals |
| --- | --- | --- |
| Spatial integrity | State the CRS and axis order, the linear units, geometry validity, geodesic or projected measurement, and the tolerance of each check. | Output contract with `crs`; `crs_match`, `geometry_match`, `validity_match`; tolerances with units ([`metrics.md`](metrics.md)) |
| Data provenance | Record the source or citation, access date, license, attribution, processing steps, checksum, version and known limitations of every asset. | Dataset manifest schema; `geoevals data verify` ([`data-governance.md`](data-governance.md)) |
| Split integrity | Pick a geographic, scene, temporal or entity holdout that matches the claim, and document the leakage checks. | `splits` in the spec, the `split` of each case and asset |
| Uncertainty | Report sample counts and intervals, the uncertainty of the reference, and the coverage limits. | `n`, `n_failed` and a 95% bootstrap interval for every summary metric |
| Robustness | Break results down by region, density, class, time of day or other shifts that matter for the claim. | Case `strata`; the report's breakdown section |
| Efficiency | Record wall-clock time, hardware or API, memory where possible, tokens and cost, retries and failure rate. | Run `efficiency` and the environment fingerprint |
| Fairness and privacy | Aggregate demographics, avoid re-identification, report group-level errors, and apply minimum aggregation thresholds where needed. | Data governance rules; no personal traces in the repository |
| Human judgments | Use a clear rubric, independent ratings, agreement statistics and sampling details, and keep preferences apart from measurements. | The `judgment` evidence type ([`human-context.md`](human-context.md)) |
| Comparability | Version the benchmark and the metrics, pin the config, and state which changes break direct comparison. | Versions and hashes in every run result ([`reproducibility.md`](reproducibility.md)) |

## Practices for benchmark authors

- **Start narrow.** One well-specified operation with traps and clear tolerances is better
  than many loosely defined ones.
- **Write the request two ways.** Give each case a natural-language `prompt` (for model-based
  adapters) and structured `inputs` (for deterministic adapters). Both must ask for the same
  thing.
- **Add traps on purpose.** Include the mistakes that practitioners make: swapped axes,
  distances in degrees, buffers on unprojected data, the wrong spatial predicate, mismatched
  CRSs, timezones and opening hours that cross midnight. Mark them with a `trap` stratum.
- **Include requests that must be declined.** Missing units, missing CRS information, absent
  features or attributes, contradictory requests and requests outside the data extent.
- **Test the boundaries.** Check that an answer exactly at the tolerance passes and one just
  beyond it fails, and that an empty geometry, a null output and a malformed output are each
  handled.
- **Avoid environment-dependent results.** Do not use CRS pairs that need a PROJ grid, such as
  NAD27 in the continental US. Check expected outputs with `PROJ_NETWORK=OFF`.
- **Keep fixtures small and synthetic** (under 1 MB per benchmark) unless the license allows
  redistribution.
- **Write the limitations down.** State what the benchmark does not test in the spec's
  `limitations` and in the benchmark card.

## Practices for evaluators

- **Report the versions with the score.** Benchmark version, metric versions, split, dataset
  manifest hash and adapter version. The report shows all of them.
- **Read the failure table first.** Aggregates hide which cases fail and why.
- **Look at the strata.** A high overall score can hide a stratum that always fails, for
  example every axis-order trap.
- **Report the interval, not only the mean.** With few cases per stratum, intervals are wide.
- **Report the cost.** Give latency percentiles, failure and timeout rates, tokens and cost
  together with the correctness scores. State the price table you used.
- **Do not compare across versions.** If the benchmark version, a metric version, the split
  or the manifest hash differs, the runs are not comparable.
- **Do not present a proxy as an observation.** Keep the evidence type of each value.

## Metric choice

Use a metric only where its assumptions hold:

| Metric family | Examples | Caution |
| --- | --- | --- |
| Detection and segmentation | Precision, recall, F1, IoU, AP | Class balance and matching rules matter. |
| Geometry | Hausdorff distance, displacement, length and area error | Choose projected or geodesic measurement deliberately. |
| Network | Connectivity, component count, route stretch, reachability | Define the graph construction and its tolerances. |
| Access | Travel time, reachable destinations, population-weighted access | Schedules, travel mode, departure time and the population denominator matter. |
| Activity | Count error, MAE and RMSE, temporal profile error | A proxy is not the same as observed pedestrian activity. |
| Ranking and suitability | NDCG, pairwise agreement, preference satisfaction | The ground truth depends on the context and the user. |
| Calibration and uncertainty | Brier score, ECE, interval coverage | Use only when predictions have a real probabilistic meaning. |
| Agent success | Exact output checks, task completion, valid artifact rate | Use deterministic checks when there is one checkable answer. An LLM grader is allowed only in a graded eval that follows the graded-eval rules ([eval-authoring.md](eval-authoring.md#rules)). |
| Efficiency | Latency, throughput, cost per case, failure rate | Include setup, retries and the hardware or API context. |

v0.1 implements the geometry, network, access, agent-success and efficiency families. The
registered metrics are defined in [`metrics.md`](metrics.md).
