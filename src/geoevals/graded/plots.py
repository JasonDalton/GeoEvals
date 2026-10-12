"""One SVG box plot per graded eval, every model side by side, byte-stable.

The whiskers reach the minimum and maximum (``whis=(0, 100)``) and the box spans the quartiles,
so the plot shows the same numbers as the table; a triangle marks the mean. The SVG is the same
bytes on every build: text stays text (``svg.fonttype: none``) in DejaVu Sans, which matplotlib
ships, element IDs come from a fixed hash salt, and the date and creator metadata are left out.
Needs the ``plots`` extra (``uv sync --extra plots``).
"""

import io
from pathlib import Path
from typing import Any

from geoevals.graded.board import PLOTS_DIR, GradedRow
from geoevals.leaderboard.table import MODEL_NAMES

RC: dict[Any, Any] = {
    "svg.hashsalt": "geoevals",
    "svg.fonttype": "none",
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "path.simplify": False,
}
FIGSIZE = (6.4, 3.6)


def box_plot_svg(title: str, series: list[tuple[str, list[float]]]) -> str:
    """The SVG text of a box plot of ``series`` (label, task scores in [0, 1])."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with matplotlib.rc_context(RC):
        fig, ax = plt.subplots(figsize=FIGSIZE)
        ax.boxplot(
            [scores for _, scores in series],
            tick_labels=[label for label, _ in series],
            whis=(0, 100),
            showmeans=True,
        )
        ax.set_ylim(0, 1)
        ax.set_ylabel("Task score")
        ax.set_title(f"{title}: task scores by model")
        buffer = io.StringIO()
        fig.savefig(buffer, format="svg", metadata={"Date": None, "Creator": None})
        plt.close(fig)
    return buffer.getvalue()


def plot_files(rows: list[GradedRow], graded_dir: Path) -> dict[Path, str]:
    """``graded_dir/plots/<eval>.svg`` -> its SVG text, for every eval in ``rows``."""
    files: dict[Path, str] = {}
    for eval_id in sorted({row.eval_id for row in rows}):
        series = [(MODEL_NAMES[r.model], list(r.scores)) for r in rows if r.eval_id == eval_id]
        files[graded_dir / PLOTS_DIR / f"{eval_id}.svg"] = box_plot_svg(eval_id, series)
    return files
