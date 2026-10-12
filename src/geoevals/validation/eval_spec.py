"""Pydantic v2 model mirroring ``schemas/eval-spec.schema.json`` (graded eval specs).

Keep the model and the JSON Schema in step: ``tests/test_graded_spec.py`` asserts that both
reject the same documents.
"""

from typing import Annotated, Literal

from pydantic import Field

from geoevals.validation.benchmark import (
    Identifier,
    NonEmptyStr,
    Provenance,
    SemVer,
    _SchemaModel,
)

EVAL_SCHEMA_VERSION = "1.0.0"


class EvalSpec(_SchemaModel):
    schema_version: Literal["1.0.0"]
    id: Identifier
    version: SemVer
    title: NonEmptyStr
    concept: NonEmptyStr
    task_statement: NonEmptyStr
    intended_use: NonEmptyStr
    tasks: NonEmptyStr
    rubric_criteria: NonEmptyStr
    reference: NonEmptyStr
    dataset_manifest: NonEmptyStr
    answer_word_limit: Annotated[int, Field(ge=1)]
    license: NonEmptyStr
    provenance: Provenance
    limitations: Annotated[list[NonEmptyStr], Field(min_length=1)]
