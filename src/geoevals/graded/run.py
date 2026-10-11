"""Graded runs: one answer per task from an adapter, with the city mounted. No scores.

``run_eval`` sends every task of an eval to an adapter, as ``geoevals.runner.run`` sends
benchmark cases (one worker process, the run config's timeout and retries), and returns a result
that matches ``schemas/graded-result.schema.json``. Grading is a separate step, ``geoevals
grade``.

The adapter's case input for a task:

- ``case_id``: the task ID
- ``prompt``: the task prompt, the audience and the word limit
- ``inputs``: ``{"files": {}, "params": <the task location>}``
- ``benchmark_dir``: the eval's directory (the Claude adapters read ``eval.yaml`` from it)

The task's ``params`` and key are never sent. A Claude adapter also gets ``prompt: graded`` and
``data_mount`` (the city's ``layers/``, mounted read-only at ``/bench/data``); they are not part
of the recorded config, because the mount path is local to the machine.

Task statuses: ``answered``; ``invalid_output`` (not the answer schema, an empty answer, or
longer than the eval's word limit); ``adapter_error``; ``timeout``; ``skipped``.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from geoevals.adapters.registry import adapter_factory
from geoevals.graded.city import LAYERS_DIR, layers_sha256
from geoevals.graded.spec import OUTPUT_SCHEMA, EvalTask, load_tasks, spec_file
from geoevals.metrics.base import percentile
from geoevals.runner.config import RunConfig, canonical_config, config_hash
from geoevals.runner.environment import environment_fingerprint
from geoevals.runner.layout import make_run_id
from geoevals.runner.run import RunError
from geoevals.runner.worker import Worker, WorkerSetupError
from geoevals.validation import (
    SpecValidationError,
    ValidationIssue,
    load_dataset_manifest,
    load_eval_spec,
)
from geoevals.validation.validate import schema_issues

logger = logging.getLogger(__name__)

GRADED_RESULT_SCHEMA_VERSION = "1.0.0"
SPLIT = "test"
TASK_STATUSES = ("answered", "invalid_output", "adapter_error", "timeout", "skipped")
_ATTEMPT_STATUS = {"timeout": "timeout", "skipped": "skipped", "error": "adapter_error"}


def word_count(text: str) -> int:
    return len(text.split())


def answer_problem(output: Any, word_limit: int) -> str | None:
    """Why ``output`` is not a valid answer, or None."""
    errors = sorted(
        Draft202012Validator(OUTPUT_SCHEMA).iter_errors(output),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        return "; ".join(
            f"{'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors
        )
    if not output["answer"].strip():
        return "the answer is empty"
    words = word_count(output["answer"])
    if words > word_limit:
        return f"the answer has {words} words; the limit is {word_limit}"
    return None


def case_input(task: EvalTask, spec_path: Path, word_limit: int) -> dict[str, Any]:
    """What the adapter receives for ``task``; see the module docstring."""
    prompt = (
        f"{task.prompt}\n\nWrite for: {task.audience}.\nAnswer in at most {word_limit:,} words."
    )
    return {
        "case_id": task.task_id,
        "prompt": prompt,
        "inputs": {"files": {}, "params": task.location.model_dump(exclude_none=True)},
        "benchmark_dir": str(spec_path.parent.resolve()),
    }


def _run_task(
    worker: Worker, task: EvalTask, case: dict[str, Any], config: RunConfig, word_limit: int
) -> dict[str, Any]:
    attempts = 0
    while True:
        attempts += 1
        attempt = worker.predict(case, f"{config.seed}:{task.task_id}", config.timeout_s)
        if attempt.kind != "error" or attempts > config.max_retries:
            break
        logger.warning(
            "task %s attempt %d: %s: %s; retrying",
            task.task_id, attempts, attempt.error_type, attempt.error_message,
        )  # fmt: skip
    record: dict[str, Any] = {
        "task_id": task.task_id,
        "status": "answered",
        "output": None,
        "latency_s": attempt.latency_s,
        "retries": attempts - 1,
        "tokens": None,
        "error": None,
    }
    if attempt.tokens is not None:
        record["tokens"] = {"input": attempt.tokens[0], "output": attempt.tokens[1]}
    if attempt.trajectory is not None:
        record["trajectory"] = attempt.trajectory
    if attempt.kind == "ok":
        problem = answer_problem(attempt.output, word_limit)
        record["output"] = attempt.output if isinstance(attempt.output, dict) else None
        if problem is not None:
            record["status"] = "invalid_output"
            record["error"] = {"type": "InvalidOutput", "message": problem}
    else:
        record["status"] = _ATTEMPT_STATUS[attempt.kind]
        record["error"] = {
            "type": attempt.error_type or "Error",
            "message": attempt.error_message or "",
        }
    log = logger.info if record["status"] == "answered" else logger.warning
    log("task %s: %s", task.task_id, record["status"])
    return record


def _efficiency(records: list[dict[str, Any]], wall_clock_s: float) -> dict[str, Any]:
    latencies = sorted(r["latency_s"] for r in records if r["latency_s"] is not None)
    return {
        "wall_clock_s": wall_clock_s,
        "latency_p50_s": percentile(latencies, 0.5) if latencies else None,
        "latency_p90_s": percentile(latencies, 0.9) if latencies else None,
        "tokens_input_total": sum(r["tokens"]["input"] for r in records if r["tokens"]),
        "tokens_output_total": sum(r["tokens"]["output"] for r in records if r["tokens"]),
    }


def _timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_graded_result(document: Any) -> list[ValidationIssue]:
    issues = schema_issues(document, "graded-result.schema.json")
    if issues:
        return issues
    seen: set[str] = set()
    for i, task in enumerate(document["tasks"]):
        if task["task_id"] in seen:
            issues.append(ValidationIssue(f"tasks[{i}].task_id", f"duplicate {task['task_id']!r}"))
        seen.add(task["task_id"])
    return issues


def load_graded_result(path: Path) -> dict[str, Any]:
    """A graded run's ``result.json`` (or its directory). Raises ``SpecValidationError``."""
    path = path / "result.json" if path.is_dir() else path
    document = json.loads(path.read_text(encoding="utf-8"))
    issues = validate_graded_result(document)
    if issues:
        raise SpecValidationError(path, issues)
    return document


