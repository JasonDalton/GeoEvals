import json
from pathlib import Path
from typing import Any

import pytest

from geoevals.adapters.claude import ClaudeAdapterConfig
from geoevals.cli import main
from geoevals.graded.board import GRADED_END, GRADED_START
from geoevals.graded.spec import load_tasks
from geoevals.leaderboard.table import (
    END,
    START,
    LeaderboardError,
    add_run,
    load_rows,
    render,
    update_readme,
)
from geoevals.runner.config import load_run_config
from geoevals.runner.run import load_cases
from geoevals.validation import load_benchmark_spec, load_eval_spec

README = f"# Title\n\nIntro.\n\n{START}\nold table\n{END}\n\n## Next\n"
GRADED_README = README.replace("## Next", f"{GRADED_START}\nold graded\n{GRADED_END}\n\n## Next")


def _result(
    adapter: str = "claude_direct_opus_5_5",
    benchmark: str = "gis_correctness",
    statuses: tuple[str, ...] = ("scored", "scored", "scored", "invalid_output"),
    mean: float = 0.75,
    version: str = "0.1.0",
    manifest: str = "a" * 64,
    errors: dict[int, str] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = errors or {}
    return {
        "benchmark": {"id": benchmark, "version": version},
        "adapter": {
            "name": adapter,
            "version": "0.1.0+cc.2.1.296",
            "config": config if config is not None else {"effort": "high", "prompt_version": "v1"},
        },
        "dataset_manifest_hash": manifest,
        "summary_metrics": {
            "task_success": {"mean": mean, "ci_low": 0.62, "ci_high": 0.851, "n": len(statuses)}
        },
        "efficiency": {
            "latency_p50_s": 12.34,
            "latency_p90_s": 30.06,
            "tokens_input_total": 1234567,
            "tokens_output_total": 89012,
        },
        "cases": [
            {
                "case_id": f"c{i}",
                "split": "test",
                "status": status,
                "error": {"type": errors[i], "message": "m"} if i in errors else None,
            }
            for i, status in enumerate(statuses)
        ],
    }


def _write(results: Path, result: dict[str, Any]) -> Path:
    target = results / result["benchmark"]["id"] / result["adapter"]["name"]
    target.mkdir(parents=True)
    (target / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return target


def test_render_sorts_and_formats(tmp_path: Path) -> None:
    _write(tmp_path, _result("claude_python_haiku_5_5"))
    _write(tmp_path, _result("claude_direct_haiku_5_5"))
    _write(tmp_path, _result("claude_direct_opus_5_5"))
    _write(tmp_path, _result("claude_direct_opus_5_5", benchmark="human_context_access"))
    rows = load_rows(tmp_path)
    assert [(r.benchmark, r.track, r.model) for r in rows] == [
        ("gis_correctness", "direct", "opus_5_5"),
        ("gis_correctness", "direct", "haiku_5_5"),
        ("gis_correctness", "python", "haiku_5_5"),
        ("human_context_access", "direct", "opus_5_5"),
    ]
    table = render(rows)
    first = table.splitlines()[2]
    assert first == (
        "| Opus 5.5 | direct | `gis_correctness` 0.1.0 | 0.750 [0.62, 0.85] | 1 of 4 "
        "| 12.3 / 30.1 | 1,234,567 | 89,012 |"
    )
    assert "Claude Code 2.1.296" in table
    assert "effort high" in table
    assert f"manifest `{'a' * 12}`" in table


def test_render_with_no_runs(tmp_path: Path) -> None:
    assert load_rows(tmp_path) == []
    assert "No runs have been added yet" in render([])


def test_codex_run_provenance_and_mixed_leaderboard(tmp_path: Path) -> None:
    _write(tmp_path, _result())
    result = _result("codex_python_luna")
    result["adapter"]["version"] = "0.1.1+codex.0.160.0"
    _write(tmp_path, result)
    table = render(load_rows(tmp_path))
    assert "GPT-6 Luna | python" in table
    assert "Claude Code 2.1.296 on a Claude subscription" in table
    assert "Codex CLI 0.160.0 on a ChatGPT subscription" in table


@pytest.mark.parametrize("error", ["CodexHarnessError", "CodexUsageLimit"])
def test_codex_harness_failures_cannot_be_published(tmp_path: Path, error: str) -> None:
    _write(
        tmp_path,
        _result("codex_direct_luna", statuses=("adapter_error",), errors={0: error}),
    )
    with pytest.raises(LeaderboardError, match="failed in the harness"):
        load_rows(tmp_path)


@pytest.mark.parametrize("adapter", ["codex_python_opus_5_5", "claude_direct_luna"])
def test_model_must_match_provider(tmp_path: Path, adapter: str) -> None:
    _write(tmp_path, _result(adapter))
    with pytest.raises(LeaderboardError, match="supported leaderboard adapter"):
        load_rows(tmp_path)


def test_build_rejects_runs_with_skipped_cases(tmp_path: Path) -> None:
    _write(tmp_path, _result(statuses=("scored", "skipped")))
    with pytest.raises(LeaderboardError, match="1 of 2 case"):
        load_rows(tmp_path)


def test_build_rejects_other_adapters(tmp_path: Path) -> None:
    _write(tmp_path, _result(adapter="gis_baseline"))
    with pytest.raises(LeaderboardError, match="gis_baseline"):
        load_rows(tmp_path)


def test_build_rejects_incomparable_runs(tmp_path: Path) -> None:
    _write(tmp_path, _result("claude_direct_opus_5_5"))
    _write(tmp_path, _result("claude_direct_haiku_5_5", manifest="b" * 64))
    with pytest.raises(LeaderboardError, match="not comparable"):
        load_rows(tmp_path)


def test_update_readme_replaces_only_between_markers() -> None:
    updated = update_readme(README, "NEW")
    assert updated == f"# Title\n\nIntro.\n\n{START}\nNEW\n{END}\n\n## Next\n"
    assert update_readme(updated, "NEW") == updated
    with pytest.raises(LeaderboardError, match="once each"):
        update_readme("# no markers\n", "NEW")
    with pytest.raises(LeaderboardError):
        update_readme(f"{END}\n{START}\n", "NEW")


def test_add_run_copies_result_and_config(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "some-run"
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(json.dumps(_result()), encoding="utf-8")
    (run_dir / "config.yaml").write_text("split: test\n", encoding="utf-8")
    (run_dir / "run.log").write_text("log\n", encoding="utf-8")
    target = add_run(run_dir, tmp_path / "results")
    assert target == tmp_path / "results" / "gis_correctness" / "claude_direct_opus_5_5"
    assert sorted(p.name for p in target.iterdir()) == ["config.yaml", "result.json"]


def test_add_run_refuses_a_pilot(tmp_path: Path) -> None:
    run_dir = tmp_path / "pilot"
    run_dir.mkdir()
    (run_dir / "result.json").write_text(
        json.dumps(_result(statuses=("scored", "skipped", "skipped"))), encoding="utf-8"
    )
    with pytest.raises(LeaderboardError, match="skipped"):
        add_run(run_dir, tmp_path / "results")
    assert not (tmp_path / "results").exists()


def test_cli_build_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(GRADED_README, encoding="utf-8")
    results = tmp_path / "results"
    _write(results, _result())
    args = [
        "leaderboard",
        "build",
        "--results",
        str(results),
        "--readme",
        str(readme),
        "--graded",
        str(tmp_path / "graded"),
    ]
    assert main([*args, "--check"]) == 1
    assert "out of date" in capsys.readouterr().out
    assert main(args) == 0
    assert "| Opus 5.5 | direct |" in readme.read_text(encoding="utf-8")
    assert main([*args, "--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_cli_add_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "result.json").write_text(json.dumps(_result(adapter="mock")), encoding="utf-8")
    assert main(["leaderboard", "add", str(run_dir), "--results", str(tmp_path / "r")]) == 1
    assert "mock" in capsys.readouterr().err


def test_leaderboard_configs_are_valid() -> None:
    repo = Path(__file__).parent.parent
    configs = sorted((repo / "leaderboard" / "configs").glob("*.yaml"))
    assert [path.name for path in configs] == [
        "direct.yaml",
        "pilot-direct.yaml",
        "pilot-graded.yaml",
        "pilot-python.yaml",
        "python.yaml",
    ]
    case_ids: dict[str, set[str]] = {}
    for bench_dir in [
        repo / "benchmarks" / "gis_correctness",
        repo / "benchmarks" / "human_context",
    ]:
        spec = load_benchmark_spec(bench_dir / "benchmark.yaml")
        case_ids[spec.id] = {case.case_id for case in load_cases(spec, bench_dir)}
    task_ids: dict[str, set[str]] = {}
    for eval_dir in sorted((repo / "evals").glob("*/eval.yaml")):
        if eval_dir.parent.name == "city":
            continue
        eval_spec = load_eval_spec(eval_dir)
        task_ids[eval_spec.id] = {task.task_id for task in load_tasks(eval_dir, eval_spec)}
    for path in configs:
        config = load_run_config(path)
        adapter = ClaudeAdapterConfig.model_validate(config.adapter)
        assert adapter.case_timeout_s < config.timeout_s, path.name
        assert adapter.effort == "high" and adapter.prompt_version == "v1"
        if path.name == "pilot-graded.yaml":
            assert adapter.only_cases is not None
            for ids in task_ids.values():
                assert len(set(adapter.only_cases) & ids) == 1, path.name
            assert set(adapter.only_cases) <= set.union(*task_ids.values())
        elif path.name.startswith("pilot-"):
            assert adapter.only_cases is not None
            for ids in case_ids.values():
                assert len(set(adapter.only_cases) & ids) == 5, path.name
            assert set(adapter.only_cases) <= set.union(*case_ids.values())
        else:
            assert adapter.only_cases is None


@pytest.mark.parametrize(
    "error_type", ["ClaudeAuthError", "ClaudeRunError", "ClaudeUnexpectedModel", "WorkerCrashed"]
)
def test_build_rejects_harness_errors(tmp_path: Path, error_type: str) -> None:
    _write(tmp_path, _result(statuses=("scored", "adapter_error"), errors={1: error_type}))
    with pytest.raises(LeaderboardError, match=f"harness.*{error_type}"):
        load_rows(tmp_path)


def test_model_failures_are_accepted_as_failed_cases(tmp_path: Path) -> None:
    errors = {1: "ClaudeTimeout", 2: "ClaudeRefusal", 3: "ClaudeBudgetExceeded"}
    statuses = ("scored", "adapter_error", "adapter_error", "adapter_error", "invalid_output")
    _write(tmp_path, _result(statuses=statuses, errors=errors))
    [row] = load_rows(tmp_path)
    assert row.not_scored == 4


def test_build_rejects_runner_timeouts(tmp_path: Path) -> None:
    _write(tmp_path, _result(statuses=("scored", "timeout"), errors={1: "TimeoutError"}))
    with pytest.raises(LeaderboardError, match="runner's timeout"):
        load_rows(tmp_path)


def test_build_rejects_a_custom_cli(tmp_path: Path) -> None:
    _write(tmp_path, _result(config={"effort": "high", "claude_command": ["fake"]}))
    with pytest.raises(LeaderboardError, match="claude_command"):
        load_rows(tmp_path)


def test_build_rejects_mixed_effort(tmp_path: Path) -> None:
    _write(tmp_path, _result("claude_direct_opus_5_5"))
    _write(
        tmp_path,
        _result("claude_direct_haiku_5_5", config={"effort": "low", "prompt_version": "v1"}),
    )
    with pytest.raises(LeaderboardError, match="effort low"):
        load_rows(tmp_path)


def test_build_rejects_other_splits(tmp_path: Path) -> None:
    result = _result()
    result["cases"][0]["split"] = "dev"
    _write(tmp_path, result)
    with pytest.raises(LeaderboardError, match="split"):
        load_rows(tmp_path)
