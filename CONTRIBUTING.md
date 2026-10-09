# Contributing to GeoEvals

Thank you for helping. This guide covers the development setup, the quality gates, what a
benchmark needs before it can merge, and how versions change. By taking part you agree to
follow the [code of conduct](CODE_OF_CONDUCT.md). Report security problems privately, as
[`SECURITY.md`](SECURITY.md) describes, not in a public issue.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and git. uv installs a suitable Python (3.11 or
later) and the locked dependencies:

```sh
git clone <your fork URL> geoevals
cd geoevals
uv sync
uv run geoevals --help
```

`uv sync` installs the package in editable mode with the `dev` dependency group (pytest,
Ruff, Pyright, and networkx and SciPy for the human-context benchmark). No credentials or paid
services are needed for development or for the tests.

- Add a runtime dependency with `uv add <package>` and a development tool with
  `uv add --dev <package>`, so `uv.lock` stays in sync. Commit `uv.lock`.
- Change the package version only in `pyproject.toml`.
- Never commit data under `data/raw/` or run output under `runs/`. Both are gitignored.

## Quality gates

Run these before you open a pull request. CI runs the same commands and they must all pass:

```sh
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

| Gate | What it checks |
| --- | --- |
| `ruff check .` | Lint rules E, F, W, I, B, UP, SIM, RUF; line length 100 |
| `ruff format --check .` | Formatting (`uv run ruff format .` fixes it) |
| `pyright` | Types in `src/` and `tests/`, "standard" mode |
| `pytest` | Unit and integration tests, including the README quickstart and the published-baseline reproduction. Tests marked `network` download real data and run only with `uv run pytest -m network`. |

CI runs on Ubuntu (Python 3.11 and 3.12) and macOS (Python 3.12). It also validates every
benchmark spec and dataset manifest with `geoevals validate`, runs the smoke benchmark,
reproduces the published baseline with `geoevals reproduce`, and validates `CITATION.cff`
with `cffconvert --validate`.

Write documentation and comments in American English (color, analyze, modeling). The tests
check the Markdown files for common British spellings.

## Pull requests

- Keep each pull request to one change. Describe what changed and why.
- Add or update tests for every change in behavior.
- If the change can change a score or an output, bump the version as the
  [version rules](#versions-and-breaking-changes) below say, and say so in the pull request.
- Fill in the checklist in the pull request template.

Use the issue templates to report a bug, propose a benchmark or propose a new adapter.

## Benchmark definition of done

A new benchmark, or a change to a benchmark, can merge only when it meets the
[definition of done](docs/benchmark-authoring.md#definition-of-done). In short:

1. A written task statement specifies the intended capability and intended use.
2. Inputs, outputs, spatial and temporal scope, and required metadata are machine-readable.
3. Dataset source, license, provenance, version and known limitations are documented.
4. The train, dev and test split strategy and the leakage controls are explained.
5. Metrics include formulas or unambiguous implementation references, units, tolerances and
   aggregation.
6. A baseline and an executable evaluation path are available.
7. Tests cover ordinary cases, boundary cases, malformed outputs and missing data.
8. A report exposes per-case failures, subgroup or region breakdowns where appropriate,
   uncertainty and cost.
9. Reproduction instructions work from a clean environment.
10. Maintainer review confirms that the claims are supported by the data and the evaluation
    design.

[`docs/benchmark-authoring.md`](docs/benchmark-authoring.md) says where GeoEvals checks each
item, and has a worked example that adds an operation to `gis_correctness` from start to end.

## Versions and breaking changes

Benchmarks, metrics, adapters and the JSON Schemas in `schemas/` use semantic versions
(`MAJOR.MINOR.PATCH`). The rule: **if a change can change a score or an output for the same
input, the version changes**, and runs from before and after the change are not comparable.
The full rules are in [`docs/reproducibility.md`](docs/reproducibility.md#version-rules).

A **breaking change** (a major bump) is one that existing users cannot absorb without a change
on their side:

| Item | Breaking change (major) | Minor | Patch |
| --- | --- | --- | --- |
| Benchmark | A change to `input_schema` or `output_schema` that existing adapters cannot meet | Cases added, removed or changed; expected outputs, fixtures, tolerances, splits or the metric list changed | Text only: the card, `limitations`, descriptions. Scores cannot change. |
| Metric | The meaning of the value changes, for example its units or its direction (`higher_is_better`) | A new check or param, or a changed edge case. Scores of some outputs can change. | A fix that cannot change any score, for example a clearer `detail` message |
| Schema | A field is removed or renamed, or its meaning changes | A field or a rule is added | Descriptions only |

Minor and major changes to a benchmark or a metric both make old and new runs incomparable.
The difference is that a major change also breaks adapters or consumers of the value.

When you bump a version:

- A metric: update its definition in [`docs/metrics.md`](docs/metrics.md) in the same pull
  request, and update the specs that use it to ask for the new version.
- A benchmark: regenerate the expected outputs with `uv run geoevals bench regenerate <id>`
  (never edit them by hand), update the benchmark card, and republish the baseline in
  `baselines/` so that `geoevals reproduce` passes.
- A schema: add a migration note to [`docs/reproducibility.md`](docs/reproducibility.md) and
  update `schema_version` in every document that uses it.
- An adapter: any change to how it answers bumps its version, which every run records.

## Data

Commit only small, synthetic, redistributable fixtures. Every data asset needs a dataset
manifest with its source, license and SHA-256. Restricted data, such as OpenStreetMap
extracts, is fetched into `data/raw/` with `geoevals data fetch` and never committed. Never
commit credentials, precise personal location traces or sensitive operational data. See
[`docs/data-governance.md`](docs/data-governance.md).

## License

GeoEvals is MIT-licensed. By contributing, you agree that your contribution is licensed under
the [MIT License](LICENSE).
