import json
from pathlib import Path

import pytest

from claude_fakes import FAKE_COMMAND, FakeClaude, init_event, result_event
from geoevals.cli import main
from geoevals.graded.grader import (
    GRADER_MODEL,
    GradeError,
    GraderConfig,
    check_grade,
    grade_run,
    load_grades,
    task_score,
)
from geoevals.graded.run import load_graded_result
from graded_helpers import graded_run_dir

IDS = ["relations", "reasoning", "assumptions", "data_use", "clarity"]
USAGE = {GRADER_MODEL: {"inputTokens": 5, "outputTokens": 50}}


def grade(score: int = 3, words: int = 5) -> dict:
    return {
        "criteria": {i: {"score": score, "justification": " ".join(["key"] * words)} for i in IDS}
    }


def events(answer: dict | None, **fields) -> list[dict]:
    return [init_event(), result_event(answer, model_usage=USAGE, **fields)]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    return FakeClaude(tmp_path, monkeypatch)


def _config(root: Path) -> GraderConfig:
    return GraderConfig(command=FAKE_COMMAND, evals_root=root / "evals")


def test_check_grade() -> None:
    assert check_grade(grade(), IDS) is None
    assert "missing" in (check_grade({"criteria": {}}, IDS) or "")
    extra = grade()
    extra["criteria"]["style"] = {"score": 1, "justification": "x"}
    assert "unexpected" in (check_grade(extra, IDS) or "")
    high = grade()
    high["criteria"]["clarity"]["score"] = 5
    assert "0 to 4" in (check_grade(high, IDS) or "")
    assert "60 words" in (check_grade(grade(words=61), IDS) or "")
    assert check_grade("not json", IDS) is not None


def test_task_score_is_the_mean_over_passes_of_mean_criteria_over_4() -> None:
    passes = [grade(4)["criteria"], grade(2)["criteria"]]
    assert task_score(passes) == pytest.approx(0.75)


def test_grade_run_grades_answered_tasks_twice(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered", "sample-002": "answered"})
    fake.set(events(grade(3)))
    grades = grade_run(run_dir, data, _config(tmp_path))
    assert [t.status for t in grades.tasks] == ["graded", "graded"]
    assert all(len(t.passes) == 2 and t.score == pytest.approx(0.75) for t in grades.tasks)
    assert grades.grader.model == GRADER_MODEL
    assert grades.grader.claude_code_version == "9.9.9"
    assert grades.grader.passes == 2
    assert grades.stopped is None
    assert len(fake.records) == 4


def test_no_answer_scores_zero_without_a_call(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(
        tmp_path, {"sample-001": "invalid_output", "sample-003": "timeout"}
    )
    grades = grade_run(run_dir, data, _config(tmp_path))
    assert [(t.status, t.score) for t in grades.tasks] == [("no_answer", 0.0), ("no_answer", 0.0)]
    assert not fake.called


def test_invalid_grade_is_retried_once(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set_sequence([events({"criteria": {}}), events(grade(4)), events(grade(4))])
    [task] = grade_run(run_dir, data, _config(tmp_path)).tasks
    assert task.status == "graded" and task.score == 1.0
    assert len(fake.records) == 3


def test_two_invalid_grades_leave_the_task_not_graded(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set(events(grade(words=61)))
    [task] = grade_run(run_dir, data, _config(tmp_path)).tasks
    assert task.status == "not_graded" and task.score is None
    assert "60 words" in (task.error or "")


def test_usage_limit_stops_grading(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered", "sample-002": "answered"})
    fake.set(events(None, is_error=True, subtype="error_during_execution", api_error_status=429))
    grades = grade_run(run_dir, data, _config(tmp_path))
    assert grades.stopped is not None and "usage limit" in grades.stopped
    assert [t.status for t in grades.tasks] == ["not_graded", "not_graded"]
    assert len(fake.records) == 1


def test_wrong_model_stops_grading(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    other = {"claude-sonnet-5-5": {"inputTokens": 5, "outputTokens": 50}}
    fake.set([init_event(), result_event(grade(), model_usage=other)])
    grades = grade_run(run_dir, data, _config(tmp_path))
    assert grades.stopped is not None and "ClaudeUnexpectedModel" in grades.stopped


def test_grader_never_sees_who_answered(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set(events(grade()))
    grade_run(run_dir, data, _config(tmp_path))
    record = fake.records[0]
    sent = record["stdin"] + " ".join(record["argv"])
    for name in ("haiku", "claude_python", load_graded_result(run_dir)["run_id"]):
        assert name.lower() not in sent.lower(), name
    assert "walking_nearest" in record["stdin"], "the key is sent"
    assert "North Pharmacy (node/500)" in record["stdin"], "the answer is sent"
    assert "50.000538987" in record["stdin"], "the task location is sent"
    argv = record["argv"]
    assert argv[argv.index("--model") + 1] == GRADER_MODEL
    assert argv[argv.index("--tools") + 1] == ""


def test_grade_refuses_missing_or_stale_keys(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    keys = data / "keys" / "sample.jsonl"
    keys.write_text(keys.read_text().replace("node/500", "node/999"), encoding="utf-8")
    with pytest.raises(GradeError, match="sample-001"):
        grade_run(run_dir, data, _config(tmp_path))
    keys.unlink()
    with pytest.raises(GradeError, match="no keys file"):
        grade_run(run_dir, data, _config(tmp_path))
    assert not fake.called


def test_grade_cli_writes_grades_json(
    tmp_path: Path, fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set(events(grade()))
    monkeypatch.setattr("geoevals.cli.GRADER_COMMAND", FAKE_COMMAND)
    code = main(["grade", str(run_dir), "--data", str(data), "--evals", str(tmp_path / "evals")])
    assert code == 0
    grades = load_grades(run_dir / "grades.json")
    assert grades.run_id == load_graded_result(run_dir)["run_id"]
    assert json.loads((run_dir / "grades.json").read_text())["schema_version"] == "1.0.0"


def test_grade_cli_exits_1_when_tasks_are_not_graded(
    tmp_path: Path, fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set(events(grade(words=61)))
    monkeypatch.setattr("geoevals.cli.GRADER_COMMAND", FAKE_COMMAND)
    code = main(["grade", str(run_dir), "--data", str(data), "--evals", str(tmp_path / "evals")])
    assert code == 1
    [task] = load_grades(run_dir / "grades.json").tasks
    assert task.status == "not_graded"


def test_grade_run_refuses_a_task_the_eval_no_longer_has(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    result = json.loads((run_dir / "result.json").read_text())
    result["tasks"][0]["task_id"] = "sample-009"
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(
        GradeError, match=r"sample-009 is not in .*tasks\.jsonl; was the eval changed"
    ):
        grade_run(run_dir, data, _config(tmp_path))
    assert not fake.called


def test_grade_cli_refuses_to_overwrite_grades_without_force(
    tmp_path: Path,
    fake: FakeClaude,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    (run_dir / "grades.json").write_text("{}\n", encoding="utf-8")
    fake.set(events(grade()))
    monkeypatch.setattr("geoevals.cli.GRADER_COMMAND", FAKE_COMMAND)
    args = ["grade", str(run_dir), "--data", str(data), "--evals", str(tmp_path / "evals")]
    assert main(args) == 1
    assert "--force" in capsys.readouterr().err
    assert (run_dir / "grades.json").read_text() == "{}\n"
    assert not fake.called
    assert main([*args, "--force"]) == 0
    assert load_grades(run_dir / "grades.json").tasks[0].status == "graded"
