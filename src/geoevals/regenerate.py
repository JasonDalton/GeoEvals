"""Regenerate a benchmark's expected outputs from its reference workflow.

A benchmark with a reference workflow keeps it in ``<benchmark_dir>/reference.py``, which
defines ``reference_output(case, benchmark_dir) -> dict``: the expected output of one case,
given the case line without ``expected``. For each case of the spec, the output is written to
the case's ``expected``:

- an object: replaced inline, and the case line is rewritten;
- a string: the path, relative to the spec, of a JSON file that is (re)written.

Files are written in one canonical form: case lines as ``json.dumps`` in the line's key order,
expected files as indented JSON with sorted keys, and every float rounded as in the run
directory (``runner.layout.stable``). So regenerating twice gives the same bytes, and the
committed outputs can be checked with ``regenerate(..., write=False)``.
"""

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml

from geoevals.runner.layout import dumps, stable
from geoevals.validation import load_benchmark_spec
from geoevals.validation.validate import load_yaml

SPEC_FILE = "benchmark.yaml"
REFERENCE_FILE = "reference.py"

ReferenceOutput = Callable[[dict[str, Any], Path], dict[str, Any]]


class RegenerateError(RuntimeError):
    """The benchmark, its reference workflow or a case file cannot be read."""


def find_benchmark_dir(root: Path, benchmark_id: str) -> Path:
    """The directory under ``root`` that holds the spec of ``benchmark_id``.

    That is ``<root>/<benchmark_id>/`` when it has a spec, else the first directory (in name
    order) whose ``benchmark.yaml`` has ``id: <benchmark_id>`` (a benchmark's directory name may
    differ from its ID, as ``human_context`` holds ``human_context_access``). When none does,
    ``<root>/<benchmark_id>/``, so that the caller reports the missing spec there.
    """
    direct = root / benchmark_id
    if (direct / SPEC_FILE).is_file():
        return direct
    for spec_path in sorted(root.glob(f"*/{SPEC_FILE}")):
        try:
            document = load_yaml(spec_path)
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(document, dict) and document.get("id") == benchmark_id:
            return spec_path.parent
    return direct


def _reference_output(benchmark_dir: Path, benchmark_id: str) -> ReferenceOutput:
    path = benchmark_dir / REFERENCE_FILE
    if not path.is_file():
        raise RegenerateError(f"{path}: reference workflow not found")
    module_spec = importlib.util.spec_from_file_location(f"geoevals_reference_{benchmark_id}", path)
    if module_spec is None or module_spec.loader is None:
        raise RegenerateError(f"{path}: cannot be imported")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    function = getattr(module, "reference_output", None)
    if not callable(function):
        raise RegenerateError(f"{path}: defines no reference_output(case, benchmark_dir)")
    return cast(ReferenceOutput, function)


def expected_outputs(benchmark_dir: Path, benchmark_id: str) -> dict[Path, str]:
    """Every file the reference workflow writes for the benchmark, mapped to its content.

    Raises ``SpecValidationError`` for an invalid spec and ``RegenerateError`` when the spec ID
    is not ``benchmark_id`` or a case cannot be read.
    """
    spec_path = benchmark_dir / SPEC_FILE
    if not spec_path.is_file():
        raise RegenerateError(f"{spec_path}: benchmark spec not found")
    spec = load_benchmark_spec(spec_path)
    if spec.id != benchmark_id:
        raise RegenerateError(f"{spec_path}: id is {spec.id!r}, not {benchmark_id!r}")
    reference_output = _reference_output(benchmark_dir, benchmark_id)
    case_files = [spec.cases] if isinstance(spec.cases, str) else list(spec.cases)
    files: dict[Path, str] = {}
    for case_file in case_files:
        path = benchmark_dir / case_file
        if not path.is_file():
            raise RegenerateError(f"{path}: case file not found")
        lines = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RegenerateError(f"{path}:{number}: invalid JSON: {exc}") from exc
            if not isinstance(case, dict) or "expected" not in case:
                raise RegenerateError(f"{path}:{number}: a case must be an object with expected")
            case_input = {key: value for key, value in case.items() if key != "expected"}
            output = stable(reference_output(case_input, benchmark_dir))
            if isinstance(case["expected"], str):
                files[benchmark_dir / case["expected"]] = dumps(output) + "\n"
            else:
                case["expected"] = output
            lines.append(json.dumps(stable(case), ensure_ascii=False, allow_nan=False) + "\n")
        files[path] = "".join(lines)
    return files


def regenerate(benchmark_dir: Path, benchmark_id: str, write: bool = True) -> list[Path]:
    """Return the files whose committed content differs from the reference workflow's output
    (missing files included), and rewrite them when ``write`` is true."""
    stale = []
    for path, content in expected_outputs(benchmark_dir, benchmark_id).items():
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        stale.append(path)
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return stale
