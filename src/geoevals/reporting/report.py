"""Render a run result as ``report.md`` and a self-contained ``report.html``.

Both files come from Jinja2 templates in ``reporting/templates`` and share one context, so they
hold the same sections in the same order. All values are formatted to strings here; the
templates only lay them out. The HTML page has inline CSS and no links, scripts, images or
fonts, so opening it makes no network requests.
"""

import json
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

from geoevals.metrics.status import ABSTAIN_STATUSES
from geoevals.reporting.compare import load_run
from geoevals.runner.config import load_run_config
from geoevals.runner.layout import CONFIG_FILE, RESULT_FILE

REPORT_MD = "report.md"
REPORT_HTML = "report.html"

COMPARABILITY_NOTE = (
    "Comparisons are valid only between runs with the same benchmark version, metric versions, "
    "split, and dataset manifest hash."
)

NOT_RECORDED = "not recorded"
NOT_SET = "(not set)"

EFFICIENCY_LABELS: dict[str, str] = {
    "wall_clock_s": "Wall clock (s)",
    "cases_total": "Cases",
    "cases_per_s": "Throughput (cases/s)",
    "latency_p50_s": "Latency p50 (s)",
    "latency_p90_s": "Latency p90 (s)",
    "latency_p99_s": "Latency p99 (s)",
    "latency_max_s": "Latency max (s)",
    "timeout_rate": "Timeout rate",
    "failure_rate": "Failure rate",
    "retries_total": "Retries",
    "peak_rss_bytes": "Peak RSS (bytes)",
    "tokens_input_total": "Input tokens",
    "tokens_output_total": "Output tokens",
    "cost_usd_total": "Cost, total (USD)",
    "cost_usd_per_case": "Cost per case (USD)",
    "price_table_hash": "Price table hash",
    "tool_error_rate": "Tool error rate",
    "mean_steps": "Mean agent steps",
}
"""Every field of the run result's ``efficiency`` block, in report order."""


def fmt(value: Any) -> str:
    """Format a value for a report cell: ``n/a`` for null, 6 significant digits for floats."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, int | str):
        return str(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class _Stat:
    mean: str
    n: str
    failed: str


def _stratum_stat(cases: Iterable[Mapping[str, Any]], metric_id: str) -> _Stat:
    """Mean, n and failed count of one metric, counted as ``metrics.aggregate_values`` does."""
    values = [case["metrics"][metric_id] for case in cases if metric_id in case["metrics"]]
    numbers = [v["value"] for v in values if v["value"] is not None]
    failed = sum(1 for v in values if v["passed"] is False)
    mean = statistics.fmean(numbers) if numbers else None
    return _Stat(fmt(mean), str(len(numbers)), str(failed))


def _stratum_order(value: Any) -> tuple[int, Any]:
    if value is None:
        return (3, "")
    if isinstance(value, bool):
        return (0, value)
    if isinstance(value, int | float):
        return (1, value)
    return (2, str(value))


def _strata(cases: list[Mapping[str, Any]], metric_ids: list[str]) -> list[dict[str, Any]]:
    keys = sorted({key for case in cases for key in case["strata"]})
    breakdowns = []
    for key in keys:
        groups: dict[Any, list[Mapping[str, Any]]] = {}
        for case in cases:
            groups.setdefault(case["strata"].get(key), []).append(case)
        rows = []
        for value in sorted(groups, key=_stratum_order):
            group = groups[value]
            rows.append(
                {
                    "value": NOT_SET if value is None else fmt(value),
                    "cases": str(len(group)),
                    "scored": str(sum(1 for case in group if case["status"] == "scored")),
                    "metrics": [_stratum_stat(group, metric_id) for metric_id in metric_ids],
                }
            )
        breakdowns.append({"key": key, "rows": rows})
    return breakdowns


def _ratio(numerator: int, denominator: int) -> str:
    return fmt(numerator / denominator) if denominator else "n/a"


def _abstention(cases: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Answered-vs-abstained confusion counts over the scored cases with ``status_match``
    (whose ``detail`` holds both statuses), with abstaining as the positive class. A case
    abstains when its status is one of ``ABSTAIN_STATUSES``; any other status, missing
    included, counts as answered. ``None`` when no case has the counts."""
    counts = {(expected, predicted): 0 for expected in (True, False) for predicted in (True, False)}
    for case in cases:
        detail = case["metrics"].get("status_match", {}).get("detail") or {}
        if case["status"] == "scored" and "expected" in detail and "predicted" in detail:
            key = (detail["expected"] in ABSTAIN_STATUSES, detail["predicted"] in ABSTAIN_STATUSES)
            counts[key] += 1
    if not any(counts.values()):
        return None
    tp, fn = counts[(True, True)], counts[(True, False)]
    fp, tn = counts[(False, True)], counts[(False, False)]
    return {
        "rows": [
            ("Should abstain", str(tp), str(fn)),
            ("Should answer", str(fp), str(tn)),
        ],
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
    }


