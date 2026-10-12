"""The graded-eval leaderboard: accepted runs, per-model score distributions, and the README
section between ``<!-- graded:start -->`` and ``<!-- graded:end -->``.

An accepted run is ``leaderboard/graded/<eval>/<adapter>/`` with ``result.json``,
``grades.json`` and ``config.yaml``, copied there by ``geoevals leaderboard add``. A run is
accepted only if it comes from a ``claude_python_<model>`` adapter with the default CLI, no task
was skipped, stopped by the runner's timeout or failed in the harness, its grades belong to it,
grading did not stop, every answered task was graded, and there are at least two passes. Tasks
that were not answered score 0.

All runs of an eval must share its version, the city layers (``data_sha256``), the dataset
manifest, the answering effort and prompt version, the rubric version, and the grader (model,
effort, prompt version, Claude Code version, passes). Runs graded by different versions are not
comparable, so the build rejects a mix.

Per model and eval the table shows the mean task score with its 95% bootstrap interval
(``geoevals.metrics.base.bootstrap_ci``, fixed seed), and the minimum, quartiles and maximum
(linear interpolation, as matplotlib's box plot draws them). Grader agreement per eval: the
share of criterion scores on which the first two passes differ by at most 1 point, and the mean
absolute difference of the passes' task scores.
"""

import json
import shutil
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from geoevals.adapters.claude import MODELS
from geoevals.graded.grader import GRADES_FILE, GraderInfo, Grades, load_grades
from geoevals.graded.run import load_graded_result
from geoevals.leaderboard.claude_cli import HARNESS_ERRORS
from geoevals.leaderboard.table import MODEL_NAMES
from geoevals.metrics.base import bootstrap_ci

GRADED_START = "<!-- graded:start -->"
GRADED_END = "<!-- graded:end -->"
DEFAULT_GRADED = Path("leaderboard/graded")
PLOTS_DIR = "plots"
README_PLOTS = "leaderboard/graded/plots"
RESULT_FILE = "result.json"
CONFIG_FILE = "config.yaml"
PREFIX = "claude_python_"


class GradedError(ValueError):
    """A graded run cannot go on the leaderboard."""


@dataclass(frozen=True)
class Agreement:
    within_one: float
    mean_abs_diff: float
    pairs: int


@dataclass(frozen=True)
class GradedRow:
    eval_id: str
    eval_version: str
    model: str
    scores: tuple[float, ...]
    mean: float
    ci_low: float
    ci_high: float
    minimum: float
    q1: float
    median: float
    q3: float
    maximum: float
    n: int
    comparable: tuple[str, ...]
    grader: GraderInfo

    def sort_key(self) -> tuple[str, int]:
        return self.eval_id, list(MODELS).index(self.model)


def quartiles(scores: list[float]) -> tuple[float, float, float]:
    if len(scores) == 1:
        return scores[0], scores[0], scores[0]
    q1, median, q3 = statistics.quantiles(scores, n=4, method="inclusive")
    return q1, median, q3


def is_graded_result(document: dict[str, Any]) -> bool:
    return "eval" in document and "tasks" in document


