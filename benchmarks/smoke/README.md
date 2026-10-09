# Benchmark card: `smoke`

| Field | Value |
| --- | --- |
| Benchmark ID | `smoke` |
| Version | 0.1.0 (`benchmark.yaml`) |
| Cases | 5, one split (`test`) |
| License | MIT (spec and cases) |
| Adapter | `mock` with [`run_config.yaml`](run_config.yaml) |

## Purpose

`smoke` is a CI check, not a benchmark of any system. It runs the whole pipeline (spec and
manifest validation, the runner, the `status_match` metric, the run result and the report) on
five tiny cases with the `mock` adapter. Its scores say nothing about any
real system.

## Collection process

The GeoEvals contributors wrote the five cases in [`cases.jsonl`](cases.jsonl) by hand. There
is no fixture data: four cases ask about the unit square, one ("Buffer the river.") must be
declined with `needs_clarification`, and the file of cases is itself the only asset in [`manifest.yaml`](manifest.yaml). Editing `cases.jsonl` changes its
SHA-256, so update the manifest with it.

## Geography

None. The cases ask about the unit square `[0, 0, 1, 1]` in `EPSG:3857`, which describes no
real place, and an unnamed river.

## Time range

None. The cases have no time dimension; the manifest records their creation date,
2026-10-09, as the asset's `time_range`.

## Schema

Each case is one JSON line with `case_id`, `prompt`, `expected` (a `status` and, for `ok`, a
`value` with `units` or a `geometry` with its `crs`) and `strata` (`kind`). The input and output
contracts are the `input_schema` and `output_schema` in [`benchmark.yaml`](benchmark.yaml); only
`status` is scored (`status_match`).

## License

MIT, like the rest of the repository (attribution "GeoEvals contributors",
`redistributable: true`). See the
[license inventory](../../datasets/README.md#license-inventory).

## Limitations

- Five cases, scored on `status` only: a run can pass with wrong values or geometries.
- The `mock` adapter returns the reference answer, except for one scripted wrong answer and
  one malformed output (see [`run_config.yaml`](run_config.yaml)), so the run tests the
  harness, not an adapter.

## Intended uses

- CI and local checks that the harness works end to end after a change.
- A minimal example of a spec, a manifest and a case file for new benchmark authors.

## Prohibited uses

- Do not report smoke scores as results for any system, or compare systems with them.
- Do not copy its metrics or tolerances into a real benchmark: it scores only `status` and
  sets no tolerances (see [`docs/benchmark-authoring.md`](../../docs/benchmark-authoring.md)).
