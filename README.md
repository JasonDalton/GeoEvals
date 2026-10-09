# GeoEvals

A reproducible, practitioner-focused framework for evaluating geospatial AI systems.

## Development

```sh
uv sync
uv run geoevals --version
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```
