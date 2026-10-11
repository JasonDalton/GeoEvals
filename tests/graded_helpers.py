"""Helpers for the graded-eval tests: a writable copy of the sample eval and a data directory
with the synthetic city's layers."""

import shutil
from pathlib import Path

import yaml

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
