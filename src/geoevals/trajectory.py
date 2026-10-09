"""Agent trajectories: the step records an agent adapter returns, and the counts derived from them.

A trajectory is the ordered list of an agent's steps for one case. Each step is a JSON object
with the fields of ``$defs/trajectoryStep`` in ``schemas/run-result.schema.json``:

- ``step``: position in the trajectory, from 0
- ``tool``: the tool called, or null for a step that calls no tool (the final answer, or a loop
  guard stopping the agent)
- ``args``: the tool-call arguments as a JSON object
- ``status``: ``ok`` or ``error``
- ``error_message``: a non-empty string when ``status`` is ``error``, else null
- ``duration_s``: wall-clock seconds, or null when not measured
- ``tokens``: ``{input, output}`` or null

A trajectory is recorded next to the output and never scored: a metric sees only the output, so
tool calls that all succeed say nothing about whether the answer is right.
"""

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator

SUMMARY_FIELDS = ("tool_calls", "tool_errors", "agent_steps", "agent_runtime_s")


@cache
def _trajectory_validator() -> Draft202012Validator:
    # geoevals.validation imports this module, so load the schema lazily.
    from geoevals.validation.validate import load_schema

    schema = load_schema("run-result.schema.json")
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "type": "array",
            "items": {"$ref": "#/$defs/trajectoryStep"},
        }
    )


def trajectory_problem(trajectory: Any) -> str | None:
    """Why an adapter's ``trajectory`` cannot be recorded, or ``None`` when it can.

    Checks that it is JSON, matches the step schema, and is numbered 0, 1, 2, ... in order.
    """
    try:
        json.dumps(trajectory, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return f"trajectory is not JSON: {exc}"
    issues = sorted(
        (f"trajectory.{'.'.join(map(str, e.absolute_path)) or '<root>'}", e.message)
        for e in _trajectory_validator().iter_errors(trajectory)
    )
    if issues:
        return "; ".join(f"{field}: {message}" for field, message in issues)
    return step_numbering_problem(trajectory)


def summarize_trajectory(steps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The case record's ``agent`` block for a (schema-valid) trajectory.

    ``tool_calls`` counts the steps with a tool, ``tool_errors`` those of them with status
    ``error``, ``agent_steps`` every step. ``agent_runtime_s`` is the sum of the step durations,
    or null when any step has none.
    """
    durations = [step["duration_s"] for step in steps]
    return {
        "tool_calls": sum(1 for step in steps if step["tool"] is not None),
        "tool_errors": sum(
            1 for step in steps if step["tool"] is not None and step["status"] == "error"
        ),
        "agent_steps": len(steps),
        "agent_runtime_s": None if None in durations else math.fsum(durations),
    }


def step_numbering_problem(steps: Sequence[Mapping[str, Any]]) -> str | None:
    """Why the ``step`` numbers are not 0, 1, 2, ... in order, or ``None`` when they are."""
    for index, step in enumerate(steps):
        if step["step"] != index:
            return f"step {index} has step number {step['step']}; steps are numbered from 0"
    return None


def summary_problem(summary: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> str | None:
    """Why a recorded ``agent`` block does not match its trajectory, or ``None``."""
    expected = summarize_trajectory(steps)
    for name in SUMMARY_FIELDS:
        recorded, derived = summary[name], expected[name]
        if name == "agent_runtime_s" and recorded is not None and derived is not None:
            matches = math.isclose(recorded, derived, rel_tol=1e-9, abs_tol=1e-12)
        else:
            matches = recorded == derived
        if not matches:
            return f"{name} is {recorded}, but the trajectory gives {derived}"
    return None


def run_aggregates(summaries: Iterable[Mapping[str, Any]]) -> dict[str, float | None]:
    """Run-level ``tool_error_rate`` and ``mean_steps`` over the cases' ``agent`` blocks.

    ``tool_error_rate`` is the total of ``tool_errors`` over the total of ``tool_calls`` (null
    with no tool calls); ``mean_steps`` the mean ``agent_steps`` (null with no trajectories).
    """
    summaries = list(summaries)
    calls = sum(s["tool_calls"] for s in summaries)
    errors = sum(s["tool_errors"] for s in summaries)
    steps = sum(s["agent_steps"] for s in summaries)
    return {
        "tool_error_rate": errors / calls if calls else None,
        "mean_steps": steps / len(summaries) if summaries else None,
    }