def run_eval(
    spec_path: Path,
    adapter_name: str,
    config: RunConfig,
    data_dir: Path,
    on_start: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run ``adapter_name`` on every task of the eval at ``spec_path``; return the result.

    Raises ``SpecValidationError`` for an invalid spec, tasks or manifest, and ``RunError`` when
    the run cannot start. Failing tasks never raise; they get a failure status.
    """
    spec = load_eval_spec(spec_path)
    tasks = load_tasks(spec_path, spec)
    if config.split != SPLIT:
        raise RunError(
            f"graded evals have one split, {SPLIT!r}; the config asks for {config.split!r}"
        )
    manifest_path = spec_file(spec_path, spec.dataset_manifest)
    load_dataset_manifest(manifest_path)
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    layers_dir = data_dir / LAYERS_DIR
    try:
        data_sha256 = layers_sha256(layers_dir)
    except OSError:
        raise RunError(
            f"{layers_dir}: no city layers; run `geoevals evals build-city` first"
        ) from None
    factory = adapter_factory(adapter_name)
    adapter = factory()
    adapter_config = dict(config.adapter)
    if adapter_name.startswith("claude_"):
        adapter_config.update(prompt="graded", data_mount=str(layers_dir.resolve()))
    digest = config_hash(config)
    started = datetime.now(UTC)
    run_id = make_run_id(spec.id, adapter_name, started, digest)
    if on_start is not None:
        on_start(run_id)
    logger.info(
        "running %d task(s) of eval %s %s with adapter %s %s",
        len(tasks), spec.id, spec.version, adapter.name, adapter.version,
    )  # fmt: skip
    clock = time.perf_counter()
    worker = Worker(factory, adapter_config)
    records: list[dict[str, Any]] = []
    try:
        for task in tasks:
            case = case_input(task, spec_path, spec.answer_word_limit)
            records.append(_run_task(worker, task, case, config, spec.answer_word_limit))
    except WorkerSetupError as exc:
        raise RunError(str(exc)) from exc
    finally:
        worker.close()
    wall_clock_s = time.perf_counter() - clock
    result: dict[str, Any] = {
        "run_id": run_id,
        "schema_version": GRADED_RESULT_SCHEMA_VERSION,
        "eval": {"id": spec.id, "version": spec.version},
        "adapter": {
            "name": adapter.name,
            "version": adapter.version,
            "config": canonical_config(config)["adapter"],
        },
        "config_hash": digest,
        "dataset_manifest_hash": manifest_hash,
        "data_sha256": data_sha256,
        "environment": environment_fingerprint(),
        "started_at": _timestamp(started),
        "finished_at": _timestamp(datetime.now(UTC)),
        "efficiency": _efficiency(records, wall_clock_s),
        "tasks": records,
    }
    issues = validate_graded_result(result)
    if issues:
        raise RunError("graded result is invalid: " + "; ".join(map(str, issues)))
    return result
