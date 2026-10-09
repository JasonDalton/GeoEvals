import copy
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from geoevals.cli import main
from geoevals.metrics import registry
from geoevals.validation import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkSpec,
    SpecValidationError,
    load_benchmark_spec,
    validate_benchmark_document,
    validate_benchmark_file,
)
from geoevals.validation.validate import load_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "benchmark.schema.json"
VALID_SPEC = Path(__file__).parent / "fixtures" / "benchmarks" / "valid_benchmark.yaml"
KNOWN_METRICS = {"value_abs_error"}

Doc = dict[str, Any]


@pytest.fixture
def valid_doc() -> Doc:
    return load_yaml(VALID_SPEC)


@pytest.fixture
def registered_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {"value_abs_error": "1.0.0"})


def _write(tmp_path: Path, doc: Doc) -> Path:
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _fields(doc: Doc) -> dict[str, str]:
    return {i.field: i.message for i in validate_benchmark_document(doc, KNOWN_METRICS)}


# --- schema file ---------------------------------------------------------------------------


def test_schema_is_draft_2020_12_with_version() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["schema_version"] == "1.1.0" == BENCHMARK_SCHEMA_VERSION
    Draft202012Validator.check_schema(schema)


def test_schema_requires_story_fields() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    expected = {
        "id", "version", "title", "pillar", "task_statement", "intended_use", "input_schema",
        "output_schema", "cases", "splits", "metrics", "tolerances", "dataset_manifest",
        "license", "provenance", "limitations",
    }  # fmt: skip
    assert expected <= set(schema["required"])
    assert set(schema["$defs"]["metricRef"]["required"]) == {"id", "version", "params"}
    assert schema["properties"]["pillar"]["enum"] == [
        "perception",
        "spatial_reasoning",
        "human_context",
    ]


def test_model_and_schema_have_same_fields() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    model_fields = BenchmarkSpec.model_fields
    assert set(model_fields) == set(schema["properties"])
    assert {name for name, f in model_fields.items() if f.is_required()} == set(schema["required"])


# --- validation behavior ---------------------------------------------------------------------


def test_valid_spec(valid_doc: Doc) -> None:
    assert validate_benchmark_file(VALID_SPEC, KNOWN_METRICS) == []
    spec = load_benchmark_spec(VALID_SPEC, KNOWN_METRICS)
    assert spec.id == "example_distance"
    assert spec.provenance.created == "2026-10-09"  # unquoted YAML date stays a string
    assert spec.metrics[0].id == "value_abs_error"


def test_missing_required_field(valid_doc: Doc) -> None:
    del valid_doc["license"]
    assert _fields(valid_doc) == {"<root>": "'license' is a required property"}


def test_wrong_enum_value(valid_doc: Doc) -> None:
    valid_doc["pillar"] = "gis"
    issues = _fields(valid_doc)
    assert list(issues) == ["pillar"]
    assert (
        "'gis' is not one of ['perception', 'spatial_reasoning', 'human_context']"
        in (issues["pillar"])
    )


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "01.0.0", "1.0.0.0", "latest"])
def test_invalid_semver(valid_doc: Doc, version: str) -> None:
    valid_doc["version"] = version
    issues = _fields(valid_doc)
    assert list(issues) == ["version"]
    assert "not a valid semantic version" in issues["version"]


def test_invalid_metric_semver_names_nested_field(valid_doc: Doc) -> None:
    valid_doc["metrics"][0]["version"] = "1"
    assert list(_fields(valid_doc)) == ["metrics[0].version"]


def test_unregistered_metric_id(valid_doc: Doc) -> None:
    valid_doc["metrics"].append({"id": "made_up_metric", "version": "1.0.0", "params": {}})
    issues = _fields(valid_doc)
    assert list(issues) == ["metrics[1].id"]
    assert "'made_up_metric' is not registered" in issues["metrics[1].id"]


def test_unregistered_metric_uses_registry_by_default(
    valid_doc: Doc, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})
    assert [i.field for i in validate_benchmark_document(valid_doc)] == ["metrics[0].id"]


def test_load_benchmark_spec_raises_with_issues(tmp_path: Path, valid_doc: Doc) -> None:
    del valid_doc["title"]
    path = _write(tmp_path, valid_doc)
    with pytest.raises(SpecValidationError) as exc:
        load_benchmark_spec(path, KNOWN_METRICS)
    assert exc.value.issues[0].message == "'title' is a required property"


