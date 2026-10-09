"""GeoEvals validation package."""

from geoevals.validation.benchmark import BENCHMARK_SCHEMA_VERSION, BenchmarkSpec
from geoevals.validation.manifest import MANIFEST_SCHEMA_VERSION, Asset, DatasetManifest
from geoevals.validation.validate import (
    SpecValidationError,
    ValidationIssue,
    detect_document_type,
    load_benchmark_spec,
    load_dataset_manifest,
    validate_benchmark_document,
    validate_benchmark_file,
    validate_file,
    validate_manifest_document,
    validate_manifest_file,
)

__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "Asset",
    "BenchmarkSpec",
    "DatasetManifest",
    "SpecValidationError",
    "ValidationIssue",
    "detect_document_type",
    "load_benchmark_spec",
    "load_dataset_manifest",
    "validate_benchmark_document",
    "validate_benchmark_file",
    "validate_file",
    "validate_manifest_document",
    "validate_manifest_file",
]
