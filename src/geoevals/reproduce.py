"""Check that a committed baseline still reproduces.

A baseline directory, such as ``baselines/<benchmark_id>/<adapter>/``, holds a run's
``result.json``, ``cases.jsonl``, ``config.yaml`` and ``report.md``. Reproducing it reruns the
benchmark named in ``result.json`` (``<benchmarks_root>/<benchmark.id>/benchmark.yaml``) with the
adapter named there and the committed ``config.yaml``, then compares the new run with the
committed one:

- per case, ``status``, ``output`` and ``metrics``, as ``geoevals compare`` does;
- the run-level fields in ``RUN_FIELDS``: what was run (benchmark, adapter, config and dataset
  hashes) and what it scored (summary metrics, failures).

Timing, memory and timestamps are never compared, nor ``run_id`` (it holds the start time) and
``environment`` (it describes the machine, not the result).

Numbers match within ``DEFAULT_TOLERANCE``. GEOS and PROJ builds differ between platforms in
the last bits: the baseline, written on macOS arm64, differed from reruns on Linux arm64 by at
most 4.4e-9 (a geodesic distance in meters) and on Linux x86_64 by at most 6.0e-9 (a projected
coordinate in meters). Everything else (status, strings, booleans, number types, list lengths,
keys) must match exactly.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from geoevals.reporting.compare import MISSING, Difference, Tolerance, compare_runs, diff_values

SPEC_FILE = "benchmark.yaml"

DEFAULT_TOLERANCE = Tolerance(abs=1e-7, rel=1e-9)
"""Absolute 1e-7 (1 cm in degrees, 0.1 um in meters); relative 1e-9."""

RUN_FIELDS = (
    "benchmark",
    "adapter",
    "config_hash",
    "dataset_manifest_hash",
    "summary_metrics",
    "failures",
)
"""Run-level fields that must match; differences are reported with the case ID ``<run>``."""

RUN_CASE_ID = "<run>"


def baseline_spec(baseline: Mapping[str, Any], benchmarks_root: Path) -> Path:
    """Path of the benchmark spec that produced ``baseline`` (a run result)."""
    return benchmarks_root / baseline["benchmark"]["id"] / SPEC_FILE


def compare_reproduction(
    baseline: Mapping[str, Any],
    rerun: Mapping[str, Any],
    tolerance: Tolerance = DEFAULT_TOLERANCE,
) -> list[Difference]:
    """Differences between a committed baseline and its rerun: run-level fields, then cases."""
    differences = []
    for name in RUN_FIELDS:
        a, b = baseline.get(name, MISSING), rerun.get(name, MISSING)
        differences += [
            Difference(RUN_CASE_ID, f, x, y) for f, x, y in diff_values(a, b, name, tolerance)
        ]
    return differences + compare_runs(baseline, rerun, tolerance)
