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

Feature extraction from imagery is not planned. Many benchmarks already cover it.

### LLM and hosted-API adapters

Adapters for language models and hosted APIs. The adapter protocol, the run-result token and
cost fields and the price table already support them; v0.1.0 ships none. Open questions:
who maintains the price table, and how price changes are versioned so that historical cost
figures stay interpretable.

### Agentic GIS tasks with real agents

GIS tasks for real tool-using agents, with executable reference trajectories and validation of
the final output. v0.1.0 captures and scores trajectories only with the scripted `mock_agent`.
A successful tool call or trajectory never counts toward `task_success` on its own.

### Expanded place-context cases

More human-context cases and places, and temporal and geographic transfer evaluations. An
activity-intensity or human-rating task is added only when credible observation data or a
validated rating protocol exists. The 1,000-case PlaceContext-1K benchmark is a later target.

### Leaderboard policy

A leaderboard only after comparability and verification rules are defined: what a submission
contains, how a result is verified (local runs, submitted artifacts or community reports), and
the trust level each one carries. An open question is whether the run-result schema reserves
a submission or verification block before then, to avoid a breaking schema change.

### Maintainer review and benchmark versioning

Written policies for maintainer review of new benchmarks, metrics and adapters, and for
benchmark versioning and deprecation.
