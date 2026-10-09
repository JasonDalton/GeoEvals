---
name: Benchmark proposal
about: Propose a new benchmark or a large change to an existing one
title: "benchmark: "
labels: benchmark
---

<!--
Read docs/benchmark-authoring.md first. A benchmark merges only when it meets the
definition of done (CONTRIBUTING.md). Answer what you can now; the rest can follow in the
pull request.
-->

## Task statement

<!-- The capability the benchmark measures, in one or two sentences. -->

## Intended use

<!-- Who uses the results to decide what. Also say what the benchmark must not be used for. -->

## Pillar

- [ ] Geospatial perception
- [ ] Spatial reasoning and GIS agents
- [ ] Human-centered place context

## Inputs and outputs

<!-- What an adapter receives and what it must return (status, value, units, geometry, CRS). -->

## Data

| Asset | Source | License | Redistributable? | Size | CRS, extent, time range |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

<!-- Data that is not redistributable is fetched into data/raw/ and never committed. -->

## Cases and splits

<!-- Approximate case count, how cases are made, the split strategy and the leakage controls. -->

## Metrics and tolerances

<!-- Existing metrics (docs/metrics.md) or new ones, with units, tolerances and aggregation. -->

## Baseline and reference workflow

<!-- How the expected outputs are computed, and which adapter is the baseline. -->

## Known limitations

<!-- Geographic, temporal or scale coverage; anything the scores cannot support. -->
