# GeoEvals

A reproducible, practitioner-focused framework for evaluating geospatial AI systems.

## Development

```sh
uv sync
uv run geoevals --version
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

## Reproduce the published baseline

```sh
uv run geoevals reproduce baselines/gis_correctness/gis_baseline
```

See the benchmark card, [`benchmarks/gis_correctness/README.md`](benchmarks/gis_correctness/README.md).
