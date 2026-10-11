"""What the Claude adapters send to the model: the system prompt and the user message of a case.

``benchmark_dir`` is a benchmark's directory, or a graded eval's (with ``eval.yaml``).
The system prompt is a versioned template from ``geoevals/adapters/prompts/<track>_<version>.md``
with the benchmark's task statement filled in. The user message holds the case ``prompt``, its
``inputs.params`` and its input files. Nothing else from the case is sent: not ``expected``,
``strata`` (which flags trap cases), ``tolerances``, ``metric_params`` or the case ID.

On the direct track the files are inlined as GeoJSON text (GeoParquet files are converted with
GeoPandas, coordinates unchanged). On the python track the model gets each file's path in the
sandbox instead.
"""

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

import geopandas as gpd

from geoevals.validation import load_benchmark_spec

PROMPTS_DIR = Path(__file__).parent.parent / "adapters" / "prompts"
SPEC_FILE = "benchmark.yaml"
EVAL_SPEC_FILE = "eval.yaml"
ANNOTATION_KEYWORDS = frozenset({"evidence_type"})
"""GeoEvals keywords in output schemas that the CLI's schema validator rejects."""


def load_template(track: str, version: str) -> str:
    """The system prompt template of ``track`` (direct or python) at ``version`` (v1, ...)."""
    path = PROMPTS_DIR / f"{track}_{version}.md"
    if not path.is_file():
        raise ValueError(f"no prompt template {track!r} version {version!r} ({path})")
    return path.read_text(encoding="utf-8")


def system_prompt(template: str, task_statement: str) -> str:
    return template.replace("{task_statement}", task_statement.strip())


@cache
def _spec(benchmark_dir: str) -> tuple[str, str]:
    directory = Path(benchmark_dir)
    if (directory / EVAL_SPEC_FILE).is_file():
        # A graded eval: its task statement and the fixed answer schema.
        from geoevals.graded.spec import OUTPUT_SCHEMA
        from geoevals.validation import load_eval_spec

        eval_spec = load_eval_spec(directory / EVAL_SPEC_FILE)
        return eval_spec.task_statement, json.dumps(OUTPUT_SCHEMA)
    spec = load_benchmark_spec(directory / SPEC_FILE)
    return spec.task_statement, json.dumps(spec.output_schema)


def spec_for(case_input: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The task statement and output schema of the benchmark the case belongs to."""
    task_statement, schema = _spec(str(case_input["benchmark_dir"]))
    return task_statement, json.loads(schema)


def cli_schema(schema: Any) -> Any:
    """A copy of ``schema`` without the GeoEvals annotation keywords, for ``--json-schema``."""
    if isinstance(schema, dict):
        return {
            key: cli_schema(value)
            for key, value in schema.items()
            if key not in ANNOTATION_KEYWORDS
        }
    if isinstance(schema, list):
        return [cli_schema(item) for item in schema]
    return schema


def _header(case_input: Mapping[str, Any]) -> str:
    params = case_input["inputs"].get("params", {})
    return f"{case_input['prompt']}\n\nParameters (JSON):\n{json.dumps(params, indent=2)}"


def _files(case_input: Mapping[str, Any]) -> dict[str, str]:
    return dict(case_input["inputs"].get("files", {}))


def _geojson(path: Path) -> str:
    if path.suffix == ".parquet":
        return gpd.read_parquet(path).to_json(drop_id=True)
    return path.read_text(encoding="utf-8").strip()


def direct_message(case_input: Mapping[str, Any]) -> str:
    """The user message of the direct track: request, params and every file as GeoJSON."""
    benchmark_dir = Path(case_input["benchmark_dir"])
    parts = [_header(case_input)]
    for name, relative in _files(case_input).items():
        text = _geojson(benchmark_dir / relative)
        parts.append(f'Input file "{name}" ({relative}, GeoJSON):\n{text}')
    return "\n\n".join(parts)


def python_message(case_input: Mapping[str, Any], mount: str = "/bench") -> str:
    """The user message of the python track: request, params and the file paths in the sandbox."""
    parts = [_header(case_input)]
    files = _files(case_input)
    if files:
        lines = [f'Input file "{name}": {mount}/{relative}' for name, relative in files.items()]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
