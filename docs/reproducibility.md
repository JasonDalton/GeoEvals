# Reproducibility

## Schema versions

GeoEvals has three versioned JSON Schemas in `schemas/`. Every document states the schema
version it targets in `schema_version`, and `geoevals validate` accepts only the current
version.

| Schema | Current version |
| --- | --- |
| `benchmark.schema.json` (benchmark spec) | 1.1.0 |
| `dataset-manifest.schema.json` (dataset manifest) | 1.0.0 |
| `run-result.schema.json` (run result) | 1.0.0 |

## Migration notes

### Benchmark spec 1.0.0 → 1.1.0

What changed:

- An output field in `output_schema.properties` may carry `evidence_type`: `observed`,
  `proxy` or `judgment`. See [`human-context.md`](human-context.md#evidence-types).
- A spec with `pillar: human_context` must list its output fields in
  `output_schema.properties`, and every field must have an `evidence_type`.

To migrate a 1.0.0 spec:

1. Change `schema_version: "1.0.0"` to `schema_version: "1.1.0"`.
2. For a `human_context` spec, add `evidence_type` to every field in
   `output_schema.properties`.
3. Run `geoevals validate <benchmark.yaml>`.

No other field changed, so a `spatial_reasoning` or `perception` spec needs only step 1.
The change does not affect scoring: run results and published baselines stay the same.
