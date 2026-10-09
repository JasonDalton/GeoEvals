# Download instructions: `human_context_pilot`

The real-geography pilot of the human-context access benchmark runs on an OpenStreetMap (OSM)
extract. The extract is licensed under the Open Database License (`ODbL-1.0`) and must be
attributed as "© OpenStreetMap contributors". It is **not redistributable from this
repository**: neither the extract nor anything built from it (a derived database under the
ODbL) may be committed. Both stay in the gitignored `data/raw/human_context_pilot/`.

This is a manual path. It needs network access to the Overpass API, so it is not part of the
default test run or CI.

## What is downloaded

[`datasets/manifests/human_context_pilot.yaml`](../manifests/human_context_pilot.yaml)
describes the extract:

| Field | Value |
| --- | --- |
| Source | Overpass API, `https://overpass-api.de/api/interpreter` |
| Bounding box | `[-73.225, 44.465, -73.2, 44.485]` (lon/lat): a **placeholder**, part of Burlington, Vermont, USA, until the pilot geography is decided |
| Snapshot date | 2026-01-01, 00:00 UTC (`time_range.end`; an Overpass `date:` query, so later edits to OSM do not change the data) |
| Contents | Walkable `highway` ways with their node coordinates; shops, pharmacies, schools, clinics, parks and transit stops as points |
| License | `ODbL-1.0`, attribution "© OpenStreetMap contributors", `redistributable: false` |
| Size | About 1.1 MB for the default box |

## Steps

```sh
uv sync                                          # includes networkx and scipy (dev group)
uv run geoevals data fetch human_context_pilot   # about a minute; writes data/raw/human_context_pilot/
uv run geoevals bench build human_context_pilot  # writes data/raw/human_context_pilot/benchmark/
uv run geoevals run --benchmark data/raw/human_context_pilot/benchmark/benchmark.yaml \
  --adapter access_baseline --config data/raw/human_context_pilot/benchmark/run_config.yaml \
  --out data/raw/human_context_pilot/runs
```

`geoevals data fetch human_context_pilot` writes three files into
`data/raw/human_context_pilot/`:

- `osm_extract.json`: the extract, normalized (the Overpass header is dropped and the elements
  are sorted) so that the same box and date give the same bytes;
- `manifest.yaml`: the committed manifest with the asset entry describing what was fetched:
  `access_date` (the day of the fetch), `sha256`, `bbox` and `time_range`. Check it at any time
  with `uv run geoevals data verify data/raw/human_context_pilot/manifest.yaml`;
- `fetch.json`: the fetch record (the query, `access_date`, `sha256`, size and the server's
  database timestamp).

Before writing, the command checks with git that each output path is gitignored (or outside the
repository) and refuses otherwise, so it never writes into a tracked path. It never edits the
committed manifest. When the default box and date return a checksum other than the one in the
committed manifest, it prints a warning: the server returned different data (for example after
a redaction).

## Another geography or date

```sh
uv run geoevals data fetch human_context_pilot --bbox -73.25,44.45,-73.20,44.49 --date 2025-06-01
```

`--bbox` (`min_lon,min_lat,max_lon,max_lat`) and `--date` (`YYYY-MM-DD`) override the manifest;
the local `manifest.yaml` and `fetch.json` record what was used. Change `timezone` in
[`benchmarks/human_context/pilot.yaml`](../../benchmarks/human_context/pilot.yaml) to the
box's IANA time zone before building. Keep requests small (a few square kilometers): the Overpass
API is a shared public service, and the reference workflow is slow on large networks.
`--out DIR` writes elsewhere, but `DIR` must also be gitignored.

## What the build produces

`geoevals bench build human_context_pilot` checks the extract against the recorded `sha256` and
writes a runnable benchmark (`benchmark.yaml`, `cases/`, `fixtures/`, `reference.py`) and
`report.md` (data freshness, missingness, spatial-unit sensitivity). See the "Real-geography
pilot" section of [`benchmarks/human_context/README.md`](../../benchmarks/human_context/README.md).

## Test

The end-to-end check downloads the real extract and is marked `network`, so the default
`pytest` run and CI skip it. Run it manually:

```sh
uv run pytest -m network
```
