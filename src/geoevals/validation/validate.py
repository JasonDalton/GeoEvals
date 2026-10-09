"""Validate benchmark spec files against the JSON Schema and the metric registry."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from geoevals.metrics.registry import registered_metric_ids
from geoevals.validation.benchmark import BenchmarkSpec

_PACKAGED_SCHEMAS = Path(__file__).resolve().parent.parent / "_schemas"
_REPO_SCHEMAS = Path(__file__).resolve().parents[3] / "schemas"


@dataclass(frozen=True)
class ValidationIssue:
    """One field-level validation failure."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


class SpecValidationError(ValueError):
    """Raised when a spec file fails validation; ``issues`` lists every failure."""

    def __init__(self, path: Path, issues: list[ValidationIssue]) -> None:
        self.path = path
        self.issues = issues
        super().__init__("\n".join(f"{path}: {issue}" for issue in issues))


class _SpecLoader(yaml.SafeLoader):
    """SafeLoader that keeps unquoted dates (``2026-10-09``) as strings, as JSON would."""


_SpecLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.load(f, Loader=_SpecLoader)  # _SpecLoader is a SafeLoader


@cache
def load_schema(name: str) -> dict[str, Any]:
    """Load a JSON Schema by file name from the installed package or the source checkout."""
    for directory in (_PACKAGED_SCHEMAS, _REPO_SCHEMAS):
        path = directory / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"schema {name!r} not found in {_PACKAGED_SCHEMAS} or {_REPO_SCHEMAS}")


def _field_path(parts: Iterable[str | int]) -> str:
    path = "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in parts)
    return path.lstrip(".") or "<root>"


def _describe(error: ValidationError) -> str:
    schema = error.schema if isinstance(error.schema, dict) else {}
    if error.validator == "pattern" and "description" in schema:
        return f"{error.instance!r} is not a valid {schema['description']}"
    return error.message


def schema_issues(document: Any, schema_name: str) -> list[ValidationIssue]:
    """Return JSON Schema violations of ``document``, sorted by field path."""
    validator = Draft202012Validator(load_schema(schema_name))
    issues = [
        ValidationIssue(_field_path(error.absolute_path), _describe(error))
        for error in validator.iter_errors(document)
    ]
    return sorted(issues, key=lambda issue: (issue.field, issue.message))


def validate_benchmark_document(
    document: Any, known_metric_ids: Iterable[str] | None = None
) -> list[ValidationIssue]:
    """Validate a parsed benchmark spec. Returns an empty list when the spec is valid.

    ``known_metric_ids`` defaults to the IDs in the metric registry.
    """
    issues = schema_issues(document, "benchmark.schema.json")
    if issues:
        return issues
    known = set(registered_metric_ids() if known_metric_ids is None else known_metric_ids)
    for i, metric in enumerate(document["metrics"]):
        if metric["id"] not in known:
            issues.append(
                ValidationIssue(
                    f"metrics[{i}].id",
                    f"metric {metric['id']!r} is not registered "
                    f"(registered: {', '.join(sorted(known)) or 'none'})",
                )
            )
    return issues


def validate_benchmark_file(
    path: Path, known_metric_ids: Iterable[str] | None = None
) -> list[ValidationIssue]:
    """Load a YAML benchmark spec and validate it."""
    try:
        document = load_yaml(path)
    except yaml.YAMLError as exc:
        return [ValidationIssue("<root>", f"invalid YAML: {exc}")]
    return validate_benchmark_document(document, known_metric_ids)


def load_benchmark_spec(path: Path, known_metric_ids: Iterable[str] | None = None) -> BenchmarkSpec:
    """Load and validate a YAML benchmark spec. Raises ``SpecValidationError`` if it is invalid."""
    issues = validate_benchmark_file(path, known_metric_ids)
    if issues:
        raise SpecValidationError(path, issues)
    return BenchmarkSpec.model_validate(load_yaml(path))
