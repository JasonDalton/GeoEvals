"""`geoevals data licenses`: runtime dependency licenses and the GPL/AGPL gate."""

import importlib.metadata as metadata
from email.message import Message
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.data.licenses import DependencyLicense, license_of, runtime_dependencies


@pytest.mark.parametrize(
    ("license_text", "copyleft"),
    [
        ("MIT", False),
        ("BSD-3-Clause AND 0BSD AND MIT", False),
        ("LGPL-2.1-or-later", False),
        ("GNU Lesser General Public License v3 (LGPLv3)", False),
        ("GPL-3.0-only", True),
        ("AGPL-3.0-or-later", True),
        ("GNU General Public License v2 (GPLv2)", True),
        ("GNU Affero General Public License v3", True),
        ("MIT OR GPL-2.0-only", False),
        ("GPL-2.0-only OR AGPL-3.0-only", True),
        ("MIT AND GPL-3.0-only", True),
    ],
)
def test_copyleft(license_text: str, copyleft: bool) -> None:
    assert DependencyLicense("pkg", "1.0", license_text).copyleft is copyleft


class _FakeDistribution(metadata.Distribution):
    def __init__(self, headers: dict[str, list[str]]) -> None:
        self._message = Message()
        for key, values in headers.items():
            for value in values:
                self._message[key] = value

    @property
    def metadata(self) -> metadata.PackageMetadata:  # type: ignore[override]
        return self._message  # type: ignore[return-value]

    def read_text(self, filename: str) -> str | None:
        return None

    def locate_file(self, path: str | Path) -> Path:  # type: ignore[override]
        return Path(path)


def test_license_of_prefers_the_spdx_expression() -> None:
    dist = _FakeDistribution(
        {"License-Expression": ["MIT"], "Classifier": ["License :: OSI Approved :: BSD License"]}
    )
    assert license_of(dist) == "MIT"


def test_license_of_skips_a_full_license_text_and_reads_classifiers() -> None:
    dist = _FakeDistribution(
        {
            "License": ["Copyright (c) 2001 Someone\n\nRedistribution and use ..."],
            "Classifier": [
                "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
                "Programming Language :: Python",
            ],
        }
    )
    assert license_of(dist) == "GNU General Public License v3 (GPLv3)"
    assert license_of(_FakeDistribution({})) == "UNKNOWN"


def test_runtime_dependencies_exclude_dev_tools_and_include_extras() -> None:
    names = {dep.name.lower() for dep in runtime_dependencies()}
    assert {"geopandas", "pydantic", "jinja2", "networkx", "scipy"} <= names
    assert not names & {"pytest", "ruff", "pyright", "geoevals"}


def test_installed_runtime_dependencies_have_no_copyleft_license() -> None:
    assert [dep for dep in runtime_dependencies() if dep.copyleft] == []


def test_cli_writes_the_report_and_fails_on_gpl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "docs" / "dependency-licenses.md"
    assert main(["data", "licenses", "--out", str(out)]) == 0
    report = out.read_text(encoding="utf-8")
    assert report.startswith("# Dependency licenses\n")
    assert "| `pydantic` |" in report

    def with_gpl(root: str = "geoevals") -> list[DependencyLicense]:
        return [DependencyLicense("copyleft-lib", "1.0", "GPL-3.0-only")]

    monkeypatch.setattr("geoevals.cli.runtime_dependencies", with_gpl)
    assert main(["data", "licenses", "--out", str(out)]) == 1
    assert "copyleft-lib 1.0: GPL-3.0-only" in capsys.readouterr().err