def graded_row(result: dict[str, Any], grades: Grades, where: str) -> GradedRow:
    """The table row of one graded run. Raises ``GradedError`` when it is not accepted."""
    adapter = result["adapter"]
    model = adapter["name"].removeprefix(PREFIX)
    if not adapter["name"].startswith(PREFIX) or model not in MODELS:
        raise GradedError(f"{where}: {adapter['name']!r} is not a claude_python_<model> adapter")
    config = adapter.get("config") or {}
    if "claude_command" in config:
        raise GradedError(f"{where}: runs with a custom claude_command are not accepted")
    tasks = result["tasks"]
    if not tasks:
        raise GradedError(f"{where}: the run has no tasks")
    harness = [
        t
        for t in tasks
        if t["status"] == "adapter_error" and (t.get("error") or {}).get("type") in HARNESS_ERRORS
    ]
    problems = {
        "skipped": [t for t in tasks if t["status"] == "skipped"],
        "stopped by the runner's timeout": [t for t in tasks if t["status"] == "timeout"],
        "failed in the harness": harness,
    }
    for reason, bad in problems.items():
        if bad:
            raise GradedError(f"{where}: {len(bad)} of {len(tasks)} task(s) {reason}")
    if grades.run_id != result["run_id"] or grades.eval != result["eval"]:
        raise GradedError(f"{where}: grades.json belongs to another run")
    if [t.task_id for t in grades.tasks] != [t["task_id"] for t in tasks]:
        raise GradedError(f"{where}: grades.json does not cover the run's tasks")
    if grades.stopped is not None:
        raise GradedError(f"{where}: grading stopped: {grades.stopped}")
    ungraded = [t.task_id for t in grades.tasks if t.status == "not_graded"]
    if ungraded:
        raise GradedError(f"{where}: {len(ungraded)} task(s) not graded (first: {ungraded[0]})")
    if grades.grader.passes < 2:
        raise GradedError(f"{where}: graded in {grades.grader.passes} pass(es); at least 2")
    scores = [t.score if t.score is not None else 0.0 for t in grades.tasks]
    ci = bootstrap_ci(scores) or (scores[0], scores[0])
    q1, median, q3 = quartiles(scores)
    comparable = (
        result["eval"]["version"],
        result["data_sha256"],
        result["dataset_manifest_hash"],
        str(config.get("effort", "high")),
        str(config.get("prompt_version", "v1")),
        grades.rubric_version,
        json.dumps(grades.grader.model_dump(), sort_keys=True),
    )
    return GradedRow(
        eval_id=result["eval"]["id"],
        eval_version=result["eval"]["version"],
        model=model,
        scores=tuple(scores),
        mean=sum(scores) / len(scores),
        ci_low=ci[0],
        ci_high=ci[1],
        minimum=min(scores),
        q1=q1,
        median=median,
        q3=q3,
        maximum=max(scores),
        n=len(scores),
        comparable=comparable,
        grader=grades.grader,
    )


def agreement(all_grades: list[Grades]) -> Agreement:
    """Agreement between the first two passes over every graded task of ``all_grades``."""
    close = pairs = 0
    differences: list[float] = []
    for grades in all_grades:
        for task in grades.tasks:
            if task.status != "graded" or len(task.passes) < 2:
                continue
            first, second = task.passes[0].criteria, task.passes[1].criteria
            for cid in first:
                pairs += 1
                close += abs(first[cid].score - second[cid].score) <= 1
            mean = [sum(c.score for c in p.values()) / len(p) / 4 for p in (first, second)]
            differences.append(abs(mean[0] - mean[1]))
    return Agreement(
        within_one=close / pairs if pairs else 0.0,
        mean_abs_diff=sum(differences) / len(differences) if differences else 0.0,
        pairs=pairs,
    )


def load_graded(results_dir: Path) -> tuple[list[GradedRow], dict[str, Agreement]]:
    """Every accepted graded run under ``results_dir`` and each eval's grader agreement."""
    rows: list[GradedRow] = []
    by_eval: dict[str, list[Grades]] = {}
    for path in sorted(results_dir.glob(f"*/*/{RESULT_FILE}")):
        try:
            result = load_graded_result(path)
            grades = load_grades(path.parent / GRADES_FILE)
        except (OSError, ValueError) as exc:
            raise GradedError(f"{path.parent}: cannot be read: {exc}") from exc
        rows.append(graded_row(result, grades, str(path.parent)))
        by_eval.setdefault(result["eval"]["id"], []).append(grades)
    for eval_id in sorted({row.eval_id for row in rows}):
        variants = {row.comparable for row in rows if row.eval_id == eval_id}
        if len(variants) > 1:
            raise GradedError(
                f"runs of {eval_id} are not comparable: they differ in eval version, city data, "
                "manifest, effort, prompt version, rubric version or grader"
            )
    agreements = {eval_id: agreement(grades) for eval_id, grades in by_eval.items()}
    return sorted(rows, key=GradedRow.sort_key), agreements


