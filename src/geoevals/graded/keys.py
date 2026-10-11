"""Reference keys: computed from the city, kept out of git, checked by their hashes.

A task's key is OpenStreetMap-derived, so it is never committed (``docs/data-governance.md``).
``regenerate_keys`` computes every key of an eval with its reference script, writes them to
``<data dir>/keys/<eval id>.jsonl`` (a gitignored path), and records each key's SHA-256 in the
committed ``tasks.jsonl`` (``key_sha256``). A key's hash is the SHA-256 of its canonical JSON
(sorted keys, no spaces); keys round floats to 0.1, so the hash is the same on every platform.

``load_keys`` reads the keys file for grading and refuses a missing file or a key whose hash
differs from the committed one: the grader must see the keys the tasks were reviewed with.

The data directory holds ``layers/`` (``geoevals evals build-city``) and ``keys/``. By default
it is the directory of the city's dataset manifest asset (``data/raw/osm_city_<town>/``).
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from geoevals.data.fetch import ensure_ignored
from geoevals.graded.city import LAYERS_DIR, load_layers
from geoevals.graded.reference import load_reference
from geoevals.graded.spec import load_tasks, spec_file
from geoevals.validation import load_dataset_manifest, load_eval_spec

KEYS_DIR = "keys"


class KeysError(RuntimeError):
    """Keys cannot be computed, or the keys file is missing or stale."""


def canonical_key(key: Any) -> str:
    return json.dumps(
        key, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def key_sha256(key: Any) -> str:
    return hashlib.sha256(canonical_key(key).encode("utf-8")).hexdigest()


def keys_path(data_dir: Path, eval_id: str) -> Path:
    return data_dir / KEYS_DIR / f"{eval_id}.jsonl"


def default_data_dir(spec_path: Path) -> Path:
    """The directory of the city's dataset manifest asset."""
    spec = load_eval_spec(spec_path)
    manifest_path = spec_file(spec_path, spec.dataset_manifest)
    asset = load_dataset_manifest(manifest_path).assets[0]
    return Path(os.path.normpath(manifest_path.parent / asset.path)).parent


def compute_keys(spec_path: Path, data_dir: Path) -> dict[str, dict[str, Any]]:
    """Every task's key, by task ID. Raises ``KeysError`` naming the task that failed."""
    spec = load_eval_spec(spec_path)
    compute = load_reference(spec_path, spec)
    layers = load_layers(data_dir / LAYERS_DIR)
    keys = {}
    for task in load_tasks(spec_path, spec):
        try:
            keys[task.task_id] = compute(task.key_type, task.params, layers)
        except ValueError as exc:
            raise KeysError(f"{task.task_id}: {exc}") from exc
    return keys


def regenerate_keys(spec_path: Path, data_dir: Path, write: bool = True) -> list[str]:
    """Compute the keys; return the IDs of tasks whose committed ``key_sha256`` is stale.

    With ``write``, write the keys file and update the stale hashes in ``tasks.jsonl`` (each line
    keeps its key order).
    """
    spec = load_eval_spec(spec_path)
    tasks = load_tasks(spec_path, spec)
    keys = compute_keys(spec_path, data_dir)
    stale = [t.task_id for t in tasks if t.key_sha256 != key_sha256(keys[t.task_id])]
    if not write:
        return stale
    path = keys_path(data_dir, spec.id)
    ensure_ignored(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps({"task_id": t.task_id, "key": keys[t.task_id]}, ensure_ascii=False) + "\n"
            for t in tasks
        ),
        encoding="utf-8",
    )
    if stale:
        tasks_file = spec_file(spec_path, spec.tasks)
        lines = []
        for line in tasks_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            task = json.loads(line)
            task["key_sha256"] = key_sha256(keys[task["task_id"]])
            lines.append(json.dumps(task, ensure_ascii=False) + "\n")
        tasks_file.write_text("".join(lines), encoding="utf-8")
    return stale


def load_keys(spec_path: Path, data_dir: Path) -> dict[str, dict[str, Any]]:
    """The keys of every task, checked against the committed hashes. Raises ``KeysError``."""
    spec = load_eval_spec(spec_path)
    path = keys_path(data_dir, spec.id)
    if not path.is_file():
        raise KeysError(f"{path}: no keys file; run `geoevals evals regenerate {spec.id}`")
    stored = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            stored[entry["task_id"]] = entry["key"]
    keys = {}
    for task in load_tasks(spec_path, spec):
        key = stored.get(task.task_id)
        if key is None or task.key_sha256 is None or key_sha256(key) != task.key_sha256:
            raise KeysError(
                f"{task.task_id}: the key in {path} does not match key_sha256 in the tasks; run "
                f"`geoevals evals regenerate {spec.id}` and review the change"
            )
        keys[task.task_id] = key
    return keys