def _error_text(error: Mapping[str, Any] | None) -> str:
    if error is None:
        return "no error recorded"
    return f"{error['type']}: {error['message']}" if error["message"] else error["type"]


def _failures(cases: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Every non-``scored`` case and every metric with ``passed: false``, in case-ID order."""
    rows = []
    for case in cases:
        if case["status"] != "scored":
            rows.append(
                {
                    "case_id": case["case_id"],
                    "status": case["status"],
                    "metric": "",
                    "detail": _error_text(case["error"]),
                }
            )
        for metric_id in sorted(case["metrics"]):
            value = case["metrics"][metric_id]
            if value["passed"] is False:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "status": case["status"],
                        "metric": metric_id,
                        "detail": f"value {fmt(value['value'])}; detail {fmt(value['detail'])}",
                    }
                )
    return rows


def _outcome(case: Mapping[str, Any]) -> str:
    """``not scored``, ``failed`` (a metric with ``passed: false``) or ``passed``."""
    if case["status"] != "scored":
        return "not scored"
    if any(value["passed"] is False for value in case["metrics"].values()):
        return "failed"
    return "passed"


def _trajectories(cases: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """One summary row per case with a trajectory, and every step of each case that did not
    pass. ``None`` when no case has a trajectory."""
    agent_cases = [case for case in cases if "trajectory" in case]
    if not agent_cases:
        return None
    summary = [
        {
            "case_id": case["case_id"],
            "status": case["status"],
            "outcome": _outcome(case),
            **{key: fmt(value) for key, value in case["agent"].items()},
        }
        for case in agent_cases
    ]
    failed = [
        {
            "case_id": case["case_id"],
            "outcome": _outcome(case),
            "steps": [
                {
                    "step": str(step["step"]),
                    "tool": step["tool"] or "(no tool)",
                    "args": fmt(step["args"]),
                    "status": step["status"],
                    "error": step["error_message"] or "-",
                    "duration": fmt(step["duration_s"]),
                    "tokens": fmt(step["tokens"]),
                }
                for step in case["trajectory"]
            ],
        }
        for case in agent_cases
        if _outcome(case) != "passed"
    ]
    return {"summary": summary, "failed": failed}


def _split(result: Mapping[str, Any], run_dir: Path | None) -> str:
    """The run's split, from ``config.yaml`` when present, else from the case records."""
    if run_dir is not None and (run_dir / CONFIG_FILE).is_file():
        return load_run_config(run_dir / CONFIG_FILE).split
    splits = sorted({case["split"] for case in result["cases"]})
    return ", ".join(splits) if splits else NOT_RECORDED


def _model(adapter_config: Mapping[str, Any]) -> str:
    """The ``model`` in the adapter config, where model-based adapters take their model ID."""
    model = adapter_config.get("model")
    if model is None:
        return "none recorded (the adapter config has no model)"
    return fmt(model)


def report_context(result: Mapping[str, Any], split: str) -> dict[str, Any]:
    """The values both report templates render, all formatted as strings."""
    cases = list(result["cases"])
    summary_metrics = result["summary_metrics"]
    metric_ids = sorted(summary_metrics)
    scored = sum(1 for case in cases if case["status"] == "scored")
    benchmark, adapter = result["benchmark"], result["adapter"]
    summary = [
        ("Run ID", result["run_id"]),
        ("Benchmark", f"{benchmark['id']} {benchmark['version']}"),
        ("Split", split),
        ("Adapter", f"{adapter['name']} {adapter['version']}"),
        ("Model", _model(adapter["config"])),
        ("Adapter config", fmt(adapter["config"])),
        (
            "Metric versions",
            ", ".join(f"{m} {summary_metrics[m]['version']}" for m in metric_ids) or "none",
        ),
        ("Config hash", result["config_hash"]),
        ("Dataset manifest hash", result["dataset_manifest_hash"]),
        ("Run result schema", result["schema_version"]),
        ("Started", result["started_at"]),
        ("Finished", result["finished_at"]),
        ("Cases", f"{len(cases)} ({scored} scored, {len(cases) - scored} not scored)"),
    ]
    metrics = [
        {
            "id": metric_id,
            "version": summary["version"],
            "mean": fmt(summary["mean"]),
            "median": fmt(summary["median"]),
            "ci": (
                NOT_RECORDED
                if summary["ci_low"] is None
                else f"[{fmt(summary['ci_low'])}, {fmt(summary['ci_high'])}]"
            ),
            "n": str(summary["n"]),
            "n_failed": str(summary["n_failed"]),
        }
        for metric_id, summary in sorted(summary_metrics.items())
    ]
    efficiency = result["efficiency"]
    environment = result["environment"]
    return {
        "title": f"{benchmark['id']} {benchmark['version']} / {adapter['name']}",
        "comparability_note": COMPARABILITY_NOTE,
        "summary": summary,
        "metrics": metrics,
        "metric_ids": metric_ids,
        "abstention": _abstention(cases),
        "strata": _strata(cases, metric_ids),
        "efficiency": [
            (label, fmt(efficiency[key]) if key in efficiency else NOT_RECORDED)
            for key, label in EFFICIENCY_LABELS.items()
        ],
        "failures": _failures(cases),
        "trajectories": _trajectories(cases),
        "environment": [(key, fmt(environment[key])) for key in sorted(environment)],
        "provenance": _provenance(result),
        "limitations": list(result["limitations"]),
    }


def _provenance(result: Mapping[str, Any]) -> dict[str, Any] | None:
    provenance = result.get("provenance")
    if provenance is None:
        return None
    benchmark, dataset = provenance["benchmark"], provenance["dataset"]
    rows = [
        ("Benchmark license", benchmark["license"]),
        ("Authors", ", ".join(benchmark["authors"])),
        ("Created", benchmark["created"]),
    ]
    rows += [
        (label, benchmark[key])
        for key, label in (("reference_workflow", "Reference workflow"), ("notes", "Notes"))
        if key in benchmark
    ]
    rows.append(("Dataset", dataset["dataset_id"]))
    assets = [
        {
            "asset_id": asset["asset_id"],
            "license": asset["license"],
            "attribution": asset["attribution"],
            "redistributable": fmt(asset["redistributable"]),
            "source": "; ".join(asset[key] for key in ("source_url", "citation") if key in asset),
        }
        for asset in dataset["assets"]
    ]
    return {"rows": rows, "assets": assets}


def _md_cell(value: Any) -> str:
    """Escape a value for a Markdown table cell."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _environment(autoescape: bool) -> Environment:
    env = Environment(
        loader=PackageLoader("geoevals.reporting", "templates"),
        autoescape=autoescape,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["cell"] = _md_cell
    return env


def render_markdown(context: Mapping[str, Any]) -> str:
    return _environment(autoescape=False).get_template("report.md.j2").render(context)


def render_html(context: Mapping[str, Any]) -> str:
    return _environment(autoescape=True).get_template("report.html.j2").render(context)


def write_report(path: Path) -> tuple[Path, Path]:
    """Write ``report.md`` and ``report.html`` into the run directory and return their paths.

    ``path`` is a run directory or its ``result.json``. Raises ``SpecValidationError`` if the
    run result is missing or invalid.
    """
    run_dir = path.parent if path.name == RESULT_FILE and path.is_file() else path
    result = load_run(path)
    context = report_context(result, _split(result, run_dir))
    md_path, html_path = run_dir / REPORT_MD, run_dir / REPORT_HTML
    md_path.write_text(render_markdown(context), encoding="utf-8")
    html_path.write_text(render_html(context), encoding="utf-8")
    return md_path, html_path
