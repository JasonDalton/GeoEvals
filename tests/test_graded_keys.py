import json
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.graded.keys import (
    KeysError,
    canonical_key,
    key_sha256,
    keys_path,
    load_keys,
    regenerate_keys,
)
from graded_helpers import copy_sample_eval, sample_data


def test_canonical_key_sorts_keys_and_is_compact() -> None:
    assert canonical_key({"b": 1, "a": [0.5, None]}) == '{"a":[0.5,null],"b":1}'
    assert key_sha256({"b": 1, "a": 2}) == key_sha256({"a": 2, "b": 1})


def _tasks(spec_path: Path) -> list[dict]:
    lines = spec_path.parent.joinpath("tasks.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _write_tasks(spec_path: Path, tasks: list[dict]) -> None:
    spec_path.parent.joinpath("tasks.jsonl").write_text(
        "".join(json.dumps(t) + "\n" for t in tasks), encoding="utf-8"
    )


def _unhashed_copy(tmp_path: Path) -> Path:
    """A copy of the sample eval whose tasks have no key_sha256 yet."""
    spec_path = copy_sample_eval(tmp_path)
    _write_tasks(spec_path, [{**t, "key_sha256": None} for t in _tasks(spec_path)])
    return spec_path


def test_regenerate_writes_keys_and_hashes(tmp_path: Path) -> None:
    spec_path, data = _unhashed_copy(tmp_path), sample_data(tmp_path)
    stale = regenerate_keys(spec_path, data, write=True)
    assert stale == ["sample-001", "sample-002", "sample-003"], "hashes start null"
    keys = load_keys(spec_path, data)
    assert keys["sample-001"]["walking_nearest"] == "node/500"
    assert keys["sample-003"]["disconnected_by_closure"] is True
    for task in _tasks(spec_path):
        assert task["key_sha256"] == key_sha256(keys[task["task_id"]])
    assert regenerate_keys(spec_path, data, write=False) == []
    lines = keys_path(data, "sample").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["task_id"] for line in lines] == [
        "sample-001",
        "sample-002",
        "sample-003",
    ]


def test_check_reports_a_changed_task(tmp_path: Path) -> None:
    spec_path, data = copy_sample_eval(tmp_path), sample_data(tmp_path)
    regenerate_keys(spec_path, data)
    tasks = _tasks(spec_path)
    tasks[0]["params"]["top"] = 1
    _write_tasks(spec_path, tasks)
    assert regenerate_keys(spec_path, data, write=False) == ["sample-001"]


def test_load_keys_refuses_missing_and_stale_keys(tmp_path: Path) -> None:
    spec_path, data = _unhashed_copy(tmp_path), sample_data(tmp_path)
    with pytest.raises(KeysError, match="evals regenerate"):
        load_keys(spec_path, data)
    regenerate_keys(spec_path, data)
    path = keys_path(data, "sample")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    lines[1]["key"]["targets"]["way/400"]["visible"] = False
    path.write_text("".join(json.dumps(entry) + "\n" for entry in lines), encoding="utf-8")
    with pytest.raises(KeysError, match="sample-002"):
        load_keys(spec_path, data)


def test_regenerate_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path, data = _unhashed_copy(tmp_path), sample_data(tmp_path)
    root = str(spec_path.parent.parent)
    args = ["evals", "regenerate", "sample", "--root", root, "--data", str(data)]
    assert main([*args, "--check"]) == 1
    assert "sample-001: out of date" in capsys.readouterr().out
    assert main(args) == 0
    assert main([*args, "--check"]) == 0
    assert "keys are up to date" in capsys.readouterr().out


def test_committed_sample_hashes_are_current(tmp_path: Path) -> None:
    spec_path, data = copy_sample_eval(tmp_path), sample_data(tmp_path)
    assert regenerate_keys(spec_path, data, write=False) == []
