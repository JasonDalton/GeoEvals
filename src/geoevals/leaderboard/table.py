"""The leaderboard table in the README, generated from committed run results.

Each accepted run is ``leaderboard/results/<benchmark_id>/<adapter>/result.json`` (with its
``config.yaml``), copied there by ``geoevals leaderboard add <run_dir>``. ``geoevals
leaderboard build`` writes the table between the README markers ``<!-- leaderboard:start -->``
and ``<!-- leaderboard:end -->``.

A run is accepted only if it comes from a Claude leaderboard adapter with the default CLI, on
the ``test`` split, and every case ran on the model: no case was skipped (a pilot with
``only_cases``, or a run stopped by the usage limit), hit the runner's own timeout, or failed
with a harness error (``claude_cli.HARNESS_ERRORS``: auth, CLI errors, an unexpected model, a
version change). The model's own failures (timeouts within ``case_timeout_s``, refusals, no or
invalid answer, the per-case budget) count as failed cases. All runs of a benchmark must share
its version, dataset manifest hash, effort and prompt version, so that rows are comparable.
Every column comes from fields the run result already has.
"""

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from geoevals.adapters.claude import MODELS
from geoevals.leaderboard.claude_cli import HARNESS_ERRORS

START = "<!-- leaderboard:start -->"
END = "<!-- leaderboard:end -->"
DEFAULT_RESULTS = Path("leaderboard/results")
RESULT_FILE = "result.json"
CONFIG_FILE = "config.yaml"
TRACKS = ("direct", "python")
SPLIT = "test"
ADAPTER_PATTERN = re.compile(rf"^claude_({'|'.join(TRACKS)})_({'|'.join(MODELS)})$")
MODEL_NAMES = {"opus_5_5": "Opus 5.5", "sonnet_5_5": "Sonnet 5.5", "haiku_5_5": "Haiku 5.5"}


class LeaderboardError(ValueError):
    """A run result cannot go on the leaderboard."""


@dataclass(frozen=True)
class Row:
    benchmark: str
    benchmark_version: str
    manifest_hash: str
    model: str
    """Model slug, for example ``opus_5_5``."""
    track: str
    success: float
    ci_low: float
    ci_high: float
    cases: int
    not_scored: int
    latency_p50_s: float | None
    latency_p90_s: float | None
    tokens_in: int
    tokens_out: int
    claude_code: str
    prompt_version: str
    effort: str

    def sort_key(self) -> tuple[str, int, int]:
        return (self.benchmark, TRACKS.index(self.track), list(MODELS).index(self.model))


def row_from_result(result: dict[str, Any], where: str) -> Row:
    """The table row of one run result. Raises ``LeaderboardError`` when it is not accepted."""
    adapter = result["adapter"]
    match = ADAPTER_PATTERN.match(adapter["name"])
    if match is None:
        raise LeaderboardError(
            f"{where}: adapter {adapter['name']!r} is not a Claude leaderboard adapter"
        )
    track, model = match.groups()
    config = adapter.get("config") or {}
    if "claude_command" in config:
        raise LeaderboardError(f"{where}: runs with a custom claude_command are not accepted")
    cases = result["cases"]
    splits = sorted({case.get("split") for case in cases}, key=str)
    if splits != [SPLIT]:
        raise LeaderboardError(f"{where}: the run covers split(s) {splits}, not only {SPLIT!r}")
    problems = {
        "skipped": [c for c in cases if c["status"] == "skipped"],
        "stopped by the runner's timeout": [c for c in cases if c["status"] == "timeout"],
        "failed in the harness": [
            c
            for c in cases
            if c["status"] == "adapter_error"
            and (c.get("error") or {}).get("type") in HARNESS_ERRORS
        ],
    }
    for reason, bad in problems.items():
        if bad:
            first = bad[0]
            error = first.get("error") or {}
            raise LeaderboardError(
                f"{where}: {len(bad)} of {len(cases)} case(s) {reason} (first: "
                f"{first['case_id']} {error.get('type', '')}: {error.get('message', '')}); "
                "only complete runs are accepted"
            )
    success = result["summary_metrics"]["task_success"]
    efficiency = result["efficiency"]
    version = str(adapter["version"])
    return Row(
        benchmark=result["benchmark"]["id"],
        benchmark_version=result["benchmark"]["version"],
        manifest_hash=result["dataset_manifest_hash"],
        model=model,
        track=track,
        success=success["mean"],
        ci_low=success["ci_low"],
        ci_high=success["ci_high"],
        cases=len(cases),
        not_scored=sum(case["status"] != "scored" for case in cases),
        latency_p50_s=efficiency["latency_p50_s"],
        latency_p90_s=efficiency["latency_p90_s"],
        tokens_in=efficiency["tokens_input_total"],
        tokens_out=efficiency["tokens_output_total"],
        claude_code=version.split("+cc.", 1)[1] if "+cc." in version else "unknown",
        prompt_version=str(config.get("prompt_version", "v1")),
        effort=str(config.get("effort", "high")),
    )


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LeaderboardError(f"{path}: cannot be read: {exc}") from exc


