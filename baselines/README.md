# Published baselines

Each directory `baselines/<benchmark_id>/<name>/` is one committed run: `result.json`,
`cases.jsonl`, the pinned run config `config.yaml` and `report.md`. Each report states the
adapter and its version, the model (none for these adapters), the dataset manifest hash and the
benchmark's known limitations.

| Baseline | Adapter | Cases | What it shows |
| --- | --- | --- | --- |
| [`gis_correctness/gis_baseline`](gis_correctness/gis_baseline/report.md) | `gis_baseline` (deterministic, GeoPandas/Shapely/pyproj) | 56 | `task_success = 1.0`: the harness and the reference agree |
| [`gis_correctness/mock_failures`](gis_correctness/mock_failures/report.md) | `mock` (scripted) | 56 | Every case status (`scored`, `adapter_error`, `timeout`, `invalid_output`, `skipped`) and the abstention penalty (`answered_when_should_abstain`) |
| [`human_context_access/access_baseline`](human_context_access/access_baseline/report.md) | `access_baseline` (deterministic, `scipy.sparse.csgraph`) | 51 | `task_success = 1.0`: an independent implementation agrees with the networkx reference |

Rerun one and compare it with the committed result:

```sh
uv run geoevals reproduce baselines/gis_correctness/gis_baseline
```

CI's `reproduce` job reruns every directory here in a fresh environment
(`uv sync --frozen --no-cache`) and fails on any difference. See
[`docs/reproducibility.md`](../docs/reproducibility.md#reproduce-a-published-baseline).

Known limitations of the baselines themselves:

- `gis_baseline` uses the same libraries as the `gis_correctness` reference workflow (Shapely,
  pyproj, GEOS, PROJ), so an error those libraries share is not caught. `access_baseline`
  computes paths with `scipy.sparse.csgraph` and the reference with networkx, but both share
  the opening-hours parser. Perfect scores show that the harness works. They do not show that
  the benchmarks are hard.
- The `mock_failures` scores describe a scripted adapter, not any real system. Its `timeout`
  case depends on `timeout_s: 2` in `config.yaml`.
- No baseline calls a model, so none of them records tokens or cost from a real API.
- The baselines were written on macOS arm64. Reruns on other platforms match within the
  tolerance of `geoevals reproduce` (absolute 1e-07, relative 1e-09), not bit for bit.
