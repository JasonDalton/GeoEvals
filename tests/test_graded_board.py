import json
from pathlib import Path

import pytest

from geoevals.graded.board import (
    GRADED_END,
    GRADED_START,
    GradedError,
    agreement,
    graded_row,
    load_graded,
    quartiles,
    render_graded,
)
from geoevals.graded.grader import Grades

GRADER = {
    "model": "claude-opus-5-5",
    "effort": "high",
    "prompt_version": "grader_v1",
    "claude_code_version": "9.9.9",
    "passes": 2,
}


def _grades(scores_per_task: list[tuple[int, int]], statuses: list[str] | None = None) -> dict:
    statuses = statuses or ["graded"] * len(scores_per_task)
    tasks = []
    for i, ((first, second), status) in enumerate(zip(scores_per_task, statuses, strict=True)):
        passes = [
            {
                "criteria": {
                    "relations": {"score": first, "justification": "key"},
                    "clarity": {"score": first, "justification": "key"},
                }
            },
            {
                "criteria": {
                    "relations": {"score": second, "justification": "key"},
                    "clarity": {"score": second, "justification": "key"},
                }
            },
        ]
        graded = status == "graded"
        tasks.append(
            {
                "task_id": f"proximity-{i + 1:03d}",
                "status": status,
                "score": (first + second) / 8
                if graded
                else (0.0 if status == "no_answer" else None),
                "passes": passes if graded else [],
                "error": None,
            }
        )
    return {
        "schema_version": "1.0.0",
        "run_id": "r",
        "eval": {"id": "proximity", "version": "0.1.0"},
        "rubric_version": "1.0.0",
        "grader": GRADER,
        "graded_at": "2026-10-11T00:00:00Z",
        "stopped": None,
        "tasks": tasks,
    }


def _result(
    adapter: str = "claude_python_opus_5_5",
    n: int = 4,
    statuses: list[str] | None = None,
    data: str = "d" * 64,
    errors: dict[int, str] | None = None,
) -> dict:
    statuses = statuses or ["answered"] * n
    errors = errors or {}
    return {
        "run_id": "r",
        "schema_version": "1.0.0",
        "eval": {"id": "proximity", "version": "0.1.0"},
        "adapter": {
            "name": adapter,
            "version": "0.1.0+cc.9.9.9",
            "config": {"effort": "high", "prompt_version": "v1"},
        },
        "config_hash": "0" * 64,
        "dataset_manifest_hash": "1" * 64,
        "data_sha256": data,
        "environment": {},
        "started_at": "s",
        "finished_at": "f",
        "efficiency": {
            "wall_clock_s": 1.0,
            "latency_p50_s": 1.0,
            "latency_p90_s": 1.0,
            "tokens_input_total": 1,
            "tokens_output_total": 1,
        },
        "tasks": [
            {
                "task_id": f"proximity-{i + 1:03d}",
                "status": s,
                "output": {"status": "ok", "answer": "x"} if s == "answered" else None,
                "latency_s": 1.0,
                "retries": 0,
                "tokens": None,
                "error": {"type": errors[i], "message": "m"} if i in errors else None,
            }
            for i, s in enumerate(statuses)
        ],
    }


def _write(root: Path, result: dict, grades: dict) -> None:
    target = root / result["eval"]["id"] / result["adapter"]["name"]
    target.mkdir(parents=True)
    (target / "result.json").write_text(json.dumps(result))
    (target / "grades.json").write_text(json.dumps(grades))


def test_quartiles() -> None:
    assert quartiles([0.0, 0.25, 0.5, 0.75, 1.0]) == (0.25, 0.5, 0.75)
    assert quartiles([0.4]) == (0.4, 0.4, 0.4)


def test_graded_row_statistics() -> None:
    grades = Grades.model_validate(_grades([(4, 4), (2, 2), (0, 0), (4, 0)]))
    row = graded_row(_result(), grades, "w")
    assert row.scores == (1.0, 0.5, 0.0, 0.5)
    assert row.mean == pytest.approx(0.5)
    assert (row.minimum, row.median, row.maximum) == (0.0, 0.5, 1.0)
    assert row.n == 4
    assert row.ci_low <= row.mean <= row.ci_high


def test_agreement_counts_criterion_pairs_within_one_point() -> None:
    grades = Grades.model_validate(_grades([(4, 4), (4, 2)]))
    result = agreement([grades])
    assert result.pairs == 4
    assert result.within_one == pytest.approx(0.5)
    assert result.mean_abs_diff == pytest.approx(0.25)  # task 2: |1.0 - 0.5|, task 1: 0


def test_board_rejects_not_graded_tasks() -> None:
    grades = Grades.model_validate(_grades([(4, 4), (0, 0)], ["graded", "not_graded"]))
    with pytest.raises(GradedError, match="not graded"):
        graded_row(_result(n=2), grades, "w")


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (_result(adapter="claude_direct_opus_5_5", n=1), "python"),
        (_result(n=1, statuses=["skipped"]), "skipped"),
        (_result(n=1, statuses=["timeout"]), "runner's timeout"),
        (_result(n=1, statuses=["adapter_error"], errors={0: "ClaudeUsageLimit"}), "harness"),
    ],
)
def test_board_rejects_incomplete_runs(result: dict, message: str) -> None:
    grades = Grades.model_validate(
        _grades([(4, 4)], ["no_answer"] if result["tasks"][0]["status"] != "answered" else None)
    )
    with pytest.raises(GradedError, match=message):
        graded_row(result, grades, "w")


def test_load_graded_rejects_mixed_data(tmp_path: Path) -> None:
    _write(tmp_path, _result(), _grades([(4, 4)] * 4))
    _write(
        tmp_path, _result(adapter="claude_python_haiku_5_5", data="e" * 64), _grades([(2, 2)] * 4)
    )
    with pytest.raises(GradedError, match="not comparable"):
        load_graded(tmp_path)


def test_render_graded(tmp_path: Path) -> None:
    _write(tmp_path, _result(), _grades([(4, 4), (2, 2), (0, 0), (4, 0)]))
    _write(tmp_path, _result(adapter="claude_python_haiku_5_5"), _grades([(2, 2)] * 4))
    rows, agreements = load_graded(tmp_path)
    text = render_graded(rows, agreements)
    lines = text.splitlines()
    assert lines[0] == "| Model | Eval | Mean (95% CI) | Min | Q1 | Median | Q3 | Max |"
    assert lines[2].startswith("| Opus 5.5 | `proximity` 0.1.0 | 0.500 [")
    assert lines[3].startswith("| Haiku 5.5 | `proximity` 0.1.0 | 0.500 [")
    assert "![proximity: task scores by model](leaderboard/graded/plots/proximity.svg)" in text
    assert "Opus 5.5 also answered" in text
    assert "never combined" in text


def test_render_with_no_graded_runs() -> None:
    assert "No graded runs" in render_graded([], {})


def test_markers_are_distinct_from_the_benchmark_table() -> None:
    from geoevals.leaderboard.table import END, START

    assert {GRADED_START, GRADED_END}.isdisjoint({START, END})
