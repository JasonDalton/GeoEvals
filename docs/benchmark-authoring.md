# Benchmark authoring

This guide explains how to add a benchmark, a case, a metric, an adapter or a dataset
manifest. It ends with a worked example that adds a new operation to `gis_correctness`, and
with the definition of done that every benchmark must meet.

Read [`principles.md`](principles.md) and [`best-practices.md`](best-practices.md) first.

## The parts of a benchmark

A benchmark is a directory under `benchmarks/`:

```text
benchmarks/<name>/
  benchmark.yaml   # the spec: task, schemas, cases, splits, metrics, tolerances, provenance
  cases/*.jsonl    # one case per line (or a single cases.jsonl)
  expected/        # optional: expected outputs too large to keep inline in a case line
  fixtures/        # small input files (under 1 MB in total)
  manifest.yaml    # a dataset manifest that lists every fixture with its SHA-256
  reference.py     # the reference workflow that computes every expected output
  README.md        # the benchmark card
```

The directory name is usually the benchmark ID. It may differ (`benchmarks/human_context/`
holds `human_context_access`); commands find a benchmark by the `id` in its spec.

### The spec

`benchmark.yaml` must match [`schemas/benchmark.schema.json`](../schemas/benchmark.schema.json)
(`schema_version: "1.1.0"`). The required fields are:

| Field | Contents |
| --- | --- |
| `id`, `version`, `title` | A lower_snake_case ID and a semver version |
| `pillar` | `perception`, `spatial_reasoning` or `human_context` |
| `task_statement`, `intended_use` | The capability tested and what the scores may be used for |
| `input_schema`, `output_schema` | JSON Schemas for a case input and for an adapter's output. Output that fails `output_schema` gets the status `invalid_output`. |
| `cases` | The case file, or a list of case files, relative to the spec |
| `splits` | Split name -> `{description}` |
| `metrics` | A list of `{id, version, params}`; every ID must be a registered metric |
| `tolerances` | Benchmark-wide default tolerances: name -> `{value, units}` |
| `dataset_manifest` | The path of the manifest, relative to the spec |
| `license`, `provenance`, `limitations` | The license, `{authors, created, reference_workflow, notes}` and a list of limitations |

