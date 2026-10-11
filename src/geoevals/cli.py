"""Command-line entry point for ``geoevals``."""

import argparse
import dataclasses
import json
import logging
import os
import sys
import tempfile
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from geoevals import __version__
from geoevals.adapters import create_adapter, registered_adapter_names
from geoevals.data.fetch import (
    DEFAULT_MANIFESTS,
    Bbox,
    FetchError,
    ensure_ignored,
    fetch_dataset,
    manifest_path,
    parse_bbox,
)
from geoevals.data.inventory import DEFAULT_README, InventoryError, update_inventory
from geoevals.data.licenses import DEFAULT_REPORT, render_report, runtime_dependencies
from geoevals.data.verify import verify_manifest
from geoevals.graded.board import (
    DEFAULT_GRADED,
    GRADED_END,
    GRADED_START,
    GradedError,
    add_graded_run,
    is_graded_result,
    load_graded,
    render_graded,
)
from geoevals.graded.city import LAYERS_DIR, convert_extract, write_layers
from geoevals.graded.grader import GRADES_FILE, GradeError, GraderConfig, grade_run
from geoevals.graded.keys import default_data_dir, regenerate_keys
from geoevals.graded.run import run_eval
from geoevals.graded.spec import find_eval_spec
from geoevals.graded.towns import EXTRACT_FILE, fetch_candidate, measure_layers, stats_table
from geoevals.leaderboard.table import (
    DEFAULT_RESULTS,
    LeaderboardError,
    add_run,
    load_rows,
    render,
    replace_section,
    update_readme,
)
from geoevals.regenerate import RegenerateError, find_benchmark_dir, regenerate
from geoevals.reporting.compare import Tolerance, compare_runs, load_run
from geoevals.reporting.report import REPORT_HTML, write_report
from geoevals.reproduce import DEFAULT_TOLERANCE, baseline_spec, compare_reproduction
from geoevals.rescore import RescoreError, rescore_run
from geoevals.runner.config import RunConfigError, load_run_config
from geoevals.runner.cost import PriceTable, PriceTableError, load_price_table
from geoevals.runner.layout import (
    CASES_FILE,
    CONFIG_FILE,
    LOG_FILE,
    RESULT_FILE,
    write_cases,
    write_config,
    write_result,
    write_run_dir,
)
from geoevals.runner.run import RunError, run_benchmark, run_logging
from geoevals.validation import (
    SpecValidationError,
    load_dataset_manifest,
    validate_file,
    validate_run_result_file,
)
from geoevals.validation.validate import load_yaml

logger = logging.getLogger("geoevals.cli")

GRADER_COMMAND: tuple[str, ...] = ("claude",)
DEFAULT_PRICES = Path("examples/prices.example.yaml")
"""Relative to the working directory, like the other paths on the command line."""

DEFAULT_BENCHMARKS = Path("benchmarks")
"""Directory holding one directory per benchmark, relative to the working directory."""


def add_adapter_argument(parser: argparse.ArgumentParser) -> None:
    """Add ``--adapter <name>``, limited to the registered adapter names."""
    parser.add_argument(
        "--adapter",
        required=True,
        choices=sorted(registered_adapter_names()),
        help="Registered adapter name.",
    )


def add_tolerance_arguments(parser: argparse.ArgumentParser, default: Tolerance) -> None:
    """Add ``--abs-tol`` and ``--rel-tol``: two numbers match within either tolerance."""
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=default.abs,
        help=f"Numbers within this absolute difference match (default: {default.abs:g}).",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=default.rel,
        help=f"Numbers within this relative difference match (default: {default.rel:g}).",
    )


