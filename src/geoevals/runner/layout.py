"""The run directory: what a run writes to ``<out>/<run_id>/``.

::

    <out>/<run_id>/
        result.json     the run result (validated against run-result.schema.json)
        cases.jsonl     one case record per line, in case-ID order (the same records as
                        result.json's ``cases``)
        config.yaml     the resolved run config (defaults filled in); its config_hash is the
                        run result's ``config_hash``
        run.log         the run's log
        artifacts/      one GeoParquet file per case whose output contains GeoJSON geometry

``run_id`` is ``<benchmark_id>-<adapter>-<UTC timestamp>-<first 8 chars of config_hash>``.

JSON is written with sorted keys, and every float is rounded to 15 significant digits (the
precision a double always holds) and then written as the shortest decimal that reads back as the
same float. Values that differ only by floating-point noise (``0.1 + 0.2``) are written the same,
and the text does not depend on the platform, so ``git diff`` shows real changes only.
"""

import hashlib
import json
import logging
import math
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from geoevals.runner.config import RunConfig, canonical_config

logger = logging.getLogger(__name__)

RESULT_FILE = "result.json"
CASES_FILE = "cases.jsonl"
CONFIG_FILE = "config.yaml"
LOG_FILE = "run.log"
ARTIFACTS_DIR = "artifacts"

GEOMETRY_TYPES = frozenset(
    {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def make_run_id(benchmark_id: str, adapter_name: str, started: datetime, digest: str) -> str:
    """``<benchmark_id>-<adapter>-<UTC timestamp>-<first 8 chars of config_hash>``."""
    return f"{benchmark_id}-{adapter_name}-{started.strftime('%Y%m%dT%H%M%SZ')}-{digest[:8]}"


def stable(value: Any) -> Any:
    """Round floats to 15 significant digits (and ``-0.0`` to ``0.0``), recursively."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"cannot write a non-finite number as JSON: {value!r}")
        return float(f"{value:.15g}") + 0.0
    if isinstance(value, Mapping):
        return {key: stable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [stable(item) for item in value]
    return value


def dumps(value: Any, indent: int | None = 2) -> str:
    """JSON with sorted keys and stable floats; compact on one line when ``indent`` is None."""
    separators = (",", ":") if indent is None else (",", ": ")
    return json.dumps(
        stable(value),
        indent=indent,
        separators=separators,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )


def write_result(result: Mapping[str, Any], path: Path) -> None:
    """Write a run result as indented JSON."""
    path.write_text(dumps(result) + "\n", encoding="utf-8")


def write_cases(cases: list[Mapping[str, Any]], path: Path) -> None:
    """Write case records as JSONL, one compact record per line."""
    path.write_text("".join(dumps(case, indent=None) + "\n" for case in cases), encoding="utf-8")


def write_config(config: RunConfig, path: Path) -> None:
    """Write the resolved run config as YAML with sorted keys."""
    text = yaml.safe_dump(canonical_config(config), sort_keys=True, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def find_geometries(value: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Return ``(field path, geometry)`` for every GeoJSON geometry object in ``value``.

    A geometry is a mapping whose ``type`` is a GeoJSON geometry type and that has
    ``coordinates`` (or ``geometries`` for a GeometryCollection). The search does not descend
    into a geometry, so a GeometryCollection is one geometry. Features are found through their
    ``geometry`` member.
    """
    if isinstance(value, Mapping):
        member = "geometries" if value.get("type") == "GeometryCollection" else "coordinates"
        if value.get("type") in GEOMETRY_TYPES and member in value:
            return [(path or "<root>", dict(value))]
        found = []
        for key in sorted(value):
            found += find_geometries(value[key], f"{path}.{key}" if path else str(key))
        return found
    if isinstance(value, list):
        found = []
        for i, item in enumerate(value):
            found += find_geometries(item, f"{path}[{i}]")
        return found
    return []


def artifact_name(case_id: str) -> str:
    """File name for a case's artifact. Case IDs with unsafe characters get a hash suffix."""
    safe = _SAFE_NAME.sub("_", case_id)
    if safe != case_id:
        safe += "-" + hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8]
    return f"{safe}.parquet"


def write_artifacts(cases: list[Mapping[str, Any]], directory: Path) -> list[Path]:
    """Write one GeoParquet file per case whose output contains geometry; return the paths.

    Each file has one row per geometry: ``path`` (the field path in the output, such as
    ``features[0].geometry``) and ``geometry``. The CRS is left undefined, since outputs do not
    state one. A geometry that shapely cannot read is logged and left out; the case output in
    ``cases.jsonl`` still has it.
    """
    written = []
    for case in cases:
        found = find_geometries(case.get("output"))
        if not found:
            continue
        # Imported here: geopandas is slow to import and most runs have no geometry outputs.
        import geopandas
        import shapely.geometry

        paths, shapes = [], []
        for field, geometry in found:
            try:
                shapes.append(shapely.geometry.shape(geometry))
            except Exception as exc:
                logger.warning(
                    "case %s: output.%s is not a readable geometry (%s: %s); left out of the "
                    "artifact",
                    case["case_id"],
                    field,
                    type(exc).__name__,
                    exc,
                )
                continue
            paths.append(field)
        if not shapes:
            continue
        target = directory / artifact_name(case["case_id"])
        frame = geopandas.GeoDataFrame({"path": paths}, geometry=shapes, crs=None)
        frame.to_parquet(target, index=False)
        written.append(target)
    return written


def write_run_dir(result: Mapping[str, Any], run_dir: Path) -> None:
    """Write ``result.json``, ``cases.jsonl`` and ``artifacts/`` (always created, so the layout
    is the same for every run) into ``run_dir``."""
    (run_dir / ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)
    write_result(result, run_dir / RESULT_FILE)
    write_cases(result["cases"], run_dir / CASES_FILE)
    artifacts = write_artifacts(result["cases"], run_dir / ARTIFACTS_DIR)
    if artifacts:
        logger.info("wrote %d GeoParquet artifact(s)", len(artifacts))
