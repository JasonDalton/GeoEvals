# Graded spatial-reasoning evals on a real city: design

Date: 2026-10-10. Status: design approved by the user in conversation; this written spec awaits
the user's review.

## Goal

Add a second kind of evaluation to GeoEvals: open-ended spatial-reasoning tasks whose answers a
grading agent scores against a rubric and a reference key. The first set is five evals
(proximity, adjacency, visibility, containment, direction) over one realistic city: a pinned
OpenStreetMap snapshot with every mapped layer, so that the model has to find what matters among
context and noise. The Claude models of the leaderboard answer them on the python track, and
the README shows each model's score distribution per eval as a table and a box plot.

## Terms

| Term | Meaning | Scored by |
| --- | --- | --- |
| **Benchmark** | A task with one checkable answer, an expected output and tolerances. `gis_correctness`, `human_context_access`, the planned OSM vector benchmark. | Code (deterministic metrics) |
| **Graded eval** | An open-ended task with a rubric and a reference key computed from data. | A grading agent, against the rubric and key |

The two are never combined: no shared score, no shared table, no shared directory.

## Decisions taken

| Decision | Choice |
| --- | --- |
| What is graded | New open-ended tasks, not the reasoning behind existing benchmark cases |
| Concepts | Proximity, adjacency and topology, visibility, containment and boundaries, direction and orientation: one eval each |
| Size | 12 tasks per eval, 60 in total; each eval 0.1.0 |
| Data | A full city: a pinned OpenStreetMap snapshot of one mid-size town, every mapped layer, fetched under a dataset manifest and never committed (ODbL-1.0) |
| Town | Chosen by the user from 2 or 3 candidates measured on real OSM data (checkpoint 1) |
| Tracks | Python only: the whole city is mounted read-only in the sandbox. The direct track cannot take a city that does not fit in a prompt |
| Models | The leaderboard's three: Opus 5.5, Sonnet 5.5, Haiku 5.5, effort high |
| Grader | Opus 5.5, effort high, in its own `claude -p` session with no tools; it sees the task, rubric, reference key and answer, never which model answered |
| Grading passes | Two per answer; the task score is their mean, and their agreement is reported |
| Scale | Each rubric criterion 0 to 4 with written anchors; task score = mean of criteria / 4 |
| Table | Per model and eval: mean (95% CI), min, Q1, median, Q3, max |
| Plot | One box plot per eval, all models side by side, SVG generated from the committed results |
| Cost | Runs on the maintainer's Claude subscription like the leaderboard; no API key |
| Policy | `docs/best-practices.md` changes from "Do not use an LLM judge as the only evaluator" to the graded-eval rules below (approved 2026-10-10) |

## Graded-eval rules (the policy)

These replace the single LLM-judge caution in `docs/best-practices.md` and go into
`CONTRIBUTING.md` and `docs/eval-authoring.md`:

1. Use a benchmark when a task has one checkable answer. Use a graded eval only when the answer
   is open-ended.
2. Every graded task has a rubric with written anchors for each score, and a reference key of
   facts computed from the data by a committed reference script, never written by hand.
3. Graded scores are reported apart from benchmark scores and never averaged with them.
4. Each answer is graded at least twice, and the report states the grader's agreement with
   itself, the grader model, its effort, the grader prompt version and the Claude Code version.
5. When the grader is one of the graded models, the report says so: its own rows may be biased.

## Layout

```
evals/
  README.md                     # what graded evals are; how they differ from benchmarks
  city/                         # shared by the five evals
    reference.py                # computes every reference key from the snapshot
    rubric_criteria.yaml        # the shared criteria and their 0-4 anchors
  proximity/eval.yaml           # one spec per eval
  proximity/tasks.jsonl
  adjacency/...  visibility/...  containment/...  direction/...
datasets/manifests/osm_city_<town>.yaml   # the pinned snapshot
src/geoevals/graded/            # spec model, grader, aggregation, table and plot
schemas/eval_spec.schema.json, graded_result.schema.json
leaderboard/graded/<eval>/<adapter>/      # accepted runs: result.json and grades.json
```

