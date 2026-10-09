"""Pydantic v2 models mirroring ``schemas/benchmark.schema.json``.

Keep these models and the JSON Schema in step: ``tests/test_benchmark_validation.py`` asserts
that both accept and reject the same documents.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BENCHMARK_SCHEMA_VERSION = "1.1.0"

SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-((0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)(\.(0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(\+([0-9a-zA-Z-]+(\.[0-9a-zA-Z-]+)*))?$"
)
IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]*$"
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"

NonEmptyStr = Annotated[str, Field(min_length=1)]
Identifier = Annotated[str, Field(pattern=IDENTIFIER_PATTERN)]
SemVer = Annotated[str, Field(pattern=SEMVER_PATTERN)]
Pillar = Literal["perception", "spatial_reasoning", "human_context"]
EvidenceType = Literal["observed", "proxy", "judgment"]
EVIDENCE_TYPES: tuple[EvidenceType, ...] = ("observed", "proxy", "judgment")


class _SchemaModel(BaseModel):
    # strict: no type coercion, so the model rejects what the JSON Schema rejects.
    # python-re: same regex engine (and `$` semantics) as the jsonschema library.
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, regex_engine="python-re")


class Split(_SchemaModel):
    description: NonEmptyStr


class MetricRef(_SchemaModel):
    id: Identifier
    version: SemVer
    params: dict[str, Any]


class Tolerance(_SchemaModel):
    value: Annotated[float, Field(ge=0)]
    units: NonEmptyStr


class Provenance(_SchemaModel):
    authors: Annotated[list[NonEmptyStr], Field(min_length=1)]
    created: Annotated[str, Field(pattern=DATE_PATTERN)]
    reference_workflow: NonEmptyStr | None = None
    notes: NonEmptyStr | None = None


class BenchmarkSpec(_SchemaModel):
    schema_version: Literal["1.1.0"]
    id: Identifier
    version: SemVer
    title: NonEmptyStr
    pillar: Pillar
    task_statement: NonEmptyStr
    intended_use: NonEmptyStr
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    cases: NonEmptyStr | Annotated[list[NonEmptyStr], Field(min_length=1)]
    splits: Annotated[dict[Identifier, Split], Field(min_length=1)]
    metrics: Annotated[list[MetricRef], Field(min_length=1)]
    tolerances: dict[Identifier, Tolerance]
    dataset_manifest: NonEmptyStr
    license: NonEmptyStr
    provenance: Provenance
    limitations: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def _check_output_fields(self) -> "BenchmarkSpec":
        """Mirror the schema's ``evidence_type`` rules for ``output_schema.properties``."""
        fields = self.output_schema.get("properties", {})
        if not isinstance(fields, dict):
            raise ValueError("output_schema.properties must be an object")
        human_context = self.pillar == "human_context"
        if human_context and not fields:
            raise ValueError("a human_context output_schema must declare its output fields")
        for name, field in fields.items():
            if not isinstance(field, dict) or "evidence_type" not in field:
                if human_context:
                    raise ValueError(f"human_context output field {name!r} has no evidence_type")
            elif field["evidence_type"] not in EVIDENCE_TYPES:
                raise ValueError(f"output field {name!r} has an invalid evidence_type")
        return self
