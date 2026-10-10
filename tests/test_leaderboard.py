import json
from pathlib import Path
from typing import Any

import pytest

from geoevals.adapters.claude import ClaudeAdapterConfig
from geoevals.cli import main
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
from geoevals.validation import load_benchmark_spec

README = f"# Title\n\nIntro.\n\n{START}\nold table\n{END}\n\n## Next\n"


def _result(
    adapter: str = "claude_direct_opus_5_5",
    benchmark: str = "gis_correctness",
    statuses: tuple[str, ...] = ("scored", "scored", "scored", "invalid_output"),
    mean: float = 0.75,
    version: str = "0.1.0",
    manifest: str = "a" * 64,
) -> dict[str, Any]:
    return {
        "benchmark": {"id": benchmark, "version": version},
        "adapter": {
            "name": adapter,
            "version": "0.1.0+cc.2.1.296",
            "config": {"effort": "high", "prompt_version": "v1"},
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
        "cases": [{"case_id": f"c{i}", "status": status} for i, status in enumerate(statuses)],
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
    readme.write_text(README, encoding="utf-8")
    results = tmp_path / "results"
    _write(results, _result())
    args = ["leaderboard", "build", "--results", str(results), "--readme", str(readme)]
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
    for path in configs:
        config = load_run_config(path)
        adapter = ClaudeAdapterConfig.model_validate(config.adapter)
        assert adapter.case_timeout_s < config.timeout_s, path.name
        assert adapter.effort == "high" and adapter.prompt_version == "v1"
        if path.name.startswith("pilot-"):
            assert adapter.only_cases is not None
            for ids in case_ids.values():
                assert len(set(adapter.only_cases) & ids) == 5, path.name
            assert set(adapter.only_cases) <= set.union(*case_ids.values())
        else:
            assert adapter.only_cases is None
