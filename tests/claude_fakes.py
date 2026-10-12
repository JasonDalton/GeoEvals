"""Helpers for tests that run the fake ``claude`` CLI (``tests/fake_claude.py``)."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

FAKE_COMMAND = (sys.executable, str(Path(__file__).parent / "fake_claude.py"))
MODEL = "claude-haiku-5-5"


def init_event(api_key_source: str = "none", tools: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "init",
        "apiKeySource": api_key_source,
        "claude_code_version": "9.9.9",
        "tools": tools if tools is not None else ["StructuredOutput"],
        "model": MODEL,
    }


def result_event(
    answer: dict[str, Any] | None = None, model_usage: dict[str, Any] | None = None, **fields: Any
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "stop_reason": "tool_use",
        "api_error_status": None,
        "num_turns": 2,
        "result": json.dumps(answer),
        "structured_output": answer,
        "modelUsage": model_usage
        if model_usage is not None
        else {
            MODEL: {
                "inputTokens": 2,
                "outputTokens": 115,
                "cacheReadInputTokens": 10,
                "cacheCreationInputTokens": 1099,
            }
        },
    }
    if answer is None:
        del event["structured_output"]
    event.update(fields)
    return event


class FakeClaude:
    """Writes a scenario for the fake CLI and reads back what it recorded."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.scenario_path = tmp_path / "scenario.json"
        self.record_path = tmp_path / "record.json"
        monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(self.scenario_path))
        monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(self.record_path))
        self.set([init_event(), result_event({"status": "ok"})])

    def set(self, events: list[dict[str, Any]], **extra: Any) -> None:
        self.scenario_path.write_text(json.dumps({"events": events, **extra}), encoding="utf-8")
        self._reset_counter()

    def set_sequence(self, scenarios: list[list[dict[str, Any]]]) -> None:
        """One list of events per call; the last repeats."""
        sequence = [{"events": events} for events in scenarios]
        self.scenario_path.write_text(json.dumps({"sequence": sequence}), encoding="utf-8")
        self._reset_counter()

    def _reset_counter(self) -> None:
        self.scenario_path.with_name(self.scenario_path.name + ".count").unlink(missing_ok=True)

    @property
    def records(self) -> list[dict[str, Any]]:
        return json.loads(self.record_path.read_text(encoding="utf-8"))

    @property
    def record(self) -> dict[str, Any]:
        return self.records[-1]

    @property
    def called(self) -> bool:
        return self.record_path.is_file()
