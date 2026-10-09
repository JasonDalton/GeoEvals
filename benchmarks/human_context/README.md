# Benchmark card: `human_context_access`

| Field | Value |
| --- | --- |
| Benchmark ID | `human_context_access` (directory `benchmarks/human_context/`) |
| Version | 0.1.0 (`benchmark.yaml`) |
| Pillar | `human_context` |
| Cases | 32, one split (`test`) |
| License | MIT (spec, cases, generator and fixtures) |
| Reference workflow | [`reference.py`](reference.py) (networkx Dijkstra via `geoevals.metrics.network`) |
| Second implementation | `access_baseline` adapter (`scipy.sparse.csgraph`, GeoPandas) |

## Purpose

`human_context_access` checks whether a system computes walking access correctly on a stated
street network: travel time to the nearest amenity, the number of amenities within 10 or 15
minutes, and how much longer the network route is than a straight line. It also checks whether
the system declines requests that the data cannot answer. The concepts (snapping, walking speed,
inclusive thresholds, the detour ratio) are defined in
[`docs/human-context.md`](../../docs/human-context.md); every value is a `proxy`.

It runs in CI on a synthetic town, so it needs no licensed data.

## The synthetic town

[`make_fixture.py`](make_fixture.py) generates the town (seed 20261009) into `fixtures/`: four
GeoParquet 1.1.0 files in `OGC:CRS84`, together about 18 KB.

| File | Contents |
| --- | --- |
| `town_nodes.parquet` | 199 street nodes with `node_id` and `neighborhood_type` |
| `town_edges.parquet` | 310 street edges with `u`, `v`, `length_m` (meters), `highway`, `oneway` (ignored for walking) |
| `town_pois.parquet` | 43 points of interest: `poi_id`, `name`, `amenity_category`, `opening_hours` (OSM syntax; null for 2), `neighborhood_type` |
| `town_neighborhoods.parquet` | 4 neighborhood outlines with `neighborhood_type` |

Neighborhood types: `grid` (100 m blocks), `mixed_use_core` (60 m blocks, some one-way streets),
`cul_de_sac_suburban` (side streets that end in cul-de-sacs, one access road) and `rural_fringe`
(a loop road with spurs, and a hamlet that no road connects to the rest of the town). Amenity
categories: grocery, pharmacy, school, park, transit_stop, clinic.

The generator is deterministic, and its output is the same bytes on macOS and Linux for the
locked package versions. `manifest.yaml` records each file's SHA-256, and
`test_regenerated_fixture_matches_the_manifest` regenerates the town and compares. After a change
to the generator, or a pyarrow upgrade (pyarrow writes its version into each file), run
`uv run python benchmarks/human_context/make_fixture.py` and update the manifest checksums.

## Operations and case counts

| Operation | Cases | What it asks |
| --- | --- | --- |
| `nearest_amenity` | 8 | Walking time in seconds to the nearest POI of a category, and its ID (all tied IDs when several are equally near) |
| `amenity_count` | 9 | Number and IDs of POIs of a category within 10 or 15 minutes, boundary inclusive |
| `network_detour` | 6 | Network distance / geodesic distance between two points (`ratio`) |
| `abstention` | 9 | Requests to decline: an origin or destination off the network, no path (the hamlet), a category not in the data (`insufficient_data`); a negative threshold, coincident points (`invalid_request`); no category or no threshold (`needs_clarification`) |
| **Total** | **32** | |

Strata: `operation`, `neighborhood_type` (of the origin; `outside_network` when it does not
snap), `amenity_category` (`none` for detour questions), plus `threshold_min` for counts and
`abstention`/`expected_status` for abstentions.

## Metrics and tolerances

The headline metric is `task_success` (status, then the value within `abs_tol`). The access
metrics `travel_time_abs_error_s`, `reachable_count_error`, `reachable_set_jaccard` and
`route_stretch_abs_error` report the error per kind of answer; see
[`docs/metrics.md`](../../docs/metrics.md).

| Tolerance | Units | Values |
| --- | --- | --- |
| `abs_tol`, `time_tol_s` | s | 0.001 |
| `abs_tol`, `count_tol` | count | 0 |
| `abs_tol`, `stretch_tol` | ratio | 1e-06 |

The tolerances are tight on purpose. The network, the edge lengths and the speed are all given,
so a correct answer is exact up to floating-point summation order.

## Reference outputs

`reference.py` computes every expected output with networkx; regenerate them with
`uv run geoevals bench regenerate human_context_access`. The `access_baseline` adapter computes
the same answers independently with `scipy.sparse.csgraph.shortest_path`. The tests check that
the two agree within 1e-6 s on every case and on every pair of network nodes. The detour ratios
use PROJ's geodesic, which differs between macOS and Linux in the 15th significant digit, so the
committed-output test compares numbers within a relative 1e-12.

Run the baseline:

```sh
uv run geoevals run --benchmark benchmarks/human_context/benchmark.yaml \
  --adapter access_baseline --config benchmarks/human_context/run_config.yaml --out runs/access
```

It scores `task_success = 1.0` on all 32 cases.

## Limitations

- One small synthetic town: the cases test access computations, not scale or real-world data
  quality.
- Walking is a constant speed on mapped street lengths. Crossings, slope, signals and personal
  mobility are not modeled.
- Opening hours are in the data but no case uses them yet.
