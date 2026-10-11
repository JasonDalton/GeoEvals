# Changelog

All notable changes to GeoEvals are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Benchmarks,
metrics and schemas carry their own versions; see
[Versioning and comparability](README.md#versioning-and-comparability).

## Unreleased

### Changed

- `gis_correctness` 0.2.0 and `human_context_access` 0.2.0: tolerances recalibrated so that a
  correct answer given to 5 decimal places passes, while each case still catches the mistake it
  targets. `crs_transform-004` and `-005` (answers in longitude and latitude): `tol_m` 0.001 m to
  1 m; the smallest targeted mistake is 21 km off. `buffer-005`: `tol_m` 0.2 m to 1 m; its trap
  is 8.3 m off. `network_detour-001` to `-006`: `abs_tol` and `stretch_tol` 1e-6 to 1e-4; a
  haversine straight-line distance is at least 1.0e-3 off. Expected outputs are unchanged.
  Scores are not comparable with 0.1.0.
- `crs_match` 1.1.0 and `gis_correctness` 0.3.0: the CRS label is compared up to axis order,
  so `EPSG:4326` passes where `OGC:CRS84` is expected, and the reverse. Coordinates are always
  longitude first; a swapped answer still fails `geometry_match`. Another datum (for example
  `EPSG:4258`) still fails `crs_match`. Scores are not comparable with 0.2.0.

## 0.1.0 - 2026-10-09

The first release: the evaluation contracts, a deterministic GIS correctness benchmark and a
human-context pilot on walking access to everyday amenities. Only deterministic and mock
adapters ship; no adapter needs credentials or network access.

### Added

#### Benchmarks

- `gis_correctness` 0.1.0 (spatial reasoning): 56 cases covering CRS transformation, distance,
  buffering, geometry validity, spatial joins, overlays and abstention, on 13 synthetic
  GeoJSON fixtures, with an executable reference workflow.
- `human_context_access` 0.1.0 (human context): 51 cases covering travel time, amenity counts,
  detour ratio, opening hours and abstention, on a seeded synthetic town. Every output field
  carries an `evidence_type` (`observed`, `proxy` or `judgment`). A real-geography pilot on
  OpenStreetMap data is built locally with `geoevals data fetch` and `geoevals bench build`;
  no OpenStreetMap data is committed.
- `smoke` 0.1.0: a 5-case benchmark that CI runs with the mock adapter.
- Published baselines with reports: `gis_correctness/gis_baseline`,
  `gis_correctness/mock_failures` and `human_context_access/access_baseline`.

#### Schemas

- Benchmark spec schema 1.1.0 (`schemas/benchmark.schema.json`), with `evidence_type` on
  every output field of a human-context benchmark.
- Dataset manifest schema 1.0.0 (`schemas/dataset-manifest.schema.json`), in YAML or JSONL,
  with source, license, checksum, and spatial and temporal metadata for every asset.
- Run result schema 1.0.0 (`schemas/run-result.schema.json`), with per-case status, metrics,
  timing, tokens, cost and trajectories, and the environment fingerprint.

#### Metrics

- `task_success` 1.3.0: true only when every applicable check passes.
- `status_match` 1.1.0, `crs_match` 1.0.0, `geometry_match` 1.1.0, `validity_match` 1.1.0
  and `attribute_match` 1.1.0.
- `value_abs_error` 1.0.0 and `value_rel_error` 1.0.0.
- Network access: `travel_time_abs_error_s` 1.0.0, `reachable_count_error` 1.0.0,
  `reachable_set_jaccard` 1.0.0, `route_stretch_abs_error` 1.0.0 and
  `unknown_set_jaccard` 1.0.0.

#### Adapters

- `gis_baseline` 0.1.0: a deterministic Shapely, pyproj and GeoPandas baseline for
  `gis_correctness`.
- `access_baseline` 0.1.0: a SciPy sparse-graph and GeoPandas baseline for
  `human_context_access`.
- `mock` 0.1.0: injects every failure status (`adapter_error`, `timeout`, `invalid_output`,
  `skipped`), and in `mock_agent` mode writes scripted agent trajectories.

#### Framework and tools

- A runner with per-case timeouts in worker processes, retries, `workers: N` concurrency,
  per-case and run-level latency, throughput, memory, tokens and cost (from a user-supplied
  price table), and an environment fingerprint.
- Run directories with `result.json`, `cases.jsonl`, `config.yaml`, `run.log` and GeoParquet
  artifacts, and Markdown and self-contained HTML reports.
- The `geoevals` command: `validate`, `run`, `report`, `compare`, `reproduce`,
  `adapters list|predict`, `data verify|fetch|inventory|licenses`, `bench regenerate|build`
  and `--version`.
- Documentation, benchmark and dataset cards, a generated license inventory, governance files
  and a citation file.
- CI on Ubuntu (Python 3.11 and 3.12) and macOS (Python 3.12): lint, format, type check,
  tests, document validation, license checks, the smoke benchmark, baseline reproduction from
  a clean environment, a wheel install in a fresh venv, and a gitleaks scan of the full
  history.

<!-- TODO(maintainer): once the repository is hosted (open question 3 in the PRD), make the
version headings links: [Unreleased] compares v0.1.0...HEAD, [0.1.0] is the v0.1.0 tag. -->