def _model_slug(model_id: str) -> str:
    """``claude-opus-5-5`` -> ``opus_5_5``, the slug in adapter names."""
    return model_id.removeprefix("claude-").replace("-", "_")


def _model_name(model_id: str) -> str:
    """``claude-opus-5-5`` -> ``Opus 5.5``."""
    return MODEL_NAMES.get(_model_slug(model_id), model_id)


def _task_counts(rows: list[GradedRow]) -> str:
    """One sentence on how many tasks the rows cover."""
    counts = {row.n for row in rows}
    if len(counts) == 1:
        return f"Each row covers {counts.pop()} tasks."
    per_eval = []
    for eval_id in sorted({row.eval_id for row in rows}):
        numbers = sorted({row.n for row in rows if row.eval_id == eval_id})
        per_eval.append(f"`{eval_id}` {' or '.join(map(str, numbers))} tasks")
    listed = ", ".join(per_eval[:-1]) + f" and {per_eval[-1]}"
    return f"Rows cover {listed}."


def render_graded(rows: list[GradedRow], agreements: dict[str, Agreement]) -> str:
    """The Markdown between the graded markers."""
    if not rows:
        return "No graded runs have been added yet. See [`evals/README.md`](evals/README.md)."
    lines = [
        "| Model | Eval | Mean (95% CI) | Min | Q1 | Median | Q3 | Max |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {MODEL_NAMES[row.model]} | `{row.eval_id}` {row.eval_version} "
            f"| {row.mean:.3f} [{row.ci_low:.2f}, {row.ci_high:.2f}] | {row.minimum:.2f} "
            f"| {row.q1:.2f} | {row.median:.2f} | {row.q3:.2f} | {row.maximum:.2f} |"
        )
    evals = sorted({row.eval_id for row in rows})
    lines.append("")
    for eval_id in evals:
        lines.append(f"![{eval_id}: task scores by model]({README_PLOTS}/{eval_id}.svg)")
    grader = rows[0].grader
    agreement_text = "; ".join(
        f"`{e}` {agreements[e].within_one:.0%} of criterion scores within 1 point, mean task-score "
        f"difference {agreements[e].mean_abs_diff:.2f}"
        for e in evals
    )
    answered_by_grader = _model_slug(grader.model) in {row.model for row in rows}
    notes = [
        "",
        f"Graded by Claude {_model_name(grader.model)} (effort {grader.effort}, grader prompt "
        f"{grader.prompt_version}, Claude Code {grader.claude_code_version}) in "
        f"{grader.passes} passes per answer. The grader saw the task with its location, the "
        "rubric, the reference key and the answer, never which model answered. "
        f"Agreement between passes: {agreement_text}.",
    ]
    if answered_by_grader:
        notes.append(
            f"{_model_name(grader.model)} also answered these tasks, so its own rows may be "
            "biased in its favor."
        )
    notes += [
        "",
        "A task score is the mean of the rubric criteria (0 to 4) divided by 4, averaged over the "
        f"passes, from 0 to 1. {_task_counts(rows)} Tasks without an answer (errors, model "
        "timeouts, invalid output) score 0. Graded scores are not comparable with benchmark "
        "scores and are never combined with them.",
        "",
        "Tasks, answers and reference keys use map data © OpenStreetMap contributors (ODbL-1.0).",
    ]
    return "\n".join(lines + notes)


def add_graded_run(run_dir: Path, results_dir: Path) -> Path:
    """Copy an accepted graded run to ``results_dir/<eval>/<adapter>/``."""
    result_path = run_dir / RESULT_FILE if run_dir.is_dir() else run_dir
    result = load_graded_result(result_path)
    grades = load_grades(result_path.parent / GRADES_FILE)
    graded_row(result, grades, str(result_path.parent))
    target = results_dir / result["eval"]["id"] / result["adapter"]["name"]
    target.mkdir(parents=True, exist_ok=True)
    for name in (RESULT_FILE, GRADES_FILE, CONFIG_FILE):
        if (result_path.parent / name).is_file():
            shutil.copyfile(result_path.parent / name, target / name)
    return target
