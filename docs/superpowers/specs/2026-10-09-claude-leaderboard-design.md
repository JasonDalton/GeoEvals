# Claude model leaderboard: design

Date: 2026-10-09, revised 2026-10-10. Status: approved by the user; revised for local runs on a
Claude subscription.

## Goal

Run the two v0.1.0 benchmarks against three Claude models in two answer modes, and publish the
results as a table in the main README with scores, timing and tokens used. Opus 5.5 is built
and run first; Sonnet 5.5 and Haiku 5.5 follow with the same code and settings. Every run
happens on the maintainer's machine, through the local Claude Code CLI signed in to a Claude
subscription. No API key is used.

## Scope: vector data only

The leaderboard covers the two benchmarks that exist, both on vector data:
`gis_correctness` (spatial reasoning) and `human_context_access` (human context). Feature
extraction from imagery (the perception pillar) is not planned: many existing benchmarks
already cover it (`ROADMAP.md`, `docs/principles.md`). So the leaderboard has no imagery
track. The planned vector benchmark on OpenStreetMap data joins the leaderboard when it ships;
it is out of scope here.

## Decisions taken

| Decision | Choice |
| --- | --- |
| Answer modes | Two tracks, reported separately: **direct** (model only) and **python** (model with a sandboxed Python tool) |
| Model access | The local `claude` CLI in print mode (`claude -p`), signed in to the maintainer's Claude subscription; `ANTHROPIC_API_KEY` is removed from its environment |
| Python sandbox | Local Docker container, no network, built from the project's locked dependencies |
| Models | `claude-opus-5-5` (first), `claude-sonnet-5-5`, `claude-haiku-5-5` |
| Benchmarks | `gis_correctness` 0.1.0 (56 cases) and `human_context_access` 0.1.0 (51 cases), split `test` |
| Where results appear | A leaderboard table in `README.md`, generated from committed run results |

## Components

### 1. Claude CLI runner

One module, `src/geoevals/leaderboard/claude_cli.py`, runs one case through the CLI and parses
its output. Both adapters use it. It has no dependency beyond the standard library.

Each call is:

```text
claude -p <user message> --model <model-id> --effort high
  --restricted --tools "" --strict-mcp-config [--mcp-config <file> --allowedTools <tool>]
  --disable-slash-commands --no-session-persistence --permission-prompts none
  --system-prompt <template> --json-schema <output schema>
  --max-budget-usd <cap> --output-format stream-json --verbose
```

run in a new empty temporary directory, with stdin closed and `ANTHROPIC_API_KEY` removed from
the environment, so that the subscription is used. These flags were checked on Claude Code
2.1.296 on 2026-10-10:

- `--restricted` ignores the user, project and local settings files, so the maintainer's
  plugins, hooks and `CLAUDE.md` do not reach the model. A canary phrase from the global
  `CLAUDE.md` was not in the model's context.
- `--tools ""` removes every built-in tool. The model sees only `StructuredOutput` (from
  `--json-schema`) and, on the python track, the sandbox tool.
- `--json-schema` makes the final answer a `StructuredOutput` tool call, returned as
  `structured_output` in the result. The benchmark output schemas are passed after removing the
  GeoEvals annotation keyword `evidence_type`, which the CLI's schema validator rejects. The
  runner still validates every answer against the full spec schema.
- `--safe-mode` is not used: it also disables `--mcp-config` servers.

Adaptive thinking is Claude Code's default and is not configurable separately. Effort is set
explicitly to `high` because the model defaults differ. Claude Code applies its own prompt
caching; that cannot be turned off, so token counts include cache reads (see below). No
fallback model is configured.

From the `result` event it reads `structured_output`, `usage`, `modelUsage`, `num_turns`,
`subtype`, `stop_reason` and `api_error_status`. From the `system` `init` event it records the
`apiKeySource` (it must be `none`, which means subscription sign-in) and the tool list.

The per-case wall-clock limit of the CLI process (`case_timeout_s`) is shorter than the run's
`timeout_s`, so the adapter, not the runner, stops a slow case and can clean up. The CLI runs in
its own process group, and the whole group is killed on timeout.

### 2. Adapters

Two adapter classes in `src/geoevals/adapters/claude.py`, registered once per model, so that
each model and track has its own adapter name:

- `claude_direct_<model>`, for example `claude_direct_opus_5_5`
- `claude_python_<model>`, for example `claude_python_haiku_5_5`

