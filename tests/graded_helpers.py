"""Helpers for the graded-eval tests: a writable copy of the sample eval and a data directory
with the synthetic city's layers."""

import json
import shutil
from pathlib import Path

import yaml

from geoevals.graded.city import layers_sha256
from geoevals.graded.keys import regenerate_keys
from geoevals.validation.validate import load_yaml
from graded_city import build_data_dir

REPO = Path(__file__).parent.parent
SAMPLE = REPO / "tests" / "fixtures" / "graded" / "sample" / "eval.yaml"
PATH_FIELDS = ("rubric_criteria", "reference", "dataset_manifest")


def copy_sample_eval(root: Path) -> Path:
    """Copy the sample eval to ``root/sample/`` with absolute paths to the shared files, so that
    tests can rewrite its tasks; return the copy's ``eval.yaml``."""
    directory = root / "sample"
    directory.mkdir(parents=True)
    shutil.copy(SAMPLE.parent / "tasks.jsonl", directory / "tasks.jsonl")
    document = load_yaml(SAMPLE)
    for field in PATH_FIELDS:
        document[field] = str((SAMPLE.parent / document[field]).resolve())
    path = directory / "eval.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def sample_data(root: Path) -> Path:
    """A data directory (``layers/``) holding the synthetic city."""
    return build_data_dir(root / "data")


ANSWER = {"status": "ok", "answer": "North Pharmacy (node/500) is nearest on foot: 330 m."}


def graded_run_dir(
    root: Path, statuses: dict[str, str], adapter: str = "claude_python_haiku_5_5"
) -> tuple[Path, Path]:
    """A graded run of the sample eval with the given task statuses, its eval under
    ``root/evals/sample/`` and keys regenerated; return (run directory, data directory)."""
    spec_path = copy_sample_eval(root / "evals")
    data = sample_data(root)
    regenerate_keys(spec_path, data)
    tasks = []
    for task_id, status in statuses.items():
        answered = status == "answered"
        tasks.append(
            {
                "task_id": task_id,
                "status": status,
                "output": ANSWER if answered else None,
                "latency_s": 1.0,
                "retries": 0,
                "tokens": {"input": 10, "output": 5},
                "error": None if answered else {"type": "ClaudeTimeout", "message": "slow"},
            }
        )
    result = {
        "run_id": "sample-" + adapter + "-20261011T000000Z-00000000",
        "schema_version": "1.0.0",
        "eval": {"id": "sample", "version": "0.1.0"},
        "adapter": {"name": adapter, "version": "0.1.0+cc.9.9.9", "config": {"effort": "high"}},
        "config_hash": "0" * 64,
        "dataset_manifest_hash": "1" * 64,
        "data_sha256": layers_sha256(data / "layers"),
        "environment": {},
        "started_at": "2026-10-11T00:00:00.000000Z",
        "finished_at": "2026-10-11T00:01:00.000000Z",
        "efficiency": {
            "wall_clock_s": 60.0,
            "latency_p50_s": 1.0,
            "latency_p90_s": 1.0,
            "tokens_input_total": 10 * len(tasks),
            "tokens_output_total": 5 * len(tasks),
        },
        "tasks": tasks,
    }
    run_dir = root / "runs" / result["run_id"]
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return run_dir, data