## The city data

- **Town selection (checkpoint 1).** Candidates are mid-size towns (roughly 20,000 to 100,000
  people) with no world-famous landmarks, so that answers cannot come from memory. For each, a
  measurement script queries OSM and reports: building count, share of buildings with `height`
  or `building:levels`, footway and path length, POI count, land-use coverage, water features,
  and extract size. The user picks one.
- **Snapshot.** One date, fixed in the manifest. The fetch downloads the town's extract for that
  date (an Overpass query with `[date:...]` over the town boundary, or a dated regional extract
  clipped to it; the plan picks one after checking which is reproducible), records its checksum,
  and converts it to GeoParquet layers in `data/raw/osm_city_<town>/`: `buildings`, `streets`,
  `paths`, `landuse`, `water`, `parks`, `pois`, `boundaries`, plus `all_features` with every tag.
  A second fetch must give the same checksum; if the source cannot promise that, the manifest
  records the checksum of the converted layers and the fetch fails on a mismatch.
- **Nothing OSM-derived is committed**, as `docs/data-governance.md` requires. Reference keys
  hold only IDs, counts, distances and short labels computed from the data, and the plan checks
  with the governance rules that this is allowed; if it is not, the keys are regenerated
  locally and only their hashes are committed.
- **CI** uses a small synthetic city (`tests/fixtures/graded_city/`) with the same layers.
- **Building heights.** Where a building has no `height`, its height is `building:levels` x 3 m,
  else unknown. Visibility tasks state this rule, and their keys follow it. Unknown heights are
  part of the realistic noise; the rubric rewards stating the assumption.

## Tasks

A task line in `tasks.jsonl`:

```json
{"task_id": "visibility-003", "prompt": "...", "location": {"point": [lon, lat], "feature_ids": ["way/123"]},
 "params": {...}, "rubric": ["relations", "reasoning", "assumptions", "data_use", "clarity"],
 "key": {"visible": ["way/12", "way/40"], "blocked_by": {"way/7": "way/12"}}, "strata": {...}}
```

- `key` is written by `evals/city/reference.py`, never by hand, and checked like the benchmarks'
  expected outputs (`geoevals evals regenerate <id> --check`, numbers compared to 5 decimal
  places).
- The five shared criteria, each 0 to 4 with anchors in `rubric_criteria.yaml`: spatial
  relations correct (against the key), reasoning sound, assumptions and edge cases stated, use of
  the data, clarity for the stated audience. An eval may add task-specific anchors.
- **Drafting (checkpoint 2).** I draft all 60 tasks, compute their keys, and the user reviews the
  prompts and rubrics before the evals are frozen at 0.1.0.

Example concepts per eval: proximity (walking versus straight-line nearness across barriers such
as rivers and rail), adjacency (shared edges versus corner touches, what a closure disconnects),
visibility (line of sight between buildings with heights), containment (overlapping boundaries,
points on a boundary), direction (turn-by-turn directions with landmarks, misleading bearings).

## Running and grading

- **Answers.** `geoevals run --eval evals/<id>/eval.yaml --adapter claude_python_<model>` with a
  graded config. The python adapter gains one config option, `data_mount`, the local directory
  mounted read-only at `/bench/data` (the city layers); the default stays the benchmark's
  fixtures. The answer schema: `status` (as in the benchmarks) and `answer` (Markdown text, at
  most 4,000 words). The run writes no scores.
- **Grading.** `geoevals grade <run_dir>` runs, for each answered task and each of two passes, a
  separate `claude -p` session: Opus 5.5, effort high, no tools, the same isolation as the
  leaderboard adapters (`--restricted`, stripped environment, empty working directory,
  subscription check). Its input is the grader prompt (versioned, `grader_v1`), the task prompt,
  the rubric with anchors, the key and the answer. The model's name, the adapter and the
  trajectory are not included. Its output (JSON schema): per criterion an integer 0 to 4 and a
  justification of at most 60 words that cites the key. Grades go to `grades.json` in the run
  directory with the grader model, effort, prompt version and Claude Code version.
