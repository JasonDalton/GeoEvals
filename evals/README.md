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
