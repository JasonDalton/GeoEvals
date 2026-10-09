"""Build the real-geography pilot of the human-context access benchmark.

``geoevals bench build human_context_pilot`` turns the OpenStreetMap extract fetched by
``geoevals data fetch human_context_pilot`` into a runnable benchmark directory, by default
``data/raw/human_context_pilot/benchmark/`` (gitignored: the files are derived from ODbL data
and are not committed). The settings come from ``pilot.yaml`` in a benchmark directory under
``--root`` (``benchmarks/human_context/pilot.yaml``), the geography from the fetched extract.

Steps:

1. Check the extract against the checksum the fetch recorded (``manifest.yaml`` next to it).
2. Convert it to the GeoParquet layout of ``human_context_access`` (``fixtures/nodes``,
   ``edges``, ``pois``): every node of a walkable way is a network node, every pair of
   consecutive nodes an edge whose ``length_m`` is the WGS 84 geodesic length; each POI gets one
   of the benchmark's six amenity categories (``poi_category``) and keeps its OSM
   ``opening_hours`` (null when the tag is missing).
3. Lay a square grid of ``density_cell_m`` cells in the bounding box's UTM zone (cell edges at
   multiples of the cell size, so 250 m cells nest in 1 km cells) over the bounding box (only
   cells wholly inside it), and measure each cell's street-network density (meters of street per
   square kilometer). Rank the cells by density and split them into three equal-count terciles,
   the neighborhood types ``low_density``, ``medium_density`` and ``high_density``.
4. Sample ``origins`` origins evenly across the terciles (seeded): a cell of the tercile drawn
   without replacement, then a uniform point in it. Origins are not moved onto the network, so
   some fail to snap (``insufficient_data``); the report counts them.
5. Ask each origin four questions with the operations of ``human_context_access``: the nearest
   amenity (the category cycles), the amenity count within ``count_minutes`` for each of
   ``count_categories``, and ``open_question``. The expected outputs come from the benchmark's
   reference workflow (``reference.py``, copied into the build so that
   ``geoevals bench regenerate`` works on it).
6. Write ``report.md``: data freshness, missingness and spatial-unit sensitivity.
"""

import json
import math
import os
import shutil
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from geoevals.data.fetch import FETCH_RECORD, LOCAL_MANIFEST, ensure_ignored
from geoevals.data.verify import sha256_file, verify_manifest
from geoevals.regenerate import SPEC_FILE, regenerate
from geoevals.validation.validate import load_dataset_manifest, load_yaml

PILOT_FILE = "pilot.yaml"
REPORT_FILE = "report.md"
DENSITY_TYPES = ("low_density", "medium_density", "high_density")
CATEGORIES = ("grocery", "pharmacy", "school", "park", "transit_stop", "clinic")
FIXTURES = {
    "nodes": "fixtures/nodes.parquet",
    "edges": "fixtures/edges.parquet",
    "pois": "fixtures/pois.parquet",
}
SNAP_TOL_M = 25.0
"""The snapping tolerance of ``geoevals.metrics.network`` (``DEFAULT_SNAP_TOL_M``)."""


class PilotError(RuntimeError):
    """The pilot cannot be built (settings, missing or changed extract, unwritable output)."""


@dataclass(frozen=True)
class PilotConfig:
    id: str
    dataset_manifest: Path
    benchmark_dir: Path
    """The directory holding ``pilot.yaml`` and the reference workflow."""
    timezone: str
    seed: int
    origins: int
    density_cell_m: float
    sensitivity_cells_m: tuple[float, ...]
    count_minutes: float
    count_categories: tuple[str, ...]
    open_question: Mapping[str, Any]


def find_pilot(root: Path, pilot_id: str) -> Path:
    """The ``pilot.yaml`` under ``root`` whose ``id`` is ``pilot_id``."""
    for path in sorted(root.glob(f"*/{PILOT_FILE}")):
        document = load_yaml(path)
        if isinstance(document, dict) and document.get("id") == pilot_id:
            return path
    raise PilotError(f"no {PILOT_FILE} with id {pilot_id!r} under {root}")