# --- evidence types (schema 1.1.0) -----------------------------------------------------------


def _human_context(doc: Doc) -> None:
    doc["pillar"] = "human_context"
    doc["output_schema"]["properties"] = {
        "status": {"enum": ["ok", "insufficient_data"], "evidence_type": "observed"},
        "travel_time_s": {"type": "number", "evidence_type": "proxy"},
    }


def test_evidence_type_is_optional_outside_human_context(valid_doc: Doc) -> None:
    assert _fields(valid_doc) == {}
    valid_doc["output_schema"]["properties"]["status"]["evidence_type"] = "judgment"
    assert _fields(valid_doc) == {}


def test_unknown_evidence_type(valid_doc: Doc) -> None:
    valid_doc["output_schema"]["properties"]["status"]["evidence_type"] = "measured"
    issues = _fields(valid_doc)
    assert list(issues) == ["output_schema.properties.status.evidence_type"]
    assert (
        "is not one of ['observed', 'proxy', 'judgment']"
        in issues["output_schema.properties.status.evidence_type"]
    )


def test_human_context_spec_with_evidence_types_is_valid(valid_doc: Doc) -> None:
    _human_context(valid_doc)
    assert _fields(valid_doc) == {}


def test_human_context_field_without_evidence_type_fails(valid_doc: Doc) -> None:
    _human_context(valid_doc)
    del valid_doc["output_schema"]["properties"]["travel_time_s"]["evidence_type"]
    assert _fields(valid_doc) == {
        "output_schema.properties.travel_time_s": "'evidence_type' is a required property"
    }


def test_human_context_spec_must_declare_output_fields(valid_doc: Doc) -> None:
    _human_context(valid_doc)
    del valid_doc["output_schema"]["properties"]
    assert _fields(valid_doc) == {"output_schema": "'properties' is a required property"}


def test_human_context_doc_example_is_valid(valid_doc: Doc) -> None:
    text = (REPO_ROOT / "docs" / "human-context.md").read_text(encoding="utf-8")
    [example] = re.findall(r"```yaml\n(.*?)```", text, flags=re.DOTALL)
    valid_doc.update(yaml.safe_load(example))
    assert valid_doc["pillar"] == "human_context"
    assert _fields(valid_doc) == {}


def test_old_schema_version_is_rejected(valid_doc: Doc) -> None:
    valid_doc["schema_version"] = "1.0.0"
    assert list(_fields(valid_doc)) == ["schema_version"]


def test_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "benchmark.yaml"
    path.write_text("id: [unclosed\n", encoding="utf-8")
    issues = validate_benchmark_file(path, KNOWN_METRICS)
    assert len(issues) == 1
    assert issues[0].message.startswith("invalid YAML")


# --- CLI -------------------------------------------------------------------------------------


@pytest.mark.usefixtures("registered_metric")
def test_cli_validate_valid(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(VALID_SPEC)]) == 0
    assert "valid benchmark spec" in capsys.readouterr().out


@pytest.mark.usefixtures("registered_metric")
@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.pop("cases"), "<root>: 'cases' is a required property"),
        (lambda d: d.update(pillar="gis"), "pillar: 'gis' is not one of"),
        (lambda d: d.update(version="1.0"), "version: '1.0' is not a valid semantic version"),
        (
            lambda d: d["metrics"][0].update(id="nope"),
            "metrics[0].id: metric 'nope' is not registered",
        ),
    ],
)
def test_cli_validate_invalid(
    tmp_path: Path,
    valid_doc: Doc,
    capsys: pytest.CaptureFixture[str],
    mutate: Callable[[Doc], object],
    expected: str,
) -> None:
    mutate(valid_doc)
    path = _write(tmp_path, valid_doc)
    assert main(["validate", str(path)]) == 1
    err = capsys.readouterr().err
    assert f"{path}: {expected}" in err


def test_cli_validate_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(tmp_path / "nope.yaml")]) == 1
    assert "file not found" in capsys.readouterr().err


# --- Pydantic model and JSON Schema agree ----------------------------------------------------


def _set(*path: str | int, value: Any) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        target: Any = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _delete(*path: str | int) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        target: Any = doc
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return mutate


