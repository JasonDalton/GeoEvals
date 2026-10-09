# Claude model leaderboard: design

Date: 2026-10-09. Status: approved in conversation, awaiting written-spec review.

## Goal

Run the two v0.1.0 benchmarks against three Claude models in two answer modes, and publish the
results as a table in the main README with scores, timing and tokens used. Opus 5.5 is built
and run first; Sonnet 5.5 and Haiku 5.5 follow with the same code and settings.

## Decisions taken

| Decision | Choice |
| --- | --- |
| Answer modes | Two tracks, reported separately: **direct** (model only) and **python** (model with a sandboxed Python tool) |
| Python sandbox | Local Docker container, no network, built from the project's locked dependencies |
| Models | `claude-opus-5-5` (first), `claude-sonnet-5-5`, `claude-haiku-5-5` |
| Benchmarks | `gis_correctness` 0.1.0 (56 cases) and `human_context_access` 0.1.0 (51 cases), split `test` |
| Where results appear | A leaderboard table in `README.md`, generated from committed run results |

## Components

### 1. Adapters

Two adapter classes in `src/geoevals/adapters/`, registered once per model, so that each
model and track has its own adapter name and its own price-table entry (the price table is
keyed by adapter name, `src/geoevals/runner/cost.py`):

- `claude_direct:<model-id>`, for example `claude_direct:claude-opus-5-5`
- `claude_python:<model-id>`, for example `claude_python:claude-haiku-5-5`

Both use the official `anthropic` Python SDK, added as an optional extra (`llm`) so that the
core install does not change. Both set adaptive thinking and `output_config.effort: high` on
every model; the effort is set explicitly because the model defaults differ (Opus 5.5 and
Haiku 5.5 default to `medium`, Sonnet 5.5 to `high`). Requests are streamed. Prompt caching
is off in this version, because the price table has no cache-read price and cached tokens would
make the recorded tokens and cost disagree with it. Server-side refusal fallbacks are not
enabled, because a fallback would score another model's answer under this model's name.

Each adapter returns `TokenUsage` summed over every request it made for the case.

#### Direct track

One request per case. The user message holds the case `prompt` and the case inputs as text:
`params` as JSON, and each file in `inputs.files` as GeoJSON text (GeoJSON files as they are;
Parquet files converted to GeoJSON with GeoPandas, coordinates unchanged). The answer must
match the benchmark's `output_schema`, enforced with structured outputs
(`output_config.format`). If the API rejects a benchmark schema for structured outputs (the
schemas use `oneOf` and `$defs`), the adapter falls back to a prompt instruction plus
`jsonschema` validation of the reply, and an invalid reply fails the case as
`invalid_output`. Which path each benchmark uses is recorded in the run result config.

#### Python track

A manual tool-use loop (not the beta tool runner, so that every step is recorded) with two
client tools, both `strict: true`:

- `run_python(code)`: runs the code in the case's container and returns stdout, stderr and the
  exit code. Limits: 60 s per call, 20 KB of output (truncated with a marker). A non-zero exit
  is returned as a tool error that the model can recover from.
- `submit_answer(answer)`: the final answer, validated against the benchmark `output_schema`.

The case ends at `submit_answer`, or fails with `turn_limit` after 20 tool turns. Every tool
call and result is recorded as a trajectory step (`geoevals.trajectory`). Trajectories are
recorded and never scored.

### 2. Sandbox

A Docker image built from the project's `uv.lock` (GeoPandas, Shapely, pyproj, NetworkX,
SciPy), with no API key and no project source except the fixtures. One container per case,
started with `--network none`, a read-only mount of the benchmark's `fixtures/` directory at a
fixed path stated in the system prompt, CPU and memory limits, and removal at case end. The
sandbox module has no Anthropic dependency and is tested on its own.

### 3. Run configs and settings

One run config per benchmark and track under `leaderboard/configs/`, with `timeout_s: 600`,
`max_retries: 0` (the SDK retries 429, 5xx and connection errors, 5 attempts),
`workers: 1`, `seed: 0`, and the adapter config (`model`, `effort`, `max_tokens`,
`prompt_version`, `budget_usd`). A versioned prompt template per track lives in
`src/geoevals/adapters/prompts/`; its version is stored in every run result.

