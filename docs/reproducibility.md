# Reproducibility

GeoEvals aims for runs that anyone can repeat and comparisons that mean something. This
document states what a run records, which runs may be compared, how versions change, and how
to reproduce a published result.

## Comparability

Every report states:

> Comparisons are valid only between runs with the same benchmark version, metric versions,
> split, and dataset manifest hash.

Each of these is in the run result: `benchmark.version`, the `version` of every entry in
`summary_metrics`, the split in the config, and `dataset_manifest_hash`. If any of them
differs, the runs measured different things, and a difference in scores says nothing about
the systems.

Other recorded fields explain a difference but do not by themselves make runs incomparable:

| Field | What it records |
| --- | --- |
| `adapter` | The adapter name, version and config |
| `config_hash` | The SHA-256 of the canonical run config (sorted keys, normalized types) |
| `environment` | Python, OS and platform, CPU and core count, RAM, versions of geoevals, Shapely, pyproj, GeoPandas, GEOS and PROJ, the git commit and dirty flag, and the SHA-256 of `uv.lock` |
| `efficiency.price_table_hash` | The price table used for `cost_usd` |

Efficiency figures (latency, throughput, memory) depend on the machine. Compare them only
between runs on the same hardware, and report the hardware with them.

## Version rules

Benchmarks, metrics, adapters and schemas use semantic versions (`MAJOR.MINOR.PATCH`). The
rule for all of them: if a change can change a score or an output for the same input, the
version changes, and runs from before and after the change are not comparable.

| Item | Bump | Examples |
| --- | --- | --- |
| Benchmark | major | A change to `input_schema` or `output_schema` that existing adapters cannot meet |
| Benchmark | minor | Cases added, removed or changed; expected outputs, fixtures, tolerances, splits or the metric list changed |
| Benchmark | patch | Text only: the card, `limitations`, descriptions. Scores cannot change. |
| Metric | major | The meaning of the value changes, for example its units or its direction |
| Metric | minor | A new check or param, or a changed edge case. Scores of some outputs can change. |
| Metric | patch | A fix that cannot change any score, for example a clearer `detail` message |
| Adapter | any | Any change to how it answers. The adapter version is recorded in every run. |
| Schema | see below | A change to a JSON Schema in `schemas/` |

A change to a metric definition in [`metrics.md`](metrics.md) bumps that metric's version,
and the specs that use it then ask for the new version. A change to a benchmark also needs a
new published baseline (see the benchmark card), or `geoevals reproduce` fails.

When a benchmark change touches only scoring (a metric version, a tolerance, an expected
output) and leaves everything an adapter sees as it was (cases, prompts, inputs, fixtures and
`output_schema`, which model adapters receive), a finished run can be scored again from its
saved outputs instead of rerun: `geoevals rescore <run_dir>`. It rewrites `result.json` (and
`cases.jsonl`, if present) against the current spec and adds a `limitations` line that names
the version the run was scored against before. It refuses a run of another benchmark, with
another dataset manifest or other case IDs, or with a saved output that no longer meets
`output_schema`. It cannot check prompts, which a run result does not hold: whoever rescores
checks that the change left them alone. Failed cases stay as they were.

## Run determinism

With the same config, dataset and lockfile, two runs give identical per-case `status`,
`output` and `metrics`. Only timing, memory, timestamps, `run_id` and the environment may
differ. To get this:

- The run config fixes the split, the seed, the timeout, the retries, the workers and the
  adapter config. Each case gets its own seeded random state.
- Cases are written in case-ID order, whatever order they finish in.
- JSON is written with sorted keys and floats rounded to 15 significant digits, so diffs are
  meaningful.
- Bootstrap confidence intervals use a fixed seed (0).

Check it with `geoevals compare`:

```sh
uv run geoevals compare runs/a/<run_id> runs/b/<run_id>   # exit 0: no differences
```

`compare` lists per-case differences in `status`, `output` and `metrics`. Numbers must match
exactly unless you pass `--abs-tol` or `--rel-tol`.

## Reproduce a published baseline

A published baseline in `baselines/<benchmark_id>/<adapter>/` holds `result.json`,
`cases.jsonl`, the pinned `config.yaml` and `report.md`. Rerun it and compare:

```sh
uv run geoevals reproduce baselines/gis_correctness/gis_baseline
```

The command runs `benchmarks/<benchmark_id>/benchmark.yaml` with the committed config and the
adapter named in `result.json`. It then compares each case and the run-level fields: the
benchmark, the adapter, the config hash, the dataset manifest hash, the summary metrics and the
failures. Exit status 0 means no differences.

CI's `reproduce` job runs it on every push for every directory under `baselines/`, in a fresh
environment: `uv sync --frozen --no-cache` from `uv.lock`, with the uv cache turned off. Any
difference, or a baseline that cannot be read, fails the job. The published baselines are
listed in [`baselines/README.md`](../baselines/README.md).

## Leaderboard runs

The leaderboard ([`leaderboard/README.md`](../leaderboard/README.md)) pins what it can:
the benchmark version and dataset manifest hash (the same for every row of a benchmark), the
run config in `leaderboard/configs/`, the prompt template version
(`src/geoevals/adapters/prompts/`), the effort level, the model ID, and the Claude Code or Codex CLI
version (in the adapter version). The python track's sandbox image is built from `uv.lock`.

Model outputs are not deterministic, so a leaderboard run cannot be reproduced bit for bit, and
`geoevals reproduce` does not apply to it. Each committed `result.json` holds every case's
output and scores, and `uv run geoevals leaderboard build` rebuilds the README table from them;
CI checks that the table matches.

## Across platforms

GEOS and PROJ builds on different platforms can differ in the last bits of a result. For
example, a Linux x86_64 rerun of the macOS arm64 `gis_correctness` baseline differed by at most
6.0e-09 m. For this reason `geoevals reproduce` accepts numbers within an absolute 1e-07 or a
relative 1e-09, and `geoevals compare` has the same options. Everything else must match
exactly.

Benchmarks avoid results that depend on the environment. For example, `gis_correctness` uses
no CRS pairs that need a PROJ grid, and expected outputs are checked with `PROJ_NETWORK=OFF`.

## Schema versions

GeoEvals has three versioned JSON Schemas in `schemas/`. Every document states the schema
version it targets in `schema_version`, and `geoevals validate` accepts only the current
version.

| Schema | Current version |
| --- | --- |
| `benchmark.schema.json` (benchmark spec) | 1.1.0 |
| `dataset-manifest.schema.json` (dataset manifest) | 1.0.0 |
| `run-result.schema.json` (run result) | 1.0.0 |

A change to a schema bumps its version: major when a field is removed or renamed or its
meaning changes, minor when a field or a rule is added (as in 1.1.0 below), patch for
descriptions only. Each change adds a
migration note below, and every document that targets the schema gets the new
`schema_version`.

## Migration notes

### Benchmark spec 1.0.0 → 1.1.0

What changed:

- An output field in `output_schema.properties` may carry `evidence_type`: `observed`,
  `proxy` or `judgment`. See [`human-context.md`](human-context.md#evidence-types).
- A spec with `pillar: human_context` must list its output fields in
  `output_schema.properties`, and every field must have an `evidence_type`.

To migrate a 1.0.0 spec:

1. Change `schema_version: "1.0.0"` to `schema_version: "1.1.0"`.
2. For a `human_context` spec, add `evidence_type` to every field in
   `output_schema.properties`.
3. Run `geoevals validate <benchmark.yaml>`.

No other field changed, so a `spatial_reasoning` or `perception` spec needs only step 1.
The change does not affect scoring: run results and published baselines stay the same.