def _bbox_argument(text: str) -> tuple[float, float, float, float]:
    try:
        return parse_bbox(text)
    except FetchError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geoevals",
        description="Reproducible evaluation framework for geospatial AI systems.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    validate = subparsers.add_parser(
        "validate",
        help="Validate a benchmark spec (YAML), dataset manifest (YAML or JSONL), "
        "or run result (<run-dir>/result.json).",
    )
    validate.add_argument(
        "path", type=Path, help="Path to a benchmark spec, dataset manifest, or run result."
    )

    data = subparsers.add_parser("data", help="Dataset tools.")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    verify = data_commands.add_parser(
        "verify", help="Recompute SHA-256 checksums of a manifest's local assets."
    )
    verify.add_argument("manifest", type=Path, help="Path to a dataset manifest.")
    fetch = data_commands.add_parser(
        "fetch",
        help="Download a dataset that may not be committed into its gitignored path (data/raw/) "
        "and record its access date and SHA-256 there; never writes into a tracked path.",
    )
    fetch.add_argument("dataset_id", help="Dataset ID: <manifests>/<dataset_id>.yaml.")
    fetch.add_argument(
        "--manifests",
        type=Path,
        default=DEFAULT_MANIFESTS,
        help=f"Directory of dataset manifests (default: {DEFAULT_MANIFESTS}).",
    )
    fetch.add_argument(
        "--bbox",
        type=_bbox_argument,
        help="min_lon,min_lat,max_lon,max_lat (default: the manifest asset's bbox).",
    )
    fetch.add_argument(
        "--date",
        help="Snapshot date YYYY-MM-DD (default: the manifest asset's time_range end).",
    )
    fetch.add_argument(
        "--out",
        type=Path,
        help="Directory to write into; must be gitignored (default: the directory of the "
        "manifest asset's path).",
    )

    inventory = data_commands.add_parser(
        "inventory",
        help="Regenerate the license inventory table in datasets/README.md from every "
        "manifest under benchmarks/ and datasets/manifests/.",
    )
    inventory.add_argument(
        "--root", type=Path, default=Path("."), help="Repository root (default: .)."
    )
    inventory.add_argument(
        "--readme",
        type=Path,
        help=f"README holding the table (default: <root>/{DEFAULT_README}).",
    )
    inventory.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the committed table is out of date.",
    )
    licenses = data_commands.add_parser(
        "licenses",
        help="Write the license report of the installed runtime dependencies; exit 1 on a GPL "
        "or AGPL dependency.",
    )
    licenses.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Markdown report to write (default: {DEFAULT_REPORT}).",
    )

    adapters = subparsers.add_parser("adapters", help="Adapter tools.")
    adapter_commands = adapters.add_subparsers(dest="adapters_command", required=True)
    adapter_commands.add_parser("list", help="List registered adapter names.")
    predict = adapter_commands.add_parser(
        "predict", help="Run one adapter on one case input (JSON) and print the response."
    )
    add_adapter_argument(predict)
    predict.add_argument("--config", type=Path, help="Adapter config (YAML).")
    predict.add_argument("case_input", type=Path, help="Path to a case input (JSON object).")

    run = subparsers.add_parser("run", help="Run an adapter on every case of a benchmark split.")
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--benchmark", type=Path, help="Benchmark spec (YAML).")
    target.add_argument(
        "--eval",
        type=Path,
        help="Graded eval spec (eval.yaml): answers only; score them with `geoevals grade`.",
    )
    add_adapter_argument(run)
    run.add_argument("--config", type=Path, required=True, help="Run config (YAML).")
    run.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Parent directory; the run is written to <out>/<run_id>/.",
    )
    run.add_argument(
        "--data",
        type=Path,
        help="Graded evals: the data directory with layers/ (default: the city manifest asset's "
        "directory).",
    )
    run.add_argument(
        "--prices",
        type=Path,
        help=f"Price table (YAML) for cost_usd (default: {DEFAULT_PRICES}; costs are null "
        "when the default file does not exist).",
    )
    run.add_argument(
        "--log-level",
        default="INFO",
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level for run.log and stderr (default: INFO).",
    )
    run.add_argument(
        "--report",
        action="store_true",
        help="After the run, write report.md and report.html into the run directory.",
    )
    run.add_argument(
        "--open",
        action="store_true",
        help="Like --report, then open report.html in the default web browser (set by the "
        "BROWSER environment variable, if any).",
    )

    compare = subparsers.add_parser(
        "compare",
        help="List per-case differences in status, output and metrics between two runs "
        "(exit 0: none, 1: some, 2: a run could not be read).",
    )
    compare.add_argument("run_a", type=Path, help="Run directory or its result.json.")
    compare.add_argument("run_b", type=Path, help="Run directory or its result.json.")
    add_tolerance_arguments(compare, Tolerance())

    report = subparsers.add_parser(
        "report",
        help="Write report.md and report.html into a run directory (exit 2: the run could not "
        "be read).",
    )
    report.add_argument("run_dir", type=Path, help="Run directory or its result.json.")

    reproduce = subparsers.add_parser(
        "reproduce",
        help="Rerun a committed baseline with its config.yaml and compare the new run with its "
        "result.json, ignoring timing, memory, timestamps and the environment (exit 0: no "
        "differences, 1: differences or the rerun failed, 2: the baseline could not be read).",
    )
    reproduce.add_argument(
        "baseline_dir", type=Path, help="Baseline directory with result.json and config.yaml."
    )
    reproduce.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_BENCHMARKS,
        help="Directory of benchmark directories; the spec is "
        f"<root>/<benchmark id>/benchmark.yaml (default: {DEFAULT_BENCHMARKS}).",
    )
    reproduce.add_argument(
        "--out",
        type=Path,
        help="Keep the rerun in <out>/<run_id>/ (default: a temporary directory, deleted "
        "afterwards).",
    )
    add_tolerance_arguments(reproduce, DEFAULT_TOLERANCE)
    reproduce.add_argument(
        "--log-level",
        default="WARNING",
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level for the rerun (default: WARNING).",
    )

    rescore = subparsers.add_parser(
        "rescore",
        help="Score a run's saved outputs again with the current version of its benchmark and "
        "rewrite its result.json (and cases.jsonl, if present). Only valid when the benchmark "
        "change left the prompts, inputs and fixtures as they were (exit 0: rescored, 1: the "
        "run does not fit the benchmark, 2: the run could not be read).",
    )
    rescore.add_argument("run_dir", type=Path, help="Run directory with result.json.")
    rescore.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_BENCHMARKS,
        help="Directory of benchmark directories; the spec is "
        f"<root>/<benchmark id>/benchmark.yaml (default: {DEFAULT_BENCHMARKS}).",
    )

    bench = subparsers.add_parser("bench", help="Benchmark authoring tools.")
    bench_commands = bench.add_subparsers(dest="bench_command", required=True)
    regen = bench_commands.add_parser(
        "regenerate",
        help="Recompute every expected output of a benchmark with its reference workflow "
        "(reference.py in the benchmark's directory under --root).",
    )
    regen.add_argument(
        "benchmark_id",
        help="Benchmark ID: its directory name under --root, or the id in that directory's "
        "benchmark.yaml.",
    )
    regen.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_BENCHMARKS,
        help=f"Directory of benchmark directories (default: {DEFAULT_BENCHMARKS}).",
    )
    regen.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; exit 1 when a committed expected output is out of date.",
    )
    build = bench_commands.add_parser(
        "build",
        help="Build a pilot benchmark from fetched data (settings in <root>/*/pilot.yaml), "
        "with a data report, into a gitignored directory.",
    )
    build.add_argument("pilot_id", help="The id in a pilot.yaml under --root.")
    build.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_BENCHMARKS,
        help=f"Directory of benchmark directories (default: {DEFAULT_BENCHMARKS}).",
    )
    build.add_argument(
        "--source",
        type=Path,
        help="Directory written by `geoevals data fetch` (default: the directory of the "
        "dataset manifest asset's path).",
    )
    build.add_argument(
        "--out",
        type=Path,
        help="Directory to write the benchmark into; must be gitignored and is replaced "
        "(default: <source>/benchmark).",
    )
    leaderboard = subparsers.add_parser("leaderboard", help="Claude model leaderboard tools.")
    leaderboard_commands = leaderboard.add_subparsers(dest="leaderboard_command", required=True)
    add = leaderboard_commands.add_parser(
        "add",
        help="Copy a complete Claude run's result.json and config.yaml to "
        "<results>/<benchmark>/<adapter>/.",
    )
    add.add_argument("run_dir", type=Path, help="Run directory or its result.json.")
    add.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help=f"Leaderboard results directory (default: {DEFAULT_RESULTS}).",
    )
    add.add_argument(
        "--graded",
        type=Path,
        default=DEFAULT_GRADED,
        help=f"Graded leaderboard directory (default: {DEFAULT_GRADED}).",
    )
    board = leaderboard_commands.add_parser(
        "build",
        help="Write the leaderboard table into the README between its leaderboard markers.",
    )
    board.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help=f"Leaderboard results directory (default: {DEFAULT_RESULTS}).",
    )
    board.add_argument(
        "--graded",
        type=Path,
        default=DEFAULT_GRADED,
        help=f"Graded leaderboard directory (default: {DEFAULT_GRADED}).",
    )
    board.add_argument(
        "--readme",
        type=Path,
        default=Path("README.md"),
        help="README to update (default: README.md).",
    )
    board.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; exit 1 when the README table is out of date.",
    )
    grade = subparsers.add_parser(
        "grade",
        help="Grade a graded run's answers with Claude Opus 5.5 (two passes per answer, on the "
        "local Claude subscription) and write grades.json into the run directory.",
    )
    grade.add_argument("run_dir", type=Path, help="Graded run directory (with result.json).")
    grade.add_argument(
        "--data",
        type=Path,
        help="Data directory with keys/ (default: the city manifest asset's directory).",
    )
    grade.add_argument(
        "--evals", type=Path, default=Path("evals"), help="Directory of evals (default: evals)."
    )
    grade.add_argument(
        "--passes", type=int, default=2, help="Grading passes per answer (default: 2)."
    )
    evals = subparsers.add_parser("evals", help="Graded eval tools (agent-graded, not benchmarks).")
    evals_commands = evals.add_subparsers(dest="evals_command", required=True)
    measure = evals_commands.add_parser(
        "measure-town",
        help="Fetch a candidate town's OpenStreetMap extract at a snapshot date into a gitignored "
        "directory, convert it to layers and print its measurement row.",
    )
    measure.add_argument("--name", required=True, help="Town name, for the table.")
    measure.add_argument(
        "--bbox", required=True, type=parse_bbox, help="min_lon,min_lat,max_lon,max_lat."
    )
    measure.add_argument("--date", required=True, help="Snapshot date, YYYY-MM-DD.")
    measure.add_argument(
        "--out",
        type=Path,
        default=Path("data/raw/town_candidates"),
        help="Parent directory of the fetch (default: data/raw/town_candidates).",
    )
    measure.add_argument(
        "--source",
        type=Path,
        help=f"Measure an existing fetch (a directory with {EXTRACT_FILE}) instead of fetching.",
    )
    build_city = evals_commands.add_parser(
        "build-city",
        help="Convert a fetched city extract (`geoevals data fetch osm_city_<town>`) into "
        "GeoParquet layers in <source>/layers/.",
    )
    build_city.add_argument("dataset_id", help="The city's dataset ID, osm_city_<town>.")
    build_city.add_argument(
        "--manifests",
        type=Path,
        default=DEFAULT_MANIFESTS,
        help=f"Directory of dataset manifests (default: {DEFAULT_MANIFESTS}).",
    )
    build_city.add_argument(
        "--source",
        type=Path,
        help="Directory of the fetched extract (default: the manifest asset's directory).",
    )
    regen_keys = evals_commands.add_parser(
        "regenerate",
        help="Compute an eval's reference keys from the city layers, write them to the gitignored "
        "data directory and update key_sha256 in its tasks.jsonl.",
    )
    regen_keys.add_argument("eval_id", help="The eval ID (a directory under --root).")
    regen_keys.add_argument(
        "--root", type=Path, default=Path("evals"), help="Directory of evals (default: evals)."
    )
    regen_keys.add_argument(
        "--data",
        type=Path,
        help="Data directory with layers/ (default: the city manifest asset's directory).",
    )
    regen_keys.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; exit 1 when a committed key_sha256 is out of date.",
    )
    return parser


