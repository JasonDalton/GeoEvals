import sys
from pathlib import Path

import pytest

from geoevals.graded.plots import box_plot_svg, plot_files


def test_box_plot_svg_is_byte_stable() -> None:
    series = [("Opus 5.5", [0.2, 0.5, 0.9, 1.0]), ("Haiku 5.5", [0.1, 0.3, 0.4, 0.8])]
    first = box_plot_svg("proximity", series)
    assert first == box_plot_svg("proximity", series)
    assert first.startswith("<?xml")
    assert "<dc:date>" not in first
    assert "Opus 5.5" in first and "Haiku 5.5" in first


def test_plot_files_one_per_eval(tmp_path: Path) -> None:
    from geoevals.graded.board import graded_row
    from geoevals.graded.grader import Grades
    from test_graded_board import _grades, _result

    row = graded_row(_result(), Grades.model_validate(_grades([(4, 4)] * 4)), "w")
    files = plot_files([row], tmp_path)
    assert list(files) == [tmp_path / "plots" / "proximity.svg"]


def _build_args(tmp_path: Path, with_run: bool) -> tuple[list[str], Path]:
    import json

    from geoevals.cli import main
    from geoevals.graded.board import GRADED_END, GRADED_START
    from geoevals.leaderboard.table import END, START
    from test_graded_board import _grades, _result

    graded = tmp_path / "graded"
    if with_run:
        run = tmp_path / "run"
        run.mkdir()
        (run / "result.json").write_text(json.dumps(_result()))
        (run / "grades.json").write_text(json.dumps(_grades([(4, 4), (2, 2), (0, 0), (4, 0)])))
        assert main(["leaderboard", "add", str(run), "--graded", str(graded)]) == 0
    readme = tmp_path / "README.md"
    readme.write_text(f"{START}\n{END}\n\n{GRADED_START}\nold\n{GRADED_END}\n")
    empty = tmp_path / "results"
    empty.mkdir()
    args = ["leaderboard", "build", "--results", str(empty), "--readme", str(readme)]
    return [*args, "--graded", str(graded)], graded / "plots" / "proximity.svg"


def test_build_writes_plot_and_check_passes(tmp_path: Path) -> None:
    from geoevals.cli import main

    args, svg = _build_args(tmp_path, True)
    assert main(args) == 0
    assert svg.read_text(encoding="utf-8").startswith("<?xml")
    assert main([*args, "--check"]) == 0


def test_check_flags_missing_and_modified_plot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from geoevals.cli import main

    args, svg = _build_args(tmp_path, True)
    assert main(args) == 0
    capsys.readouterr()
    svg.write_text("changed", encoding="utf-8")
    assert main([*args, "--check"]) == 1
    assert f"{svg}: plot is out of date" in capsys.readouterr().out
    svg.unlink()
    assert main([*args, "--check"]) == 1
    assert f"{svg}: plot is out of date" in capsys.readouterr().out


def test_build_without_graded_rows_needs_no_matplotlib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from geoevals.cli import main

    args, _ = _build_args(tmp_path, False)
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.delitem(sys.modules, "geoevals.graded.plots", raising=False)
    assert main(args) == 0


def test_build_with_graded_rows_reports_missing_matplotlib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from geoevals.cli import main

    args, _ = _build_args(tmp_path, True)
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.delitem(sys.modules, "geoevals.graded.plots", raising=False)
    assert main(args) == 1
    assert "uv sync --extra plots" in capsys.readouterr().err
