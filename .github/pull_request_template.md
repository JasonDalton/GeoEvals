## What and why

<!-- What this pull request changes and why. Link the issue it closes. -->

## Checklist

- [ ] The quality gates pass: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
- [ ] Tests cover the change
- [ ] Documentation is updated (American spelling)
- [ ] Versions are bumped where a score or an output can change (see "Versions and breaking changes" in CONTRIBUTING.md), and a breaking change is called out above
- [ ] No credentials, restricted data (`data/raw/`) or run output (`runs/`) is committed

## Benchmark definition of done

<!--
Fill this in if the pull request adds or changes a benchmark; otherwise delete it.
docs/benchmark-authoring.md#definition-of-done says where each item is checked.
-->

- [ ] A written task statement specifies the intended capability and intended use.
- [ ] Inputs, outputs, spatial and temporal scope, and required metadata are machine-readable.
- [ ] Dataset source, license, provenance, version and known limitations are documented.
- [ ] The train, dev and test split strategy and the leakage controls are explained.
- [ ] Metrics include formulas or unambiguous implementation references, units, tolerances and aggregation.
- [ ] A baseline and an executable evaluation path are available.
- [ ] Tests cover ordinary cases, boundary cases, malformed outputs and missing data.
- [ ] A report exposes per-case failures, subgroup or region breakdowns where appropriate, uncertainty and cost.
- [ ] Reproduction instructions work from a clean environment.
- [ ] Maintainer review confirms that the claims are supported by the data and the evaluation design.
