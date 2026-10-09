"""Pydantic v2 models mirroring ``schemas/run-result.schema.json``.

Keep these models and the JSON Schema in step: ``tests/test_run_result.py`` asserts that both
accept and reject the same documents.
"""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from geoevals.validation.benchmark import (
    DATE_PATTERN,
    Identifier,
    NonEmptyStr,
    SemVer,
    _SchemaModel,
)
from geoevals.validation.manifest import SHA256_PATTERN

RUN_RESULT_SCHEMA_VERSION = "1.0.0"

TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)

CaseStatus = Literal["scored", "adapter_error", "timeout", "invalid_output", "skipped"]
FailureStatus = Literal["adapter_error", "timeout", "invalid_output", "skipped"]

Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
Timestamp = Annotated[str, Field(pattern=TIMESTAMP_PATTERN)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class BenchmarkRef(_SchemaModel):
    id: Identifier
    version: SemVer


class AdapterRef(_SchemaModel):
    name: NonEmptyStr
    version: NonEmptyStr
    config: dict[str, Any]


class CaseError(_SchemaModel):
    type: NonEmptyStr
    message: str


class MetricValue(_SchemaModel):
    value: float | None
    passed: bool | None
    detail: dict[str, Any]


class SummaryMetric(_SchemaModel):
    version: SemVer
    mean: float | None
    median: float | None
    n: NonNegativeInt
    n_failed: NonNegativeInt
    ci_low: float | None
    ci_high: float | None


class Efficiency(_SchemaModel):
    wall_clock_s: NonNegativeFloat | None = None
    cases_total: NonNegativeInt | None = None
    cases_per_s: NonNegativeFloat | None = None
    latency_p50_s: NonNegativeFloat | None = None
    latency_p90_s: NonNegativeFloat | None = None
    latency_p99_s: NonNegativeFloat | None = None
    latency_max_s: NonNegativeFloat | None = None
    timeout_rate: NonNegativeFloat | None = None
    failure_rate: NonNegativeFloat | None = None
    retries_total: NonNegativeInt | None = None
    peak_rss_bytes: NonNegativeInt | None = None
    tokens_input_total: NonNegativeInt | None = None
    tokens_output_total: NonNegativeInt | None = None
    cost_usd_total: NonNegativeFloat | None = None
    cost_usd_per_case: NonNegativeFloat | None = None
    price_table_hash: Sha256 | None = None
    tool_error_rate: NonNegativeFloat | None = None
    mean_steps: NonNegativeFloat | None = None


class Failure(_SchemaModel):
    case_id: NonEmptyStr
    status: FailureStatus
    error: CaseError | None


class Tokens(_SchemaModel):
    input: NonNegativeInt
    output: NonNegativeInt


class TrajectoryStep(_SchemaModel):
    step: NonNegativeInt
    tool: NonEmptyStr | None
    args: dict[str, Any]
    status: Literal["ok", "error"]
    error_message: str | None
    duration_s: NonNegativeFloat | None
    tokens: Tokens | None

    @model_validator(mode="after")
    def _error_message_matches_status(self) -> Self:
        if self.status == "error" and not self.error_message:
            raise ValueError("error_message must be a non-empty string when status is error")
        if self.status == "ok" and self.error_message is not None:
            raise ValueError("error_message must be null when status is ok")
        return self


class AgentSummary(_SchemaModel):
    tool_calls: NonNegativeInt
    tool_errors: NonNegativeInt
    agent_steps: NonNegativeInt
    agent_runtime_s: NonNegativeFloat | None


class CaseRecord(_SchemaModel):
    case_id: NonEmptyStr
    split: Identifier
    status: CaseStatus
    strata: dict[Identifier, str | float | bool]
    output: dict[str, Any] | None
    metrics: dict[Identifier, MetricValue]
    latency_s: NonNegativeFloat | None
    scoring_s: NonNegativeFloat | None
    retries: NonNegativeInt
    tokens: Tokens | None
    cost_usd: NonNegativeFloat | None
    peak_memory_bytes: NonNegativeInt | None
    memory_note: NonEmptyStr | None = None
    trajectory: list[TrajectoryStep] | None = None
    agent: AgentSummary | None = None
    error: CaseError | None

    @model_validator(mode="after")
    def _memory_note_explains_null(self) -> Self:
        if self.peak_memory_bytes is None and self.memory_note is None:
            raise ValueError("memory_note is required when peak_memory_bytes is null")
        if (self.trajectory is None) != (self.agent is None):
            raise ValueError("trajectory and agent must be given together")
        return self


class BenchmarkProvenance(_SchemaModel):
    license: NonEmptyStr
    authors: Annotated[list[NonEmptyStr], Field(min_length=1)]
    created: Annotated[str, Field(pattern=DATE_PATTERN)]
    reference_workflow: NonEmptyStr | None = None
    notes: NonEmptyStr | None = None


class AssetLicense(_SchemaModel):
    asset_id: Identifier
    license: NonEmptyStr
    attribution: NonEmptyStr
    redistributable: bool
    source_url: NonEmptyStr | None = None
    citation: NonEmptyStr | None = None


class DatasetProvenance(_SchemaModel):
    dataset_id: Identifier
    assets: list[AssetLicense]


class RunProvenance(_SchemaModel):
    benchmark: BenchmarkProvenance
    dataset: DatasetProvenance


class RunResult(_SchemaModel):
    run_id: NonEmptyStr
    schema_version: Literal["1.0.0"]
    benchmark: BenchmarkRef
    adapter: AdapterRef
    config_hash: Sha256
    dataset_manifest_hash: Sha256
    environment: dict[str, Any]
    started_at: Timestamp
    finished_at: Timestamp
    summary_metrics: dict[Identifier, SummaryMetric]
    efficiency: Efficiency
    failures: list[Failure]
    limitations: list[NonEmptyStr]
    provenance: RunProvenance | None = None
    cases: list[CaseRecord]
