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

The graded evals pin a whole-town OpenStreetMap snapshot. The tooling to fetch and convert one exists (`geoevals data fetch osm_city_<town>`, `geoevals evals build-city`), and the graded evals pin Oregon City, Oregon (`osm_city_oregon_city`, from Geofabrik's 2026-10-11 extract); this benchmark can reuse that fetch.

Feature extraction from imagery is not planned. Many benchmarks already cover it.

### Graded evals on a real city

The engine for agent-graded evals exists (see `docs/eval-authoring.md`). Planned: five evals (proximity, adjacency, visibility, containment, direction) on one pinned town, 12 tasks each, graded by Claude Opus 5.5. The town is Oregon City, Oregon; the 60 tasks are frozen (visibility at 0.2.0, the other four at 0.1.0) and a one-task-per-eval pilot has run.

Ideas for later graded evals, not yet designed:

- **Multi-skill tasks.** One task that needs several of the five skills. The model is a
  multi-criteria site search such as the "Home Finder" exercise of a study of 104 geography
  students in Waterloo, Ontario: homes within a walking distance of a school, away from rail,
  inside city limits. The key lists each part and the facts that link them. Read against the
  five single-skill evals, which come first.
- **Reading a rendered map.** The same questions from a map image instead of the layers, so that
  paired tasks measure what a model loses reading a map. The map is supplied pre-rendered and
  pinned by its SHA-256 in the dataset manifest; GeoEvals does not render it. Needs image input
  in the adapters, a grader that sees the image or keys limited to what the image shows, and a
  governance decision on shipping the image (a rendered map is an ODbL Produced Work).
- **Grading the strategy.** A criterion graded from the python-track code transcript: whether
  the model narrowed candidates criterion by criterion, checked its distances, and kept the
  method in proportion to the problem. Needs a new grader prompt version.
- **Influence at a distance.** How a feature affects the places around it, more weakly with
  distance: noise from a highway, the shade of a tall building, the reach of a flood, a
  school's catchment. Needs a reference method for each kind of influence.
- **Over and under.** Features stacked in three dimensions: a path under a bridge, a road over
  a railway, a tunnel, the floors of a building. Needs the layer, bridge and tunnel tags in
  the walking network, which today records only which ways connect.
- **Patterns and association.** Clustering and dispersion (nearest-neighbor ratio, quadrat
  counts) and association between feature types (co-location quotient), computed from the data.
- **Difficulty tiers.** Each task tagged describe, analyze or infer in its `strata`, so the
  report shows where scores fall off.
- **A human baseline.** A subset of tasks answered by GIS students, to place model scores on a
  human scale.

### LLM and hosted-API adapters

Adapters for language models and hosted APIs. The first are not yet released: the Claude
leaderboard adapters (`claude_direct_<model>`, `claude_python_<model>`) run Claude models
through the local Claude Code CLI; Codex Luna adapters (`codex_direct_luna`,
`codex_python_luna`) use the local Codex CLI. Both use subscriptions, with no API key
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

A first leaderboard is not yet released: Claude models and GPT-6 Luna on the two v0.1.0
benchmarks, run locally by the maintainer, in the [README](README.md#leaderboard). Its rules: a row is a
complete run (no skipped case), every row of a benchmark shares its version and dataset
manifest hash, and the CLI version, prompt version and effort are stated with the
table. These rows are local runs, not verified submissions. Still open: what a submission
contains, how a result is verified (local runs, submitted artifacts or community reports), the
trust level each one carries, and whether the run-result schema reserves a submission or
verification block before then, to avoid a breaking schema change.

### Maintainer review and benchmark versioning

Written policies for maintainer review of new benchmarks, metrics and adapters, and for
benchmark versioning and deprecation.