def _then(*mutations: Callable[[Doc], None]) -> Callable[[Doc], None]:
    def mutate(doc: Doc) -> None:
        for mutation in mutations:
            mutation(doc)

    return mutate


AGREEMENT_CASES: dict[str, Callable[[Doc], None]] = {
    # documents both must accept
    "valid": lambda d: None,
    "cases_list": _set("cases", value=["cases/a.jsonl", "cases/b.jsonl"]),
    "prerelease_version": _set("version", value="1.0.0-rc.1+build.5"),
    "integer_tolerance": _set("tolerances", "distance", "value", value=1),
    "empty_tolerances": _set("tolerances", value={}),
    "optional_provenance": _set("provenance", "reference_workflow", value="reference.py"),
    "each_pillar": _set("pillar", value="perception"),
    "evidence_type": _set("output_schema", "properties", "status", "evidence_type", value="proxy"),
    "human_context_tagged": _human_context,
    "output_field_boolean": _set("output_schema", "properties", "extra", value=True),
    # documents both must reject
    "missing_id": _delete("id"),
    "missing_schema_version": _delete("schema_version"),
    "wrong_schema_version": _set("schema_version", value="2.0.0"),
    "old_schema_version": _set("schema_version", value="1.0.0"),
    "bad_evidence_type": _set("output_schema", "properties", "status", "evidence_type", value="x"),
    "output_properties_list": _set("output_schema", "properties", value=[]),
    "human_context_untagged": _set("pillar", value="human_context"),
    "human_context_no_fields": _then(_human_context, _delete("output_schema", "properties")),
    "human_context_empty_fields": _then(
        _human_context, _set("output_schema", "properties", value={})
    ),
    "human_context_boolean_field": _then(
        _human_context, _set("output_schema", "properties", "extra", value=True)
    ),
    "bad_pillar": _set("pillar", value="gis"),
    "bad_semver": _set("version", value="1.0"),
    "trailing_text_semver": _set("version", value="1.0.0 beta"),
    "numeric_version": _set("version", value=1.0),
    "bad_id": _set("id", value="Bad-ID"),
    "empty_title": _set("title", value=""),
    "extra_field": _set("unexpected", value=1),
    "cases_empty_list": _set("cases", value=[]),
    "cases_number": _set("cases", value=3),
    "splits_empty": _set("splits", value={}),
    "split_bad_name": _set("splits", value={"Test": {"description": "x"}}),
    "split_missing_description": _set("splits", "test", value={}),
    "metrics_empty": _set("metrics", value=[]),
    "metric_missing_params": _delete("metrics", 0, "params"),
    "metric_params_list": _set("metrics", 0, "params", value=[]),
    "metric_bad_version": _set("metrics", 0, "version", value="1"),
    "tolerance_negative": _set("tolerances", "distance", "value", value=-1),
    "tolerance_string": _set("tolerances", "distance", "value", value="0.01"),
    "tolerance_bool": _set("tolerances", "distance", "value", value=True),
    "tolerance_no_units": _delete("tolerances", "distance", "units"),
    "input_schema_string": _set("input_schema", value="schema.json"),
    "provenance_no_authors": _delete("provenance", "authors"),
    "provenance_bad_date": _set("provenance", "created", value="Oct 9 2026"),
    "limitations_empty": _set("limitations", value=[]),
    "limitations_string": _set("limitations", value="none"),
    "license_number": _set("license", value=1),
    "not_a_mapping": lambda d: d.clear(),
}

EXPECTED_VALID = {
    "valid",
    "cases_list",
    "prerelease_version",
    "integer_tolerance",
    "empty_tolerances",
    "optional_provenance",
    "each_pillar",
    "evidence_type",
    "human_context_tagged",
    "output_field_boolean",
}


@pytest.mark.parametrize("name", list(AGREEMENT_CASES))
def test_model_and_schema_agree(valid_doc: Doc, name: str) -> None:
    doc = copy.deepcopy(valid_doc)
    AGREEMENT_CASES[name](doc)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_ok = Draft202012Validator(schema).is_valid(doc)
    try:
        BenchmarkSpec.model_validate(doc)
        model_ok = True
    except ValidationError:
        model_ok = False
    assert schema_ok == model_ok, f"schema accepts={schema_ok}, model accepts={model_ok}"
    assert schema_ok == (name in EXPECTED_VALID)