def _leaderboard_add(run_dir: Path, results: Path, graded: Path) -> int:
    try:
        result_path = run_dir / "result.json" if run_dir.is_dir() else run_dir
        document = json.loads(result_path.read_text(encoding="utf-8"))
        if is_graded_result(document):
            target = add_graded_run(run_dir, graded)
        else:
            target = add_run(run_dir, results)
    except (LeaderboardError, GradedError, SpecValidationError, OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"added {target}")
    return 0


def _leaderboard_build(results: Path, readme: Path, check: bool, graded: Path) -> int:
    try:
        text = readme.read_text(encoding="utf-8")
        updated = update_readme(text, render(load_rows(results)))
        rows, agreements = load_graded(graded)
        updated = replace_section(
            updated, GRADED_START, GRADED_END, render_graded(rows, agreements)
        )
    except (OSError, LeaderboardError, GradedError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if updated == text:
        print(f"{readme}: leaderboard is up to date")
        return 0
    if check:
        print(f"{readme}: leaderboard is out of date; run `geoevals leaderboard build`")
        return 1
    readme.write_text(updated, encoding="utf-8")
    print(f"{readme}: leaderboard written")
    return 0


def _print_issues(path: Path, issues: Sequence[object]) -> None:
    for issue in issues:
        print(f"{path}: {issue}", file=sys.stderr)
    print(f"{path}: invalid ({len(issues)} error(s))", file=sys.stderr)


def _validate(path: Path) -> int:
    if not path.is_file():
        print(f"{path}: file not found", file=sys.stderr)
        return 1
    kind, issues = validate_file(path)
    if issues:
        _print_issues(path, issues)
        return 1
    print(f"{path}: valid {kind}")
    return 0


def _data_verify(manifest: Path) -> int:
    if not manifest.is_file():
        print(f"{manifest}: file not found", file=sys.stderr)
        return 1
    try:
        checks = verify_manifest(manifest)
    except SpecValidationError as exc:
        _print_issues(manifest, exc.issues)
        return 1
    for check in checks:
        line = f"{check.asset_id}: {check.status} ({check.path})"
        if check.status == "checksum_mismatch":
            line += f" expected {check.expected}, got {check.actual}"
        print(line)
    failed = sum(check.status != "ok" for check in checks)
    if failed:
        summary = f"{failed} of {len(checks)} asset(s) failed verification"
        print(f"{manifest}: {summary}", file=sys.stderr)
        return 1
    return 0


def _data_inventory(root: Path, readme: Path | None, check: bool) -> int:
    readme = readme or root / DEFAULT_README
    try:
        stale = update_inventory(root, readme, write=not check)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except (InventoryError, FileNotFoundError) as exc:
        print(f"{readme}: {exc}", file=sys.stderr)
        return 1
    if not stale:
        print(f"{readme}: license inventory is up to date")
        return 0
    if check:
        print(
            f"{readme}: license inventory is out of date; run `geoevals data inventory`",
            file=sys.stderr,
        )
        return 1
    print(f"{readme}: license inventory written")
    return 0


def _data_licenses(out: Path) -> int:
    dependencies = runtime_dependencies()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(dependencies), encoding="utf-8")
    print(f"{out}: {len(dependencies)} runtime dependencies")
    copyleft = [dep for dep in dependencies if dep.copyleft]
    for dep in copyleft:
        print(
            f"{dep.name} {dep.version}: {dep.license} is not compatible with the MIT license",
            file=sys.stderr,
        )
    return 1 if copyleft else 0


