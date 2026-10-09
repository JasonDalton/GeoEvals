"""Compare the per-case results of two runs.

Only each case's ``status``, ``output`` and ``metrics`` are compared, matched by ``case_id``.
Everything else is ignored: timing (``latency_s``, ``scoring_s``, the ``efficiency`` block),
memory (``peak_memory_bytes``, ``memory_note``), timestamps, ``run_id``, and the rest of the run
record. A case found in only one run is a difference too.

Values are compared exactly unless a ``Tolerance`` is given; it applies only to two numbers of
the same type (never to booleans), so it absorbs floating-point drift between platforms but not
a changed status, string or type.
"""

import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from geoevals.runner.layout import RESULT_FILE
from geoevals.validation import SpecValidationError, ValidationIssue, validate_run_result_file

COMPARED_FIELDS = ("status", "output", "metrics")


class _Missing:
    def __repr__(self) -> str:
        return "<missing>"


MISSING: Any = _Missing()
"""Stands for a value that one side does not have."""


@dataclass(frozen=True)
class Tolerance:
    """Two numbers match when ``|a - b| <= max(rel * max(|a|, |b|), abs)``."""

    abs: float = 0.0
    rel: float = 0.0

    def close(self, a: Any, b: Any) -> bool:
        if not (self.abs or self.rel) or type(a) is not type(b):
            return False
        if not isinstance(a, int | float) or isinstance(a, bool):
            return False
        return math.isclose(a, b, rel_tol=self.rel, abs_tol=self.abs)


EXACT = Tolerance()


@dataclass(frozen=True)
class Difference:
    case_id: str
    field: str
    """Path in the case record, such as ``output.area_m2``; empty when the case is missing."""
    a: Any
    b: Any

    def __str__(self) -> str:
        if not self.field:
            side = "a" if self.b is MISSING else "b"
            return f"{self.case_id}: only in run {side}"
        return f"{self.case_id}: {self.field}: {_show(self.a)} -> {_show(self.b)}"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _show(value: Any) -> str:
    return "<missing>" if value is MISSING else _canonical(value)


def diff_values(
    a: Any, b: Any, path: str, tolerance: Tolerance = EXACT
) -> Iterator[tuple[str, Any, Any]]:
    """Yield ``(path, a, b)`` for every leaf where ``a`` and ``b`` differ.

    Mappings are compared key by key and equal-length lists item by item; anything else is
    compared as canonical JSON, so ``1`` and ``1.0`` or ``1`` and ``true`` differ, unless
    ``tolerance`` finds two numbers close.
    """
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        for key in sorted(set(a) | set(b)):
            yield from diff_values(
                a.get(key, MISSING), b.get(key, MISSING), f"{path}.{key}", tolerance
            )
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (item_a, item_b) in enumerate(zip(a, b, strict=True)):
            yield from diff_values(item_a, item_b, f"{path}[{i}]", tolerance)
    elif a is MISSING or b is MISSING:
        if a is not b:
            yield path, a, b
    elif _canonical(a) != _canonical(b) and not tolerance.close(a, b):
        yield path, a, b


def compare_runs(
    run_a: Mapping[str, Any], run_b: Mapping[str, Any], tolerance: Tolerance = EXACT
) -> list[Difference]:
    """Per-case differences between two run results, in case-ID order."""
    cases_a = {case["case_id"]: case for case in run_a["cases"]}
    cases_b = {case["case_id"]: case for case in run_b["cases"]}
    differences = []
    for case_id in sorted(set(cases_a) | set(cases_b)):
        if case_id not in cases_b:
            differences.append(Difference(case_id, "", cases_a[case_id], MISSING))
            continue
        if case_id not in cases_a:
            differences.append(Difference(case_id, "", MISSING, cases_b[case_id]))
            continue
        for name in COMPARED_FIELDS:
            a = cases_a[case_id].get(name, MISSING)
            b = cases_b[case_id].get(name, MISSING)
            differences += [
                Difference(case_id, f, x, y) for f, x, y in diff_values(a, b, name, tolerance)
            ]
    return differences


def load_run(path: Path) -> dict[str, Any]:
    """Load and validate a run result from a run directory or a ``result.json`` path.

    Raises ``SpecValidationError`` if the file is missing or invalid.
    """
    if path.is_dir():
        path = path / RESULT_FILE
    if not path.is_file():
        raise SpecValidationError(path, [ValidationIssue("<root>", "file not found")])
    issues = validate_run_result_file(path)
    if issues:
        raise SpecValidationError(path, issues)
    return json.loads(path.read_text(encoding="utf-8"))
