"""Command-line entry point for ``geoevals``."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from geoevals import __version__
from geoevals.validation import validate_benchmark_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geoevals",
        description="Reproducible evaluation framework for geospatial AI systems.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    validate = subparsers.add_parser("validate", help="Validate a benchmark spec (YAML).")
    validate.add_argument("path", type=Path, help="Path to a benchmark.yaml file.")
    return parser


def _validate(path: Path) -> int:
    if not path.is_file():
        print(f"{path}: file not found", file=sys.stderr)
        return 1
    issues = validate_benchmark_file(path)
    if issues:
        for issue in issues:
            print(f"{path}: {issue}", file=sys.stderr)
        print(f"{path}: invalid ({len(issues)} error(s))", file=sys.stderr)
        return 1
    print(f"{path}: valid benchmark spec")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    parser.print_help()
    return 0
