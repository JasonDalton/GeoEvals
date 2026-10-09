"""Validate benchmark specs, dataset manifests, and run results against their JSON Schemas.

Benchmark specs are also checked against the metric registry. Dataset manifests are also checked
for duplicate asset IDs and for restricted assets placed where git could commit them. Run results
are also checked for duplicate case IDs and for case metrics without a versioned summary entry.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from geoevals.metrics.registry import registered_metric_ids
from geoevals.validation.benchmark import BenchmarkSpec
from geoevals.validation.git import GitPathState, git_path_state
from geoevals.validation.manifest import DatasetManifest
from geoevals.validation.run_result import RunResult

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
    if error.validator == "anyOf" and "description" in schema:
        return schema["description"]
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


# --- dataset manifests -----------------------------------------------------------------------


def load_manifest_document(path: Path) -> tuple[Any, list[ValidationIssue]]:
    """Parse a YAML or JSONL manifest into one document. Returns ``(document, parse_issues)``.

    In a JSONL manifest the first line holds every top-level field except ``assets`` and each
    later line holds one asset.
    """
    if path.suffix != ".jsonl":
        try:
            return load_yaml(path), []
        except yaml.YAMLError as exc:
            return None, [ValidationIssue("<root>", f"invalid YAML: {exc}")]
    records: list[Any] = []
    issues: list[ValidationIssue] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            issues.append(ValidationIssue(f"line {number}", f"invalid JSON: {exc}"))
    if issues:
        return None, issues
    if not records:
        return None, [ValidationIssue("<root>", "empty JSONL manifest")]
    header, assets = records[0], records[1:]
    if not isinstance(header, dict):
        return None, [ValidationIssue("line 1", "header line must be a JSON object")]
    if "assets" in header:
        return None, [ValidationIssue("line 1", "header line must not contain 'assets'")]
    return {**header, "assets": assets}, []


def _restricted_asset_issues(document: Any, base_dir: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for i, asset in enumerate(document["assets"]):
        if asset["redistributable"]:
            continue
        state = git_path_state(base_dir / asset["path"])
        if state is GitPathState.TRACKED:
            problem = "is tracked in git"
            fix = "untrack it with `git rm --cached` and keep it in a gitignored path"
        elif state is GitPathState.UNIGNORED:
            problem = "is inside the git working tree and not gitignored"
            fix = "move it to a gitignored path"
        else:
            continue
        issues.append(
            ValidationIssue(
                f"assets[{i}].path",
                f"asset {asset['asset_id']!r} has redistributable: false but its path "
                f"{asset['path']!r} {problem}; restricted data must be referenced, not "
                f"committed ({fix} such as data/raw/)",
            )
        )
    return issues


def validate_manifest_document(
    document: Any, base_dir: Path | None = None
) -> list[ValidationIssue]:
    """Validate a parsed dataset manifest. Returns an empty list when the manifest is valid.

    When ``base_dir`` (the manifest's directory) is given, assets with ``redistributable: false``
    must not be tracked in git or sit in a path git would commit.
    """
    issues = schema_issues(document, "dataset-manifest.schema.json")
    if issues:
        return issues
    first_index: dict[str, int] = {}
    for i, asset in enumerate(document["assets"]):
        asset_id = asset["asset_id"]
        if asset_id in first_index:
            issues.append(
                ValidationIssue(
                    f"assets[{i}].asset_id",
                    f"duplicate asset_id {asset_id!r} "
                    f"(first used by assets[{first_index[asset_id]}])",
                )
            )
        first_index.setdefault(asset_id, i)
    if base_dir is not None:
        issues.extend(_restricted_asset_issues(document, base_dir))
    return issues


def validate_manifest_file(path: Path, check_git: bool = True) -> list[ValidationIssue]:
    """Load a YAML or JSONL dataset manifest and validate it.

    ``check_git`` enables the check that restricted assets are not committable.
    """
    document, issues = load_manifest_document(path)
    if issues:
        return issues
    return validate_manifest_document(document, path.parent if check_git else None)


def load_dataset_manifest(path: Path, check_git: bool = True) -> DatasetManifest:
    """Load and validate a dataset manifest. Raises ``SpecValidationError`` if it is invalid."""
    issues = validate_manifest_file(path, check_git)
    if issues:
        raise SpecValidationError(path, issues)
    document, _ = load_manifest_document(path)
    return DatasetManifest.model_validate(document)


# --- run results -----------------------------------------------------------------------------


def validate_run_result_document(document: Any) -> list[ValidationIssue]:
    """Validate a parsed run result. Returns an empty list when the run result is valid."""
    issues = schema_issues(document, "run-result.schema.json")
    if issues:
        return issues
    first_index: dict[str, int] = {}
    for i, case in enumerate(document["cases"]):
        case_id = case["case_id"]
        if case_id in first_index:
            issues.append(
                ValidationIssue(
                    f"cases[{i}].case_id",
                    f"duplicate case_id {case_id!r} (first used by cases[{first_index[case_id]}])",
                )
            )
        first_index.setdefault(case_id, i)
        # summary_metrics records each metric's version, so every scored metric needs an entry.
        for metric_id in case["metrics"]:
            if metric_id not in document["summary_metrics"]:
                issues.append(
                    ValidationIssue(
                        f"cases[{i}].metrics.{metric_id}",
                        f"metric {metric_id!r} has no summary_metrics entry recording its version",
                    )
                )
    return issues


def _load_json(path: Path) -> tuple[Any, list[ValidationIssue]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except json.JSONDecodeError as exc:
        return None, [ValidationIssue("<root>", f"invalid JSON: {exc}")]


def validate_run_result_file(path: Path) -> list[ValidationIssue]:
    """Load a run result (``<run-dir>/result.json``) and validate it."""
    document, issues = _load_json(path)
    if issues:
        return issues
    return validate_run_result_document(document)


def load_run_result(path: Path) -> RunResult:
    """Load and validate a run result. Raises ``SpecValidationError`` if it is invalid."""
    issues = validate_run_result_file(path)
    if issues:
        raise SpecValidationError(path, issues)
    document, _ = _load_json(path)
    return RunResult.model_validate(document)


# --- document type dispatch ------------------------------------------------------------------

DocumentType = Literal["benchmark spec", "dataset manifest", "run result"]


def detect_document_type(path: Path) -> DocumentType:
    """Guess the document type.

    ``result.json`` files and mappings with ``run_id`` are run results, JSONL files and mappings
    with ``assets`` are dataset manifests, and anything else is a benchmark spec.
    """
    if path.name == "result.json":
        return "run result"
    if path.suffix == ".jsonl":
        return "dataset manifest"
    try:
        document = load_yaml(path)
    except yaml.YAMLError:
        return "benchmark spec"
    if isinstance(document, dict) and "assets" in document:
        return "dataset manifest"
    if isinstance(document, dict) and "run_id" in document:
        return "run result"
    return "benchmark spec"


def validate_file(path: Path) -> tuple[DocumentType, list[ValidationIssue]]:
    """Detect the document type of ``path`` and validate it."""
    kind = detect_document_type(path)
    if kind == "dataset manifest":
        return kind, validate_manifest_file(path)
    if kind == "run result":
        return kind, validate_run_result_file(path)
    return kind, validate_benchmark_file(path)
