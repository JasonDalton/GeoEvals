"""Every benchmark directory has a dataset card with the required sections."""

import re
from pathlib import Path

REPO = Path(__file__).parent.parent

CARD_SECTIONS = [
    "Purpose",
    "Collection process",
    "Geography",
    "Time range",
    "Schema",
    "License",
    "Limitations",
    "Intended uses",
    "Prohibited uses",
]
"""Level-2 headings (``## <section>``) every ``benchmarks/<name>/README.md`` must have."""


def missing_sections(card: str) -> list[str]:
    headings = {heading.strip().lower() for heading in re.findall(r"^## (.+)$", card, re.MULTILINE)}
    return [section for section in CARD_SECTIONS if section.lower() not in headings]


def benchmark_dirs() -> list[Path]:
    return sorted(path.parent for path in (REPO / "benchmarks").glob("*/benchmark.yaml"))


def test_missing_sections_finds_absent_and_wrong_level_headings() -> None:
    card = "# Card\n\n## Purpose\n\n### Geography\n\n## time range\n"
    missing = missing_sections(card)
    assert "Purpose" not in missing
    assert "Time range" not in missing
    assert "Geography" in missing
    assert "Prohibited uses" in missing


def test_benchmarks_exist() -> None:
    assert len(benchmark_dirs()) >= 3


def test_every_benchmark_has_a_dataset_card() -> None:
    problems = []
    for directory in benchmark_dirs():
        card = directory / "README.md"
        if not card.is_file():
            problems.append(f"{card.relative_to(REPO)}: missing")
            continue
        missing = missing_sections(card.read_text(encoding="utf-8"))
        if missing:
            problems.append(f"{card.relative_to(REPO)}: no '## ' section for {missing}")
    assert not problems, "\n".join(problems)