### 4. Spend control

- The key is read only from `ANTHROPIC_API_KEY` and never written to a run result, log or
  report.
- A pilot of 5 cases per model and track runs first. Its measured tokens and cost per case,
  and the projected full-run cost, go to the user for approval before any full run.
- `budget_usd` in the adapter config: when the adapter's own cost (from the price table) passes
  it, the remaining cases are declined with `SkipCase("budget exhausted")`. The leaderboard
  rejects a run that has skipped cases, so a cap never produces a partial row.

### 5. Price table

`leaderboard/prices.yaml` lists every adapter name with the first-party API prices on the day
of the run (per 1K tokens): Opus 5.5 $0.004 / $0.020, Sonnet 5.5 $0.002 / $0.010, Haiku 5.5
$0.0001 / $0.0005, and `usd_per_call: 0`. Its hash is in every run result. Docker compute is
local and not priced.

### 6. Leaderboard command and README table

A new command, `geoevals leaderboard build --results leaderboard/results --readme README.md`,
reads the committed run results and writes the table between
`<!-- leaderboard:start -->` and `<!-- leaderboard:end -->` in the README. With `--check` it
exits 1 when the README table is out of date (used in `tests/test_docs.py`).

Columns: model, track, benchmark, task success rate (with the `ci_low`/`ci_high` interval
that the run result's metric summary already records), latency per case at p50 and p90
(`efficiency.latency_p50_s`, `latency_p90_s`), input and output tokens
(`efficiency.tokens_input_total`, `tokens_output_total`), and cost in USD
(`efficiency.cost_usd_total`). Every column comes from fields the run result already has; the
run result schema does not change. A run is accepted only if every case ran, and only if all accepted runs for a benchmark
share the benchmark version, the dataset manifest hash and the price table hash. Below the
table, the README states these values plus the prompt versions and effort level.

Run results are committed under `leaderboard/results/<benchmark>/<adapter>.json`, so that
anyone can rebuild the table and check scores with `geoevals reproduce`.

### 7. Documentation

- `ROADMAP.md`: the leaderboard item is updated to state the comparability rules above, so
  that the README table does not contradict the roadmap.
- `docs/reproducibility.md`: a section on leaderboard runs (what is pinned, how to reproduce a
  row).
- `docs/data-governance.md`: a note that case inputs, which are MIT-licensed synthetic
  fixtures, are sent to the Anthropic API.

## Error handling

| Event | Recorded as |
| --- | --- |
| `stop_reason: "refusal"` | Failed case; refusal category in `raw` |
| `stop_reason: "max_tokens"` | Failed case, `truncated` |
| API error after SDK retries | `adapter_error` |
| Reply not valid against the output schema | Failed case, `invalid_output` |
| 20 tool turns without `submit_answer` | Failed case, `turn_limit` |
| Budget exhausted | `skipped`; the run is rejected by the leaderboard |
| Correct abstention status | A valid answer, scored as usual |

## Testing

No test calls the API or needs a secret.

- Adapter tests with a scripted fake client: prompt building, Parquet-to-GeoJSON conversion,
  answer parsing and schema fallback, refusal, truncation, turn limit, token summing, budget.
- Sandbox tests: no network, read-only fixtures, time limit, output limit. Skipped when Docker
  is not available.
- Leaderboard tests with fixture run results: table content, rejection of incomplete and
  incomparable runs, and the `--check` mode.
- `tests/test_docs.py`: the README table matches the committed results.
- One live test of a single case, run only when `GEOEVALS_LIVE_API=1` is set; never in CI.

## Prerequisite and risks

- **Linux reference output.** CI on Ubuntu fails three `gis_correctness` tests because one
  committed expected output (a case file ending `in-005.json`) differs from what the reference
  workflow computes on Linux. The python track runs in a Linux container, so this must be
  diagnosed, with the user's approval for any change to reference data, before the python
  track is scored.
- **Structured outputs and the benchmark schemas** may not be compatible; the fallback in
  section 1 covers this, and the run result records which path was used.
- **Cost** is not known until the pilot runs. No estimate is given before then.

## Out of scope

Fable 5.1 and other providers; prompt caching; batch API; scoring trajectories; a hosted
leaderboard or submission process; the OSM vector benchmark.
