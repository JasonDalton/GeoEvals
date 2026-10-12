"""GeoEvals validation package."""

from geoevals.validation.benchmark import BENCHMARK_SCHEMA_VERSION, BenchmarkSpec
from geoevals.validation.eval_spec import EVAL_SCHEMA_VERSION, EvalSpec
from geoevals.validation.manifest import MANIFEST_SCHEMA_VERSION, Asset, DatasetManifest
from geoevals.validation.run_result import (
    RUN_RESULT_SCHEMA_VERSION,
    CaseRecord,
    CaseStatus,
    RunResult,
)
from geoevals.validation.validate import (
    SpecValidationError,
    ValidationIssue,
    detect_document_type,
    load_benchmark_spec,
    load_dataset_manifest,
    load_eval_spec,
    load_run_result,
    validate_benchmark_document,
    validate_benchmark_file,
    validate_eval_document,
    validate_eval_file,
    validate_file,
    validate_manifest_document,
    validate_manifest_file,
    validate_run_result_document,
    validate_run_result_file,
)

__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "EVAL_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "RUN_RESULT_SCHEMA_VERSION",
    "Asset",
    "BenchmarkSpec",
    "CaseRecord",
    "CaseStatus",
    "DatasetManifest",
    "EvalSpec",
    "RunResult",
    "SpecValidationError",
    "ValidationIssue",
    "detect_document_type",
    "load_benchmark_spec",
    "load_dataset_manifest",
    "load_eval_spec",
    "load_run_result",
    "validate_benchmark_document",
    "validate_benchmark_file",
    "validate_eval_document",
    "validate_eval_file",
    "validate_file",
    "validate_manifest_document",
    "validate_manifest_file",
    "validate_run_result_document",
    "validate_run_result_file",
]