def load_pilot_config(path: Path) -> PilotConfig:
    document = load_yaml(path)
    if not isinstance(document, dict):
        raise PilotError(f"{path}: expected a mapping")
    try:
        config = PilotConfig(
            id=str(document["id"]),
            dataset_manifest=path.parent / document["dataset_manifest"],
            benchmark_dir=path.parent,
            timezone=str(document["timezone"]),
            seed=int(document["seed"]),
            origins=int(document["origins"]),
            density_cell_m=float(document["density_cell_m"]),
            sensitivity_cells_m=tuple(float(size) for size in document["sensitivity_cells_m"]),
            count_minutes=float(document["count_minutes"]),
            count_categories=tuple(document["count_categories"]),
            open_question=dict(document["open_question"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PilotError(f"{path}: invalid pilot settings: {exc!r}") from exc
    if config.origins < 30:
        raise PilotError(f"{path}: origins must be at least 30, got {config.origins}")
    unknown = set(config.count_categories) - set(CATEGORIES)
    if unknown:
        raise PilotError(f"{path}: unknown count_categories {sorted(unknown)}")
    return config


# --- OSM extract -> network and POIs -------------------------------------------------------


def poi_category(tags: Mapping[str, str]) -> str | None:
    """The amenity category of an OSM element, or None when it is not a pilot POI."""
    if tags.get("shop") in ("supermarket", "convenience", "greengrocer"):
        return "grocery"
    amenity = tags.get("amenity")
    if amenity == "pharmacy":
        return "pharmacy"
    if amenity == "school":
        return "school"
    if amenity in ("clinic", "doctors"):
        return "clinic"
    if tags.get("leisure") == "park":
        return "park"
    if tags.get("highway") == "bus_stop" or tags.get("railway") in ("station", "halt", "tram_stop"):
        return "transit_stop"
    return None


@dataclass
class Extract:
    nodes: dict[int, tuple[float, float]]
    """Network node ID (OSM node ID) -> ``(lon, lat)``."""
    edges: list[dict[str, Any]]
    """``{edge_id, u, v, length_m, highway, osm_way_id}``."""
    pois: list[dict[str, Any]]
    """``{poi_id, name, amenity_category, opening_hours, lon, lat}``."""


def read_extract(path: Path) -> Extract:
    """Streets and POIs of a normalized Overpass extract (``geoevals.data.fetch``)."""
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    elements = json.loads(path.read_text(encoding="utf-8"))["elements"]
    nodes: dict[int, tuple[float, float]] = {}
    edges: list[dict[str, Any]] = []
    pois: dict[str, dict[str, Any]] = {}
    for element in elements:
        tags = element.get("tags", {})
        if element["type"] == "way" and "geometry" in element:
            points = [
                None if point is None else (point["lon"], point["lat"])
                for point in element["geometry"]
            ]
            ids = element["nodes"]
            for i in range(len(ids) - 1):
                (u, a), (v, b) = (ids[i], points[i]), (ids[i + 1], points[i + 1])
                if a is None or b is None or u == v:
                    continue
                nodes[u], nodes[v] = a, b
                _, _, length = geod.inv(a[0], a[1], b[0], b[1])
                edges.append(
                    {
                        "edge_id": len(edges) + 1,
                        "u": u,
                        "v": v,
                        "length_m": float(length),
                        "highway": tags.get("highway"),
                        "osm_way_id": element["id"],
                    }
                )
            continue
        category = poi_category(tags)
        point = element.get("center") or (
            {"lon": element["lon"], "lat": element["lat"]} if "lat" in element else None
        )
        if category is None or point is None:
            continue
        poi_id = f"{element['type']}/{element['id']}"
        pois[poi_id] = {
            "poi_id": poi_id,
            "name": tags.get("name"),
            "amenity_category": category,
            "opening_hours": tags.get("opening_hours"),
            "lon": point["lon"],
            "lat": point["lat"],
        }
    return Extract(nodes, edges, [pois[key] for key in sorted(pois)])


def _write_fixtures(extract: Extract, out_dir: Path) -> None:
    import geopandas
    from shapely.geometry import LineString, Point

    (out_dir / "fixtures").mkdir(parents=True, exist_ok=True)
    crs = "OGC:CRS84"
    node_ids = sorted(extract.nodes)
    geopandas.GeoDataFrame(
        {"node_id": node_ids},
        geometry=[Point(extract.nodes[node]) for node in node_ids],
        crs=crs,
    ).to_parquet(out_dir / FIXTURES["nodes"])
    geopandas.GeoDataFrame(
        extract.edges,
        geometry=[
            LineString([extract.nodes[edge["u"]], extract.nodes[edge["v"]]])
            for edge in extract.edges
        ],
        crs=crs,
    ).to_parquet(out_dir / FIXTURES["edges"])
    geopandas.GeoDataFrame(
        [{key: poi[key] for key in poi if key not in ("lon", "lat")} for poi in extract.pois],
        geometry=[Point(poi["lon"], poi["lat"]) for poi in extract.pois],
        crs=crs,
    ).to_parquet(out_dir / FIXTURES["pois"])


# --- grid, density terciles, origins -------------------------------------------------------


@dataclass(frozen=True)
class Grid:
    """Transforms between lon/lat and the UTM zone that grid cells are laid out in."""

    utm: str
    """The UTM CRS (``EPSG:326xx`` or ``EPSG:327xx``)."""
    to_utm: Any
    to_lonlat: Any

    def xy(self, lon: float, lat: float) -> tuple[float, float]:
        x, y = self.to_utm.transform(lon, lat)
        return float(x), float(y)

    def lonlat(self, x: float, y: float) -> tuple[float, float]:
        lon, lat = self.to_lonlat.transform(x, y)
        return float(lon), float(lat)


def utm_grid(bbox: Sequence[float]) -> Grid:
    from pyproj import CRS, Transformer
    from pyproj.aoi import AreaOfInterest
    from pyproj.database import query_utm_crs_info

    min_lon, min_lat, max_lon, max_lat = bbox
    [info, *_] = query_utm_crs_info(
        datum_name="WGS 84",
        area_of_interest=AreaOfInterest(min_lon, min_lat, max_lon, max_lat),
    )
    utm = f"{info.auth_name}:{info.code}"
    return Grid(
        utm,
        Transformer.from_crs(CRS("OGC:CRS84"), CRS(utm), always_xy=True),
        Transformer.from_crs(CRS(utm), CRS("OGC:CRS84"), always_xy=True),
    )


def cell_of(x: float, y: float, size_m: float) -> tuple[int, int]:
    """The column and row of the grid cell holding ``(x, y)``; cells nest when sizes divide."""
    return math.floor(x / size_m), math.floor(y / size_m)


def density_cells(
    extract: Extract, grid: Grid, bbox: Sequence[float], size_m: float
) -> dict[tuple[int, int], float]:
    """Street-network density (m of street per km^2) of every grid cell inside ``bbox``."""
    import shapely
    from shapely.geometry import LineString, box

    min_lon, min_lat, max_lon, max_lat = bbox
    corners = [(min_lon, min_lat), (max_lon, min_lat), (max_lon, max_lat), (min_lon, max_lat)]
    area = shapely.Polygon([grid.xy(lon, lat) for lon, lat in corners])
    min_x, min_y, max_x, max_y = area.bounds
    cells: dict[tuple[int, int], Any] = {}
    for col in range(math.floor(min_x / size_m), math.ceil(max_x / size_m)):
        for row in range(math.floor(min_y / size_m), math.ceil(max_y / size_m)):
            cell = box(col * size_m, row * size_m, (col + 1) * size_m, (row + 1) * size_m)
            if area.contains(cell):
                cells[col, row] = cell
    if not cells:
        raise PilotError(f"bounding box {list(bbox)} holds no whole {size_m:g} m cell")
    projected = {node: grid.xy(*lonlat) for node, lonlat in extract.nodes.items()}
    lines = [LineString([projected[e["u"]], projected[e["v"]]]) for e in extract.edges]
    tree = shapely.STRtree(lines)
    density = {}
    for key, cell in sorted(cells.items()):
        hits = tree.query(cell)
        length = sum(lines[i].intersection(cell).length for i in hits)
        density[key] = length / (size_m * size_m / 1e6)
    return density


def density_terciles(density: Mapping[tuple[int, int], float]) -> dict[tuple[int, int], str]:
    """Cell -> neighborhood type: cells ranked by density (ties by cell) in three equal parts."""
    if len(density) < 3:
        raise PilotError(f"need at least 3 density cells for terciles, got {len(density)}")
    ranked = sorted(density, key=lambda key: (density[key], key))
    return {key: DENSITY_TYPES[3 * rank // len(ranked)] for rank, key in enumerate(ranked)}


def sample_origins(
    types: Mapping[tuple[int, int], str], grid: Grid, size_m: float, count: int, seed: int
) -> list[dict[str, Any]]:
    """``count`` origins spread evenly over the density types (seeded)."""
    rng = np.random.default_rng(seed)
    origins = []
    for index in range(count):
        kind = DENSITY_TYPES[index % len(DENSITY_TYPES)]
        origins.append({"neighborhood_type": kind})
    by_type: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for key in sorted(types):
        by_type[types[key]].append(key)
    for kind in DENSITY_TYPES:
        wanted = [origin for origin in origins if origin["neighborhood_type"] == kind]
        cells = by_type[kind]
        picks = rng.choice(len(cells), size=len(wanted), replace=len(wanted) > len(cells))
        for origin, pick in zip(wanted, picks, strict=True):
            col, row = cells[int(pick)]
            x = (col + float(rng.uniform())) * size_m
            y = (row + float(rng.uniform())) * size_m
            lon, lat = grid.lonlat(x, y)
            origin["origin"] = [round(lon, 7), round(lat, 7)]
    for number, origin in enumerate(origins, start=1):
        origin["origin_id"] = f"origin-{number:03d}"
    return origins


def snapped(extract: Extract, points: Iterable[Sequence[float]]) -> list[bool]:
    """Whether each point snaps to a network node (geodesic distance <= ``SNAP_TOL_M``)."""
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    lons = np.array([lonlat[0] for lonlat in extract.nodes.values()])
    lats = np.array([lonlat[1] for lonlat in extract.nodes.values()])
    result = []
    for lon, lat in points:
        if not len(lons):
            result.append(False)
            continue
        _, _, distances = geod.inv(np.full_like(lons, lon), np.full_like(lats, lat), lons, lats)
        result.append(bool(np.min(distances) <= SNAP_TOL_M))
    return result


# --- cases ---------------------------------------------------------------------------------

_TIME = {"abs_tol": {"value": 0.001, "units": "s"}, "time_tol_s": {"value": 0.001, "units": "s"}}
_COUNT = {"abs_tol": {"value": 0, "units": "count"}, "count_tol": {"value": 0, "units": "count"}}


def _time_of_day(time: str) -> str:
    hour = int(time.split(":")[0])
    return ("night", "morning", "afternoon", "evening")[hour // 6]


def _where(origin: Sequence[float]) -> str:
    return f"the point at longitude {origin[0]}, latitude {origin[1]}"


def make_cases(config: PilotConfig, origins: Sequence[Mapping[str, Any]]) -> dict[str, list]:
    """Case lines per operation, with placeholder ``expected`` outputs."""
    files = dict(FIXTURES)
    cases: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(operation: str, origin: Mapping[str, Any], params: dict, prompt: str, **extra) -> None:
        strata = {
            "operation": operation,
            "neighborhood_type": origin["neighborhood_type"],
            "amenity_category": params["category"],
            "time_of_day": _time_of_day(params["time"]) if "time" in params else "none",
            "origin_snaps": "yes" if origin["snaps"] else "no",
            **extra,
        }
        tolerances = _TIME if operation == "nearest_amenity" else _COUNT
        cases[operation].append(
            {
                "case_id": f"{operation}-{len(cases[operation]) + 1:03d}",
                "operation": operation,
                "split": "test",
                "prompt": prompt,
                "inputs": {"files": files, "params": {"origin": origin["origin"], **params}},
                "expected": {"status": "ok"},
                "tolerances": tolerances,
                "strata": strata,
                "origin_id": origin["origin_id"],
            }
        )

    walk = "walking at 1.33 m/s on the OpenStreetMap street network"
    question = config.open_question
    for index, origin in enumerate(origins):
        category = CATEGORIES[index % len(CATEGORIES)]
        add(
            "nearest_amenity",
            origin,
            {"category": category},
            f"How many seconds does it take to reach the nearest {category} from "
            f"{_where(origin['origin'])}, {walk}? Give the travel time and the POI ID.",
        )
        minutes = config.count_minutes
        for category in config.count_categories:
            add(
                "amenity_count",
                origin,
                {"category": category, "minutes": _number(minutes)},
                f"How many {category} POIs can be reached within {minutes:g} minutes from "
                f"{_where(origin['origin'])}, {walk}? List their POI IDs.",
                threshold_min=_number(minutes),
            )
        add(
            "open_amenities",
            origin,
            {
                "category": question["category"],
                "minutes": _number(float(question["minutes"])),
                "date": question["date"],
                "time": question["time"],
                "timezone": config.timezone,
            },
            f"Which {question['category']} POIs within {question['minutes']} minutes' walk of "
            f"{_where(origin['origin'])} are open at {question['time']} on {question['date']}, "
            f"local time in the {config.timezone} time zone? Walk at 1.33 m/s on the "
            "OpenStreetMap street network. Public holidays: none. Give the number open, their "
            "POI IDs, and the IDs of the POIs whose opening hours are unknown.",
            threshold_min=_number(float(question["minutes"])),
        )
    return dict(cases)


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _spec(config: PilotConfig, case_files: Sequence[str], record: Mapping[str, Any]) -> dict:
    """The pilot's benchmark spec: the ``human_context_access`` spec with pilot changes."""
    spec = load_yaml(config.benchmark_dir / SPEC_FILE)
    spec["id"] = config.id
    spec["title"] = "Human-context walking access: real-geography pilot (OpenStreetMap)"
    spec["task_statement"] = spec["task_statement"].replace(
        "a small synthetic town", "an OpenStreetMap extract"
    )
    strata = spec["input_schema"]["properties"]["strata"]
    strata["properties"]["neighborhood_type"] = {
        "description": "Street-network density tercile of the origin's grid cell.",
        "enum": list(DENSITY_TYPES),
    }
    spec["input_schema"]["properties"]["origin_id"] = {"type": "string"}
    spec["cases"] = list(case_files)
    spec["license"] = "ODbL-1.0"
    spec["provenance"]["notes"] = (
        f"Built by `geoevals bench build {config.id}` from the OpenStreetMap extract of "
        f"{record['snapshot_date']} for bbox {record['bbox']} (fetched {record['access_date']}, "
        f"sha256 {record['sha256']}). Data © OpenStreetMap contributors, ODbL-1.0; this "
        "directory is a derived database and must not be committed or redistributed."
    )
    spec["limitations"] = [
        "OpenStreetMap completeness varies by region and feature type; see report.md.",
        *spec["limitations"][1:],
    ]
    return spec


def _derived_manifest(record: Mapping[str, Any], out_dir: Path) -> dict[str, Any]:
    assets = []
    for name, path in FIXTURES.items():
        assets.append(
            {
                "asset_id": f"pilot_{name}",
                "path": path,
                "citation": "OpenStreetMap contributors, https://www.openstreetmap.org/copyright",
                "access_date": record["access_date"],
                "license": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors",
                "redistributable": False,
                "sha256": sha256_file(out_dir / path),
                "crs": "OGC:CRS84",
                "bbox": record["bbox"],
                "time_range": {"start": record["snapshot_date"], "end": record["snapshot_date"]},
                "processing_steps": [
                    f"Derived from the OpenStreetMap extract with sha256 {record['sha256']} by "
                    f"geoevals.pilot (geoevals bench build {record['dataset_id']})."
                ],
                "split": "test",
                "known_limitations": [
                    "OpenStreetMap completeness varies by region and feature type.",
                ],
            }
        )
    return {"schema_version": "1.0.0", "dataset_id": "human_context_pilot_build", "assets": assets}


# --- build ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildResult:
    out_dir: Path
    cases: int
    origins: int
    report: Path


def build_pilot(
    pilot_id: str,
    root: Path,
    source_dir: Path | None = None,
    out_dir: Path | None = None,
) -> BuildResult:
    """Build the pilot benchmark; see the module docstring.

    ``source_dir`` holds the fetched extract and its records (default: the directory of the
    committed manifest's asset path); ``out_dir`` defaults to ``<source_dir>/benchmark``.
    """
    config = load_pilot_config(find_pilot(root, pilot_id))
    committed = config.dataset_manifest
    manifest = load_dataset_manifest(committed)
    asset = manifest.assets[0]
    if source_dir is None:
        source_dir = Path(os.path.normpath(committed.parent / asset.path)).parent
    local = source_dir / LOCAL_MANIFEST
    if not local.is_file():
        raise PilotError(
            f"{local}: not found; run `geoevals data fetch {manifest.dataset_id}` first"
        )
    for check in verify_manifest(local):
        if check.status != "ok":
            raise PilotError(f"{check.path}: {check.status}; fetch the extract again")
    record = json.loads((source_dir / FETCH_RECORD).read_text(encoding="utf-8"))
    local_asset = load_dataset_manifest(local).assets[0]

    out_dir = source_dir / "benchmark" if out_dir is None else out_dir
    ensure_ignored(out_dir / SPEC_FILE)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    extract = read_extract(source_dir / local_asset.path)
    if not extract.edges:
        raise PilotError(f"{source_dir / local_asset.path}: the extract has no streets")
    _write_fixtures(extract, out_dir)
    grid = utm_grid(local_asset.bbox)
    density = density_cells(extract, grid, local_asset.bbox, config.density_cell_m)
    types = density_terciles(density)
    origins = sample_origins(types, grid, config.density_cell_m, config.origins, config.seed)
    snaps = snapped(extract, [origin["origin"] for origin in origins])
    for origin, snap in zip(origins, snaps, strict=True):
        origin["snaps"] = snap

    cases = make_cases(config, origins)
    (out_dir / "cases").mkdir()
    case_files = []
    for operation, lines in cases.items():
        path = f"cases/{operation}.jsonl"
        case_files.append(path)
        text = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
        (out_dir / path).write_text(text, encoding="utf-8")
    spec = _spec(config, case_files, record)
    spec["dataset_manifest"] = LOCAL_MANIFEST
    (out_dir / SPEC_FILE).write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    derived = _derived_manifest(record, out_dir)
    (out_dir / LOCAL_MANIFEST).write_text(
        yaml.safe_dump(derived, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    for name in ("reference.py", "run_config.yaml"):
        shutil.copyfile(config.benchmark_dir / name, out_dir / name)
    regenerate(out_dir, config.id)

    built = [
        json.loads(line)
        for path in case_files
        for line in (out_dir / path).read_text(encoding="utf-8").splitlines()
    ]
    report = out_dir / REPORT_FILE
    report.write_text(
        pilot_report(config, record, extract, density, types, origins, built, grid),
        encoding="utf-8",
    )
    return BuildResult(out_dir, len(built), len(origins), report)


# --- report --------------------------------------------------------------------------------


def _percent(part: int, whole: int) -> str:
    return "n/a" if whole == 0 else f"{100 * part / whole:.1f}%"


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def sensitivity(
    counts: Sequence[tuple[tuple[float, float], float]], sizes: Sequence[float]
) -> list[dict[str, Any]]:
    """Per origin, the mean amenity count of its grid cell at each cell size.

    ``counts`` holds ``((x, y), count)`` per origin with an answer. A cell's value is the mean
    count of the origins in it; each origin row gets ``cell_<size>`` and ``mean_<size>``.
    """
    rows: list[dict[str, Any]] = [{"xy": xy, "count": count} for xy, count in counts]
    for size in sizes:
        members: dict[tuple[int, int], list[float]] = defaultdict(list)
        for row in rows:
            x, y = row["xy"]
            row[f"cell_{size:g}"] = cell_of(x, y, size)
            members[row[f"cell_{size:g}"]].append(row["count"])
        for row in rows:
            row[f"mean_{size:g}"] = _mean(members[row[f"cell_{size:g}"]])
    return rows


def pilot_report(
    config: PilotConfig,
    record: Mapping[str, Any],
    extract: Extract,
    density: Mapping[tuple[int, int], float],
    types: Mapping[tuple[int, int], str],
    origins: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    grid: Grid,
) -> str:
    """The pilot's data report (Markdown)."""
    lines = [
        f"# Pilot data report: `{config.id}`",
        "",
        "Data © OpenStreetMap contributors, ODbL-1.0. Generated by "
        f"`geoevals bench build {config.id}`; do not commit or redistribute.",
        "",
        "## Data freshness",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Extract date (OSM snapshot) | {record['snapshot_date']} (00:00 UTC) |",
        f"| Access date (fetched) | {record['access_date']} |",
        f"| Server database timestamp | {record.get('osm_base')} |",
        f"| Bounding box (lon/lat) | {record['bbox']} |",
        f"| Extract sha256 | `{record['sha256']}` |",
        f"| Network | {len(extract.nodes)} nodes, {len(extract.edges)} edges |",
        f"| UTM grid | {grid.utm} |",
        "",
    ]

    lines += ["## Missingness", "", "### POIs without `opening_hours`", ""]
    lines += ["| Category | POIs | Missing opening_hours | Percent |", "| --- | --- | --- | --- |"]
    for category in (*CATEGORIES, None):
        pois = [p for p in extract.pois if category is None or p["amenity_category"] == category]
        missing = sum(1 for poi in pois if not poi["opening_hours"])
        label = "**all**" if category is None else category
        lines.append(f"| {label} | {len(pois)} | {missing} | {_percent(missing, len(pois))} |")
    lines += ["", f"### Origins that fail to snap (no node within {SNAP_TOL_M:g} m)", ""]
    lines += [
        "| Neighborhood type | Origins | Fail to snap | Percent |",
        "| --- | --- | --- | --- |",
    ]
    for kind in (*DENSITY_TYPES, None):
        group = [o for o in origins if kind is None or o["neighborhood_type"] == kind]
        failed = sum(1 for origin in group if not origin["snaps"])
        label = "**all**" if kind is None else kind
        lines.append(f"| {label} | {len(group)} | {failed} | {_percent(failed, len(group))} |")

    lines += ["", "## Neighborhood types (street-network density terciles)", ""]
    lines += [
        f"{len(density)} grid cells of {config.density_cell_m:g} m wholly inside the bounding "
        "box, ranked by street length per km^2 and split into three equal-count terciles.",
        "",
        "| Neighborhood type | Cells | Density range (m/km^2) | Origins |",
        "| --- | --- | --- | --- |",
    ]
    for kind in DENSITY_TYPES:
        values = [density[key] for key in density if types[key] == kind]
        count = sum(1 for origin in origins if origin["neighborhood_type"] == kind)
        lines.append(f"| {kind} | {len(values)} | {min(values):.0f}-{max(values):.0f} | {count} |")

    sizes = config.sensitivity_cells_m
    small, large = f"{min(sizes):g}", f"{max(sizes):g}"
    lines += ["", "## Spatial-unit sensitivity", ""]
    lines += [
        f"Amenity counts within {config.count_minutes:g} minutes, aggregated on {small} m and "
        f"{large} m grids (UTM, nested cells). A cell's value is the mean count of the origins "
        f"in it; the difference is the {large} m value minus the {small} m value for the same "
        "origin. Origins without an answer (no snap) are left out.",
    ]
    by_origin = {o["origin_id"]: o for o in origins}
    for category in config.count_categories:
        answered = [
            (by_origin[case["origin_id"]], case["expected"]["value"])
            for case in cases
            if case["operation"] == "amenity_count"
            and case["inputs"]["params"]["category"] == category
            and case["expected"]["status"] == "ok"
        ]
        lines += ["", f"### {category}", ""]
        if not answered:
            lines.append("No origin has an answer.")
            continue
        rows = sensitivity([(grid.xy(*o["origin"]), count) for o, count in answered], sizes)
        for row, (origin, _) in zip(rows, answered, strict=True):
            row["type"] = origin["neighborhood_type"]
        diffs = [row[f"mean_{large}"] - row[f"mean_{small}"] for row in rows]
        lines += [
            f"| Group | Origins | Mean ({small} m cells) | Mean ({large} m cells) | "
            "Difference | Mean abs. difference | Max abs. difference |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for kind in (*DENSITY_TYPES, None):
            group = [i for i, row in enumerate(rows) if kind is None or row["type"] == kind]
            label = "**all**" if kind is None else kind
            if not group:
                lines.append(f"| {label} | 0 | n/a | n/a | n/a | n/a | n/a |")
                continue
            fine = _mean([rows[i][f"mean_{small}"] for i in group])
            coarse = _mean([rows[i][f"mean_{large}"] for i in group])
            absolute = [abs(diffs[i]) for i in group]
            lines.append(
                f"| {label} | {len(group)} | {fine:.2f} | {coarse:.2f} | {coarse - fine:+.2f} | "
                f"{_mean(absolute):.2f} | {max(absolute):.2f} |"
            )
        lines += [
            "",
            f"| {large} m cell | Origins | {large} m value | {small} m cells (values) |",
            "| --- | --- | --- | --- |",
        ]
        cells: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            cells[row[f"cell_{large}"]].append(row)
        for key in sorted(cells):
            members = cells[key]
            fine_cells = sorted({(row[f"cell_{small}"], row[f"mean_{small}"]) for row in members})
            values = ", ".join(f"{value:.2f}" for _, value in fine_cells)
            lines.append(
                f"| {key} | {len(members)} | {members[0][f'mean_{large}']:.2f} | "
                f"{len(fine_cells)} ({values}) |"
            )

    statuses: dict[tuple[str, str], int] = defaultdict(int)
    for case in cases:
        statuses[case["operation"], case["expected"]["status"]] += 1
    lines += ["", "## Cases", "", "| Operation | Expected status | Cases |", "| --- | --- | --- |"]
    for (operation, status), count in sorted(statuses.items()):
        lines.append(f"| {operation} | {status} | {count} |")
    lines.append(f"| **all** | | {len(cases)} |")
    return "\n".join(lines) + "\n"
