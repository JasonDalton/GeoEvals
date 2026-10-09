import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from geoevals.cli import main
from geoevals.validation import (
    RUN_RESULT_SCHEMA_VERSION,
    CaseRecord,
    RunResult,
    SpecValidationError,
    detect_document_type,
    load_run_result,
    validate_run_result_document,
    validate_run_result_file,
)
from geoevals.validation.run_result import Efficiency

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "run-result.schema.json"
EXAMPLE = Path(__file__).parent / "fixtures" / "run_results" / "example_run" / "result.json"

Doc = dict[str, Any]


@pytest.fixture
def valid_doc() -> Doc:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _schema() -> Doc:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _write(directory: Path, doc: Doc) -> Path:
    run_dir = directory / "run"
    run_dir.mkdir()
    path = run_dir / "result.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _fields(doc: Doc) -> dict[str, str]:
    return {i.field: i.message for i in validate_run_result_document(doc)}


# --- schema file ---------------------------------------------------------------------------


def test_schema_is_draft_2020_12_with_version() -> None:
    schema = _schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["schema_version"] == "1.0.0" == RUN_RESULT_SCHEMA_VERSION
    Draft202012Validator.check_schema(schema)


def test_schema_requires_story_fields() -> None:
    schema = _schema()
    run_fields = {
        "run_id", "schema_version", "benchmark", "adapter", "config_hash",
        "dataset_manifest_hash", "environment", "started_at", "finished_at", "summary_metrics",
        "efficiency", "failures", "limitations",
    }  # fmt: skip
    assert run_fields <= set(schema["required"])
    assert set(schema["properties"]["benchmark"]["required"]) == {"id", "version"}
    assert set(schema["properties"]["adapter"]["required"]) == {"name", "version", "config"}

    case = schema["$defs"]["caseRecord"]
    case_fields = {
        "case_id", "split", "status", "strata", "output", "metrics", "latency_s", "retries",
        "tokens", "cost_usd", "peak_memory_bytes", "error",
    }  # fmt: skip
    assert case_fields <= set(case["required"])
    assert {"memory_note", "trajectory"} <= set(case["properties"])
    assert schema["$defs"]["status"]["enum"] == [
        "scored", "adapter_error", "timeout", "invalid_output", "skipped",
    ]  # fmt: skip
    assert set(schema["$defs"]["tokens"]["required"]) == {"input", "output"}
    assert set(schema["$defs"]["error"]["required"]) == {"type", "message"}


def test_model_and_schema_have_same_fields() -> None:
    schema = _schema()
    assert set(RunResult.model_fields) == set(schema["properties"])
    required = {name for name, f in RunResult.model_fields.items() if f.is_required()}
    assert required == set(schema["required"])
    case = schema["$defs"]["caseRecord"]
    assert set(CaseRecord.model_fields) == set(case["properties"])
    required = {name for name, f in CaseRecord.model_fields.items() if f.is_required()}
    assert required == set(case["required"])
    assert set(Efficiency.model_fields) == set(schema["$defs"]["efficiency"]["properties"])


# --- validation behavior ---------------------------------------------------------------------


def test_valid_example_run_result() -> None:
    assert validate_run_result_file(EXAMPLE) == []
    result = load_run_result(EXAMPLE)
    assert result.benchmark.id == "example_distance"
    assert [c.status for c in result.cases] == ["scored", "scored", "adapter_error", "timeout"]
    assert result.cases[0].strata == {
        "crs_family": "projected",
        "operation": "distance",
        "region": "europe",
    }
    assert result.cases[3].strata["trap"] is True
    assert result.cases[2].error is not None
    assert result.cases[2].error.type == "RuntimeError"


def test_unknown_status_rejected(valid_doc: Doc) -> None:
    valid_doc["cases"][0]["status"] = "crashed"
    assert _fields(valid_doc) == {
        "cases[0].status": "'crashed' is not one of "
        "['scored', 'adapter_error', 'timeout', 'invalid_output', 'skipped']"
    }
    with pytest.raises(ValidationError):
        RunResult.model_validate(valid_doc)


