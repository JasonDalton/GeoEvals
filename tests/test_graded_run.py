import json
from pathlib import Path

import pytest
import yaml

from geoevals.cli import main
from geoevals.graded.city import layers_sha256
from geoevals.graded.run import (
    answer_problem,
    case_input,
    load_graded_result,
    run_eval,
    validate_graded_result,
)
from geoevals.graded.spec import load_tasks
from geoevals.runner.config import RunConfig
from geoevals.runner.run import RunError
from geoevals.validation import load_eval_spec
from graded_helpers import SAMPLE, copy_sample_eval, sample_data

ANSWERS = {
    "sample-001": {"status": "ok", "answer": "North Pharmacy (node/500) is nearest on foot."},
    "sample-002": {"status": "ok", "answer": "word " * 4001},
    "sample-003": {"status": "insufficient_data", "answer": "The data holds no closure dates."},
}


def test_run_eval_records_answers_and_invalid_outputs(tmp_path: Path) -> None:
    spec_path, data = copy_sample_eval(tmp_path), sample_data(tmp_path)
    config = RunConfig(split="test", adapter={"references": ANSWERS})
    result = run_eval(spec_path, "mock", config, data)
    statuses = {t["task_id"]: t["status"] for t in result["tasks"]}
    assert statuses == {
        "sample-001": "answered",
        "sample-002": "invalid_output",
        "sample-003": "answered",
    }
    assert "4001 words" in result["tasks"][1]["error"]["message"]
    assert result["eval"] == {"id": "sample", "version": "0.1.0"}
    assert result["data_sha256"] == layers_sha256(data / "layers")
    assert validate_graded_result(result) == []
    assert "summary_metrics" not in result
    assert all("metrics" not in task for task in result["tasks"])


def test_answer_problem() -> None:
    assert answer_problem({"status": "ok", "answer": "a b c"}, 3) is None
    assert answer_problem({"status": "ok", "answer": "a b c d"}, 3) == (
        "the answer has 4 words; the limit is 3"
    )
    assert answer_problem({"status": "ok", "answer": "   "}, 3) == "the answer is empty"
    assert "answer" in (answer_problem({"status": "ok"}, 3) or "")
    assert "status" in (answer_problem({"status": "maybe", "answer": "x"}, 3) or "")
    assert answer_problem(["not", "an", "object"], 3) is not None


def test_case_input_hides_params_and_keys() -> None:
    spec = load_eval_spec(SAMPLE)
    task = load_tasks(SAMPLE, spec)[0]
    case = case_input(task, SAMPLE, 4000)
    assert case["case_id"] == "sample-001"
    assert case["inputs"] == {
        "files": {},
        "params": {"point": [10.0, 50.000538987], "feature_ids": []},
    }
    assert case["benchmark_dir"] == str(SAMPLE.parent.resolve())
    assert "Write for: a resident with no GIS background." in case["prompt"]
    assert "at most 4,000 words" in case["prompt"]
    text = json.dumps(case)
    assert "category" not in text and "key_sha256" not in text and "strata" not in text


def test_run_eval_refuses_other_splits_and_missing_layers(tmp_path: Path) -> None:
    spec_path = copy_sample_eval(tmp_path)
    with pytest.raises(RunError, match="one split"):
        run_eval(spec_path, "mock", RunConfig(split="dev"), sample_data(tmp_path))
    with pytest.raises(RunError, match="no city layers"):
        run_eval(spec_path, "mock", RunConfig(split="test"), tmp_path / "empty")


def test_run_eval_cli(tmp_path: Path) -> None:
    spec_path, data = copy_sample_eval(tmp_path), sample_data(tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"split": "test", "adapter": {"references": ANSWERS}}))
    out = tmp_path / "runs"
    code = main(
        [
            "run",
            "--eval",
            str(spec_path),
            "--adapter",
            "mock",
            "--config",
            str(config),
            "--out",
            str(out),
            "--data",
            str(data),
        ]
    )
    assert code == 0
    [run_dir] = list(out.iterdir())
    result = load_graded_result(run_dir / "result.json")
    assert result["adapter"]["name"] == "mock"
    assert (run_dir / "config.yaml").is_file() and (run_dir / "run.log").is_file()


def test_run_needs_a_benchmark_or_an_eval(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["run", "--adapter", "mock", "--config", "c.yaml", "--out", "o"])
