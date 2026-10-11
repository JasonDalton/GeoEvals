import json
from pathlib import Path

import pytest
import yaml

from claude_fakes import FAKE_COMMAND, FakeClaude, init_event, result_event
from geoevals.cli import main
from geoevals.graded.board import load_graded
from geoevals.graded.grader import GRADER_MODEL
from geoevals.graded.keys import regenerate_keys
from graded_helpers import copy_sample_eval, sample_data

IDS = ["relations", "reasoning", "assumptions", "data_use", "clarity"]
ANSWER = {"status": "ok", "answer": "North Pharmacy (node/500) is nearest on foot."}


def test_run_grade_add_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec_path = copy_sample_eval(tmp_path / "evals")
    data = sample_data(tmp_path)
    regenerate_keys(spec_path, data)
    config = tmp_path / "config.yaml"
    references = {f"sample-00{i}": ANSWER for i in (1, 2, 3)}
    config.write_text(yaml.safe_dump({"split": "test", "adapter": {"references": references}}))
    assert (
        main(
            [
                "run",
                "--eval",
                str(spec_path),
                "--adapter",
                "mock",
                "--config",
                str(config),
                "--out",
                str(tmp_path / "runs"),
                "--data",
                str(data),
            ]
        )
        == 0
    )
    [run_dir] = list((tmp_path / "runs").iterdir())

    fake = FakeClaude(tmp_path, monkeypatch)
    grade = {"criteria": {i: {"score": 3, "justification": "key agrees"} for i in IDS}}
    fake.set([init_event(), result_event(grade, model_usage={GRADER_MODEL: {"outputTokens": 9}})])
    monkeypatch.setattr("geoevals.cli.GRADER_COMMAND", FAKE_COMMAND)
    assert (
        main(["grade", str(run_dir), "--data", str(data), "--evals", str(tmp_path / "evals")]) == 0
    )
    grades = json.loads((run_dir / "grades.json").read_text())
    assert [t["score"] for t in grades["tasks"]] == [0.75, 0.75, 0.75]
    assert len(fake.records) == 6

    # The mock adapter is not a leaderboard adapter: the board rejects it by name.
    graded = tmp_path / "board"
    assert main(["leaderboard", "add", str(run_dir), "--graded", str(graded)]) == 1
    result = json.loads((run_dir / "result.json").read_text())
    result["adapter"]["name"] = "claude_python_haiku_5_5"
    (run_dir / "result.json").write_text(json.dumps(result))
    assert main(["leaderboard", "add", str(run_dir), "--graded", str(graded)]) == 0
    rows, agreements = load_graded(graded)
    assert [(r.model, r.mean) for r in rows] == [("haiku_5_5", 0.75)]
    assert agreements["sample"].within_one == 1.0
