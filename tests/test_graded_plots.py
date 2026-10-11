from pathlib import Path

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
