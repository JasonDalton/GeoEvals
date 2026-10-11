"""The documentation set: required files, American spelling, and the README quickstart."""

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

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
    "release-checklist.md",
]

GOVERNANCE_FILES = [
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "CITATION.cff",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/benchmark_proposal.md",
    ".github/ISSUE_TEMPLATE/new_adapter.md",
    ".github/pull_request_template.md",
]

RELEASE_FILES = ["CHANGELOG.md", "ROADMAP.md"]

RELEASE_CHECKLIST_ITEMS = 12
"""Section 10 of the kickoff plan has 12 items."""

HUMAN_REVIEWS = {"license compatibility review", "privacy review", "final scope approval"}

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
    files = [README, *(REPO / name for name in GOVERNANCE_FILES if name.endswith(".md"))]
    files += [REPO / name for name in RELEASE_FILES]
    files += sorted((REPO / ".github").glob("**/*.md"))
    files += sorted((REPO / "docs").glob("*.md"))
    files += sorted((REPO / "benchmarks").glob("*/README.md"))
    files.append(REPO / "baselines" / "README.md")
    files.append(REPO / "leaderboard" / "README.md")
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


def test_governance_files_exist() -> None:
    for name in GOVERNANCE_FILES:
        assert (REPO / name).is_file(), name


def test_code_of_conduct_is_contributor_covenant_with_a_contact_placeholder() -> None:
    text = (REPO / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    assert text.startswith("# Contributor Covenant Code of Conduct")
    assert "version 2.1" in text
    assert "TODO(maintainer)" in text
    assert "[INSERT CONTACT METHOD]" not in text


def test_citation_version_is_0_1_0() -> None:
    citation = yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))
    assert citation["cff-version"] == "1.2.0"
    assert citation["version"] == "0.1.0"
    assert citation["license"] == "MIT"


def test_release_version_is_consistent() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    citation = yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = re.findall(r"^## \[?(\d+\.\d+\.\d+)\]? - \d{4}-\d{2}-\d{2}$", changelog, re.M)
    assert project["version"] == citation["version"] == releases[0] == "0.1.0"
    assert "Keep a Changelog" in changelog
    assert (REPO / "ROADMAP.md").is_file()


def _changelog_entry(version: str) -> str:
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.split(rf"^## \[?{re.escape(version)}\]? .*$", changelog, flags=re.M)[1].split(
        "\n## ", 1
    )[0]


def _unreleased_entry() -> str:
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    return changelog.split("## Unreleased", 1)[1].split("\n## ", 1)[0]


def test_changelog_lists_benchmarks_schemas_metrics_and_adapters() -> None:
    from geoevals.adapters.registry import registered_adapter_names
    from geoevals.metrics.registry import get_metric, registered_metric_ids

    entry = _changelog_entry("0.1.0")
    for heading in ["Benchmarks", "Schemas", "Metrics", "Adapters"]:
        assert f"#### {heading}" in entry, heading
    for spec in sorted((REPO / "benchmarks").glob("*/benchmark.yaml")):
        benchmark = yaml.safe_load(spec.read_text(encoding="utf-8"))
        listed = f"`{benchmark['id']}` {benchmark['version']}"
        assert listed in entry or listed in _unreleased_entry(), benchmark["id"]
    for schema in sorted((REPO / "schemas").glob("*.schema.json")):
        listed = f"`schemas/{schema.name}`"
        assert listed in entry or listed in _unreleased_entry(), schema.name
    unreleased = _unreleased_entry()
    for metric_id in registered_metric_ids():
        listed = f"`{metric_id}` {get_metric(metric_id).version}"
        assert listed in entry or listed in unreleased, metric_id
    for name in registered_adapter_names():
        listed = f"`{name}` 0.1.0" in entry or re.search(rf"`{name}`[^\n]* 0\.1\.0", unreleased)
        assert listed, name


def test_roadmap_lists_the_phase_5_items() -> None:
    headings = re.findall(r"^### (.+)$", (REPO / "ROADMAP.md").read_text(encoding="utf-8"), re.M)
    for item in [
        "Vector benchmark on OpenStreetMap data",
        "LLM and hosted-API adapters",
        "Agentic GIS tasks with real agents",
        "Expanded place-context cases",
        "Leaderboard policy",
    ]:
        assert item in headings, item


def test_readme_has_citation_contributing_and_roadmap() -> None:
    headings = re.findall(r"^## (.+)$", README.read_text(encoding="utf-8"), re.M)
    for heading in ["Quickstart", "Contributing", "Citation", "Roadmap"]:
        assert heading in headings, heading


def test_readme_leaderboard_is_up_to_date() -> None:
    from geoevals.cli import main

    results = REPO / "leaderboard" / "results"
    assert (
        main(
            [
                "leaderboard",
                "build",
                "--check",
                "--results",
                str(results),
                "--graded",
                str(REPO / "leaderboard" / "graded"),
                "--readme",
                str(README),
            ]
        )
        == 0
    )


def test_every_registered_metric_is_documented() -> None:
    from geoevals.metrics.registry import registered_metric_ids

    headings = re.findall(r"^### `(.+)`$", (REPO / "docs" / "metrics.md").read_text("utf-8"), re.M)
    assert sorted(set(registered_metric_ids()) - set(headings)) == []


def _release_checklist() -> list[list[str]]:
    """The rows of the checklist table: number, item, status, verified by, evidence."""
    text = (REPO / "docs" / "release-checklist.md").read_text(encoding="utf-8")
    section = text.split("## Checklist", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^\| (\d+) \| (.+)\|$", section, flags=re.M)
    return [[number, *(cell.strip() for cell in rest.split(" | "))] for number, rest in rows]


def test_release_checklist_marks_every_item() -> None:
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    jobs = set(workflow["jobs"])
    rows = _release_checklist()
    assert [int(row[0]) for row in rows] == list(range(1, RELEASE_CHECKLIST_ITEMS + 1))
    for number, _item, status, verified_by, _evidence in rows:
        if status == "automated":
            named = re.findall(r"`([a-z_-]+)`", verified_by)
            assert named, f"item {number} names no CI job"
            assert set(named) <= jobs, f"item {number}: {set(named) - jobs} not in ci.yml"
        else:
            assert status == "human sign-off required", f"item {number}: {status}"
            assert verified_by in HUMAN_REVIEWS, f"item {number}: {verified_by}"
    reviews = {row[3] for row in rows if row[2] == "human sign-off required"}
    assert reviews == HUMAN_REVIEWS


def _definition_of_done() -> list[str]:
    """The requirement column of the definition-of-done table in benchmark-authoring.md."""
    text = (REPO / "docs" / "benchmark-authoring.md").read_text(encoding="utf-8")
    return re.findall(r"^\| ☐ \| (.+?) \|", text, flags=re.MULTILINE)


def test_pull_request_template_has_the_definition_of_done_checklist() -> None:
    text = (REPO / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    checklist = re.findall(r"^- \[ \] (.+)$", text, flags=re.MULTILINE)
    items = _definition_of_done()
    assert len(items) == 10
    for item in items:
        assert item in checklist, item


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