Names use underscores because the run ID, and so the run directory name, contains the adapter
name. The adapter version records the Claude Code version (`0.1.0+cc.2.1.296`), read once
from `claude --version`.

Each adapter reads the case's `benchmark.yaml` (from `benchmark_dir` in the case input) for the
task statement and output schema. The model gets the case `prompt`, the `inputs.params` as
JSON, and the input files. It never gets `expected`, `strata` (which flag trap cases),
`tolerances`, `metric_params` or the case ID.

Each adapter returns `TokenUsage` with input = input tokens + cache-creation tokens +
cache-read tokens (every prompt token the model processed) and output = output tokens
(thinking included), summed over every request of the case. The `modelUsage` keys must name only
the requested model; any other model fails the case.

#### Direct track

One CLI call per case, no tools except `StructuredOutput`. The user message holds the prompt,
the params, and each file in `inputs.files` as GeoJSON text (GeoJSON files as they are; Parquet
files converted to GeoJSON with GeoPandas, coordinates unchanged).

#### Python track

One CLI call per case with one MCP tool, `run_python(code)`, served by
`src/geoevals/leaderboard/sandbox_mcp.py` (a small stdio MCP server, standard library only).
The tool runs the code in the case's container and returns stdout, stderr and the exit code,
with a 60 s limit per call and 20 KB of output (truncated with a marker). A non-zero exit is
returned as a tool error the model can recover from. After 20 calls the tool returns an error
telling the model to submit its answer. The case ends when the model calls `StructuredOutput`.
The input files are given as paths in the container, not inlined.

Every tool call and result is recorded as a trajectory step (`geoevals.trajectory`), with the
final `StructuredOutput` call as a step with no tool. Trajectories are recorded and never
scored.

### 3. Sandbox

A Docker image, `geoevals-sandbox:<hash>`, built from `python:3.12-slim` and the project's
locked runtime dependencies (`uv export --frozen --no-dev --extra network`: GeoPandas,
Shapely, pyproj, NetworkX, SciPy). The hash covers `uv.lock` and the Dockerfile, so a
dependency change gives a new image. It holds no credentials and no project source.

One container per case, started by the MCP server on the first `run_python` call with
`--network none`, a read-only root filesystem, a writable `tmpfs` at `/tmp`, CPU, memory and
process limits, all capabilities dropped, and the benchmark's `fixtures/` directory mounted
read-only at `/bench/fixtures` (working directory `/bench`, so the case's relative file paths
work). Only `fixtures/` is mounted: the case files and expected outputs are not. The container
is removed when the CLI exits; the adapter also removes it by name afterwards, in case the
server was killed. The sandbox module is tested on its own.

### 4. Run configs

One run config per track under `leaderboard/configs/`: `timeout_s: 900`, `max_retries: 0`,
`workers: 1`, `seed: 0`, and the adapter config: `effort: high`, `prompt_version`,
`case_timeout_s: 840`, `max_case_usd` (the CLI's `--max-budget-usd`, a runaway guard per case,
measured at API list prices) and, on the python track, `max_tool_calls: 20`. A versioned
prompt template per track lives in `src/geoevals/adapters/prompts/`; its version is in the run
result's adapter config.

### 5. Usage control

- A pilot of 5 cases per model and track runs first (adapter config `only_cases`; the other
  cases are declined with `SkipCase`). Its time and tokens per case go to the user before any
  full run.
- If the subscription's usage limit is reached (the CLI reports HTTP 429 after its own
  retries), the adapter declines that case and every later case with
  `SkipCase("usage limit reached")`. The leaderboard rejects a run with skipped cases, so a
  limit never produces a partial row.

### 6. Cost

Runs on a subscription have no per-token charge, so the README table has no cost column. The
leaderboard adapters are not in a price table, so `cost_usd` is null (unknown), never 0. The
CLI's own estimate at API list prices (`total_cost_usd`) is used only for the per-case
runaway guard.

### 7. Leaderboard commands and README table

- `geoevals leaderboard add <run_dir>` copies a run's `result.json` and `config.yaml` to
  `leaderboard/results/<benchmark_id>/<adapter>/`.
- `geoevals leaderboard build [--results leaderboard/results] [--readme README.md] [--check]`
  writes the table between `<!-- leaderboard:start -->` and `<!-- leaderboard:end -->` in the
  README. With `--check` it writes nothing and exits 1 when the table is out of date
  (`tests/test_docs.py` runs it).

