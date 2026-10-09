import json
import os
import re
import shutil
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.reporting.report import (
    COMPARABILITY_NOTE,
    EFFICIENCY_LABELS,
    render_markdown,
    report_context,
)
from geoevals.validation.run_result import Efficiency

FIXTURES = Path(__file__).parent / "fixtures"
REPORT_FIXTURE = FIXTURES / "report"
EXAMPLE_RUN = FIXTURES / "run_results" / "example_run"

SECTIONS = [
    "1. Summary",
    "2. Summary metrics",
    "3. Breakdown by strata",
    "4. Efficiency",
    "5. Failures",
    "6. Environment",
    "7. Provenance and dataset licenses",
    "8. Limitations",
]

UPDATE_SNAPSHOTS = os.environ.get("GEOEVALS_UPDATE_SNAPSHOTS") == "1"
"""Set GEOEVALS_UPDATE_SNAPSHOTS=1 to rewrite the committed snapshots from the current output."""


@pytest.fixture
def report_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in ("result.json", "config.yaml"):
        shutil.copy(REPORT_FIXTURE / name, run_dir / name)
    assert main(["report", str(run_dir)]) == 0
    assert capsys.readouterr().out == f"{run_dir / 'report.md'}\n{run_dir / 'report.html'}\n"
    return run_dir


@pytest.mark.parametrize("name", ["report.md", "report.html"])
def test_report_matches_snapshot(report_dir: Path, name: str) -> None:
    rendered = (report_dir / name).read_text(encoding="utf-8")
    snapshot = REPORT_FIXTURE / f"expected_{name}"
    if UPDATE_SNAPSHOTS:
        snapshot.write_text(rendered, encoding="utf-8")
    assert rendered == snapshot.read_text(encoding="utf-8")


def _headings(text: str, pattern: str) -> list[str]:
    return [h for h in re.findall(pattern, text, flags=re.MULTILINE) if h[0].isdigit()]


def test_sections_in_order(report_dir: Path) -> None:
    md = (report_dir / "report.md").read_text(encoding="utf-8")
    html = (report_dir / "report.html").read_text(encoding="utf-8")
    assert _headings(md, r"^## (.+)$") == SECTIONS
    assert _headings(html, r"<h2>(.+?)</h2>") == SECTIONS


def test_comparability_note_word_for_word(report_dir: Path) -> None:
    note = (
        "Comparisons are valid only between runs with the same benchmark version, metric "
        "versions, split, and dataset manifest hash."
    )
    assert note == COMPARABILITY_NOTE
    for name in ("report.md", "report.html"):
        assert note in (report_dir / name).read_text(encoding="utf-8")


def test_html_is_self_contained(report_dir: Path) -> None:
    html = (report_dir / "report.html").read_text(encoding="utf-8")
    assert "<style>" in html
    for pattern in (
        r"\b(src|href|srcset|action|data|poster)\s*=",
        r"<(script|link|img|iframe|object|embed|video|audio|source|base)\b",
        r"url\(",
        r"@import",
    ):
        assert not re.search(pattern, html, flags=re.IGNORECASE), pattern


def test_failures_list_unscored_cases_and_failed_metrics(report_dir: Path) -> None:
    md = (report_dir / "report.md").read_text(encoding="utf-8")
    failures = md.split("## 5. Failures")[1].split("## 6.")[0]
    rows = [line for line in failures.splitlines() if line.startswith("| dist_")]
    assert [row.split(" | ")[:3] for row in rows] == [
        ["| dist_002", "scored", "value_abs_error"],
        ["| dist_003", "adapter_error", "-"],
        ["| dist_004", "timeout", "-"],
    ]
    assert "axis_swap" in rows[0]
    assert "RuntimeError: mock adapter raised on request" in rows[1]


def test_efficiency_labels_cover_every_field() -> None:
    assert list(EFFICIENCY_LABELS) == list(Efficiency.model_fields)


def test_markdown_cells_escape_pipes() -> None:
    result = json.loads((REPORT_FIXTURE / "result.json").read_text(encoding="utf-8"))
    result["cases"][2]["error"]["message"] = "a | b\nc"
    md = render_markdown(report_context(result, "test"))
    assert "| RuntimeError: a \\| b c |" in md


def test_report_without_provenance_or_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"
    shutil.copytree(EXAMPLE_RUN, run_dir)
    # A result.json path works too; the split comes from the case records without config.yaml.
    assert main(["report", str(run_dir / "result.json")]) == 0
    md = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "| Split | test |" in md
    assert "does not record provenance or dataset licenses" in md
    assert (run_dir / "report.html").is_file()


def test_report_unreadable_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", str(tmp_path / "nope")]) == 2
    assert "file not found" in capsys.readouterr().err
    assert not (tmp_path / "nope").exists()
