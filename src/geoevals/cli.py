"""Command-line entry point for ``geoevals``."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from geoevals import __version__
from geoevals.data.verify import verify_manifest
from geoevals.validation import SpecValidationError, validate_file


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    if args.command == "data" and args.data_command == "verify":
        return _data_verify(args.manifest)
    parser.print_help()
    return 0