def test_load_run_result_raises_on_unknown_status(tmp_path: Path, valid_doc: Doc) -> None:
    valid_doc["cases"][1]["status"] = "crashed"
    path = _write(tmp_path, valid_doc)
    with pytest.raises(SpecValidationError) as excinfo:
        load_run_result(path)
    assert [i.field for i in excinfo.value.issues] == ["cases[1].status"]


def test_failure_status_cannot_be_scored(valid_doc: Doc) -> None:
    valid_doc["failures"][0]["status"] = "scored"
    assert list(_fields(valid_doc)) == ["failures[0].status"]


def test_memory_note_required_when_memory_is_null(valid_doc: Doc) -> None:
    del valid_doc["cases"][2]["memory_note"]
    assert _fields(valid_doc) == {"cases[2]": "'memory_note' is a required property"}


def test_duplicate_case_id(valid_doc: Doc) -> None:
    valid_doc["cases"][1]["case_id"] = "dist_001"
    assert _fields(valid_doc) == {
        "cases[1].case_id": "duplicate case_id 'dist_001' (first used by cases[0])"
    }


def test_case_metric_needs_versioned_summary_entry(valid_doc: Doc) -> None:
    del valid_doc["summary_metrics"]["value_abs_error"]
    assert _fields(valid_doc) == {
        f"cases[{i}].metrics.value_abs_error": (
            "metric 'value_abs_error' has no summary_metrics entry recording its version"
        )
        for i in (0, 1)
    }


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text("{not json", encoding="utf-8")
    issues = validate_run_result_file(path)
    assert [i.field for i in issues] == ["<root>"]
    assert issues[0].message.startswith("invalid JSON")


def test_detect_document_type(tmp_path: Path, valid_doc: Doc) -> None:
    assert detect_document_type(EXAMPLE) == "run result"
    other = tmp_path / "copy.json"
    other.write_text(json.dumps(valid_doc), encoding="utf-8")
    assert detect_document_type(other) == "run result"
    broken = tmp_path / "result.json"
    broken.write_text("{not json", encoding="utf-8")
    assert detect_document_type(broken) == "run result"


# --- CLI -------------------------------------------------------------------------------------


def test_cli_validate_run_result(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(EXAMPLE)]) == 0
    assert "valid run result" in capsys.readouterr().out


def test_cli_validate_unknown_status(
    tmp_path: Path, valid_doc: Doc, capsys: pytest.CaptureFixture[str]
) -> None:
    valid_doc["cases"][0]["status"] = "crashed"
    path = _write(tmp_path, valid_doc)
    assert main(["validate", str(path)]) == 1
    assert f"{path}: cases[0].status: 'crashed' is not one of" in capsys.readouterr().err


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


