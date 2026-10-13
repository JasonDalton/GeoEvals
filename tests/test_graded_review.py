import json
import sys
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from geoevals.cli import main
from geoevals.graded.keys import regenerate_keys
from geoevals.graded.review import MAP_PAD_DEG, key_warnings, map_box, review_sheet, task_warnings
from geoevals.graded.spec import EvalTask, Location, load_tasks
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


def test_map_box_ignores_key_polygons_that_hold_the_point() -> None:
    task = EvalTask(
        task_id="sample-001",
        prompt="Which district is the marked point in?",
        audience="a resident",
        location=Location(point=[10.0, 50.0], feature_ids=["way/1"]),
        key_type="containment",
        params={"points": [{"label": "A", "point": [10.002, 50.001]}], "layers": ["boundaries"]},
        rubric=["relations"],
    )
    region = box(9.0, 49.0, 11.0, 51.0)  # a large container that holds the marked point
    shapes = {"way/1": Point(9.999, 49.999).buffer(0.0005), "relation/9": region}
    key = {"points": {"A": {"inside": ["relation/9"], "on_boundary": []}}}
    min_lon, min_lat, max_lon, max_lat = map_box(task, shapes, key) or (0, 0, 0, 0)
    assert min_lon == pytest.approx(9.9985 - MAP_PAD_DEG)
    assert min_lat == pytest.approx(49.9985 - MAP_PAD_DEG)
    assert max_lon == pytest.approx(10.002 + MAP_PAD_DEG), "params points widen the box"
    assert max_lat == pytest.approx(50.001 + MAP_PAD_DEG)


def test_map_box_widens_to_the_candidates_a_proximity_key_names() -> None:
    task = EvalTask(
        task_id="sample-001",
        prompt="Which pharmacy is the shortest walk from the marked house?",
        audience="a resident",
        location=Location(point=[10.0, 50.0], feature_ids=[]),
        key_type="proximity",
        params={"from": {"point": [10.0, 50.0]}, "category": {"amenity": "pharmacy"}},
        rubric=["relations"],
    )
    shapes = {
        "node/1": Point(10.01, 50.005),  # a candidate about 900 m away
        "relation/9": box(9.0, 49.0, 11.0, 51.0),  # a district that holds the house
    }
    key = {
        "walking_nearest": "node/1",
        "by_walking": [{"feature_id": "node/1"}],
        "district": "relation/9",
    }
    min_lon, min_lat, max_lon, max_lat = map_box(task, shapes, key) or (0, 0, 0, 0)
    assert (min_lon, min_lat) == pytest.approx((10.0 - MAP_PAD_DEG, 50.0 - MAP_PAD_DEG))
    assert (max_lon, max_lat) == pytest.approx((10.01 + MAP_PAD_DEG, 50.005 + MAP_PAD_DEG))


def test_map_box_ignores_polygons_that_meet_a_params_polygon() -> None:
    task = EvalTask(
        task_id="sample-001",
        prompt="Which districts does the park lie in?",
        audience="a resident",
        location=Location(point=[10.0, 50.0], feature_ids=["way/1", "relation/9"]),
        key_type="containment",
        params={"features": ["way/1"], "layers": ["boundaries"]},
        rubric=["relations"],
    )
    park = box(10.0, 50.0, 10.002, 50.001)
    shapes = {
        "way/1": park,
        "relation/8": box(10.002, 49.0, 11.0, 51.0),  # a district the park touches
        "relation/9": box(9.0, 49.0, 10.001, 51.0),  # a district the park overlaps
    }
    key = {"features": {"way/1": {"overlaps": ["relation/9"], "touches": ["relation/8"]}}}
    assert map_box(task, shapes, key) == pytest.approx(
        (10.0 - MAP_PAD_DEG, 50.0 - MAP_PAD_DEG, 10.002 + MAP_PAD_DEG, 50.001 + MAP_PAD_DEG)
    )


def test_map_box_needs_a_location() -> None:
    task = EvalTask(
        task_id="sample-001",
        prompt="Where?",
        audience="a resident",
        location=Location(),
        key_type="containment",
        params={"layers": ["boundaries"]},
        rubric=["relations"],
    )
    assert map_box(task, {"relation/9": box(9.0, 49.0, 11.0, 51.0)}) is None


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


def test_review_cli_reraises_other_import_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path, data = _reviewed(tmp_path)
    root = str(spec_path.parent.parent)

    def broken(*_: object) -> Path:
        raise ImportError("no module named 'pyogrio'", name="pyogrio")

    monkeypatch.setattr("geoevals.graded.review.review_sheet", broken)
    with pytest.raises(ImportError, match="pyogrio"):
        main(["evals", "review", "sample", "--root", root, "--data", str(data)])
