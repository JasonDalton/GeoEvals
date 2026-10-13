import json
import sys
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.graded.keys import regenerate_keys
from geoevals.graded.review import key_warnings, review_sheet, task_warnings
from geoevals.graded.spec import load_tasks
from geoevals.validation import load_eval_spec
from graded_city import BBOX
from graded_helpers import copy_sample_eval, sample_data


def _reviewed(tmp_path: Path) -> tuple[Path, Path]:
    spec_path = copy_sample_eval(tmp_path / "evals")
    data = sample_data(tmp_path)
    regenerate_keys(spec_path, data)
    return spec_path, data


def test_review_sheet_lists_every_task_with_its_key_and_a_map(tmp_path: Path) -> None:
    spec_path, data = _reviewed(tmp_path)
    sheet = review_sheet(spec_path, data)
    assert sheet == data / "review" / "sample.md"
    text = sheet.read_text(encoding="utf-8")
    for task_id in ("sample-001", "sample-002", "sample-003"):
        assert f"## {task_id}" in text
        assert (data / "review" / "sample" / f"{task_id}.png").stat().st_size > 0
    assert "North Pharmacy" in text, "the key is shown"
    assert "© OpenStreetMap contributors" in text


@pytest.mark.parametrize(
    ("key_type", "key", "warning"),
    [
        (
            "proximity",
            {
                "walking_nearest": None,
                "unreachable": ["node/1"],
                "by_walking": [],
                "by_straight_line": [{"straight_line_m": 100.0}],
            },
            "no candidate is reachable on foot",
        ),
        (
            "proximity",
            {
                "walking_nearest": "node/1",
                "unreachable": [],
                "by_walking": [
                    {"feature_id": "node/1", "walking_m": 900.0, "straight_line_m": 200.0}
                ],
                "by_straight_line": [],
            },
            "more than 3x the straight line",
        ),
        (
            "containment",
            {"points": {"a": {"inside": [], "on_boundary": []}}, "features": {}},
            "point 'a' is in no polygon",
        ),
        (
            "adjacency",
            {"pairs": [{"a": "way/1", "b": "way/2", "relation": "disjoint"}]},
            "no pair of features touches",
        ),
        (
            "closure",
            {
                "before": {"reachable": True, "walking_m": 100.0},
                "after": {"reachable": True, "walking_m": 100.0},
                "added_m": 0.0,
            },
            "the closure does not change the walk",
        ),
        (
            "visibility",
            {"targets": {"way/1": {"visible": None}, "way/2": {"visible": None}}},
            "every target is undecided",
        ),
        (
            "direction",
            {"reachable": True, "walking_m": 1000.0, "straight_line_m": 200.0, "steps": [{}, {}]},
            "more than 3x the straight line",
        ),
        (
            "direction",
            {"reachable": True, "walking_m": 100.0, "straight_line_m": 90.0, "steps": [{}]},
            "a one-step route",
        ),
    ],
)
def test_key_warnings(key_type: str, key: dict, warning: str) -> None:
    assert any(warning in w for w in key_warnings(key_type, key))


def test_a_sound_key_has_no_warning() -> None:
    key = {
        "walking_nearest": "node/1",
        "unreachable": [],
        "by_walking": [{"feature_id": "node/1", "walking_m": 300.0, "straight_line_m": 250.0}],
        "by_straight_line": [],
    }
    assert key_warnings("proximity", key) == []


def test_task_warnings_flag_duplicates_and_the_box_edge(tmp_path: Path) -> None:
    spec_path = copy_sample_eval(tmp_path / "evals")
    lines = spec_path.parent.joinpath("tasks.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    duplicate = {**first, "task_id": "sample-004"}
    edge = {
        **json.loads(lines[1]),
        "task_id": "sample-005",
        "location": {"point": [BBOX[0] + 0.0001, BBOX[1] + 0.0001], "feature_ids": []},
    }
    spec_path.parent.joinpath("tasks.jsonl").write_text(
        "".join(line + "\n" for line in lines)
        + json.dumps(duplicate)
        + "\n"
        + json.dumps(edge)
        + "\n",
        encoding="utf-8",
    )
    tasks = load_tasks(spec_path, load_eval_spec(spec_path))
    warnings = task_warnings(tasks, BBOX)
    assert any("same key type and params as sample-001" in w for w in warnings["sample-004"])
    assert any("within 300 m of the city box edge" in w for w in warnings["sample-005"])


def test_review_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path, data = _reviewed(tmp_path)
    root = str(spec_path.parent.parent)
    assert main(["evals", "review", "sample", "--root", root, "--data", str(data)]) == 0
    assert "sample.md" in capsys.readouterr().out


def test_review_cli_needs_current_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path = copy_sample_eval(tmp_path / "evals")
    data = sample_data(tmp_path)  # no keys regenerated
    root = str(spec_path.parent.parent)
    assert main(["evals", "review", "sample", "--root", root, "--data", str(data)]) == 1
    assert "regenerate" in capsys.readouterr().err


def test_review_cli_without_matplotlib(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path, data = _reviewed(tmp_path)
    root = str(spec_path.parent.parent)
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    assert main(["evals", "review", "sample", "--root", root, "--data", str(data)]) == 1
    assert "need matplotlib" in capsys.readouterr().err
