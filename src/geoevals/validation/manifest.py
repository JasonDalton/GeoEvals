"""Pydantic v2 models mirroring ``schemas/dataset-manifest.schema.json``.

Keep these models and the JSON Schema in step: ``tests/test_dataset_manifest.py`` asserts that
both accept and reject the same documents.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from geoevals.validation.benchmark import DATE_PATTERN, Identifier, NonEmptyStr, _SchemaModel

MANIFEST_SCHEMA_VERSION = "1.0.0"

SHA256_PATTERN = r"^[0-9a-f]{64}$"
URL_PATTERN = r"^[a-zA-Z][a-zA-Z0-9+.-]*://\S+$"

Date = Annotated[str, Field(pattern=DATE_PATTERN)]


class TimeRange(_SchemaModel):
    start: Date
    end: Date


class Asset(_SchemaModel):
    asset_id: Identifier
    path: NonEmptyStr
    source_url: Annotated[str, Field(pattern=URL_PATTERN)] | None = None
    citation: NonEmptyStr | None = None
    access_date: Date
    license: NonEmptyStr
    attribution: NonEmptyStr
    redistributable: bool
    sha256: Annotated[str, Field(pattern=SHA256_PATTERN)]
    crs: NonEmptyStr
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)]
    time_range: TimeRange
    processing_steps: list[NonEmptyStr]
    split: Identifier
    known_limitations: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def _has_source(self) -> Self:
        if self.source_url is None and self.citation is None:
            raise ValueError("asset needs at least one of 'source_url' or 'citation'")
        return self


class DatasetManifest(_SchemaModel):
    schema_version: Literal["1.0.0"]
    dataset_id: Identifier
    description: NonEmptyStr | None = None
    assets: Annotated[list[Asset], Field(min_length=1)]
