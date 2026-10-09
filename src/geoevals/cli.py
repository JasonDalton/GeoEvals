"""Command-line entry point for ``geoevals``."""

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from geoevals import __version__
from geoevals.adapters import create_adapter, registered_adapter_names
from geoevals.data.verify import verify_manifest
from geoevals.validation import SpecValidationError, validate_file
from geoevals.validation.validate import load_yaml


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
    parser.print_help()
    return 0
