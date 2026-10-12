import copy
import json
import shutil
from pathlib import Path

import pytest

from geoevals.graded.spec import (
    KEY_TYPES,
    OUTPUT_SCHEMA,
    find_eval_spec,
    load_rubric,
    load_tasks,
)
from geoevals.validation import (
    SpecValidationError,
    detect_document_type,
    load_eval_spec,
    validate_eval_document,
)
from geoevals.validation.eval_spec import EvalSpec
from geoevals.validation.validate import load_yaml

REPO = Path(__file__).parent.parent
SAMPLE = REPO / "tests" / "fixtures" / "graded" / "sample" / "eval.yaml"
RUBRIC = REPO / "evals" / "city" / "rubric_criteria.yaml"


def _document() -> dict:
    return copy.deepcopy(load_yaml(SAMPLE))


def test_sample_spec_loads() -> None:
    spec = load_eval_spec(SAMPLE)
    assert (spec.id, spec.version, spec.answer_word_limit) == ("sample", "0.1.0", 4000)
    assert detect_document_type(SAMPLE) == "eval spec"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.pop("rubric_criteria"),
        lambda d: d.update(version="1"),
        lambda d: d.update(answer_word_limit=0),
        lambda d: d.update(extra=True),
        lambda d: d.update(id="Sample"),
        lambda d: d.update(limitations=[]),
    ],
)
def test_schema_and_model_reject_the_same_specs(change) -> None:
    document = _document()
    change(document)
    assert validate_eval_document(document)
    with pytest.raises(ValueError):
        EvalSpec.model_validate(document)


def test_tasks_and_rubric_load() -> None:
    spec = load_eval_spec(SAMPLE)
    tasks = load_tasks(SAMPLE, spec)
    assert [t.task_id for t in tasks] == ["sample-001", "sample-002", "sample-003"]
    assert {t.key_type for t in tasks} <= set(KEY_TYPES)
    rubric = load_rubric(SAMPLE, spec)
    assert [c.id for c in rubric.criteria] == [
        "relations",
        "reasoning",
        "assumptions",
        "data_use",
        "clarity",
    ]
    assert all(set(c.anchors) == {"0", "1", "2", "3", "4"} for c in rubric.criteria)


def _with_tasks(tmp_path: Path, edit) -> Path:
    directory = tmp_path / "sample"
    shutil.copytree(SAMPLE.parent, directory)
    document = load_yaml(directory / "eval.yaml")
    document["rubric_criteria"] = str(RUBRIC)
    (directory / "eval.yaml").write_text(json.dumps(document), encoding="utf-8")
    lines = [json.loads(line) for line in (directory / "tasks.jsonl").read_text().splitlines()]
    edit(lines)
    (directory / "tasks.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in lines))
    return directory / "eval.yaml"


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda ls: ls.append(dict(ls[0])), "duplicate task_id"),
        (lambda ls: ls[0].update(task_id="other-001"), "must start with 'sample-'"),
        (lambda ls: ls[0].update(rubric=["relations", "style"]), "unknown criterion 'style'"),
        (lambda ls: ls[0].update(key_type="guess"), "key_type"),
        (
            lambda ls: ls[1].update(rubric=["relations"], anchors={"clarity": {"4": "x"}}),
            "not in the task's rubric",
        ),
        (lambda ls: ls[1].update(anchors={"assumptions": {"5": "x"}}), "score 5"),
        (lambda ls: ls[0].update(prompt=""), "prompt"),
        (
            lambda ls: ls[0].update(rubric=["relations", "clarity", "relations"]),
            "duplicate criterion 'relations'",
        ),
    ],
)
def test_invalid_tasks_are_reported(tmp_path: Path, edit, message: str) -> None:
    spec_path = _with_tasks(tmp_path, edit)
    with pytest.raises(SpecValidationError, match=message):
        load_tasks(spec_path, load_eval_spec(spec_path))


def test_output_schema_is_status_and_answer() -> None:
    assert OUTPUT_SCHEMA["required"] == ["status", "answer"]
    assert OUTPUT_SCHEMA["properties"]["status"]["enum"][0] == "ok"


def test_find_eval_spec(tmp_path: Path) -> None:
    (tmp_path / "proximity").mkdir()
    (tmp_path / "proximity" / "eval.yaml").write_text("id: proximity\n")
    assert find_eval_spec(tmp_path, "proximity") == tmp_path / "proximity" / "eval.yaml"
