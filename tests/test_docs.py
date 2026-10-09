"""The documentation set: required files, American spelling, and the README quickstart."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
README = REPO / "README.md"

REQUIRED_DOCS = [
    "principles.md",
    "best-practices.md",
    "metrics.md",
    "data-governance.md",
    "benchmark-authoring.md",
    "reproducibility.md",
    "human-context.md",
]

MAX_QUICKSTART_COMMANDS = 3

BRITISH_SPELLINGS = re.compile(
    r"\b("
    r"colour|flavour|behaviour|favour|honour|labour|neighbour|"
    r"centre|metre|litre|fibre|kilometre|"
    r"grey|whilst|amongst|artefact|programme|catalogue|licence|defence|judgement|"
    r"analys(e|ed|es|ing)|"
    r"(model|label|travel|cancel|signal)l(ed|ing)|"
    r"(organi|recogni|summari|normali|standardi|optimi|prioriti|initiali|seriali|visuali|"
    r"utili|minimi|maximi|categori|characteri|parametri|generali)s(e|ed|es|ing|ation|ations)"
    r")\w*",
    re.IGNORECASE,
)


def _markdown_files() -> list[Path]:
    files = [README, *sorted((REPO / "docs").glob("*.md"))]
    files += sorted((REPO / "benchmarks").glob("*/README.md"))
    files += sorted((REPO / "datasets").glob("**/*.md"))
    return files


def quickstart_block(text: str) -> str:
    """The body of the one fenced code block tagged ``quickstart``."""
    blocks = re.findall(r"^```quickstart\n(.*?)^```$", text, flags=re.MULTILINE | re.DOTALL)
    assert len(blocks) == 1, f"expected one quickstart block, found {len(blocks)}"
    return blocks[0]


def quickstart_commands(block: str) -> list[str]:
    """The shell commands in the block, with backslash continuations joined."""
    joined = re.sub(r"\\\n\s*", " ", block)
    return [line.strip() for line in joined.splitlines() if line.strip()]


def test_docs_set_exists() -> None:
    for name in REQUIRED_DOCS:
        path = REPO / "docs" / name
        assert path.is_file(), path
        assert path.read_text(encoding="utf-8").startswith("# "), path


def test_benchmark_authoring_has_the_definition_of_done_and_worked_example() -> None:
    text = (REPO / "docs" / "benchmark-authoring.md").read_text(encoding="utf-8")
    assert "## Definition of done" in text
    assert "## Worked example" in text
    assert text.count("| ☐ |") == 10, "Appendix A of the kickoff plan has 10 items"


def test_docs_use_american_spelling() -> None:
    problems = []
    for path in _markdown_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in BRITISH_SPELLINGS.finditer(line):
                problems.append(f"{path.relative_to(REPO)}:{number}: {match.group(0)}")
    assert problems == []


def test_spelling_check_catches_british_spellings() -> None:
    for word in ["colour", "analysed", "modelling", "centre", "normalise", "summarisation"]:
        assert BRITISH_SPELLINGS.search(word), word
    for word in ["color", "analyzed", "modeling", "center", "otherwise", "precise", "judgment"]:
        assert not BRITISH_SPELLINGS.search(word), word


def test_quickstart_has_at_most_three_commands() -> None:
    commands = quickstart_commands(quickstart_block(README.read_text(encoding="utf-8")))
    assert 1 <= len(commands) <= MAX_QUICKSTART_COMMANDS, commands
    assert any("benchmarks/gis_correctness/benchmark.yaml" in command for command in commands)
    assert any("--open" in command for command in commands), "the quickstart opens the report"


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("uv") is None, reason="the quickstart needs uv on PATH")
def test_readme_quickstart_runs_verbatim(tmp_path: Path) -> None:
    """Run the README's quickstart block as written, from the repository root.

    ``BROWSER=true`` makes ``webbrowser.open`` run ``true <url>``, so the report is "opened"
    without a browser.
    """
    script = tmp_path / "quickstart.sh"
    script.write_text(quickstart_block(README.read_text(encoding="utf-8")), encoding="utf-8")
    out = REPO / "runs" / "quickstart"
    before = set(out.iterdir()) if out.is_dir() else set()
    env = {**os.environ, "BROWSER": "true"}
    completed = subprocess.run(
        ["bash", "-euo", "pipefail", str(script)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    new = set(out.iterdir()) - before
    try:
        [run_dir] = new
        assert (run_dir / "result.json").is_file()
        assert (run_dir / "report.md").is_file()
        assert (run_dir / "report.html").is_file()
        assert str((run_dir / "report.html").relative_to(REPO)) in completed.stdout
    finally:
        for path in new:
            shutil.rmtree(path)
