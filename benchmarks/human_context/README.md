# Benchmark card: `human_context_access`

| Field | Value |
| --- | --- |
| Benchmark ID | `human_context_access` (directory `benchmarks/human_context/`) |
| Version | 0.2.0 (`benchmark.yaml`) |
| Pillar | `human_context` |
| Cases | 51, one split (`test`) |
| License | MIT (spec, cases, generator and fixtures) |
| Reference workflow | [`reference.py`](reference.py) (networkx Dijkstra via `geoevals.metrics.network`) |
| Second implementation | `access_baseline` adapter (`scipy.sparse.csgraph`, GeoPandas) |
| Published baseline | [`baselines/human_context_access/access_baseline/`](../../baselines/human_context_access/access_baseline/) |
| Real-geography pilot | `human_context_pilot`, built locally from OpenStreetMap (ODbL-1.0, not committed); see [below](#real-geography-pilot) |

## Purpose

`human_context_access` checks whether a system computes walking access correctly on a stated
street network: travel time to the nearest amenity, the number of amenities within 10 or 15
minutes, how much longer the network route is than a straight line, and which amenities within
a walking threshold are open at a stated local date and time. It also checks whether the system
declines requests that the data cannot answer. The concepts (snapping, walking speed, inclusive
thresholds, the detour ratio, opening hours at an instant) are defined in
[`docs/human-context.md`](../../docs/human-context.md); every value is a `proxy`.

It runs in CI on a synthetic town, so it needs no licensed data. A real-geography pilot
(`human_context_pilot`, [below](#real-geography-pilot)) runs the same operations on an
OpenStreetMap extract that each user downloads; it is a manual path, outside CI.

## Collection process

No data is collected: the benchmark runs on a synthetic town.
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

## Geography

An invented town of about 3.0 km by 2.0 km (neighborhood outlines). It is placed on the equator near longitude 0
(bounding box `[-0.0004492, -0.0040697, 0.0260511, 0.0135655]` in `OGC:CRS84`) so that plane
meters and geodesic meters agree closely; the location has no meaning and is in the sea. The
four neighborhood types stand for street patterns, not for any real place. Real geography is
only in the [pilot](#real-geography-pilot), which is not part of this benchmark's committed
data.

## Time range

The street network and the POIs have no date; each manifest asset records its creation date,
2026-10-09, as its `time_range`. The `open_amenities` cases ask about local instants
between 2026-10-08 and 2026-12-25 (stated in each case, with the time zone `Africa/Abidjan`),
and the answers depend only on the stated instant and the opening hours in the fixture.

## Schema

The four fixture files and their columns are listed under [Collection process](#collection-process).
Each case is one JSON line in `cases/<operation>.jsonl` with `case_id`, `operation`, `split`,
`prompt`, `inputs` (`files`: the fixture paths; `params`: `origin`, and `destination`,
`category`, `minutes`, an optional `speed_mps`, and `date`, `time`, `timezone` and
`public_holidays` where the question needs them), `expected`, `tolerances` and `strata`. The input and output contracts are the
`input_schema` and `output_schema` in [`benchmark.yaml`](benchmark.yaml): an answer has a
`status` and, for `ok`, a `value` with `units` (`s`, `count` or `ratio`), the `ids` it refers
to, and `unknown_ids` for opening-hours questions. Every output field declares its
`evidence_type`; all values are `proxy`.

## License

MIT, like the rest of the repository: the spec, the cases, the generator and the fixtures
(attribution "GeoEvals contributors", `redistributable: true`). The pilot's OpenStreetMap data
is `ODbL-1.0` and is never committed (see [Licenses](#licenses)). The license of every asset is
listed in the [license inventory](../../datasets/README.md#license-inventory).

## Operations and case counts

| Operation | Cases | What it asks |
| --- | --- | --- |
| `nearest_amenity` | 8 | Walking time in seconds to the nearest POI of a category, and its ID (all tied IDs when several are equally near) |
| `amenity_count` | 9 | Number and IDs of POIs of a category within 10 or 15 minutes, boundary inclusive |
| `network_detour` | 6 | Network distance / geodesic distance between two points (`ratio`) |
| `open_amenities` | 15 | Number and IDs of POIs of a category within 10 or 15 minutes that are open at a local date, time and time zone, plus `unknown_ids` for POIs with missing hours |
| `abstention` | 13 | Requests to decline: an origin or destination off the network, no path (the hamlet), a category not in the data, every POI within reach with unknown hours (`insufficient_data`); a negative threshold, coincident points, an unknown time zone, a date that does not exist (`invalid_request`); no category, no threshold or no time (`needs_clarification`) |
| **Total** | **51** | |

Strata: `operation`, `neighborhood_type` (of the origin; `outside_network` when it does not
snap), `amenity_category` (`none` for detour questions), `time_of_day` (`night` 00:00-05:59,
`morning` 06:00-11:59, `afternoon` 12:00-17:59, `evening` 18:00-23:59, `none` without a time),
plus `threshold_min` for counts, `day_type` (`weekday`, `weekend`, `public_holiday`) and
`hours_feature` (`regular`, `overnight`, `public_holiday`, `24_7`, `boundary`,
`missing_hours`) for opening-hours questions, and `abstention`/`expected_status` for
abstentions.

## Time-specific availability

Each `open_amenities` case states an ISO date, a `HH:MM` local time, an IANA time zone
(`Africa/Abidjan`, the zone of longitude 0 on the equator) and, optionally, the dates that are
public holidays. The cases cover hours that cross midnight (transit stops open
`Mo-Fr 05:00-01:00; Sa,Su 06:00-00:30`, asked at 00:15, 00:45 and 05:30), `PH off` rules on a
listed holiday (and a holiday Monday on which a weekday-only rule still applies), `24/7`
POIs at night, span boundaries (open at the start minute, closed at the end minute) and a POI
with missing hours (`poi-036`), which goes to `unknown_ids`. When every POI within reach has
unknown hours, the expected status is `insufficient_data`.

Opening hours are evaluated by `geoevals.opening_hours`, pure Python with no network access, on
the OpenStreetMap subset documented in
[`docs/human-context.md`](../../docs/human-context.md#time-specific-poi-availability). A value
that is missing or outside the subset makes the POI unknown (missing data); it never makes the
reference or the adapter fail. The reference workflow and the `access_baseline` adapter share
this module (the shortest paths stay independent), so it is tested on its own against
hand-worked expectations in `tests/test_opening_hours.py`. Travel time is not added to the
instant: a POI counts when it is open at the stated time.

## Metrics and tolerances

The headline metric is `task_success` (status, then the value within `abs_tol`). The access
metrics `travel_time_abs_error_s`, `reachable_count_error`, `reachable_set_jaccard` and
`route_stretch_abs_error` report the error per kind of answer, and `unknown_set_jaccard` checks
the unknown bucket (`unknown_ids`) of opening-hours answers; see
[`docs/metrics.md`](../../docs/metrics.md).

| Tolerance | Units | Values |
| --- | --- | --- |
| `abs_tol`, `time_tol_s` | s | 0.001 |
| `abs_tol`, `count_tol` | count | 0 |
| `abs_tol`, `stretch_tol` | ratio | 1e-04 |

The tolerances are tight on purpose. The network, the edge lengths and the speed are all given,
so a correct answer is exact up to floating-point summation order. The detour ratio tolerance,
1e-4, accepts a correct ratio given to 5 decimal places. It still catches a straight-line
distance computed with the haversine formula (at least 1.0e-3 off on these cases) or in planar
degrees, and any longer path.

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

It scores `task_success = 1.0` on all 51 cases.

The published baseline in
[`baselines/human_context_access/access_baseline/`](../../baselines/human_context_access/access_baseline/)
is this run with the same config. Rerun it and compare with the committed result:

```sh
uv run geoevals reproduce baselines/human_context_access/access_baseline
```

To publish a new baseline after an intended change, follow the steps in the
[`gis_correctness` card](../gis_correctness/README.md#reproduce-the-published-baseline) with
this benchmark's spec, the `access_baseline` adapter and
`baselines/human_context_access/access_baseline/`.

## Limitations

- One small synthetic town: the cases test access computations, not scale or real-world data
  quality.
- Walking is a constant speed on mapped street lengths. Crossings, slope, signals and personal
  mobility are not modeled.
- Opening hours use one time zone and a subset of the OpenStreetMap syntax (no months, week
  numbers, school holidays or sunrise/sunset); values outside it count as unknown.

## Intended uses

- Check whether a system, classical or model-based, computes walking access on a stated
  network correctly and abstains when the data cannot answer.
- Compare systems or versions of one system on the same cases, per operation and stratum.
- Test an access pipeline end to end before running it on real data (the pilot).

## Prohibited uses

- Do not read the values as measures of access, quality of life or opportunity in any real
  place: the town is invented and the values are proxies.
- Do not train or tune a system on the cases or the expected outputs and then report its score
  on them as a held-out result.
- Do not use the benchmark, or tools tuned on it, to rank or make decisions about real
  neighborhoods or their residents. The pilot's own prohibited uses are
  [below](#prohibited-uses-1).

## Real-geography pilot

### Purpose

The pilot shows that the access benchmark works beyond the synthetic town: the same operations,
reference workflow and adapters run on a real street network and real points of interest from
OpenStreetMap (OSM). It also reports what real data adds: missing attributes, origins that do
not reach the network, and how much results depend on the spatial unit used to summarize them.
Its cases are generated, never committed, and are not a published baseline.

### Geography and time range

| Field | Value |
| --- | --- |
| Bounding box | `[-73.225, 44.465, -73.2, 44.485]` (lon/lat, about 2 km x 2.2 km): a **placeholder**, part of Burlington, Vermont, USA, chosen only to exercise the pipeline. The pilot geography is an open question (PRD section 9, question 1) |
| Time range | OSM as of 2026-01-01 00:00 UTC (an Overpass `date:` snapshot); the opening-hours question is asked for Saturday 2025-12-13 at 19:00 `America/New_York` |
| Configuration | Box and snapshot date in [`datasets/manifests/human_context_pilot.yaml`](../../datasets/manifests/human_context_pilot.yaml) (or `--bbox`/`--date` on `geoevals data fetch`); time zone, seed, origin count, grid sizes and questions in [`pilot.yaml`](pilot.yaml) |

### Licenses

- The OSM extract and everything built from it (the pilot's fixtures, cases and report form a
  derived database) are under the Open Database License, `ODbL-1.0`, with the attribution
  "© OpenStreetMap contributors". They are `redistributable: false` here and stay in the
  gitignored `data/raw/human_context_pilot/`. Whether small derived samples could ever be
  committed is an open question (PRD section 9, question 2); until a qualified reviewer
  answers it, they are not.
- The code, the manifest, `pilot.yaml` and these instructions are MIT, like the rest of the
  repository.

### How to run it (manual)

Download instructions and details: [`datasets/download_instructions/human_context_pilot.md`](../../datasets/download_instructions/human_context_pilot.md).

```sh
uv run geoevals data fetch human_context_pilot   # Overpass API -> data/raw/human_context_pilot/
uv run geoevals bench build human_context_pilot  # -> data/raw/human_context_pilot/benchmark/
uv run geoevals run --benchmark data/raw/human_context_pilot/benchmark/benchmark.yaml \
  --adapter access_baseline --config data/raw/human_context_pilot/benchmark/run_config.yaml \
  --out data/raw/human_context_pilot/runs
```

The fetch records the `access_date` and `sha256` of the extract in
`data/raw/human_context_pilot/manifest.yaml` and refuses to write to a path git would commit.
The real-data test is marked `network` and excluded from the default `pytest` run and CI; run
it with `uv run pytest -m network`. The offline tests in `tests/test_pilot.py` cover the same
code on an invented street pattern.

### How the cases are built

`geoevals bench build` (`geoevals.pilot`) converts the extract to the benchmark's GeoParquet
layout: every node of a walkable way is a network node, and each pair of consecutive nodes is an
edge with its WGS 84 geodesic length. OSM tags map to the six amenity categories (`shop` =
supermarket/convenience/greengrocer: grocery; `amenity` = pharmacy, school, clinic/doctors;
`leisure=park`; `highway=bus_stop` and rail stations or tram stops: transit_stop).
Neighborhood types are **street-network density terciles**. 250 m UTM grid cells wholly inside
the box are ranked by meters of street per km^2 and split into three equal-count groups:
`low_density`, `medium_density` and `high_density`. 36 origins (at least 30), 12 per tercile,
are drawn at random (seed in `pilot.yaml`) inside cells of each tercile. They are not moved onto
the network. Each origin gets four cases: the nearest amenity (the category cycles), the grocery
and transit-stop counts within 15 minutes, and the open groceries at the stated instant. The
expected outputs come from `reference.py`, which is copied into the build. Strata are
`neighborhood_type`, `amenity_category`, `operation`, `time_of_day`, `threshold_min` and
`origin_snaps`.

For the default box (built on 2026-10-09), the build gave 144 cases from 36 origins on a network
of 7116 nodes and 8763 edges. The `access_baseline` adapter scored `task_success = 1.0` on all
144 cases, so the networkx and csgraph implementations agree on the real network as well.

### The pilot report

The build writes `report.md` next to the benchmark. It has:

- **Data freshness**: the extract (snapshot) date, the access date, the server's database
  timestamp, the box and the extract's SHA-256.
- **Missingness**: the share of POIs without `opening_hours`, per category, and the share of
  origins that fail to snap to the network (no node within 25 m), per neighborhood type.
- **Spatial-unit sensitivity**: amenity counts aggregated on 250 m and 1 km grids (nested UTM
  cells; a cell's value is the mean count of its origins). For each neighborhood type it shows
  the mean at each cell size and the difference, and it lists each 1 km cell with the 250 m
  cell values inside it.

### Known biases

- **OSM completeness varies by region** and by feature type. Footpaths, sidewalks, shops and
  especially `opening_hours` are mapped more completely in some places (and by some mapping
  communities) than others. Access values therefore reflect mapping effort as well as the
  built environment, and comparisons between regions can mislead. For the default box, 94% of
  POIs had no `opening_hours`.
- Origins fall uniformly in grid cells, including water, parks and parking lots. Many fail to
  snap (44% for the default box), and those that do are not weighted by population.
- Density terciles are relative to the chosen box. `high_density` in one box can be
  `low_density` in another.
- Walking is a constant speed on mapped lengths. Barriers, crossings, slope, private paths
  (`access=private` is not filtered) and personal mobility are not modeled.
- Results change with the spatial unit (the modifiable areal unit problem). The report shows
  this for two grid sizes; it does not correct for it.

### Prohibited uses

- Do not commit or redistribute the extract, the built pilot or its report outside the terms
  of the ODbL. Keep the attribution "© OpenStreetMap contributors" on anything shared.
- Do not use pilot results to rank, score or make decisions about real neighborhoods, their
  residents or their property (for example lending, insurance, policing or service
  allocation). The values are proxies of mapped access, not measures of anyone's life.
- Do not infer anything about individuals or social relationships from them (see
  [`docs/human-context.md`](../../docs/human-context.md)).
- Do not treat the placeholder geography as a chosen study area or report it as representative.
