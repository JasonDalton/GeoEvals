# Claude leaderboard

This directory holds the run configs and the committed results behind the leaderboard table in
the [main README](../README.md#leaderboard). The design is in
[`docs/superpowers/specs/2026-10-09-claude-leaderboard-design.md`](../docs/superpowers/specs/2026-10-09-claude-leaderboard-design.md).

Every run happens on the maintainer's machine through the local Claude Code CLI, signed in to a
Claude subscription. No API key is used: the adapters remove `ANTHROPIC_API_KEY` from the CLI's
environment and fail a case unless the CLI reports the subscription sign-in.

## Adapters

| Adapter | Track | Model |
| --- | --- | --- |
| `claude_direct_opus_5_5`, `claude_python_opus_5_5` | direct, python | `claude-opus-5-5` |
| `claude_direct_sonnet_5_5`, `claude_python_sonnet_5_5` | direct, python | `claude-sonnet-5-5` |
| `claude_direct_haiku_5_5`, `claude_python_haiku_5_5` | direct, python | `claude-haiku-5-5` |

- **direct**: the model gets the request, its parameters and the input files inlined as
  GeoJSON, and has no tools except the structured-output tool for its answer.
- **python**: the model gets the file paths and a `run_python` tool. Each call runs in the
  case's Docker container (`geoevals-sandbox:<hash of uv.lock>`): no network, read-only root
  filesystem, only the benchmark's `fixtures/` mounted read-only at `/bench/fixtures`, 60 s and
  20 KB of output per call, 20 calls per case.

The model never sees the expected output, the case strata (which flag trap cases), the
tolerances or the case ID. Each CLI call runs with `--restricted --tools ""` in an empty
temporary directory, so the maintainer's plugins, hooks and `CLAUDE.md` do not reach it.

## Requirements

- Claude Code on `PATH`, signed in (`claude` then `/login`).
- For the python track, a running Docker daemon. The first run builds the sandbox image from
  `uv.lock` (about 800 MB; it needs network access once).

## Run a pilot

A pilot runs five cases per benchmark and skips the rest, so its time and tokens can be checked
before a full run. A pilot is never accepted on the leaderboard.

```sh
uv run geoevals run --benchmark benchmarks/gis_correctness/benchmark.yaml \
  --adapter claude_direct_opus_5_5 --config leaderboard/configs/pilot-direct.yaml --out runs/pilot
```

Use `pilot-python.yaml` with a `claude_python_*` adapter, and
`benchmarks/human_context/benchmark.yaml` for the other benchmark.

## Run and add a full run

```sh
uv run geoevals run --benchmark benchmarks/gis_correctness/benchmark.yaml \
  --adapter claude_direct_opus_5_5 --config leaderboard/configs/direct.yaml --out runs/leaderboard
uv run geoevals leaderboard add runs/leaderboard/<run_id>
uv run geoevals leaderboard build
```

`leaderboard add` copies `result.json` and `config.yaml` to
`results/<benchmark_id>/<adapter>/`, replacing an earlier run of the same adapter. It refuses a
run with skipped cases. `leaderboard build` rewrites the table in the README; CI checks that
the table matches the committed results.

## When a run stops early

- **Usage limit.** When the subscription's usage limit is reached, the case and every later
  case are skipped, and the run cannot be added. Run it again after the limit resets.
- **Harness failures.** A case that failed in the harness, not in the model, makes the run
  unacceptable: the CLI not on the subscription sign-in, a CLI or API error (for example the
  network), a model other than the requested one, a Claude Code version change during the run,
  a crashed worker, or a case stopped by the runner's `timeout_s` instead of the adapter's
  `case_timeout_s`. Fix the cause and run it again.
- **Model failures.** A case that takes longer than `case_timeout_s` (840 s), a refusal, a
  case that passes `max_case_usd`, no answer, or an answer that does not match the output
  schema counts as a failed case in the table. These runs can be added; they are part of the
  result.

The CLI runs under a small watchdog: if the adapter's worker process is killed, the watchdog
stops the CLI and removes the case's container.

## Graded evals

Graded evals (`evals/`, see [`docs/eval-authoring.md`](../docs/eval-authoring.md)) are open-ended
tasks scored by a grading agent. They have their own table in the README and their own
directory, `leaderboard/graded/`, and are never combined with the benchmark rows.

```sh
uv run geoevals run --eval evals/<id>/eval.yaml --adapter claude_python_opus_5_5 \
  --config leaderboard/configs/python.yaml --out runs/graded
uv run geoevals grade runs/graded/<run_id>
uv run geoevals leaderboard add runs/graded/<run_id>
uv run geoevals leaderboard build
```

`leaderboard add` puts a graded run in `leaderboard/graded/<eval>/<adapter>/` with its
`result.json`, `grades.json` and `config.yaml`. `leaderboard build` writes the graded section of
the README and the box plot `leaderboard/graded/plots/<eval>.svg` (it needs the `plots` extra).

Graded runs are committed. Their answers quote OpenStreetMap names, IDs and distances, and the
grader's justifications cite the reference key; the maintainer decided on 2026-10-12 that this
may be committed with OpenStreetMap attribution (see
[`docs/data-governance.md`](../docs/data-governance.md#restricted-data)).

A graded run is accepted only if:

- it comes from a `claude_python_<model>` adapter with the default CLI;
- no task was skipped, stopped by the runner's timeout or failed in the harness;
- its grades belong to it, grading did not stop, every answered task was graded, and there are
  at least two passes;
- all runs of an eval share its version, the city layers, the dataset manifest, the answering
  effort and prompt version, the rubric version, and the grader (model, effort, prompt version,
  Claude Code version, passes). Runs graded by different versions are not comparable, so the
  build rejects a mix.

Tasks that were not answered score 0. A full graded run of one model is 60 answers and 120
grading sessions on the subscription.

## What the numbers mean

- **Task success** is the mean of `task_success` over every case, with its 95% interval.
- **Latency** is wall-clock time per case, CLI startup included.
- **Tokens in** count every prompt token the model processed, cache reads included (Claude
  Code caches its own prompt); **tokens out** include thinking.
- There is no cost column: runs on a subscription have no per-token charge. The CLI's estimate
  at API list prices is used only as a per-case runaway guard (`max_case_usd`).
- Claude Code's harness (its tool definitions and structured-output mechanism) is part of
  what is measured; its version is recorded in each adapter version (`0.1.0+cc.<version>`).

Model outputs are not deterministic, so a rerun gives a different result. The table can always
be rebuilt from the committed results.

When a benchmark changes only how answers are scored, the committed results are rescored from
their saved answers (`geoevals rescore`, see
[`docs/reproducibility.md`](../docs/reproducibility.md#version-rules)) rather than rerun; the
result's `limitations` records it. The Opus 5.5 `gis_correctness` rows were run on 0.2.0 and
rescored on 0.3.0, which accepts `EPSG:4326` as a label for longitude and latitude answers.