A `human_context` spec must also list every output field in `output_schema.properties` with
an `evidence_type` (see [`human-context.md`](human-context.md#evidence-types)).

Check a spec with `uv run geoevals validate benchmarks/<name>/benchmark.yaml`. CI validates
every `benchmark.yaml` and `manifest.yaml` under `benchmarks/`.

### Cases

A case file is JSONL: one JSON object per line. The runner reads these fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `case_id` | yes | Unique across the benchmark |
| `expected` | yes | The reference output, inline, or the path (relative to the spec) of a JSON file that holds it. It goes to the metrics, never to the adapter. |
| `split` | when the spec has more than one split | The split of the case |
| `strata` | no | Labels for the report's breakdowns, for example `operation`, `crs_family`, `trap` |
| `tolerances` | no | Name -> `{value, units}`. Each value reaches every metric as the param `name`. |
| `metric_params` | no | Other metric params, for example `key` (the feature property that pairs predicted and reference features) |

Every other field (for example `operation`, `prompt` and `inputs` in `gis_correctness`) is
part of the case input that the adapter gets, and must match `input_schema`. The runner also
adds `benchmark_dir`, the absolute path of the spec's directory, so that the adapter can open
the fixtures that a case names.

Param precedence, from lowest to highest: the spec's `tolerances`, a metric's `params` in the
spec, the case's `tolerances` and `metric_params`. Every tolerance needs explicit units.

### Expected outputs

Never write an expected output by hand. `reference.py` defines
`reference_output(case, benchmark_dir) -> dict`, which computes the expected output of a case
(given the case line without `expected`). Then:

```sh
uv run geoevals bench regenerate <id>           # rewrites stale expected outputs
uv run geoevals bench regenerate <id> --check   # exit 1 if any committed output is stale
```

An inline `expected` is replaced in the case line; a string `expected` names the file that is
rewritten. Each benchmark has a test that the committed outputs match the regenerated ones.

## Create a new benchmark

1. Create the directory with `benchmark.yaml`, a case file, `fixtures/` and `manifest.yaml`.
   Copy `benchmarks/smoke/` or `benchmarks/gis_correctness/` as a starting point.
2. List every fixture in `manifest.yaml` with its SHA-256 (`shasum -a 256 <file>`). Run
   `uv run geoevals data verify benchmarks/<name>/manifest.yaml`.
3. Write `reference.py` and give every case a placeholder `"expected": {}`. Run
   `uv run geoevals bench regenerate <id>`.
4. Add or reuse an adapter that answers the cases (see [Add an adapter](#add-an-adapter)).
5. Run the benchmark and read the report:

   ```sh
   uv run geoevals run --benchmark benchmarks/<name>/benchmark.yaml --adapter <adapter> \
     --config <run_config.yaml> --out runs/<name> --report
   ```

   A run config sets `split`, `seed`, `timeout_s`, `max_retries`, `workers` and `adapter`
   (the adapter config). See `benchmarks/human_context/run_config.yaml`.
6. Add tests under `tests/`: the spec validates, the committed expected outputs match the
   regenerated ones, the baseline passes every case, and wrong, malformed and empty answers
   fail.
7. Write the benchmark card `README.md`: purpose, operations and case counts, tolerances, data
   provenance, limitations and how to reproduce. The two existing cards are models.
8. Publish a baseline in `baselines/<id>/<adapter>/` (`result.json`, `cases.jsonl`,
   `config.yaml`, `report.md`), so that `uv run geoevals reproduce baselines/<id>/<adapter>`
   works. The commands are in
   [`benchmarks/gis_correctness/README.md`](../benchmarks/gis_correctness/README.md#reproduce-the-published-baseline).
9. Check every item of the [definition of done](#definition-of-done).

## Add a metric

1. Subclass `geoevals.metrics.Metric`. Set the class attributes `id` (lower_snake_case),
   `version` (semver), `units` and `higher_is_better`, and implement
   `score(prediction, reference, params) -> MetricValue`. `MetricValue` holds `value` (a
   number, or null when no number can be computed), `passed` (true, false or null) and
   `detail` (a dict that explains the result). The default `aggregate` gives the mean, the
   median, `n`, `n_failed` and a 95% bootstrap interval.
2. A check that does not apply to a case returns `value: null`, `passed: null`,
   `detail: {"applicable": false}`.
3. Register an instance in `src/geoevals/metrics/__init__.py` with `register_metric`, as the
   built-in metrics are. Do not register it as a side effect of importing its module.
4. Define it in [`metrics.md`](metrics.md): formula or implementation reference, units,
   tolerance semantics, edge cases (empty geometry, null output, mixed geometry types) and
   aggregation.
5. Test the boundaries: exactly at the tolerance passes, just beyond it fails, and an empty or
   null prediction fails.

Once a metric is published, any change to its definition bumps its version (see
[`reproducibility.md`](reproducibility.md#version-rules)). The runner warns when a spec asks
for a version other than the registered one, and the run result records the registered
version.

## Add an adapter

An adapter implements the `geoevals.adapters.Adapter` protocol:

```python
from collections.abc import Mapping
from typing import Any

from geoevals.adapters import AdapterResponse


class MyAdapter:
    name = "my_adapter"
    version = "0.1.0"
    deterministic = True  # optional: no paid calls, so cost_usd is 0.0 without a price table

    def setup(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)  # the run config's `adapter` mapping

    def predict(self, case_input: Mapping[str, Any]) -> AdapterResponse:
        # case_input is the case without `expected`, plus `benchmark_dir`.
        return AdapterResponse(output={"status": "insufficient_data"})

    def teardown(self) -> None:
        pass
```

- Define the class at module level. Each adapter runs in a separate worker process that is
  started with `spawn`, and the class is pickled to it.
- `predict` signals a failure by raising. The runner records `adapter_error`, retries up to
  `max_retries` times and continues with the next case. A case that runs longer than
  `timeout_s` is killed and recorded as `timeout`.
- Return `tokens` (`TokenUsage(input, output)`) when the adapter uses tokens. Cost comes from
  the price table (`--prices`, default `examples/prices.example.yaml`); an adapter that is
  missing from the table gets `cost_usd: null`, never 0.
- An agent returns its `trajectory`. The runner records and summarizes it, but never scores
  it.
- Read credentials from the environment, never from a committed file.

Register it in `src/geoevals/adapters/__init__.py`:

```python
register_adapter(MyAdapter.name, MyAdapter)
```

Then `uv run geoevals adapters list` shows it, `--adapter my_adapter` selects it, and
`uv run geoevals adapters predict --adapter my_adapter <case.json>` runs it on one case
input.

## Add a dataset manifest

A benchmark's own fixtures go in its `manifest.yaml`. A dataset that users download goes in
`datasets/manifests/<dataset_id>.yaml`, with instructions in
`datasets/download_instructions/<dataset_id>.md`. The fields and the rules for restricted data
are in [`data-governance.md`](data-governance.md). Check a manifest with:

```sh
uv run geoevals validate <manifest>
uv run geoevals data verify <manifest>
```

## Worked example: add an `area` operation to `gis_correctness`

This example adds a new operation, the geodesic area of a polygon, with one case, from the
reference workflow to the published baseline. Every step was run as shown here. The
conventions of the benchmark are in its card,
[`benchmarks/gis_correctness/README.md`](../benchmarks/gis_correctness/README.md).

### 1. Add the operation to the reference workflow

In `benchmarks/gis_correctness/reference.py`, add a function and an `OPERATIONS` entry. The
function gets the case `inputs` and the benchmark directory, and returns an output in the
benchmark's output contract. A request that it cannot answer raises `Abstain`.

```python
AREA_UNITS_IN_M2 = {"m2": 1.0, "ha": 1e4, "km2": 1e6}


def area(inputs: Mapping[str, Any], benchmark_dir: Path) -> dict[str, Any]:
    """Geodesic area on the WGS 84 ellipsoid of the polygon ``feature`` of ``files.layer``
    (found by the property ``key``), in ``units``. A missing feature is ``insufficient_data``."""
    params = inputs["params"]
    features = _read_features(benchmark_dir / inputs["files"]["layer"])
    by_key = {feature["properties"].get(params["key"]): feature for feature in features}
    if params["feature"] not in by_key:
        raise Abstain("insufficient_data", "the requested feature is not in the layer")
    polygon = shape(by_key[params["feature"]]["geometry"])
    square_meters, _ = Geod(ellps="WGS84").geometry_area_perimeter(polygon)
    units = params["units"]
    value = abs(square_meters) / AREA_UNITS_IN_M2[units]
    return {"status": "ok", "value": value, "units": units, "crs": GEOJSON_CRS}


OPERATIONS: dict[str, Callable[[Mapping[str, Any], Path], dict[str, Any]]] = {
    ...
    "overlay": overlay,
    "area": area,
    "abstention": abstention,
}
```

### 2. Teach the baseline adapter the operation

In `src/geoevals/adapters/gis_baseline.py`, add the same operation, written with GeoPandas,
and add it to that module's `OPERATIONS`. The adapter is a separate implementation: it does
not import `reference.py`. If the operation gets an abstention guard, add it to both modules.

```python
AREA_UNITS_IN_M2 = {"m2": 1.0, "ha": 1e4, "km2": 1e6}


def area(inputs: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Geodesic area of the polygon ``feature`` of ``files.layer`` (matched on the property
    ``key``) on the layer CRS's ellipsoid, in ``units``. A missing feature is
    ``insufficient_data``."""
    params = inputs["params"]
    frame = _read(inputs, "layer", base)
    if params["key"] not in frame.columns or params["feature"] not in set(frame[params["key"]]):
        raise Abstain("insufficient_data", "the requested feature is not in the layer")
    geod = CRS.from_user_input(frame.crs).get_geod()
    assert geod is not None, "a geodesic area needs a CRS with an ellipsoid"
    polygon = frame.set_index(params["key"]).geometry[params["feature"]]
    square_meters, _ = geod.geometry_area_perimeter(polygon)
    units = params["units"]
    value = abs(square_meters) / AREA_UNITS_IN_M2[units]
    return {"status": "ok", "value": value, "units": units, "crs": GEOJSON_CRS}
```

### 3. Write the case

Create `benchmarks/gis_correctness/cases/area.jsonl`. It uses an existing fixture, so the
manifest does not change. A new fixture would need a manifest entry with its SHA-256. The
`expected` is a placeholder; the reference workflow fills it in. The case states both value
tolerances in explicit units, because the spec scores both `value_abs_error` and
`value_rel_error` and a missing tolerance means an exact match.

```json
{"case_id": "area-001", "operation": "area", "split": "test", "prompt": "What is the area of parcel a1 on the WGS 84 ellipsoid, in hectares?", "inputs": {"files": {"layer": "fixtures/overlay_parcels.geojson"}, "params": {"key": "parcel_id", "feature": "a1", "units": "ha"}}, "expected": {}, "tolerances": {"abs_tol": {"value": 0.0001, "units": "ha"}, "rel_tol": {"value": 1e-06, "units": "ratio"}}, "strata": {"operation": "area", "trap": false}}
```

### 4. Add the case file to the spec and bump the version

In `benchmarks/gis_correctness/benchmark.yaml`, add `cases/area.jsonl` to `cases`. New cases
change the benchmark's scores, so bump `version` from `0.1.0` to `0.2.0` (see the
[version rules](reproducibility.md#version-rules)). Then validate the spec:

```sh
uv run geoevals validate benchmarks/gis_correctness/benchmark.yaml
```

```text
benchmarks/gis_correctness/benchmark.yaml: valid benchmark spec
```

### 5. Regenerate the expected outputs

```sh
uv run geoevals bench regenerate gis_correctness
PROJ_NETWORK=OFF uv run geoevals bench regenerate gis_correctness --check
```

```text
benchmarks/gis_correctness/cases/area.jsonl: written
benchmarks/gis_correctness: expected outputs are up to date
```

The case line now has its expected output:

```json
"expected": {"status": "ok", "value": 302.205350241852, "units": "ha", "crs": "OGC:CRS84"}
```

The `--check` run with `PROJ_NETWORK=OFF` confirms that the result does not depend on PROJ
downloading a grid, which CI cannot do.

### 6. Run the benchmark

```sh
uv run geoevals run --benchmark benchmarks/gis_correctness/benchmark.yaml \
  --adapter gis_baseline --config baselines/gis_correctness/gis_baseline/config.yaml \
  --out runs/area --report
```

The run now has 57 cases. In the report's breakdown by `operation`, the row `area` shows one
case that passes `task_success`. The baseline answered `302.2053502418518` ha against the
reference `302.205350241852` ha, an absolute error of about 1.7e-13 ha, far inside the
0.0001 ha tolerance.

### 7. Test that a wrong answer fails

A benchmark must show that a wrong answer fails. Add a test to
`tests/test_gis_correctness.py`, with the helpers that the file already has:

```python
def test_area_in_the_wrong_units_fails() -> None:
    [case] = _cases_of("area")
    expected = case["expected"]
    wrong = {**expected, "value": expected["value"] * 1e4}  # square meters labeled hectares
    assert _task_success(expected, "area-001")["value"] == 1.0
    assert _task_success(wrong, "area-001")["value"] == 0.0
```

Also change the version that `test_spec_validates_with_id_and_version` expects from `0.1.0`
to `0.2.0`.

### 8. Republish the baseline

The published baseline no longer matches: `geoevals reproduce` reports
`area-001: only in run b` and the changed counts. That is expected, and
`tests/test_reproduce.py` fails until you republish:

```sh
uv run geoevals run --benchmark benchmarks/gis_correctness/benchmark.yaml \
  --adapter gis_baseline --config baselines/gis_correctness/gis_baseline/config.yaml --out runs/baseline
run_dir=$(ls -d runs/baseline/*/ | tail -1)
cp "$run_dir"/{result.json,cases.jsonl,config.yaml} baselines/gis_correctness/gis_baseline/
uv run geoevals report baselines/gis_correctness/gis_baseline
rm baselines/gis_correctness/gis_baseline/report.html
uv run geoevals reproduce baselines/gis_correctness/gis_baseline
```

```text
reproduced: 57 case(s), no differences
```

### 9. Update the documentation and run the quality gates

Update the benchmark card: the version, the case counts, the operations table and the
tolerances table. Then run the quality gates:

```sh
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

## Definition of done

A benchmark is done when every item below holds. The right column says where GeoEvals checks
it or where to show it.

| | Requirement | Where it is checked or shown |
| --- | --- | --- |
| ☐ | A written task statement specifies the intended capability and intended use. | `task_statement`, `intended_use` in the spec (required by the schema); the card's Purpose section |
| ☐ | Inputs, outputs, spatial and temporal scope, and required metadata are machine-readable. | `input_schema`, `output_schema`; `crs`, `bbox`, `time_range` in the manifest; `geoevals validate` |
| ☐ | Dataset source, license, provenance, version and known limitations are documented. | The dataset manifest; `provenance` and `limitations` in the spec; the card; `geoevals data verify` |
| ☐ | The train, dev and test split strategy and the leakage controls are explained. | `splits` in the spec; the card |
| ☐ | Metrics include formulas or unambiguous implementation references, units, tolerances and aggregation. | [`metrics.md`](metrics.md); tolerances with units in the spec or cases |
| ☐ | A baseline and an executable evaluation path are available. | `reference.py`, a registered adapter, a published baseline in `baselines/` |
| ☐ | Tests cover ordinary cases, boundary cases, malformed outputs and missing data. | Tests under `tests/`; abstention cases in the benchmark |
| ☐ | A report exposes per-case failures, subgroup or region breakdowns where appropriate, uncertainty and cost. | `geoevals report`; case `strata` |
| ☐ | Reproduction instructions work from a clean environment. | The card's reproduction section; `geoevals reproduce` in CI |
| ☐ | Maintainer review confirms that the claims are supported by the data and the evaluation design. | Pull request review |