def load_rows(results_dir: Path) -> list[Row]:
    """Every accepted run under ``results_dir``, sorted for the table.

    Raises ``LeaderboardError`` for a run that is not accepted, and when the runs of a
    benchmark differ in benchmark version, dataset manifest hash, effort or prompt version.
    """
    rows = [
        row_from_result(_read(path), str(path))
        for path in sorted(results_dir.glob(f"*/*/{RESULT_FILE}"))
    ]
    by_benchmark: dict[str, set[tuple[str, str, str, str]]] = {}
    for row in rows:
        by_benchmark.setdefault(row.benchmark, set()).add(
            (row.benchmark_version, row.manifest_hash, row.effort, row.prompt_version)
        )
    for benchmark, variants in sorted(by_benchmark.items()):
        if len(variants) > 1:
            listed = ", ".join(
                f"{version} (manifest {digest[:8]}, effort {effort}, prompt {prompt})"
                for version, digest, effort, prompt in sorted(variants)
            )
            raise LeaderboardError(f"runs of {benchmark} are not comparable: {listed}")
    return sorted(rows, key=Row.sort_key)


def _seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _sorted_values(rows: list[Row], attribute: str) -> str:
    return ", ".join(sorted({str(getattr(row, attribute)) for row in rows}))


def render(rows: list[Row]) -> str:
    """The Markdown that goes between the README markers."""
    if not rows:
        return "No runs have been added yet. See [`leaderboard/README.md`](leaderboard/README.md)."
    lines = [
        "| Model | Track | Benchmark | Task success (95% CI) | Not scored | Latency p50 / p90 (s) "
        "| Tokens in | Tokens out |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {MODEL_NAMES[row.model]} | {row.track} | `{row.benchmark}` {row.benchmark_version} "
            f"| {row.success:.3f} [{row.ci_low:.2f}, {row.ci_high:.2f}] "
            f"| {row.not_scored} of {row.cases} "
            f"| {_seconds(row.latency_p50_s)} / {_seconds(row.latency_p90_s)} "
            f"| {row.tokens_in:,} | {row.tokens_out:,} |"
        )
    manifests = "; ".join(
        f"`{benchmark}` {version}, manifest `{digest[:12]}`"
        for benchmark, version, digest in sorted(
            {(r.benchmark, r.benchmark_version, r.manifest_hash) for r in rows}
        )
    )
    notes = [
        "",
        f"Run locally through Claude Code {_sorted_values(rows, 'claude_code')} on a Claude "
        f"subscription, effort {_sorted_values(rows, 'effort')}, prompt version "
        f"{_sorted_values(rows, 'prompt_version')}. Benchmarks: {manifests}.",
        "",
        "Task success is the mean of `task_success` over every case, with its 95% interval; cases "
        "that were not scored (errors, invalid output, timeouts) count as failures. Latency is the "
        "wall-clock time per case, including CLI startup. Tokens in count every prompt token the "
        "model processed, cache reads included; tokens out include thinking. Runs on a "
        "subscription have no per-token charge, so there is no cost column.",
    ]
    return "\n".join(lines + notes)


def update_readme(text: str, table: str) -> str:
    """``text`` with everything between the markers replaced by ``table``."""
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise LeaderboardError(f"the README must hold {START} and then {END}, once each")
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    return f"{before}{START}\n{table}\n{END}{after}"


def add_run(run_dir: Path, results_dir: Path) -> Path:
    """Copy an accepted run's result and config to ``results_dir/<benchmark>/<adapter>/``."""
    result_path = run_dir / RESULT_FILE if run_dir.is_dir() else run_dir
    result = _read(result_path)
    row_from_result(result, str(result_path))
    target = results_dir / result["benchmark"]["id"] / result["adapter"]["name"]
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(result_path, target / RESULT_FILE)
    config = result_path.parent / CONFIG_FILE
    if config.is_file():
        shutil.copyfile(config, target / CONFIG_FILE)
    return target
