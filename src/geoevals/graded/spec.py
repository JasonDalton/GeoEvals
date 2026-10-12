"""Graded eval tasks, the shared rubric, and the answer schema.

An eval is a directory with ``eval.yaml`` (``geoevals.validation.eval_spec.EvalSpec``), a JSONL
task file and pointers to the shared rubric criteria and reference script. A task line:

- ``task_id``: ``<eval id>-NNN``
- ``prompt``, ``audience``: what the model is asked, and for whom it writes
- ``location``: a point and feature IDs, sent to the model with the prompt
- ``key_type``, ``params``: how ``evals/city/reference.py`` computes the task's key; hidden
  from the model
- ``rubric``: the criterion IDs that score the task; ``anchors``: extra anchors per criterion
  and score
- ``key_sha256``: SHA-256 of the key (``geoevals evals regenerate``); null until computed
- ``strata``: labels for slicing results
"""

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator

from geoevals.validation import EvalSpec, SpecValidationError, ValidationIssue
from geoevals.validation.benchmark import Identifier, NonEmptyStr, SemVer, _SchemaModel
from geoevals.validation.validate import load_yaml

EVAL_SPEC_FILE = "eval.yaml"
SCORES = ("0", "1", "2", "3", "4")
ANSWER_STATUSES = ("ok", "needs_clarification", "insufficient_data", "invalid_request")
KEY_TYPES = ("proximity", "containment", "adjacency", "closure", "visibility", "direction")
TASK_ID_PATTERN = r"^[a-z][a-z0-9_]*-[0-9]{3}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "answer"],
    "properties": {
        "status": {
            "description": (
                "ok when you answer the question; needs_clarification, insufficient_data or "
                "invalid_request when it cannot be answered as asked."
            ),
            "enum": list(ANSWER_STATUSES),
        },
        "answer": {
            "description": "Your answer in Markdown, at most the word limit stated in the task.",
            "type": "string",
            "minLength": 1,
        },
    },
}
"""The answer every graded task asks for (status, as in the benchmarks, and Markdown text)."""


class Location(_SchemaModel):
    point: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    feature_ids: list[NonEmptyStr] = Field(default_factory=list)


class EvalTask(_SchemaModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    prompt: NonEmptyStr
    audience: NonEmptyStr
    location: Location
    key_type: Literal["proximity", "containment", "adjacency", "closure", "visibility", "direction"]
    params: dict[str, Any]
    rubric: Annotated[list[Identifier], Field(min_length=1)]
    anchors: dict[Identifier, dict[str, NonEmptyStr]] = Field(default_factory=dict)
    key_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)] | None = None
    strata: dict[Identifier, str | bool | int] = Field(default_factory=dict)


class Criterion(_SchemaModel):
    id: Identifier
    title: NonEmptyStr
    description: NonEmptyStr
    anchors: dict[str, NonEmptyStr]

    @field_validator("anchors")
    @classmethod
    def _every_score(cls, anchors: dict[str, str]) -> dict[str, str]:
        if tuple(sorted(anchors)) != SCORES:
            raise ValueError(f"anchors must cover the scores {', '.join(SCORES)} exactly")
        return anchors


class RubricCriteria(_SchemaModel):
    version: SemVer
    criteria: Annotated[list[Criterion], Field(min_length=1)]

    @field_validator("criteria")
    @classmethod
    def _unique(cls, criteria: list[Criterion]) -> list[Criterion]:
        ids = [c.id for c in criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("criterion IDs must be unique")
        return criteria


def spec_file(spec_path: Path, relative: str) -> Path:
    """A file named in the spec, relative to the spec's directory."""
    return (spec_path.parent / relative).resolve()


def find_eval_spec(root: Path, eval_id: str) -> Path:
    """``<root>/<eval_id>/eval.yaml``."""
    return root / eval_id / EVAL_SPEC_FILE


def _issues(error: ValidationError, prefix: str) -> list[ValidationIssue]:
    return [
        ValidationIssue(f"{prefix}.{'.'.join(map(str, e['loc']))}".rstrip("."), e["msg"])
        for e in error.errors()
    ]


def load_rubric(spec_path: Path, spec: EvalSpec) -> RubricCriteria:
    """The spec's rubric criteria. YAML integer score keys are read as strings."""
    path = spec_file(spec_path, spec.rubric_criteria)
    document = load_yaml(path)
    for criterion in document.get("criteria", []) if isinstance(document, dict) else []:
        if isinstance(criterion, dict) and isinstance(criterion.get("anchors"), dict):
            criterion["anchors"] = {str(k): v for k, v in criterion["anchors"].items()}
    try:
        return RubricCriteria.model_validate(document)
    except ValidationError as exc:
        raise SpecValidationError(path, _issues(exc, "criteria")) from exc


def load_tasks(spec_path: Path, spec: EvalSpec) -> list[EvalTask]:
    """The spec's tasks. Raises ``SpecValidationError`` listing every problem."""
    path = spec_file(spec_path, spec.tasks)
    criteria = {c.id for c in load_rubric(spec_path, spec).criteria}
    tasks: list[EvalTask] = []
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"line {number}"
        try:
            task = EvalTask.model_validate(json.loads(line))
        except json.JSONDecodeError as exc:
            issues.append(ValidationIssue(where, f"invalid JSON: {exc}"))
            continue
        except ValidationError as exc:
            issues.extend(_issues(exc, where))
            continue
        if task.task_id in seen:
            issues.append(ValidationIssue(where, f"duplicate task_id {task.task_id!r}"))
        seen.add(task.task_id)
        if not task.task_id.startswith(f"{spec.id}-"):
            issues.append(ValidationIssue(where, f"task_id must start with '{spec.id}-'"))
        for criterion in task.rubric:
            if criterion not in criteria:
                issues.append(ValidationIssue(where, f"unknown criterion {criterion!r}"))
        for criterion in sorted({c for c in task.rubric if task.rubric.count(c) > 1}):
            issues.append(ValidationIssue(where, f"duplicate criterion {criterion!r} in rubric"))
        for criterion, anchors in task.anchors.items():
            if criterion not in task.rubric:
                issues.append(
                    ValidationIssue(where, f"anchors for {criterion!r}, not in the task's rubric")
                )
            for score in anchors:
                if score not in SCORES:
                    issues.append(ValidationIssue(where, f"anchor for score {score}, not 0 to 4"))
        tasks.append(task)
    if not tasks and not issues:
        issues.append(ValidationIssue("<root>", "no tasks"))
    if issues:
        raise SpecValidationError(path, issues)
    return tasks