def _data_fetch(
    dataset_id: str, manifests: Path, bbox: Any, date: str | None, out: Path | None
) -> int:
    try:
        record = fetch_dataset(dataset_id, manifests, out, bbox, date)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except FetchError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{record.path}: {record.bytes} bytes, sha256 {record.sha256}")
    print(f"access_date {record.access_date}, snapshot {record.snapshot_date}, bbox {record.bbox}")
    if bbox is None and date is None:
        committed = load_yaml(manifest_path(dataset_id, manifests))["assets"][0]["sha256"]
        if committed != record.sha256:
            print(
                f"warning: the committed manifest records sha256 {committed}; the server "
                "returned different data for the same bounding box and date",
                file=sys.stderr,
            )
    return 0


def _bench_build(pilot_id: str, root: Path, source: Path | None, out: Path | None) -> int:
    # Imported here: only this command needs numpy and the pilot code.
    from geoevals.pilot import PilotError, build_pilot

    try:
        result = build_pilot(pilot_id, root, source, out)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except (PilotError, FetchError, RegenerateError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{result.out_dir}: {result.cases} cases from {result.origins} origins")
    print(result.report)
    return 0


def _adapters_predict(adapter_name: str, config_path: Path | None, case_path: Path) -> int:
    config = load_yaml(config_path) if config_path is not None else {}
    if not isinstance(config, dict):
        print(f"{config_path}: adapter config must be a mapping", file=sys.stderr)
        return 1
    case_input = json.loads(case_path.read_text(encoding="utf-8"))
    if not isinstance(case_input, dict):
        print(f"{case_path}: case input must be a JSON object", file=sys.stderr)
        return 1
    adapter = create_adapter(adapter_name)
    adapter.setup(config)
    try:
        response = adapter.predict(case_input)
    except Exception as exc:
        print(f"{adapter_name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        adapter.teardown()
    print(json.dumps(dataclasses.asdict(response), indent=2, sort_keys=True, default=str))
    return 0


def _load_prices(path: Path | None) -> PriceTable | None:
    """Load the price table. A missing default file gives None; a missing explicit file raises."""
    if path is None:
        if not DEFAULT_PRICES.is_file():
            logger.warning("%s not found; running without a price table", DEFAULT_PRICES)
            return None
        path = DEFAULT_PRICES
    if not path.is_file():
        raise PriceTableError(f"{path}: file not found")
    try:
        return load_price_table(path)
    except PriceTableError as exc:
        raise PriceTableError(f"{path}: {exc}") from exc


def _run(
    benchmark: Path,
    adapter_name: str,
    config_path: Path,
    out: Path,
    level: str,
    prices_path: Path | None = None,
    report: bool = False,
    open_report: bool = False,
) -> int:
    run_dir = _run_to_dir(benchmark, adapter_name, config_path, out, level, prices_path)
    if run_dir is None:
        return 1
    print(run_dir)
    if not (report or open_report):
        return 0
    status = _report(run_dir)
    if status == 0 and open_report:
        html = (run_dir / REPORT_HTML).resolve()
        if not webbrowser.open(html.as_uri()):
            print(f"{html}: no web browser found; open the file by hand", file=sys.stderr)
    return status


def _run_to_dir(
    benchmark: Path,
    adapter_name: str,
    config_path: Path,
    out: Path,
    level: str,
    prices_path: Path | None = None,
) -> Path | None:
    """Run a benchmark into ``<out>/<run_id>/``; return that directory, or None on failure."""
    for path in (benchmark, config_path):
        if not path.is_file():
            print(f"{path}: file not found", file=sys.stderr)
            return None
    try:
        config = load_run_config(config_path)
    except RunConfigError as exc:
        print(f"{config_path}: {exc}", file=sys.stderr)
        return None
    run_dir: Path | None = None
    with run_logging(level) as run_log:

        def start(run_id: str) -> None:
            nonlocal run_dir
            run_dir = out / run_id
            try:
                run_dir.mkdir(parents=True)
            except FileExistsError:
                raise RunError(f"{run_dir} already exists; not overwriting it") from None
            run_log.attach(run_dir / LOG_FILE)
            write_config(config, run_dir / CONFIG_FILE)
            logger.info("writing run %s to %s", run_id, run_dir)

        try:
            prices = _load_prices(prices_path)
        except PriceTableError as exc:
            logger.error("%s", exc)
            return None
        try:
            result = run_benchmark(benchmark, adapter_name, config, prices, on_start=start)
        except SpecValidationError as exc:
            # Logged rather than printed so the reason also lands in run.log once the run
            # directory exists (an invalid spec stops the run before that).
            for issue in exc.issues:
                logger.error("%s: %s", exc.path, issue)
            logger.error("%s: invalid (%d error(s))", exc.path, len(exc.issues))
            return None
        except (RunError, ValueError) as exc:
            logger.error("run failed: %s", exc)
            return None
        assert run_dir is not None
        write_run_dir(result, run_dir)
        issues = validate_run_result_file(run_dir / RESULT_FILE)
        if issues:
            for issue in issues:
                logger.error("%s: %s", run_dir / RESULT_FILE, issue)
            logger.error("%s: invalid run result", run_dir / RESULT_FILE)
            return None
    return run_dir


def _run_eval(
    spec_path: Path, adapter_name: str, config_path: Path, out: Path, data: Path | None, level: str
) -> int:
    for path in (spec_path, config_path):
        if not path.is_file():
            print(f"{path}: file not found", file=sys.stderr)
            return 1
    try:
        config = load_run_config(config_path)
        data_dir = data or default_data_dir(spec_path)
    except (RunConfigError, SpecValidationError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    run_dir: Path | None = None
    with run_logging(level) as run_log:

        def start(run_id: str) -> None:
            nonlocal run_dir
            run_dir = out / run_id
            try:
                run_dir.mkdir(parents=True)
            except FileExistsError:
                raise RunError(f"{run_dir} already exists; not overwriting it") from None
            run_log.attach(run_dir / LOG_FILE)
            write_config(config, run_dir / CONFIG_FILE)
            logger.info("writing graded run %s to %s", run_id, run_dir)

        try:
            result = run_eval(spec_path, adapter_name, config, data_dir, on_start=start)
        except SpecValidationError as exc:
            for issue in exc.issues:
                logger.error("%s: %s", exc.path, issue)
            return 1
        except (RunError, ValueError) as exc:
            logger.error("run failed: %s", exc)
            return 1
        assert run_dir is not None
        write_result(result, run_dir / RESULT_FILE)
    print(run_dir)
    return 0


def _compare(path_a: Path, path_b: Path, tolerance: Tolerance) -> int:
    try:
        run_a, run_b = load_run(path_a), load_run(path_b)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 2
    differences = compare_runs(run_a, run_b, tolerance)
    for difference in differences:
        print(difference)
    if not differences:
        print("no differences")
        return 0
    cases = len({difference.case_id for difference in differences})
    print(f"{len(differences)} difference(s) in {cases} case(s)", file=sys.stderr)
    return 1


def _report(path: Path) -> int:
    try:
        written = write_report(path)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 2
    for written_path in written:
        print(written_path)
    return 0


def _reproduce(
    baseline_dir: Path, root: Path, out: Path | None, level: str, tolerance: Tolerance
) -> int:
    try:
        baseline = load_run(baseline_dir)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 2
    config_path = baseline_dir / CONFIG_FILE
    spec = baseline_spec(baseline, root)
    adapter_name = baseline["adapter"]["name"]
    if out is not None:
        return _reproduce_into(baseline, spec, adapter_name, config_path, out, level, tolerance)
    with tempfile.TemporaryDirectory(prefix="geoevals-reproduce-") as tmp:
        return _reproduce_into(
            baseline, spec, adapter_name, config_path, Path(tmp), level, tolerance
        )


def _reproduce_into(
    baseline: dict[str, Any],
    spec: Path,
    adapter_name: str,
    config_path: Path,
    out: Path,
    level: str,
    tolerance: Tolerance,
) -> int:
    run_dir = _run_to_dir(spec, adapter_name, config_path, out, level)
    if run_dir is None:
        return 1
    differences = compare_reproduction(baseline, load_run(run_dir), tolerance)
    for difference in differences:
        print(difference)
    if not differences:
        print(f"reproduced: {len(baseline['cases'])} case(s), no differences")
        return 0
    cases = len({difference.case_id for difference in differences})
    print(f"{len(differences)} difference(s) in {cases} case(s)", file=sys.stderr)
    return 1


def _rescore(run_dir: Path, root: Path) -> int:
    try:
        result = load_run(run_dir)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 2
    try:
        rescored = rescore_run(result, baseline_spec(result, root))
    except RescoreError as exc:
        print(f"{run_dir}: {exc}", file=sys.stderr)
        return 1
    write_result(rescored, run_dir / RESULT_FILE)
    if (run_dir / CASES_FILE).is_file():
        write_cases(rescored["cases"], run_dir / CASES_FILE)
    before = result["summary_metrics"]["task_success"]["mean"]
    after = rescored["summary_metrics"]["task_success"]["mean"]
    print(
        f"{run_dir}: rescored {result['benchmark']['id']} {result['benchmark']['version']} -> "
        f"{rescored['benchmark']['version']}; task_success {before} -> {after}"
    )
    return 0


def _bench_regenerate(benchmark_id: str, root: Path, check: bool) -> int:
    benchmark_dir = find_benchmark_dir(root, benchmark_id)
    try:
        stale = regenerate(benchmark_dir, benchmark_id, write=not check)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except RegenerateError as exc:
        print(exc, file=sys.stderr)
        return 1
    for path in stale:
        print(f"{path}: {'out of date' if check else 'written'}")
    if not stale:
        print(f"{benchmark_dir}: expected outputs are up to date")
    return 1 if check and stale else 0


def _evals_measure_town(name: str, bbox: Bbox, date: str, out: Path, source: Path | None) -> int:
    try:
        directory = source or fetch_candidate(name, bbox, date, out)
        extract_path = directory / EXTRACT_FILE
        layers = convert_extract(json.loads(extract_path.read_text(encoding="utf-8")))
        ensure_ignored(directory / LAYERS_DIR / "buildings.parquet")
        write_layers(layers, directory / LAYERS_DIR)
    except (OSError, ValueError, FetchError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(stats_table([(name, measure_layers(layers, bbox, extract_path.stat().st_size))]))
    return 0


def _evals_regenerate(eval_id: str, root: Path, data: Path | None, check: bool) -> int:
    spec_path = find_eval_spec(root, eval_id)
    try:
        data_dir = data or default_data_dir(spec_path)
        stale = regenerate_keys(spec_path, data_dir, write=not check)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    for task_id in stale:
        print(f"{task_id}: {'out of date' if check else 'key_sha256 written'}")
    if not stale:
        print(f"{spec_path}: keys are up to date")
    return 1 if check and stale else 0


def _evals_build_city(dataset_id: str, manifests: Path, source: Path | None) -> int:
    try:
        path = manifest_path(dataset_id, manifests)
        manifest = load_dataset_manifest(path)
        asset = manifest.assets[0]
        directory = source or Path(os.path.normpath(path.parent / asset.path)).parent
        extract_path = directory / Path(asset.path).name
        layers = convert_extract(json.loads(extract_path.read_text(encoding="utf-8")))
        ensure_ignored(directory / LAYERS_DIR / "buildings.parquet")
        written = write_layers(layers, directory / LAYERS_DIR)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except (OSError, ValueError, FetchError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{directory / LAYERS_DIR}: wrote {len(written)} layers")
    return 0


def _grade(run_dir: Path, data: Path | None, evals: Path, passes: int) -> int:
    if passes < 2:
        print(
            "--passes must be at least 2: the report states the grader's agreement with itself",
            file=sys.stderr,
        )
        return 1
    config = GraderConfig(passes=passes, command=GRADER_COMMAND, evals_root=evals)
    try:
        grades = grade_run(run_dir, data, config)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except (GradeError, OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    path = run_dir / GRADES_FILE
    path.write_text(json.dumps(grades.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for task in grades.tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    print(f"{path}: " + ", ".join(f"{status} {n}" for status, n in sorted(counts.items())))
    if grades.stopped:
        print(f"grading stopped: {grades.stopped}", file=sys.stderr)
    if counts.get("not_graded"):
        print(
            f"{counts['not_graded']} task(s) not graded; the run cannot go on the leaderboard "
            "until they are",
            file=sys.stderr,
        )
    return 1 if grades.stopped or counts.get("not_graded") else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    if args.command == "data" and args.data_command == "verify":
        return _data_verify(args.manifest)
    if args.command == "data" and args.data_command == "fetch":
        return _data_fetch(args.dataset_id, args.manifests, args.bbox, args.date, args.out)
    if args.command == "data" and args.data_command == "inventory":
        return _data_inventory(args.root, args.readme, args.check)
    if args.command == "data" and args.data_command == "licenses":
        return _data_licenses(args.out)
    if args.command == "adapters" and args.adapters_command == "list":
        for name in sorted(registered_adapter_names()):
            print(name)
        return 0
    if args.command == "adapters" and args.adapters_command == "predict":
        return _adapters_predict(args.adapter, args.config, args.case_input)
    if args.command == "run" and args.eval is not None:
        return _run_eval(args.eval, args.adapter, args.config, args.out, args.data, args.log_level)
    if args.command == "run":
        return _run(
            args.benchmark,
            args.adapter,
            args.config,
            args.out,
            args.log_level,
            args.prices,
            report=args.report,
            open_report=args.open,
        )
    if args.command == "compare":
        return _compare(args.run_a, args.run_b, Tolerance(args.abs_tol, args.rel_tol))
    if args.command == "report":
        return _report(args.run_dir)
    if args.command == "reproduce":
        tolerance = Tolerance(args.abs_tol, args.rel_tol)
        return _reproduce(args.baseline_dir, args.root, args.out, args.log_level, tolerance)
    if args.command == "rescore":
        return _rescore(args.run_dir, args.root)
    if args.command == "bench" and args.bench_command == "regenerate":
        return _bench_regenerate(args.benchmark_id, args.root, args.check)
    if args.command == "bench" and args.bench_command == "build":
        return _bench_build(args.pilot_id, args.root, args.source, args.out)
    if args.command == "leaderboard" and args.leaderboard_command == "add":
        return _leaderboard_add(args.run_dir, args.results, args.graded)
    if args.command == "leaderboard" and args.leaderboard_command == "build":
        return _leaderboard_build(args.results, args.readme, args.check, args.graded)
    if args.command == "grade":
        return _grade(args.run_dir, args.data, args.evals, args.passes)
    if args.command == "evals" and args.evals_command == "measure-town":
        return _evals_measure_town(args.name, args.bbox, args.date, args.out, args.source)
    if args.command == "evals" and args.evals_command == "build-city":
        return _evals_build_city(args.dataset_id, args.manifests, args.source)
    if args.command == "evals" and args.evals_command == "regenerate":
        return _evals_regenerate(args.eval_id, args.root, args.data, args.check)
    parser.print_help()
    return 0