Columns: model, track, benchmark, task success with its 95% interval (`summary_metrics`
`task_success` `mean`, `ci_low`, `ci_high`), cases that failed to produce a scored answer,
latency per case at p50 and p90 (`efficiency.latency_p50_s`, `latency_p90_s`; CLI startup
included), and input and output tokens (`efficiency.tokens_input_total`,
`tokens_output_total`). Every column comes from fields a run result already has; the run
result schema does not change.

A run is accepted only if no case was skipped, and only if all accepted runs of a benchmark
share the benchmark version and dataset manifest hash. Below the table, the README states the
benchmark versions, manifest hashes, Claude Code versions, prompt versions, effort, and how
tokens are counted.

### 8. Documentation

- `ROADMAP.md`: the leaderboard item states what is shipped and the comparability rules.
- `docs/reproducibility.md`: a section on leaderboard runs: what is pinned, why model outputs
  are not reproducible bit for bit, and how to rebuild the table.
- `docs/data-governance.md`: case inputs (MIT-licensed synthetic fixtures) are sent to
  Anthropic through Claude Code.
- `leaderboard/README.md`: how to run a pilot and a full run, and add the result.

## Error handling

| Event | Recorded as |
| --- | --- |
| `stop_reason: "refusal"` | `adapter_error`, error type `ClaudeRefusal` |
| No `structured_output` in the result | `adapter_error`, error type `ClaudeNoAnswer` |
| CLI error result (`subtype` not `success`, for example the budget cap) | `adapter_error`, error type `ClaudeRunError` with the subtype |
| A model other than the requested one in `modelUsage` | `adapter_error`, error type `ClaudeUnexpectedModel` |
| `apiKeySource` other than `none` | `adapter_error`, error type `ClaudeAuthError` (the run did not use the subscription) |
| Usage limit (HTTP 429 after CLI retries) | `skipped`, and every later case too; the leaderboard rejects the run |
| CLI exceeds `case_timeout_s` | `adapter_error`, error type `ClaudeTimeout` |
| Answer not valid against the spec output schema | `invalid_output` (by the runner) |
| Correct abstention status | A valid answer, scored as usual |

## Testing

No test calls a model.

- Adapter and CLI-runner tests with a fake `claude` executable (a Python script that replays
  recorded stream-json scenarios): command line, environment (no API key), prompt content and
  what is withheld, Parquet-to-GeoJSON conversion, token summing, every error row above,
  trajectory building, `only_cases`, usage-limit skipping, timeout and process-group kill.
- MCP server tests over stdio with a fake executor: protocol messages, the call limit, output
  truncation.
- Sandbox tests (marker `docker`, excluded from the default run and CI, run locally): no
  network, read-only fixtures, only fixtures mounted, time limit, output limit, cleanup.
- Leaderboard tests with fixture run results: table content, rejection of incomplete and
  incomparable runs, `add`, and `--check`.
- `tests/test_docs.py`: the README table matches the committed results.

## Prerequisite: the Linux expected-output failure (diagnosed)

CI on Ubuntu fails three `gis_correctness` tests. Diagnosis (2026-10-10, reproduced in Docker on
linux/arm64 and linux/amd64): `runner.layout.stable` rounds floats to 15 significant digits
(`src/geoevals/runner/layout.py:69`) and `regenerate` compares the files byte for byte
(`src/geoevals/regenerate.py:120`). PROJ and GEOS differ in the last bits between platforms,
so 6 files differ in the 15th digit; each platform differs from the others. The largest
difference is 5.7e-7 m (`spatial_join-005`, `distance_m`, against a case tolerance of 0.01 m).

This does not block the leaderboard: answers are scored against the committed expected outputs
with the case tolerances, which are about four orders of magnitude larger than these
differences. The fix (for example comparing within the `geoevals reproduce` tolerance) changes
the regenerate check, so it waits for the user's decision.

## Risks

- **Claude Code's harness is part of what is measured.** Its own tool definitions and
  structured-output mechanism add tokens and may change between versions; the version is in
  every row.
- **Subscription limits** can stop a run; the usage-limit rule above keeps partial runs out of
  the table.
- **Cost and time** are not known until the pilot runs. No estimate is given before then.

## Out of scope

Fable 5.1 and other providers; API-key runs; batch processing; scoring trajectories; a hosted
leaderboard or submission process; the OSM vector benchmark.
