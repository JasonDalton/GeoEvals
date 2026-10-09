"""Run a benchmark: validate the spec and manifest, run every case in a split, and score it.

Case files are JSONL, one case per line. Each case is a JSON object with:

- ``case_id`` (required, unique across the benchmark's case files)
- ``expected`` (required): the reference output. It is passed to the metrics and never to the
  adapter; the adapter gets every other field of the case.
- ``split`` (optional): the split the case belongs to. May be left out only when the spec has
  exactly one split.
- ``strata`` (optional): labels for breakdowns, copied to the case record.

Every case ends with exactly one status. An adapter that raises gives ``adapter_error`` (retried
up to ``max_retries`` times), a case that runs longer than ``timeout_s`` is killed and gives
``timeout``, output that fails the spec's ``output_schema`` gives ``invalid_output``, and anything
else is ``scored``.

Efficiency: ``latency_s`` is the adapter's wall-clock time and ``scoring_s`` the metric scoring
time of a case. ``peak_memory_bytes`` comes from ``tracemalloc`` in the worker and is measured
only with ``workers: 1``, since concurrent cases would share the figure. The run's
``efficiency`` adds throughput, latency percentiles, timeout and failure rates, retries, and the
peak RSS of the runner and its workers (sampled with ``psutil``).
"""

import hashlib
import json
import logging
import platform
import queue
import sys
import time
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from geoevals.adapters import MockAdapter, adapter_factory
from geoevals.metrics import Metric, MetricValue, get_metric, percentile
from geoevals.runner.config import RunConfig, canonical_config, config_hash
from geoevals.runner.memory import RssSampler
from geoevals.runner.worker import Attempt, Worker, WorkerSetupError
from geoevals.validation import (
    RUN_RESULT_SCHEMA_VERSION,
    BenchmarkSpec,
    ValidationIssue,
    load_benchmark_spec,
    load_dataset_manifest,
    validate_run_result_document,
)

logger = logging.getLogger(__name__)

MEMORY_NOTE_WORKERS = "per-case memory unavailable when workers > 1"
MEMORY_NOTE_KILLED = "per-case memory unavailable: the worker was killed or exited"


class RunError(RuntimeError):
    """The run could not start or finish (bad input files, adapter setup, invalid result)."""


@dataclass(frozen=True)
class Case:
    case_id: str
    split: str
    input: dict[str, Any]
    expected: Any
    strata: dict[str, Any] = field(default_factory=dict)


def _case_paths(spec: BenchmarkSpec, spec_dir: Path) -> list[Path]:
    paths = [spec.cases] if isinstance(spec.cases, str) else list(spec.cases)
    return [spec_dir / path for path in paths]


def load_cases(spec: BenchmarkSpec, spec_dir: Path) -> list[Case]:
    """Load every case of the benchmark, in case-ID order. Raises ``RunError`` on bad cases."""
    only_split = next(iter(spec.splits)) if len(spec.splits) == 1 else None
    cases: dict[str, Case] = {}
    problems: list[str] = []
    for path in _case_paths(spec, spec_dir):
        if not path.is_file():
            raise RunError(f"{path}: case file not found")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            where = f"{path}:{number}"
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"{where}: invalid JSON: {exc}")
                continue
            if not isinstance(record, dict):
                problems.append(f"{where}: a case must be a JSON object")
                continue
            case_id = record.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                problems.append(f"{where}: case_id must be a non-empty string")
                continue
            if case_id in cases:
                problems.append(f"{where}: duplicate case_id {case_id!r}")
                continue
            if "expected" not in record:
                problems.append(f"{where}: case {case_id!r} has no 'expected' reference output")
                continue
            split = record.get("split", only_split)
            if split not in spec.splits:
                problems.append(
                    f"{where}: case {case_id!r} split {split!r} is not a split of the spec "
                    f"({', '.join(sorted(spec.splits))})"
                )
                continue
            strata = record.get("strata", {})
            if not isinstance(strata, dict):
                problems.append(f"{where}: case {case_id!r} strata must be an object")
                continue
            case_input = {key: value for key, value in record.items() if key != "expected"}
            cases[case_id] = Case(case_id, split, case_input, record["expected"], strata)
    if problems:
        raise RunError("\n".join(problems))
    return [cases[case_id] for case_id in sorted(cases)]


def _adapter_config(adapter_name: str, config: RunConfig, cases: list[Case]) -> dict[str, Any]:
    """Return the config passed to ``setup``.

    The mock adapter reads reference outputs from its config, so the split's references are added
    under ``references`` (entries given explicitly in the run config win).
    """
    adapter_config = dict(config.adapter)
    if adapter_name == MockAdapter.name:
        references = {c.case_id: c.expected for c in cases if isinstance(c.expected, dict)}
        adapter_config["references"] = {**references, **adapter_config.get("references", {})}
    return adapter_config


