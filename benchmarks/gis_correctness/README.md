# Benchmark card: `gis_correctness`

| Field | Value |
| --- | --- |
| Benchmark ID | `gis_correctness` |
| Version | 0.1.0 (`benchmark.yaml`) |
| Cases | 56, one split (`test`) |
| License | MIT (spec, cases and fixtures) |
| Reference workflow | [`reference.py`](reference.py) (Shapely, pyproj, GEOS, PROJ) |
| Published baselines | [`baselines/gis_correctness/gis_baseline/`](../../baselines/gis_correctness/gis_baseline/) (deterministic baseline), [`baselines/gis_correctness/mock_failures/`](../../baselines/gis_correctness/mock_failures/) (scripted failures) |

## Purpose

`gis_correctness` checks whether a system gets basic GIS operations right: the answer, its
coordinate reference system (CRS) and its units. It also checks whether the system declines
requests that it cannot answer correctly. It is a correctness test on small inputs, not a test
of scale or speed.

Many cases are traps (35 of 56, stratum `trap: true`). They target common mistakes: swapped
axis order, planar distances in degrees, a buffer in degrees instead of meters, `within` used
where `intersects` was asked, and a join across two CRSs. Each case states the request in
natural language (`prompt`) and in structured form (`inputs`). Thus both model-based and
deterministic adapters can run it.

## Operations and case counts

| Operation | Cases | Case file | What it covers |
| --- | --- | --- | --- |
| `crs_transform` | 10 | `cases/crs_transform.jsonl` | Web Mercator, UTM (with an axis-order trap and a southern-hemisphere false northing), State Plane in US survey feet, a NAD27 datum shift, Mercator near the antimeridian, polar stereographic, and an invalid CRS |
| `distance` | 9 | `cases/distance.jsonl` | Geodesic and projected distances in km, m, mi, ft and US survey ft |
| `buffer` | 7 | `cases/buffer.jsonl` | A point in geographic coordinates, a line, negative buffers (one collapses to empty), cap styles, a dissolved multi-buffer |
| `validity` | 9 | `cases/validity.jsonl` | Detection (bowtie, unclosed ring, duplicate vertex, hole outside the shell, overlapping parts, zero-area sliver, empty geometry) and repair (bowtie, figure eight) |
| `spatial_join` | 7 | `cases/spatial_join.jsonl` | `within`, `intersects` and `contains` joins, shared boundaries, nearest with a maximum distance, a CRS mismatch, one-to-many matches |
| `overlay` | 6 | `cases/overlay.jsonl` | Intersection, union, difference, symmetric difference, clip, mixed geometry types |
| `abstention` | 8 | `cases/abstention.jsonl` | Requests to decline: a buffer without units, a join without a CRS or a predicate, missing features or attributes, a contradictory request, an area outside the data, a planar distance in a geographic CRS |
| **Total** | **56** | | |

The expected status is `ok` for 47 cases. For the other 9, the system must decline:
`needs_clarification`, `insufficient_data` or `invalid_request`. This group has the 8
abstention cases and `crs_transform-003` (invalid CRS). The output contract is the
`output_schema` in [`benchmark.yaml`](benchmark.yaml).

## Schema

Each case is one JSON line in `cases/<operation>.jsonl` with `case_id`, `operation`, `split`,
`prompt` (the request in natural language), `inputs` (`files`: fixture paths relative to the
spec, and `params`), `expected` (inline, or a path to a JSON file in `expected/`),
`tolerances` (name -> `{value, units}`) and `strata`. The input and output contracts are the
`input_schema` and `output_schema` in [`benchmark.yaml`](benchmark.yaml). An answer has a
`status` and, for `ok`, one of a GeoJSON `geometry`, a GeoJSON `feature_collection` or a
`value` with `units`, plus the `crs` of the answer (and a `reason` category for detection
answers). The fixtures are GeoJSON (RFC 7946, `OGC:CRS84`, except two files in UTM zone 33N
that test CRS handling); [`manifest.yaml`](manifest.yaml) lists each one's CRS and bounding box.

