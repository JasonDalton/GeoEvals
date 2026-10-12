# Roadmap

v0.1.0 covers phases 1 to 4 of the kickoff plan: the evaluation contracts, the GIS correctness
benchmark, the human-context pilot on walking access, and public-beta preparation. See
[`CHANGELOG.md`](CHANGELOG.md) for what shipped.

This file lists the work planned after v0.1.0. Nothing here is a commitment to a date. Each
item still has to meet the benchmark definition of done in
[`docs/benchmark-authoring.md`](docs/benchmark-authoring.md#definition-of-done) and the
version rules in [`README.md`](README.md#versioning-and-comparability). To propose or discuss
an item, open an issue with the benchmark proposal or new adapter template.

## Phase 5: growth after launch

### Vector benchmark on OpenStreetMap data

The next benchmark works on spatial data in vector form, with OpenStreetMap as the main
input: points, lines and polygons with their tags, in place of the synthetic fixtures that
v0.1.0 ships. OSM data is licensed under the ODbL-1.0, so extracts are referenced by a dataset
manifest and downloaded, never committed, as the
[data governance rules](docs/data-governance.md) require. Open questions: which extracts and
snapshot dates to pin, and how a reference output stays stable when OSM is edited.

The graded evals will pin a whole-town OpenStreetMap snapshot. The tooling to fetch and convert one exists (`geoevals data fetch osm_city_<town>`, `geoevals evals build-city`), but no town is pinned yet; this benchmark can reuse that fetch.

Feature extraction from imagery is not planned. Many benchmarks already cover it.

### Graded evals on a real city

The engine for agent-graded evals exists (see `docs/eval-authoring.md`). Planned: five evals (proximity, adjacency, visibility, containment, direction) on one pinned town, 12 tasks each, graded by Claude Opus 5.5. They arrive with the town's dataset manifest and the task drafting.

### LLM and hosted-API adapters

Adapters for language models and hosted APIs. The first are not yet released: the Claude
leaderboard adapters (`claude_direct_<model>`, `claude_python_<model>`) run Claude models
through the local Claude Code CLI on a subscription, with no API key
([`leaderboard/README.md`](leaderboard/README.md)). Still open: adapters that call hosted APIs
with keys, who maintains the price table, and how price changes are versioned so that
historical cost figures stay interpretable.

### Agentic GIS tasks with real agents

GIS tasks for real tool-using agents, with executable reference trajectories and validation of
the final output. v0.1.0 captures and scores trajectories only with the scripted `mock_agent`.
A successful tool call or trajectory never counts toward `task_success` on its own.

### Expanded place-context cases

More human-context cases and places, and temporal and geographic transfer evaluations. An
activity-intensity or human-rating task is added only when credible observation data or a
validated rating protocol exists. The 1,000-case PlaceContext-1K benchmark is a later target.

### Leaderboard policy

A first leaderboard is not yet released: Claude models on the two v0.1.0 benchmarks, run
locally by the maintainer, in the [README](README.md#leaderboard). Its rules: a row is a
complete run (no skipped case), every row of a benchmark shares its version and dataset
manifest hash, and the Claude Code version, prompt version and effort are stated with the
table. These rows are local runs, not verified submissions. Still open: what a submission
contains, how a result is verified (local runs, submitted artifacts or community reports), the
trust level each one carries, and whether the run-result schema reserves a submission or
verification block before then, to avoid a breaking schema change.

### Maintainer review and benchmark versioning

Written policies for maintainer review of new benchmarks, metrics and adapters, and for
benchmark versioning and deprecation.