AGREEMENT_CASES: dict[str, Callable[[Doc], None]] = {
    # documents both must accept
    "valid": lambda d: None,
    "no_cases": _set("cases", value=[]),
    "empty_efficiency": _set("efficiency", value={}),
    "empty_summary_metrics": _set("summary_metrics", value={}),
    "offset_timestamp": _set("started_at", value="2026-10-09T14:00:00+02:00"),
    "status_invalid_output": _set("cases", 0, "status", value="invalid_output"),
    "status_skipped": _set("cases", 0, "status", value="skipped"),
    "integer_latency": _set("cases", 0, "latency_s", value=1),
    "null_latency": _set("cases", 0, "latency_s", value=None),
    "memory_and_note": _set("cases", 0, "memory_note", value="sampled with tracemalloc"),
    "empty_strata": _set("cases", 0, "strata", value={}),
    "numeric_stratum": _set("cases", 0, "strata", "zone", value=33),
    "null_metric_value": _set("cases", 0, "metrics", "value_abs_error", "value", value=None),
    "empty_summary_stats": _set(
        "summary_metrics",
        "value_abs_error",
        value={
            "version": "1.0.0",
            "mean": None,
            "median": None,
            "n": 0,
            "n_failed": 0,
            "ci_low": None,
            "ci_high": None,
        },
    ),
    # documents both must reject
    "missing_run_id": _delete("run_id"),
    "wrong_schema_version": _set("schema_version", value="2.0.0"),
    "extra_field": _set("unexpected", value=1),
    "benchmark_bad_version": _set("benchmark", "version", value="1.0"),
    "adapter_missing_config": _delete("adapter", "config"),
    "bad_config_hash": _set("config_hash", value="abc"),
    "missing_dataset_manifest_hash": _delete("dataset_manifest_hash"),
    "environment_list": _set("environment", value=[]),
    "naive_timestamp": _set("finished_at", value="2026-10-09T12:00:01"),
    "date_only_timestamp": _set("started_at", value="2026-10-09"),
    "summary_missing_n": _delete("summary_metrics", "value_abs_error", "n"),
    "summary_bad_metric_id": _set("summary_metrics", "Bad-ID", value={}),
    "efficiency_negative": _set("efficiency", "wall_clock_s", value=-1),
    "efficiency_extra": _set("efficiency", "unexpected", value=1),
    "failure_scored": _set("failures", 0, "status", value="scored"),
    "limitations_string": _set("limitations", value="none"),
    "unknown_status": _set("cases", 0, "status", value="crashed"),
    "missing_status": _delete("cases", 0, "status"),
    "missing_strata": _delete("cases", 0, "strata"),
    "stratum_list": _set("cases", 0, "strata", "operation", value=["a"]),
    "stratum_null": _set("cases", 0, "strata", "operation", value=None),
    "output_string": _set("cases", 0, "output", value="1234.5"),
    "missing_output": _delete("cases", 0, "output"),
    "metric_missing_passed": _delete("cases", 0, "metrics", "value_abs_error", "passed"),
    "metric_value_string": _set("cases", 0, "metrics", "value_abs_error", "value", value="0"),
    "negative_latency": _set("cases", 0, "latency_s", value=-0.1),
    "retries_negative": _set("cases", 0, "retries", value=-1),
    "retries_null": _set("cases", 0, "retries", value=None),
    "tokens_missing_output": _delete("cases", 0, "tokens", "output"),
    "tokens_string": _set("cases", 0, "tokens", "input", value="120"),
    "cost_negative": _set("cases", 0, "cost_usd", value=-1.0),
    "memory_null_without_note": _set("cases", 0, "peak_memory_bytes", value=None),
    "memory_float": _set("cases", 0, "peak_memory_bytes", value=1.5),
    "trajectory_not_list": _set("cases", 1, "trajectory", value={}),
    "error_missing_message": _delete("cases", 2, "error", "message"),
    "error_string": _set("cases", 2, "error", value="boom"),
    "missing_error": _delete("cases", 0, "error"),
    "case_extra_field": _set("cases", 0, "unexpected", value=1),
    "not_a_mapping": lambda d: d.clear(),
}

EXPECTED_VALID = {
    "valid",
    "no_cases",
    "empty_efficiency",
    "empty_summary_metrics",
    "offset_timestamp",
    "status_invalid_output",
    "status_skipped",
    "integer_latency",
    "null_latency",
    "memory_and_note",
    "empty_strata",
    "numeric_stratum",
    "null_metric_value",
    "empty_summary_stats",
}


@pytest.mark.parametrize("name", list(AGREEMENT_CASES))
def test_model_and_schema_agree(valid_doc: Doc, name: str) -> None:
    doc = copy.deepcopy(valid_doc)
    AGREEMENT_CASES[name](doc)
    schema_ok = Draft202012Validator(_schema()).is_valid(doc)
    try:
        RunResult.model_validate(doc)
        model_ok = True
    except ValidationError:
        model_ok = False
    assert schema_ok == model_ok, f"schema accepts={schema_ok}, model accepts={model_ok}"
    assert schema_ok == (name in EXPECTED_VALID)