## Metrics and tolerances

The headline metric is `task_success`. A case passes only if every check that applies passes.
The checks are `status_match`, `crs_match`, `geometry_match`, `validity_match`,
`attribute_match`, `value_abs_error` and `value_rel_error`.
[`docs/metrics.md`](../../docs/metrics.md) defines each metric.

Each case sets its own tolerances, always with explicit units. The spec sets none.

| Tolerance | Units | Metric | Values used |
| --- | --- | --- | --- |
| `tol_m` (Hausdorff distance) | m | `geometry_match` | 0.001 m for CRS transforms, joins and overlays; 0.01 m for geometry repair; 0.01 to 5 m for buffers; 12 m for the NAD27 datum shift (`crs_transform-007`) |
| `area_tol_rel` | ratio | `geometry_match` | 0.01 for buffers; 1e-06 for overlays and repairs |
| `abs_tol` | the answer's units | `value_abs_error` | 0.001 km, 0.01 m, 0.001 mi, 1e-05 mi, 0.03 ft, 0.03 US survey ft |
| `rel_tol` | ratio | `value_rel_error` | 1e-06 for every distance |
| `float_tol` | the attribute's units | `attribute_match` | 0.01 m (`spatial_join-005`, nearest distance) |

The buffer tolerances accept reasonable method choices, not errors. They allow a circle with 8
or more segments per quarter and any suitable local projection. For example, on `buffer-001`
the reference (local azimuthal equidistant) and the baseline (estimated UTM zone) differ by
0.55 m, and the tolerance is 5 m.

## Collection process

All 13 fixtures in [`fixtures/`](fixtures/) are synthetic. The GeoEvals contributors wrote them
by hand, and they contain no real-world source data. Together they take about 52 KB on disk. Each
fixture is an asset in [`manifest.yaml`](manifest.yaml) with its SHA-256, CRS, bounding box,
license (MIT) and known limitations. To check the files, run
`uv run geoevals data verify benchmarks/gis_correctness/manifest.yaml`.

`reference.py` computes every expected output (inline in a case or in `expected/`). Do not edit
expected outputs by hand. Regenerate them and check that the committed outputs are current:

```sh
uv run geoevals bench regenerate gis_correctness
PROJ_NETWORK=OFF uv run geoevals bench regenerate gis_correctness --check
```

## Geography

The fixtures are invented features placed near real places so that the coordinates look
familiar: most of them in and around Berlin (buffers, joins, overlays), places in Berlin,
Paris and London, two zones near Paris (an area outside the data extent, on purpose), and
distance points in New York, London, the Arctic at 70° N and the South Pacific, two of
them on opposite sides of the antimeridian (Suva and Apia). The CRS cases carry their
own coordinates and cover the southern hemisphere, polar regions, the continental US (State
Plane, NAD27) and the antimeridian. No fixture describes a surveyed real-world feature.

## Time range

None. The fixtures have no time dimension; each manifest asset records its creation date,
2026-10-09, as its `time_range`. The answers do not depend on any date, except through the
PROJ and GEOS versions that compute them (see Limitations).

## License

