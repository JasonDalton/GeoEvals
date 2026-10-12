"""Grade a graded run's answers with Claude Opus 5.5, twice per answer.

``grade_run`` reads a run's ``result.json``, the eval's tasks and rubric, and the verified keys
(``geoevals.graded.keys.load_keys``: a missing or stale keys file stops grading before any
call). For every answered task it runs ``passes`` separate ``claude -p`` sessions through
``geoevals.leaderboard.claude_cli.run_cli``: model ``GRADER_MODEL``, effort high, no tools,
``--restricted``, a stripped environment, an empty working directory and the subscription
check. The input is the grader prompt (``prompts/grader_v1.md``), the task prompt and audience,
the rubric with anchors, the key and the answer; never the answering model, the adapter, the run
ID or the trajectory.

A grade is valid when it scores exactly the task's criteria with integers 0 to 4, each with a
justification of at most 60 words. An error or an invalid grade is retried once; a second
failure leaves the task ``not_graded``. The usage limit, an auth failure, an unexpected model or
a Claude Code version change stops grading: every task not yet graded is ``not_graded`` and
``stopped`` says why. A task that was not answered (``invalid_output``, errors, timeouts) is
``no_answer`` with score 0, without a call.

Task score = mean over the passes of (mean of criteria / 4).
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from geoevals.graded.keys import KeysError, default_data_dir, load_keys
from geoevals.graded.run import load_graded_result, word_count
from geoevals.graded.spec import (
    Criterion,
    EvalTask,
    find_eval_spec,
    load_rubric,
    load_tasks,
    spec_file,
)
from geoevals.leaderboard.claude_cli import (
    ClaudeAuthError,
    ClaudeCliError,
    ClaudeUnexpectedModel,
    ClaudeUsageLimit,
    ClaudeVersionChanged,
    CliCall,
    claude_code_version,
    run_cli,
)
from geoevals.validation import load_eval_spec

GRADER_MODEL = "claude-opus-5-5"
GRADER_EFFORT = "high"
GRADER_PROMPT_VERSION = "grader_v1"
MAX_JUSTIFICATION_WORDS = 60
GRADES_FILE = "grades.json"
GRADES_SCHEMA_VERSION = "1.0.0"
PROMPTS_DIR = Path(__file__).parent / "prompts"
STOPPING_ERRORS = (ClaudeUsageLimit, ClaudeAuthError, ClaudeUnexpectedModel, ClaudeVersionChanged)


class GradeError(RuntimeError):
    """The run cannot be graded (unreadable run, unknown eval, missing or stale keys)."""


class InvalidGrade(ValueError):
    """The grader's answer does not meet the grade rules."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CriterionGrade(_Model):
    score: Annotated[int, Field(ge=0, le=4)]
    justification: str


class GradePass(_Model):
    criteria: dict[str, CriterionGrade]


class TaskGrade(_Model):
    task_id: str
    status: Literal["graded", "no_answer", "not_graded"]
    score: float | None
    passes: list[GradePass]
    error: str | None = None


class GraderInfo(_Model):
    model: str
    effort: str
    prompt_version: str
    claude_code_version: str
    passes: int


class Grades(_Model):
    schema_version: Literal["1.0.0"]
    run_id: str
    eval: dict[str, str]
    rubric_version: str
    grader: GraderInfo
    graded_at: str
    stopped: str | None
    tasks: list[TaskGrade]


@dataclass(frozen=True)
class GraderConfig:
    passes: int = 2
    command: tuple[str, ...] = ("claude",)
    timeout_s: float = 600.0
    max_budget_usd: float = 5.0
    evals_root: Path = field(default_factory=lambda: Path("evals"))


def grade_schema(criterion_ids: list[str]) -> dict[str, Any]:
    """The ``--json-schema`` of a grade: one score and justification per criterion."""
    criterion = {
        "type": "object",
        "additionalProperties": False,
        "required": ["score", "justification"],
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 4},
            "justification": {"type": "string", "minLength": 1},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["criteria"],
        "properties": {
            "criteria": {
                "type": "object",
                "additionalProperties": False,
                "required": list(criterion_ids),
                "properties": {cid: criterion for cid in criterion_ids},
            }
        },
    }


def check_grade(grade: Any, criterion_ids: list[str]) -> str | None:
    """Why ``grade`` breaks the grade rules, or None."""
    if not isinstance(grade, dict) or not isinstance(grade.get("criteria"), dict):
        return "the grade has no criteria object"
    criteria = grade["criteria"]
    missing = sorted(set(criterion_ids) - set(criteria))
    if missing:
        return f"missing criteria: {', '.join(missing)}"
    unexpected = sorted(set(criteria) - set(criterion_ids))
    if unexpected:
        return f"unexpected criteria: {', '.join(unexpected)}"
    for cid in criterion_ids:
        entry = criteria[cid]
        score = entry.get("score") if isinstance(entry, dict) else None
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 4:
            return f"{cid}: the score must be an integer from 0 to 4"
        justification = entry.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            return f"{cid}: no justification"
        if word_count(justification) > MAX_JUSTIFICATION_WORDS:
            return f"{cid}: the justification is longer than {MAX_JUSTIFICATION_WORDS} words"
    return None


def task_score(passes: list[dict[str, Any]]) -> float:
    """Mean over the passes of (mean of criteria / 4)."""
    per_pass = [
        sum(c["score"] for c in criteria.values()) / len(criteria) / 4 for criteria in passes
    ]
    return sum(per_pass) / len(per_pass)