def _output_problem(validator: Draft202012Validator, output: Any) -> tuple[str | None, bool]:
    """Return ``(problem, recordable)``: why ``output`` is invalid (``None`` when it is valid),
    and whether it can still be written to the case record."""
    if not isinstance(output, dict):
        return f"output must be a JSON object, got {type(output).__name__}", False
    try:
        json.dumps(output, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return f"output is not JSON: {exc}", False
    issues = sorted(
        (
            ValidationIssue(".".join(map(str, e.absolute_path)) or "<root>", e.message)
            for e in validator.iter_errors(output)
        ),
        key=lambda issue: (issue.field, issue.message),
    )
    return ("; ".join(map(str, issues)) or None), True


def _score(metrics: list[tuple[Metric, dict[str, Any]]], output: Any, expected: Any) -> dict:
    scores: dict[str, Any] = {}
    for metric, params in metrics:
        try:
            value = metric.score(output, expected, params)
        except Exception as exc:
            logger.exception("metric %s raised while scoring", metric.id)
            detail = {"scoring_error": f"{type(exc).__name__}: {exc}"}
            value = MetricValue(value=None, passed=False, detail=detail)
        scores[metric.id] = value.to_dict()
    return scores


def _error(type_: str | None, message: str | None) -> dict[str, str]:
    return {"type": type_ or "Error", "message": message or ""}


class _Runner:
    def __init__(
        self,
        spec: BenchmarkSpec,
        config: RunConfig,
        metrics: list[tuple[Metric, dict[str, Any]]],
    ) -> None:
        self.spec = spec
        self.config = config
        self.metrics = metrics
        self.output_validator = Draft202012Validator(spec.output_schema)

    def run_case(self, worker: Worker, case: Case) -> dict[str, Any]:
        attempts = 0
        while True:
            attempts += 1
            attempt = worker.predict(
                case.input, f"{self.config.seed}:{case.case_id}", self.config.timeout_s
            )
            if attempt.kind != "error" or attempts > self.config.max_retries:
                break
            logger.warning(
                "case %s attempt %d: %s: %s; retrying",
                case.case_id,
                attempts,
                attempt.error_type,
                attempt.error_message,
            )
        record = self._record(case, attempt, retries=attempts - 1)
        log = logger.info if record["status"] == "scored" else logger.warning
        log("case %s: %s", case.case_id, record["status"])
        return record

    def _record(self, case: Case, attempt: Attempt, retries: int) -> dict[str, Any]:
        if self.config.workers > 1:
            memory_note: str | None = MEMORY_NOTE_WORKERS
        elif attempt.peak_memory_bytes is None:
            memory_note = MEMORY_NOTE_KILLED
        else:
            memory_note = None
        record: dict[str, Any] = {
            "case_id": case.case_id,
            "split": case.split,
            "strata": case.strata,
            "output": None,
            "metrics": {},
            "latency_s": attempt.latency_s,
            "scoring_s": None,
            "retries": retries,
            "tokens": None,
            "cost_usd": None,
            "peak_memory_bytes": None if memory_note else attempt.peak_memory_bytes,
            "error": None,
        }
        if memory_note:
            record["memory_note"] = memory_note
        if attempt.kind == "timeout":
            record["status"] = "timeout"
            record["error"] = _error(attempt.error_type, attempt.error_message)
            return record
        if attempt.kind == "error":
            record["status"] = "adapter_error"
            record["error"] = _error(attempt.error_type, attempt.error_message)
            return record
        if attempt.tokens is not None:
            record["tokens"] = {"input": attempt.tokens[0], "output": attempt.tokens[1]}
        if attempt.trajectory is not None:
            record["trajectory"] = attempt.trajectory
        problem, recordable = _output_problem(self.output_validator, attempt.output)
        if problem is not None:
            record["status"] = "invalid_output"
            record["error"] = _error("InvalidOutput", problem)
            if recordable:
                record["output"] = attempt.output
            return record
        record["status"] = "scored"
        record["output"] = attempt.output
        start = time.perf_counter()
        record["metrics"] = _score(self.metrics, attempt.output, case.expected)
        record["scoring_s"] = time.perf_counter() - start
        return record


def _resolve_metrics(spec: BenchmarkSpec) -> list[tuple[Metric, dict[str, Any]]]:
    resolved = []
    for ref in spec.metrics:
        metric = get_metric(ref.id)
        if metric.version != ref.version:
            logger.warning(
                "spec asks for metric %s version %s; the registered version is %s",
                ref.id,
                ref.version,
                metric.version,
            )
        resolved.append((metric, dict(ref.params)))
    return resolved


def _efficiency(
    records: list[dict[str, Any]], wall_clock_s: float, peak_rss_bytes: int
) -> dict[str, Any]:
    """Run-level efficiency figures. Rates and percentiles are null when there are no cases."""
    total = len(records)
    latencies = sorted(r["latency_s"] for r in records if r["latency_s"] is not None)

    def latency(q: float) -> float | None:
        return percentile(latencies, q) if latencies else None

    def rate(count: int) -> float | None:
        return count / total if total else None

    return {
        "wall_clock_s": wall_clock_s,
        "cases_total": total,
        "cases_per_s": total / wall_clock_s if wall_clock_s > 0 else None,
        "latency_p50_s": latency(0.5),
        "latency_p90_s": latency(0.9),
        "latency_p99_s": latency(0.99),
        "latency_max_s": latencies[-1] if latencies else None,
        "timeout_rate": rate(sum(r["status"] == "timeout" for r in records)),
        "failure_rate": rate(sum(r["status"] != "scored" for r in records)),
        "retries_total": sum(r["retries"] for r in records),
        "peak_rss_bytes": peak_rss_bytes,
    }


def _timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def run_benchmark(spec_path: Path, adapter_name: str, config: RunConfig) -> dict[str, Any]:
    """Run ``adapter_name`` on every case of ``config.split`` and return the run result.

    Raises ``SpecValidationError`` for an invalid spec or manifest and ``RunError`` when the run
    cannot start or its result is invalid. Failing cases never raise; they get a failure status.
    """
    spec = load_benchmark_spec(spec_path)
    try:
        Draft202012Validator.check_schema(spec.output_schema)
    except SchemaError as exc:
        raise RunError(
            f"{spec_path}: output_schema is not a valid JSON Schema: {exc.message}"
        ) from exc
    if config.split not in spec.splits:
        known = ", ".join(sorted(spec.splits))
        raise RunError(f"split {config.split!r} is not a split of {spec.id} ({known})")
    manifest_path = spec_path.parent / spec.dataset_manifest
    load_dataset_manifest(manifest_path)
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    logger.info("benchmark %s %s and manifest %s are valid", spec.id, spec.version, manifest_path)

    cases = [case for case in load_cases(spec, spec_path.parent) if case.split == config.split]
    metrics = _resolve_metrics(spec)
    factory = adapter_factory(adapter_name)
    adapter = factory()
    digest = config_hash(config)
    logger.info(
        "running %d case(s) of split %s with adapter %s %s (config_hash %s)",
        len(cases),
        config.split,
        adapter.name,
        adapter.version,
        digest,
    )

    started = datetime.now(UTC)
    clock = time.perf_counter()
    runner = _Runner(spec, config, metrics)
    workers: queue.SimpleQueue[Worker] = queue.SimpleQueue()
    adapter_config = _adapter_config(adapter_name, config, cases)
    track_memory = config.workers == 1
    all_workers = [
        Worker(factory, adapter_config, track_memory)
        for _ in range(min(config.workers, max(len(cases), 1)))
    ]
    for worker in all_workers:
        workers.put(worker)

    def run_one(case: Case) -> dict[str, Any]:
        worker = workers.get()
        try:
            return runner.run_case(worker, case)
        finally:
            workers.put(worker)

    try:
        with RssSampler() as rss, ThreadPoolExecutor(max_workers=len(all_workers)) as pool:
            records = list(pool.map(run_one, cases))
    except WorkerSetupError as exc:
        raise RunError(str(exc)) from exc
    finally:
        for worker in all_workers:
            worker.close()
    wall_clock_s = time.perf_counter() - clock
    finished = datetime.now(UTC)

    summary_metrics = {}
    for metric, _ in metrics:
        values = [
            MetricValue(**r["metrics"][metric.id]) for r in records if metric.id in r["metrics"]
        ]
        summary_metrics[metric.id] = metric.summary(metric.aggregate(values))
    failures = [
        {"case_id": r["case_id"], "status": r["status"], "error": r["error"]}
        for r in records
        if r["status"] != "scored"
    ]
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    result: dict[str, Any] = {
        "run_id": f"{spec.id}-{adapter_name}-{stamp}-{digest[:8]}",
        "schema_version": RUN_RESULT_SCHEMA_VERSION,
        "benchmark": {"id": spec.id, "version": spec.version},
        "adapter": {
            "name": adapter.name,
            "version": adapter.version,
            "config": canonical_config(config)["adapter"],
        },
        "config_hash": digest,
        "dataset_manifest_hash": manifest_hash,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "started_at": _timestamp(started),
        "finished_at": _timestamp(finished),
        "summary_metrics": summary_metrics,
        "efficiency": _efficiency(records, wall_clock_s, rss.peak_rss_bytes),
        "failures": failures,
        "limitations": list(spec.limitations),
        "cases": records,
    }
    issues = validate_run_result_document(result)
    if issues:
        raise RunError("run result is invalid: " + "; ".join(map(str, issues)))
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    logger.info(
        "finished %d case(s) in %.2f s: %s",
        len(records),
        wall_clock_s,
        ", ".join(f"{status} {n}" for status, n in sorted(counts.items())) or "no cases",
    )
    return result


@contextmanager
def run_logging(log_path: Path, level: str) -> Iterator[None]:
    """Send ``geoevals`` log records to ``log_path`` and stderr at ``level`` while active."""
    root = logging.getLogger("geoevals")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ]
    previous_level = root.level
    root.setLevel(level)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    try:
        yield
    finally:
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(previous_level)


def write_result(result: Mapping[str, Any], path: Path) -> None:
    """Write a run result as JSON with sorted keys."""
    text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")