MIT, like the rest of the repository: the spec, the cases, the expected outputs and the
fixtures (attribution "GeoEvals contributors", `redistributable: true`). The license of every
asset is listed in the [license inventory](../../datasets/README.md#license-inventory).

## Limitations

- The fixtures are small and synthetic. They test operation correctness, not scale or the
  quality of real-world data.
- One reference workflow computes the expected outputs (Shapely, pyproj, GEOS, PROJ). If these
  libraries share an error, the benchmark does not catch it. The `gis_baseline` adapter uses the
  same libraries, so its perfect score shows that the harness works. It does not show that the
  benchmark is hard.
- Each case has its own tolerance. A looser tolerance hides small errors.
- There is one case per variant. A per-stratum score therefore comes from few cases, often one,
  and its confidence interval is wide.
- The cases avoid CRS pairs that need a PROJ grid (for example NAD27 in the continental US). Thus
  the results do not depend on network access or on installed grids. Because of this, the
  benchmark does not test grid-based datum transforms.

## Intended uses

- Check whether a GIS system, classical or model-based, returns correct geometry, CRS,
  attributes and values within stated tolerances, and abstains when it should.
- Compare systems or versions of one system on the same cases, with the run config and the
  benchmark version reported next to the scores.
- Find which operations and traps (stratum `trap`) a system gets wrong.

## Prohibited uses

- Do not report a score as a measure of general geospatial ability or of performance on real
  data: the cases are small, synthetic and one per variant.
- Do not train or tune a system on the cases or the expected outputs and then report its score
  on them as a held-out result.
- Do not compare scores across benchmark versions, or from runs with different tolerances,
  without saying so (see [`docs/reproducibility.md`](../../docs/reproducibility.md)).

## Reproduce the published baseline

The published baseline in
[`baselines/gis_correctness/gis_baseline/`](../../baselines/gis_correctness/gis_baseline/) is a
run of the deterministic `gis_baseline` adapter. It contains `result.json`, `cases.jsonl`,
`report.md` and the pinned run config `config.yaml` (split `test`, seed 0, timeout 60 s, no
retries, 1 worker). Its `task_success` is 1.0 on all 56 cases.

Rerun the baseline and compare the new run with the committed result:

```sh
uv sync
uv run geoevals reproduce baselines/gis_correctness/gis_baseline
```

The command reads the benchmark ID and the adapter from `result.json` and runs
`benchmarks/<id>/benchmark.yaml` with the committed `config.yaml`. It then compares the new run
with the committed result, as `geoevals compare` does. Exit status 0 means that nothing differs
except timing, memory, timestamps, `run_id` and `environment`. Exit status 1 lists each
difference. The rerun goes to a temporary directory. Use `--out <dir>` to keep it.

Per case, the command compares `status`, `output` and `metrics`. At run level, it compares the
benchmark, the adapter, the config hash, the dataset manifest hash, the summary metrics and
the failures. Numbers match within an absolute 1e-07 or a relative 1e-09 (`--abs-tol`,
`--rel-tol`). GEOS and PROJ builds on different platforms differ in the last bits. Compared
with this macOS arm64 baseline, a Linux x86_64 rerun differed by at most 6.0e-09 m. Everything
else must match exactly. CI runs the same check (`tests/test_reproduce.py`, marked
`integration`).

A second published run,
[`baselines/gis_correctness/mock_failures/`](../../baselines/gis_correctness/mock_failures/),
uses the `mock` adapter to show what failures look like in a run result and its report. The
mock returns the reference output for every case except nine, chosen in the commented
`config.yaml`: every failure status (`adapter_error`, `timeout`, `invalid_output`, `skipped`), two
answers to requests that should have been declined (`status_match` reason
`answered_when_should_abstain`), a wrong abstention status, a wrong value and a case that
succeeds on its retry. Its scores say nothing about any real system.

To publish a new baseline after an intended change to the benchmark or the adapter, run it
with the committed config and replace the files (for `mock_failures`, use `--adapter mock`
and keep the commented `config.yaml`: it has the same config hash as the copy):

```sh
uv run geoevals run --benchmark benchmarks/gis_correctness/benchmark.yaml \
  --adapter gis_baseline --config baselines/gis_correctness/gis_baseline/config.yaml --out runs/baseline
run_dir=$(ls -d runs/baseline/*/ | tail -1)
cp "$run_dir"/{result.json,cases.jsonl,config.yaml} baselines/gis_correctness/gis_baseline/
uv run geoevals report baselines/gis_correctness/gis_baseline
rm baselines/gis_correctness/gis_baseline/report.html
```