def grader_message(
    task: EvalTask, criteria: list[Criterion], key: dict[str, Any], output: dict[str, Any]
) -> str:
    """The user message of a grading session; see the module docstring for what it holds."""
    lines = ["# Task", "", task.prompt, "", f"Audience: {task.audience}", "", "# Rubric", ""]
    lines.append("Score each criterion from 0 to 4 using its anchors.")
    for criterion in criteria:
        lines += ["", f"## {criterion.id}: {criterion.title}", "", criterion.description, ""]
        lines += [f"- {score}: {text}" for score, text in sorted(criterion.anchors.items())]
        extra = task.anchors.get(criterion.id, {})
        if extra:
            lines += ["", "Anchors for this task:"]
            lines += [f"- {score}: {text}" for score, text in sorted(extra.items())]
    lines += [
        "",
        "# Reference key",
        "",
        "Facts computed from the city's data. Distances are in meters and bearings in degrees, "
        "rounded to 0.1.",
        "",
        "```json",
        json.dumps(key, indent=2, ensure_ascii=False),
        "```",
        "",
        "# Answer to grade",
        "",
        f"Status: {output['status']}",
        "",
        output["answer"],
    ]
    return "\n".join(lines)


def _grade_once(call: CliCall, version: str, criterion_ids: list[str]) -> dict[str, Any]:
    result = run_cli(call)
    if result.claude_code_version != version:
        raise ClaudeVersionChanged(
            f"graded on Claude Code {result.claude_code_version}, not {version}"
        )
    problem = check_grade(result.structured_output, criterion_ids)
    if problem is not None:
        raise InvalidGrade(problem)
    assert result.structured_output is not None
    return result.structured_output["criteria"]


def _grade_pass(call: CliCall, version: str, criterion_ids: list[str]) -> dict[str, Any]:
    """One pass, retried once. Raises a stopping error, or the second failure."""
    for attempt in (1, 2):
        try:
            return _grade_once(call, version, criterion_ids)
        except STOPPING_ERRORS:
            raise
        except (ClaudeCliError, InvalidGrade):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def load_grades(path: Path) -> Grades:
    return Grades.model_validate(json.loads(path.read_text(encoding="utf-8")))


def grade_run(run_dir: Path, data_dir: Path | None, config: GraderConfig) -> Grades:
    """Grade every task of a graded run; see the module docstring."""
    try:
        result = load_graded_result(run_dir)
    except (OSError, ValueError) as exc:
        raise GradeError(f"{run_dir}: {exc}") from exc
    spec_path = find_eval_spec(config.evals_root, result["eval"]["id"])
    spec = load_eval_spec(spec_path)
    if spec.version != result["eval"]["version"]:
        raise GradeError(
            f"the run answered {spec.id} {result['eval']['version']}; {spec_path} is {spec.version}"
        )
    tasks = {task.task_id: task for task in load_tasks(spec_path, spec)}
    for record in result["tasks"]:
        if record["task_id"] not in tasks:
            raise GradeError(
                f"the run's task {record['task_id']} is not in {spec_file(spec_path, spec.tasks)}; "
                "was the eval changed without a version bump?"
            )
    rubric = load_rubric(spec_path, spec)
    by_id = {criterion.id: criterion for criterion in rubric.criteria}
    try:
        keys = load_keys(spec_path, data_dir or default_data_dir(spec_path))
    except KeysError as exc:
        raise GradeError(str(exc)) from exc
    version = claude_code_version(config.command)
    system_prompt = (PROMPTS_DIR / f"{GRADER_PROMPT_VERSION}.md").read_text(encoding="utf-8")
    stopped: str | None = None
    graded: list[TaskGrade] = []
    for record in result["tasks"]:
        task = tasks[record["task_id"]]
        if record["status"] != "answered":
            graded.append(TaskGrade(task_id=task.task_id, status="no_answer", score=0.0, passes=[]))
            continue
        if stopped is not None:
            graded.append(
                TaskGrade(
                    task_id=task.task_id, status="not_graded", score=None, passes=[], error=stopped
                )
            )
            continue
        criteria = [by_id[cid] for cid in task.rubric]
        call = CliCall(
            model=GRADER_MODEL,
            system_prompt=system_prompt,
            user_message=grader_message(task, criteria, keys[task.task_id], record["output"]),
            json_schema=grade_schema(task.rubric),
            effort=GRADER_EFFORT,
            max_budget_usd=config.max_budget_usd,
            timeout_s=config.timeout_s,
            command=tuple(config.command),
        )
        passes: list[dict[str, Any]] = []
        error: str | None = None
        try:
            for _ in range(config.passes):
                passes.append(_grade_pass(call, version, task.rubric))
        except STOPPING_ERRORS as exc:
            stopped = f"{type(exc).__name__}: {exc}"
            error = stopped
        except (ClaudeCliError, InvalidGrade) as exc:
            error = f"{type(exc).__name__}: {exc}"
        if error is None:
            graded.append(
                TaskGrade(
                    task_id=task.task_id,
                    status="graded",
                    score=task_score(passes),
                    passes=[GradePass.model_validate({"criteria": p}) for p in passes],
                )
            )
        else:
            graded.append(
                TaskGrade(
                    task_id=task.task_id, status="not_graded", score=None, passes=[], error=error
                )
            )
    return Grades(
        schema_version=GRADES_SCHEMA_VERSION,
        run_id=result["run_id"],
        eval=dict(result["eval"]),
        rubric_version=rubric.version,
        grader=GraderInfo(
            model=GRADER_MODEL,
            effort=GRADER_EFFORT,
            prompt_version=GRADER_PROMPT_VERSION,
            claude_code_version=version,
            passes=config.passes,
        ),
        graded_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        stopped=stopped,
        tasks=graded,
    )
