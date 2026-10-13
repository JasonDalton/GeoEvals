"""Review sheets for drafted graded tasks (checkpoint 2 of the design).

``review_sheet(spec_path, data_dir)`` writes ``<data_dir>/review/<eval id>.md``: for each task
its prompt, audience, strata, location, warnings, params and key, and a map of the task's
features (``review/<eval id>/<task id>.png``). The sheet holds the keys, which are derived
from OpenStreetMap, so it is written only into a gitignored directory.

Warnings point a reviewer at keys that are probably not what the author meant: a walk more
than ``DETOUR_FACTOR`` times the straight line (often a connection OSM lacks), a location near
the edge of the city box (where the network is cut), duplicate tasks, and keys with nothing to
answer (no reachable place, no touching pair, an unchanged closure, only undecided targets).
"""

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import box as shapely_box

from geoevals.data.fetch import ensure_ignored
from geoevals.graded.city import LAYERS_DIR, load_layers
from geoevals.graded.keys import load_keys
from geoevals.graded.spec import EvalTask, load_tasks, spec_file
from geoevals.validation import load_dataset_manifest, load_eval_spec

REVIEW_DIR = "review"
DETOUR_FACTOR = 3.0
EDGE_M = 300.0
M_PER_DEG_LAT = 111_320.0
MAP_PAD_DEG = 0.0015
"""Padding around a task's features on its map (about 120 to 170 m)."""
POLYGONAL = ("Polygon", "MultiPolygon")
CONTAINER_TOL_DEG = 2e-5
"""How near a key polygon must be to a task's point to count as its container (about 2 m, so
it covers the 1 m boundary tolerance of containment keys)."""
FEATURE_ID = re.compile(r"^(node|way|relation)/[0-9]+$")
ATTRIBUTION = "© OpenStreetMap contributors"

Bbox = tuple[float, float, float, float]


def _detour(walking: Any, straight: Any) -> bool:
    return (
        isinstance(walking, (int, float))
        and isinstance(straight, (int, float))
        and straight > 0
        and walking > DETOUR_FACTOR * straight
    )


def key_warnings(key_type: str, key: Mapping[str, Any]) -> list[str]:
    """What looks wrong in one task's key, or an empty list."""
    warnings: list[str] = []
    detour = (
        f"a walk more than {DETOUR_FACTOR:g}x the straight line: "
        "check the map for a missing connection"
    )
    if key_type == "proximity":
        if key["walking_nearest"] is None:
            warnings.append("no candidate is reachable on foot")
        elif key["unreachable"]:
            listed = ", ".join(key["unreachable"][:5])
            warnings.append(f"{len(key['unreachable'])} candidate(s) unreachable: {listed}")
        if any(_detour(r.get("walking_m"), r.get("straight_line_m")) for r in key["by_walking"]):
            warnings.append(detour)
    elif key_type == "containment":
        for label, point in key["points"].items():
            if not point["inside"] and not point["on_boundary"]:
                warnings.append(f"point {label!r} is in no polygon")
    elif key_type == "adjacency":
        if all(pair["relation"] == "disjoint" for pair in key["pairs"]):
            warnings.append("no pair of features touches")
    elif key_type == "closure":
        if not key["before"]["reachable"]:
            warnings.append("there is no walk even before the closure")
        elif key["added_m"] == 0:
            warnings.append("the closure does not change the walk")
    elif key_type == "visibility":
        targets = list(key["targets"].values())
        if targets and all(target["visible"] is None for target in targets):
            warnings.append("every target is undecided (unknown heights)")
    elif key_type == "direction":
        if not key["reachable"]:
            warnings.append(f"no walk: {key.get('reason')}")
        else:
            if len(key["steps"]) < 2:
                warnings.append("a one-step route")
            if _detour(key["walking_m"], key["straight_line_m"]):
                warnings.append(detour)
    return warnings


def _near_edge(point: list[float], bbox: Bbox) -> bool:
    lon, lat = point
    min_lon, min_lat, max_lon, max_lat = bbox
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
    gaps_m = (
        (lon - min_lon) * m_per_deg_lon,
        (max_lon - lon) * m_per_deg_lon,
        (lat - min_lat) * M_PER_DEG_LAT,
        (max_lat - lat) * M_PER_DEG_LAT,
    )
    return min(gaps_m) < EDGE_M


