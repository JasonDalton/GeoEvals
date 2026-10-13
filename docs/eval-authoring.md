# Graded eval authoring

GeoEvals has two kinds of evaluation. This guide covers the second.

| | Benchmark | Graded eval |
| --- | --- | --- |
| Task | One checkable answer | An open-ended answer |
| Scored by | Code: deterministic metrics against an expected output and tolerances | A grading agent, against a rubric and a reference key computed from data |
| Lives in | `benchmarks/` ([`benchmark-authoring.md`](benchmark-authoring.md)) | `evals/` (this guide) |
| Reported in | The leaderboard table | The graded-evals table and box plots |

The two are never combined: no shared score, no shared table, no shared directory.

## Rules

1. Use a benchmark when a task has one checkable answer. Use a graded eval only when the answer
   is open-ended.
2. Every graded task has a rubric with written anchors for each score, and a
   reference key of facts computed from the data by a committed reference script, never written
   by hand.
3. Graded scores are reported apart from benchmark scores and never averaged with them.
4. Each answer is graded at least twice, and the report states the grader's agreement with
   itself, the grader model, its effort, the grader prompt version and the Claude Code version.
5. When the grader is one of the graded models, the report says so: its own rows may be biased.

## What an eval holds

An eval is a directory `evals/<id>/` with:

- `eval.yaml`: the spec (`schemas/eval-spec.schema.json`): ID, version, concept, task
  statement, word limit, and the paths of its tasks, the shared rubric criteria, the reference
  script and the city's dataset manifest.
- `tasks.jsonl`: one task per line: `task_id`, `prompt`, `audience`, `location` (sent to the
  model), `key_type` and `params` (the reference script's input, hidden from the model),
  `rubric` (criterion IDs), optional `anchors` for the task, `key_sha256` and `strata`.

The evals on the city share `evals/city/rubric_criteria.yaml` (five criteria, each 0 to 4 with
written anchors) and `evals/city/reference.py` (six key types: proximity, containment,
adjacency, closure, visibility, direction).

## Write a task

1. Pick a place in the city and a question whose answer needs spatial reasoning, not lookup.
   The data is a whole city, so the model has to find what bears on the question.
2. Write the `prompt` as a person would ask it, and name the `audience`.
3. Choose the `key_type` and write the `params` that compute the facts a correct answer must
   agree with. Check the key against a map before relying on it.
4. List the criteria that score the task (usually all five) and add task `anchors` where the
   shared ones are too general, for example what a 4 on assumptions needs here.

## How the reference keys behave

The keys follow a few fixed rules, so a task author should expect them:

- The walking network is densified to vertices at most 10 m apart, so a place joins the network
  within a few meters of its nearest street. A place can join each nearby connected part of the
  network, so a short isolated footway beside it does not cut it off from the street behind.
- The walking network leaves out ways a pedestrian may not use: motorways and motorway ramps,
  ways tagged `foot=no` or `foot=private`, and ways tagged `access=no` or `access=private`
  unless `foot` is `yes`, `designated` or `permissive`. Other access tags are ignored.
- A place more than 100 m from every network vertex it can reach is unreachable, and so is a
  place whose only nearby vertices are across a walk barrier: surface rail (not trams, subways,
  tunnels or bridges), a river, canal or stream that is not culverted, or a water area. Ditches
  and drains are not barriers.
- Walls up to 5 cm apart, or overlapping by up to 5 cm, count as touching.
- A target building is visible when any part of it can be seen: the key sights points every
  0.5 m along the target's outline (leaving out its far side, which the building itself hides)
  and calls the target visible when any of those lines is clear. `visible_outline_m` tells a
  sliver from a full view, and `blocked_by` lists every building that hides part of the target.
- Visibility never guesses an unknown height. When a target or an observer has no known height
  and the answer depends on it, the key says `visible: null`, and a good answer says it cannot
  tell. A building of unknown height on a sight line leaves that line undecided; the target is
  `null` when no line to it is clear and at least one is undecided.
- In directions, step distances cover only the walk on the network, not the walks to and from
  it, so they do not sum to `walking_m`.

## Compute the keys

Keys come from OpenStreetMap data, so they are not committed (see
[`data-governance.md`](data-governance.md)). To compare candidate towns before choosing one,
`uv run geoevals evals measure-town` fetches an extract into a gitignored directory and prints
its measurement row. Then fetch the chosen city, build its layers and compute the keys:

```sh
uv run geoevals data fetch osm_city_<town>
uv run geoevals data fetch osm_city_<town> --pbf <extract>   # or read a local dated .osm.pbf
uv run geoevals evals build-city osm_city_<town>
uv run geoevals evals regenerate <eval id>          # writes data/raw/osm_city_<town>/keys/
uv run geoevals evals regenerate <eval id> --check  # exit 1 when a key_sha256 is stale
```

`regenerate` records each key's SHA-256 in `tasks.jsonl`. Grading refuses keys whose hash does
not match, so a reviewer always grades against the keys the tasks were reviewed with.

## Review the drafts

```sh
uv run geoevals evals review <eval id>   # writes data/raw/osm_city_<town>/review/<eval id>.md
```

The review sheet shows each task's prompt, audience, strata, params and key, with a map of the
features it names, and warns about keys that are probably not what the author meant: a walk more
than 3 times the straight line (often a connection OpenStreetMap lacks), a location within 300 m
of the edge of the city box, duplicate tasks, and keys with nothing to answer. The sheet holds
the keys, so it stays in the gitignored data directory.

## Run and grade

```sh
uv run geoevals run --eval evals/<id>/eval.yaml --adapter claude_python_opus_5_5 \
  --config leaderboard/configs/python.yaml --out runs/graded
uv run geoevals grade runs/graded/<run_id>
uv run geoevals leaderboard add runs/graded/<run_id>
uv run geoevals leaderboard build
```

Graded evals run on the python track only: the city is mounted read-only in the sandbox at
`/bench/data`. `geoevals grade` runs Claude Opus 5.5 (effort high) in its own `claude -p`
session per answer and pass, with no tools and the leaderboard's isolation. The grader sees the
task with its location, the rubric, the key and the answer, never which model answered. Each answer is graded
twice; an error or invalid grade is retried once, and a task that still has no grade leaves the
run off the leaderboard. `geoevals grade` exits 1 when grading stopped or any task is not
graded. It refuses to replace an existing `grades.json` unless given `--force`: a run is graded
once, not re-graded until the scores look better. `leaderboard build` needs the `plots` extra
when graded rows exist.

Graded runs are committed in `leaderboard/graded/`. Their answers quote OpenStreetMap names,
IDs and distances, and the grader's justifications cite the key; the maintainer decided on
2026-10-12 that this may be committed with OpenStreetMap attribution (see
[`data-governance.md`](data-governance.md#restricted-data)).

## Review and versions

The rubric, the tasks and their keys are reviewed before an eval's first version is frozen.
A change to a task, a key, the rubric or the reference script changes scores, so it is a minor
version change of the eval, as for benchmarks
([`reproducibility.md`](reproducibility.md#version-rules)). Runs graded by different grader
versions are not comparable, and the leaderboard build rejects a mix.
