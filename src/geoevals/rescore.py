"""Score a finished run's outputs again, against the current version of its benchmark.

Rerunning an adapter can be slow or costly (a model on a subscription, for example), and its
answers change from run to run. When a benchmark changes only how answers are scored (a metric
version, a tolerance, an expected output), the saved outputs can be scored again instead.

Rescoring is valid only if the adapter would have seen the same thing: the same cases, the same
prompts and inputs, the same fixtures. The command checks what the run result records (the
benchmark ID, the dataset manifest hash, the case IDs and splits, and that every scored output
still meets ``output_schema``); it cannot check prompts, which the run result does not hold.
Whoever rescores a run must check that the benchmark change did not touch them.

Only ``scored`` cases are scored again; failed cases (timeouts, adapter errors, invalid
outputs, skips) stay as they were. The run keeps its ``run_id``, timestamps, efficiency,
environment and config hash, because the run itself did not change. ``benchmark.version``,
``summary_metrics``, the spec's ``limitations`` and ``provenance`` become the current ones, and
``limitations`` gains a line that names the version the run was scored against before (lines
from earlier rescores are kept).
"""

import copy
import hashlib
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from geoevals.runner.run import (
    _output_problem,
    _provenance,
    _resolve_metrics,
    _score,
    load_cases,
    summarize_metrics,
)
from geoevals.validation import (
    load_benchmark_spec,
    load_dataset_manifest,
    validate_run_result_document,
)

NOTE_PREFIX = "Rescored"
"""Start of the ``limitations`` line that records a rescore; earlier ones are kept."""


class RescoreError(ValueError):
    """The run cannot be rescored against this benchmark."""


def rescore_run(result: Mapping[str, Any], spec_path: Path) -> dict[str, Any]:
    """A copy of ``result`` with its scored outputs scored by the benchmark at ``spec_path``.

    Raises ``RescoreError`` when the run does not fit the benchmark (see the module docstring)
    or the rescored result is invalid. ``result`` is not modified.
    """
    spec = load_benchmark_spec(spec_path)
    previous = result["benchmark"]
    if previous["id"] != spec.id:
        raise RescoreError(f"the run is of benchmark {previous['id']}, not {spec.id}")
    manifest_path = spec_path.parent / spec.dataset_manifest
    manifest = load_dataset_manifest(manifest_path)
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if result["dataset_manifest_hash"] != manifest_hash:
        raise RescoreError(
            f"the run used dataset manifest {result['dataset_manifest_hash'][:12]}, "
            f"the benchmark has {manifest_hash[:12]}"
        )
    records = copy.deepcopy(list(result["cases"]))
    splits = {record["split"] for record in records}
    cases = {
        case.case_id: case for case in load_cases(spec, spec_path.parent) if case.split in splits
    }
    run_ids = [(record["case_id"], record["split"]) for record in records]
    spec_ids = sorted((case.case_id, case.split) for case in cases.values())
    if sorted(run_ids) != spec_ids:
        missing = sorted(set(spec_ids) - set(run_ids))
        extra = sorted(set(run_ids) - set(spec_ids))
        raise RescoreError(
            f"the run's cases differ from the benchmark's: missing case(s) {missing}, "
            f"extra case(s) {extra}"
        )

    validator = Draft202012Validator(spec.output_schema)
    metrics = _resolve_metrics(spec)
    for record in records:
        if record["status"] != "scored":
            continue
        problem, _ = _output_problem(validator, record["output"])
        if problem is not None:
            raise RescoreError(
                f"case {record['case_id']}: the output no longer meets the output schema: {problem}"
            )
        case = cases[record["case_id"]]
        start = time.perf_counter()
        record["metrics"] = _score(metrics, record["output"], case.expected, case.params)
        record["scoring_s"] = time.perf_counter() - start

    earlier_notes = [line for line in result["limitations"] if line.startswith(NOTE_PREFIX)]
    note = (
        f"{NOTE_PREFIX} against {spec.id} {spec.version} from saved outputs; previously scored "
        f"against {previous['id']} {previous['version']}."
    )
    rescored = {
        **copy.deepcopy(dict(result)),
        "benchmark": {"id": spec.id, "version": spec.version},
        "summary_metrics": summarize_metrics(metrics, records),
        "limitations": [*spec.limitations, *earlier_notes, note],
        "provenance": _provenance(spec, manifest),
        "cases": records,
    }
    issues = validate_run_result_document(rescored)
    if issues:
        raise RescoreError("rescored result is invalid: " + "; ".join(map(str, issues)))
    return rescored