def task_warnings(tasks: list[EvalTask], bbox: Bbox) -> dict[str, list[str]]:
    """Warnings that need more than one key: duplicates and locations near the box edge."""
    warnings: dict[str, list[str]] = {task.task_id: [] for task in tasks}
    seen: dict[str, str] = {}
    for task in tasks:
        signature = json.dumps([task.key_type, task.params], sort_keys=True)
        if signature in seen:
            warnings[task.task_id].append(f"same key type and params as {seen[signature]}")
        else:
            seen[signature] = task.task_id
        point = task.location.point
        if point is not None and _near_edge(point, bbox):
            warnings[task.task_id].append(f"location within {EDGE_M:g} m of the city box edge")
    return warnings


def _feature_ids(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if FEATURE_ID.match(value) else set()
    if isinstance(value, Mapping):
        return set().union(
            *(_feature_ids(v) for v in value.values()), *(_feature_ids(k) for k in value)
        )
    if isinstance(value, list):
        return set().union(*(_feature_ids(v) for v in value))
    return set()


def _points(value: Any) -> list[list[float]]:
    """Every ``"point": [lon, lat]`` pair in a task's params."""
    if isinstance(value, Mapping):
        found = []
        for name, item in value.items():
            if name == "point" and isinstance(item, list) and len(item) == 2:
                found.append([float(item[0]), float(item[1])])
            else:
                found += _points(item)
        return found
    if isinstance(value, list):
        return [p for item in value for p in _points(item)]
    return []


def map_box(
    task: EvalTask, shapes: Mapping[str, Any], key: Mapping[str, Any] | None = None
) -> Bbox | None:
    """The map extent of a task, padded: its params' features and points, plus the features its
    location and key name, except containers.

    A container is a polygon that holds one of the task's points or meets one of its params
    polygons: the city limits, Metro or a neighboring district around a containment task. One
    of them would stretch the map over the whole region, so it is drawn clipped instead. Other
    features, such as a proximity key's candidates, widen the box so they appear on the map.
    ``shapes`` maps feature IDs to geometries. ``None`` when nothing locates the task.
    """
    points = _points(task.params) + ([task.location.point] if task.location.point else [])
    marks = [ShapelyPoint(p) for p in points]
    subjects = _feature_ids(task.params) & set(shapes)
    areas = [shapes[i] for i in subjects if shapes[i].geom_type in POLYGONAL]

    def container(shape: Any) -> bool:
        return shape.geom_type in POLYGONAL and (
            any(shape.distance(mark) <= CONTAINER_TOL_DEG for mark in marks)
            or any(shape.intersects(area) for area in areas)
        )

    named = set(task.location.feature_ids) | (_feature_ids(key) if key is not None else set())
    ids = subjects | {i for i in (named & set(shapes)) - subjects if not container(shapes[i])}
    bounds = [shapes[i].bounds for i in ids]
    xs = [c for b in bounds for c in (b[0], b[2])] + [p[0] for p in points]
    ys = [c for b in bounds for c in (b[1], b[3])] + [p[1] for p in points]
    if not xs:
        return None
    return (
        min(xs) - MAP_PAD_DEG,
        min(ys) - MAP_PAD_DEG,
        max(xs) + MAP_PAD_DEG,
        max(ys) + MAP_PAD_DEG,
    )


def _draw(layers: Mapping[str, Any], task: EvalTask, key: Mapping[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    features = layers["all_features"].set_index("feature_id")
    known = set(features.index)
    own = (_feature_ids(task.params) | set(task.location.feature_ids)) & known
    named = _feature_ids(key) & known
    box = map_box(task, {i: features.geometry[i] for i in own | named}, key)
    if box is None:
        return
    frame_shape = shapely_box(*box)
    ids = sorted(own | {i for i in named if features.geometry[i].intersects(frame_shape)})
    shapes = [features.geometry[i] for i in ids]
    points = [task.location.point] if task.location.point else []
    figure, axes = plt.subplots(figsize=(7, 7), dpi=110)
    styles = {
        "landuse": {"color": "#eeeeee"},
        "water": {"color": "#9ecae1"},
        "buildings": {"color": "#d9d9d9", "edgecolor": "#bdbdbd", "linewidth": 0.3},
        "streets": {"color": "#969696", "linewidth": 0.8},
        "paths": {"color": "#bcbddc", "linewidth": 0.6, "linestyle": "--"},
        "railways": {"color": "#636363", "linewidth": 1.2, "linestyle": "-."},
    }
    for name, style in styles.items():
        frame = layers[name].cx[box[0] : box[2], box[1] : box[3]]
        if len(frame):
            frame.plot(ax=axes, **style)
    for feature_id, shape in zip(ids, shapes, strict=True):
        label = shape if shape.within(frame_shape) else shape.intersection(frame_shape)
        anchor = label.representative_point()
        axes.plot(*anchor.xy, "o", color="#e6550d", markersize=3)
        series = layers["all_features"][layers["all_features"]["feature_id"] == feature_id]
        if shape.geom_type in ("Polygon", "MultiPolygon"):
            series.boundary.plot(ax=axes, color="#e6550d", linewidth=1.2)
        elif shape.geom_type in ("LineString", "MultiLineString"):
            series.plot(ax=axes, color="#e6550d", linewidth=1.2)
        axes.annotate(feature_id, anchor.coords[0], fontsize=6)
    for point in points:
        axes.plot(point[0], point[1], "*", color="#de2d26", markersize=12)
    axes.set_xlim(box[0], box[2])
    axes.set_ylim(box[1], box[3])
    axes.set_aspect(1 / math.cos(math.radians((box[1] + box[3]) / 2)))
    axes.set_title(f"{task.task_id} ({task.key_type})   {ATTRIBUTION}", fontsize=8)
    axes.tick_params(labelsize=6)
    figure.savefig(path, bbox_inches="tight")
    plt.close(figure)


def review_sheet(spec_path: Path, data_dir: Path) -> Path:
    """Write the eval's review sheet and maps; return the sheet's path. Raises ``KeysError``
    when the keys are missing or stale (run ``geoevals evals regenerate`` first)."""
    spec = load_eval_spec(spec_path)
    tasks = load_tasks(spec_path, spec)
    keys = load_keys(spec_path, data_dir)
    asset = load_dataset_manifest(spec_file(spec_path, spec.dataset_manifest)).assets[0]
    min_lon, min_lat, max_lon, max_lat = (float(v) for v in asset.bbox)
    bbox: Bbox = (min_lon, min_lat, max_lon, max_lat)
    sheet = data_dir / REVIEW_DIR / f"{spec.id}.md"
    maps = data_dir / REVIEW_DIR / spec.id
    ensure_ignored(sheet)
    maps.mkdir(parents=True, exist_ok=True)
    layers = load_layers(data_dir / LAYERS_DIR)
    extra = task_warnings(tasks, bbox)
    lines = [
        f"# Review: {spec.id} {spec.version}",
        "",
        f"{spec.title}. {len(tasks)} tasks. Data {ATTRIBUTION} (ODbL-1.0); not for commit.",
        "",
    ]
    for task in tasks:
        key = keys[task.task_id]
        warnings = key_warnings(task.key_type, key) + extra[task.task_id]
        _draw(layers, task, key, maps / f"{task.task_id}.png")
        strata = ", ".join(f"{k}: {v}" for k, v in task.strata.items())
        lines += [
            f"## {task.task_id} · {task.key_type} · {strata}",
            "",
            f"**Audience:** {task.audience}",
            "",
            f"**Prompt:** {task.prompt}",
            "",
            f"**Location:** point {task.location.point}, features {task.location.feature_ids}",
            "",
            "**Warnings:** " + ("none" if not warnings else ""),
            *[f"- {w}" for w in warnings],
            "",
            f"![map]({spec.id}/{task.task_id}.png)",
            "",
            "<details><summary>Params and key</summary>",
            "",
            "```json",
            json.dumps(
                {"params": task.params, "anchors": task.anchors, "key": key},
                indent=1,
                ensure_ascii=False,
            ),
            "```",
            "",
            "</details>",
            "",
        ]
    sheet.write_text("\n".join(lines), encoding="utf-8")
    return sheet
