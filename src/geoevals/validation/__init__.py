"""GeoEvals validation package."""

from geoevals.validation.benchmark import BENCHMARK_SCHEMA_VERSION, BenchmarkSpec
from geoevals.validation.validate import (
    SpecValidationError,
    ValidationIssue,
    load_benchmark_spec,
    validate_benchmark_document,
    validate_benchmark_file,
)

__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "BenchmarkSpec",
    "SpecValidationError",
    "ValidationIssue",
    "load_benchmark_spec",
    "validate_benchmark_document",
    "validate_benchmark_file",
]
