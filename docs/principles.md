# Principles

GeoEvals makes evaluations of geospatial AI systems reproducible, comparable and meaningful
beyond one headline accuracy number. This document states what the framework measures and the
rules that every benchmark, metric, adapter and report follows. The other documents apply
these rules in detail.

## What GeoEvals measures

GeoEvals answers three questions about a system:

1. **Can it do the geospatial task?** The answer must be spatially correct, not only
   plausible.
2. **Can we trust its results?** How large are the errors, where does the system fail, and how
   certain is each score?
3. **Does it work in production?** What are the latency, throughput, failure rate, retries,
   memory use and cost?

The questions belong to three pillars:

| Pillar | Scope | v0.1 |
| --- | --- | --- |
| A. Geospatial perception | Extraction from imagery and other rasters: detection, segmentation, change detection | Planned for after v0.1 |
| B. Spatial reasoning and GIS agents | GIS operations, and agents that turn a natural-language request into a valid spatial output | `gis_correctness` |
| C. Human-centered place context | How places work for people: access, mobility, amenities, availability | `human_context_access` |

## Rules

### 1. A benchmark is a contract, not a dataset

A benchmark spec states the task, the intended use, the input and output schemas, the splits,
the metrics with their versions, the tolerances, the dataset manifest, the license, the
provenance and the limitations. `geoevals validate` checks every spec, manifest and run
result against a versioned JSON Schema. The runner does not start a run when the spec or the
manifest is not valid.

### 2. Score spatial correctness, not text

Metrics compare structured outputs: geometry, CRS, attributes, validity, topology, values and
task status. No metric compares code, text or the steps that an agent took. Each check is
independent and reported separately; `task_success` is true only when every check that
applies passes.

### 3. Units and tolerances are explicit

Every tolerance has a value and a unit (meters, square meters, seconds, a ratio). Each spatial
metric states whether it measures geodesically or in a named projected CRS. Coordinates are
always x = longitude or easting first. A tolerance accepts reasonable method choices; it is
not a way to hide errors.

### 4. Declining to answer can be the correct answer

Some requests cannot be answered correctly: a buffer distance without units on geographic
data, a join without CRS information, a feature that does not exist. The correct output then
is a status (`needs_clarification`, `insufficient_data` or `invalid_request`), and a confident
answer fails with the reason `answered_when_should_abstain`.

### 5. Reference outputs come from executable workflows

Every expected output is computed by a reference workflow (`reference.py`) that anyone can
rerun with `geoevals bench regenerate <id>`. Nobody edits expected outputs by hand. A test
checks that the committed outputs match the regenerated ones. Where possible, a second,
independent implementation checks the reference (the human-context benchmark computes paths
with both networkx and `scipy.sparse.csgraph`).

### 6. Failures are visible

Every case gets exactly one status: `scored`, `adapter_error`, `timeout`, `invalid_output` or
`skipped`. No case is dropped silently. One failing case never stops a run. The report lists
every case that failed before it shows aggregates, with its error or the detail of each
check.

### 7. Uncertainty is reported with every score

Each summary metric has its sample count `n`, the number of failed cases and a 95% bootstrap
confidence interval with a fixed seed. Breakdowns by stratum (operation, CRS family,
neighborhood type, time of day) show where a system fails. A score that comes from one case
has a wide interval, and the report shows that.

### 8. Operational cost is part of the result

Every run records per-case latency, scoring time, retries, tokens and cost, and run-level
throughput, latency percentiles, timeout and failure rates, peak memory and totals. A tool
call that succeeds is not a correct answer: agent trajectories are recorded and summarized
but never scored as task success.

### 9. Runs are reproducible, and comparisons are stated

A run with the same config, data and lockfile gives identical per-case results. Every run
records its versions, its config hash, its dataset manifest hash and an environment
fingerprint. Comparisons are valid only between runs with the same benchmark version, metric
versions, split, and dataset manifest hash. See [`reproducibility.md`](reproducibility.md).

### 10. Data rights and privacy come first

A dataset is not open because it is publicly accessible. Each asset records its license,
attribution and whether it can be redistributed. Restricted data is referenced, never
committed. Observations, proxies and judgments are kept apart, and the project makes no
claims about social relationships inferred from co-location, mobility proxies or
demographics. See [`data-governance.md`](data-governance.md) and
[`human-context.md`](human-context.md).

## Non-goals

- A universal score of the overall quality of a place.
- A complete global place database, or a hosted commercial platform.
- A required model architecture or cloud provider.
- A leaderboard that compares results produced with different data, splits or settings.
- Claims about social relationships inferred only from co-location, mobility proxies or
  demographics.

## Trust before breadth

A small number of well-specified benchmarks that anyone can run, with honest limitations and
failures that anyone can inspect, is worth more than a large catalog of loosely defined tasks.
New benchmarks are added only when they meet the
[definition of done](benchmark-authoring.md#definition-of-done).
