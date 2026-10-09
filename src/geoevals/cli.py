"""Command-line entry point for ``geoevals``."""

import argparse
import dataclasses
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from geoevals import __version__
from geoevals.adapters import create_adapter, registered_adapter_names
from geoevals.data.verify import verify_manifest
from geoevals.regenerate import RegenerateError, regenerate
from geoevals.reporting.compare import compare_runs, load_run
from geoevals.reporting.report import write_report
from geoevals.runner.config import RunConfigError, load_run_config
from geoevals.runner.cost import PriceTable, PriceTableError, load_price_table
from geoevals.runner.layout import CONFIG_FILE, LOG_FILE, RESULT_FILE, write_config, write_run_dir
from geoevals.runner.run import RunError, run_benchmark, run_logging
from geoevals.validation import SpecValidationError, validate_file, validate_run_result_file
from geoevals.validation.validate import load_yaml

logger = logging.getLogger("geoevals.cli")

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
    run.add_argument("--benchmark", type=Path, required=True, help="Benchmark spec (YAML).")
    add_adapter_argument(run)
    run.add_argument("--config", type=Path, required=True, help="Run config (YAML).")
    run.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Parent directory; the run is written to <out>/<run_id>/.",
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

    compare = subparsers.add_parser(
        "compare",
        help="List per-case differences in status, output and metrics between two runs "
        "(exit 0: none, 1: some, 2: a run could not be read).",
    )
    compare.add_argument("run_a", type=Path, help="Run directory or its result.json.")
    compare.add_argument("run_b", type=Path, help="Run directory or its result.json.")

    report = subparsers.add_parser(
        "report",
        help="Write report.md and report.html into a run directory (exit 2: the run could not "
        "be read).",
    )
    report.add_argument("run_dir", type=Path, help="Run directory or its result.json.")

    bench = subparsers.add_parser("bench", help="Benchmark authoring tools.")
    bench_commands = bench.add_subparsers(dest="bench_command", required=True)
    regen = bench_commands.add_parser(
        "regenerate",
        help="Recompute every expected output of a benchmark with its reference workflow "
        "(<root>/<benchmark_id>/reference.py).",
    )
    regen.add_argument("benchmark_id", help="Benchmark ID (its directory name under --root).")
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
    return parser


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
) -> int:
    for path in (benchmark, config_path):
        if not path.is_file():
            print(f"{path}: file not found", file=sys.stderr)
            return 1
    try:
        config = load_run_config(config_path)
    except RunConfigError as exc:
        print(f"{config_path}: {exc}", file=sys.stderr)
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
            logger.info("writing run %s to %s", run_id, run_dir)

        try:
            prices = _load_prices(prices_path)
        except PriceTableError as exc:
            logger.error("%s", exc)
            return 1
        try:
            result = run_benchmark(benchmark, adapter_name, config, prices, on_start=start)
        except SpecValidationError as exc:
            # Logged rather than printed so the reason also lands in run.log once the run
            # directory exists (an invalid spec stops the run before that).
            for issue in exc.issues:
                logger.error("%s: %s", exc.path, issue)
            logger.error("%s: invalid (%d error(s))", exc.path, len(exc.issues))
            return 1
        except (RunError, ValueError) as exc:
            logger.error("run failed: %s", exc)
            return 1
        assert run_dir is not None
        write_run_dir(result, run_dir)
        issues = validate_run_result_file(run_dir / RESULT_FILE)
        if issues:
            for issue in issues:
                logger.error("%s: %s", run_dir / RESULT_FILE, issue)
            logger.error("%s: invalid run result", run_dir / RESULT_FILE)
            return 1
    print(run_dir)
    return 0


def _compare(path_a: Path, path_b: Path) -> int:
    try:
        run_a, run_b = load_run(path_a), load_run(path_b)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 2
    differences = compare_runs(run_a, run_b)
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


def _bench_regenerate(benchmark_id: str, root: Path, check: bool) -> int:
    benchmark_dir = root / benchmark_id
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    if args.command == "data" and args.data_command == "verify":
        return _data_verify(args.manifest)
    if args.command == "adapters" and args.adapters_command == "list":
        for name in sorted(registered_adapter_names()):
            print(name)
        return 0
    if args.command == "adapters" and args.adapters_command == "predict":
        return _adapters_predict(args.adapter, args.config, args.case_input)
    if args.command == "run":
        return _run(
            args.benchmark, args.adapter, args.config, args.out, args.log_level, args.prices
        )
    if args.command == "compare":
        return _compare(args.run_a, args.run_b)
    if args.command == "report":
        return _report(args.run_dir)
    if args.command == "bench" and args.bench_command == "regenerate":
        return _bench_regenerate(args.benchmark_id, args.root, args.check)
    parser.print_help()
    return 0