- **Failures.** A non-`ok` status is graded too (an abstention can deserve credit). A grader error
  or unparseable grade is retried once; a second failure marks the task "not graded", and a run
  with any ungraded task is not accepted on the leaderboard. The usage-limit, auth and version
  checks of the leaderboard apply to the grader.

## Scores, table and plot

- Task score = mean over the two passes of (mean of criteria / 4), in [0, 1].
- Per eval and model: mean with a 95% bootstrap interval (`geoevals.metrics.bootstrap_ci`, with its fixed seed),
  min, Q1, median, Q3, max, and the number of tasks.
- Grader agreement per eval: the share of criterion scores on which the two passes differ by at
  most 1, and the mean absolute difference of task scores.
- README: a "Graded evals" section after the leaderboard, generated between its own markers by
  `geoevals leaderboard build`:

  | Model | Eval | Mean (95% CI) | Min | Q1 | Median | Q3 | Max |

  Below it, one SVG box plot per eval (`leaderboard/graded/plots/<eval>.svg`), all models side
  by side, made with matplotlib (a new optional dependency group), with fixed fonts and no
  timestamps so that the SVG is byte-stable. The docs test checks that the table and plots match
  the committed results.
- Notes under the table: grader model and settings, grader agreement, and that Opus grades its
  own answers.

## Docs

- `README.md`: "Benchmarks (deterministic)" and "Graded evals (agent-graded)" sections saying
  what each measures, how each is scored, and why they are reported apart.
- `CONTRIBUTING.md`: when to contribute a benchmark and when a graded eval, with the rules above.
- `docs/eval-authoring.md` (new): how to write a graded eval: spec, tasks, rubric anchors,
  reference script, regenerate, grading, review.
- `docs/best-practices.md`: the LLM-judge row changes to the graded-eval rules.
- `ROADMAP.md`: the OSM vector benchmark item notes that the city snapshot and its fetch are
  shared with the graded evals.

## Order of work

1. Town measurement script; propose 2 or 3 towns (checkpoint 1: the user picks).
2. Dataset manifest and fetch for the snapshot; synthetic CI city.
3. Eval spec and task schemas, loading, `evals regenerate`.
4. Reference script for the five key types.
5. Draft 60 tasks (checkpoint 2: the user reviews).
6. `data_mount` for the python adapter; graded runs.
7. Grader and `geoevals grade`.
8. Aggregation, table, box plots, docs.
9. Pilot: Opus, one task per eval, then two-pass grading.
10. Full runs: Opus, then Sonnet and Haiku, each needing the user's go-ahead.

## Testing

- Schemas and spec loading, with invalid specs and tasks.
- Reference keys on the synthetic city: visibility, adjacency (edge versus corner), containment
  with points on a boundary, network versus straight-line distance, and directions.
- `evals regenerate --check` within 5 decimal places.
- Grader: fake `claude` scenarios (valid grade, invalid JSON then retry, two failures, usage
  limit, wrong model); the grader input never holds the adapter or model name.
- Aggregation: quartiles, CI, agreement on fixed grades; acceptance rules (ungraded tasks,
  mixed grader versions, mixed eval versions).
- Table and SVG are byte-stable across two builds; the docs test checks they are current.
- Real runs are not part of the test suite; they need the subscription.

## Risks

- **Self-preference.** Opus grades its own answers. Mitigated by blinding, keys from data and the
  note in the README; not removed.
- **Grader drift.** A new Claude Code or model version can grade differently. The grader version
  is recorded, and runs graded by different versions are not comparable (the build rejects a
  mix).
- **Snapshot reproducibility.** If the chosen source cannot reproduce the same extract, the fetch
  fails on the checksum rather than silently changing the keys.
- **Memorization.** A real town can be known to the models. Choosing a little-known town limits
  this; it cannot be ruled out.
- **Usage.** One model's run is 60 answers and 120 grading sessions on the subscription.
