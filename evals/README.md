# Graded evals

Open-ended spatial-reasoning tasks on one real city, scored by a grading agent (Claude Opus
5.5) against a rubric and a reference key computed from the city's OpenStreetMap data. They are
reported apart from the deterministic benchmarks in `benchmarks/` and never combined with them.

| Directory | What it holds |
| --- | --- |
| `city/rubric_criteria.yaml` | The five criteria every task is scored on, each 0 to 4 with anchors |
| `city/reference.py` | Computes each task's reference key from the city's layers |
| `<eval>/eval.yaml`, `<eval>/tasks.jsonl` | One eval: its spec and its tasks |

The city's data and the keys are not committed (ODbL); `geoevals data fetch` and `geoevals
evals regenerate` recreate them. How to write, run and grade an eval:
[`docs/eval-authoring.md`](../docs/eval-authoring.md).

The evals on Oregon City, Oregon (`datasets/manifests/osm_city_oregon_city.yaml`), each 12 tasks
in three tiers (describe, analyze, infer):

| Eval | Concept |
| --- | --- |
| [`proximity`](proximity/eval.yaml) | Nearness on foot against nearness on the map, across rivers and rail |
| [`adjacency`](adjacency/eval.yaml) | Shared walls against corner touches; what a closure does to a walk |
| [`visibility`](visibility/eval.yaml) | Lines of sight between buildings with heights; undecided views |
| [`containment`](containment/eval.yaml) | Nested and overlapping boundaries; points on a boundary |
| [`direction`](direction/eval.yaml) | Turn-by-turn directions with landmarks; misleading bearings |
