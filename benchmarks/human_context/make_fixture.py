"""Generate the synthetic town of the ``human_context_access`` benchmark.

The town is invented: no real-world data goes into it. It is laid out in a local plane in
meters (x east, y north) and placed on the equator next to longitude 0, where one degree of
longitude is ``M_PER_DEG_LON`` meters and one degree of latitude ``M_PER_DEG_LAT`` meters, so
plane distances and WGS 84 geodesic distances agree closely (within about 1e-5 relative).

Four neighborhood types, each with its own street pattern:

- ``grid``: a 9 x 9 block grid with 100 m blocks;
- ``mixed_use_core``: a denser 7 x 7 grid with 60 m blocks, a few one-way streets (ignored
  for walking) and three links to the grid;
- ``cul_de_sac_suburban``: a collector street with curving side streets, each ending in a
  cul-de-sac loop, and a single access to the grid;
- ``rural_fringe``: a loop road with spurs, linked to the core by one road, plus a hamlet with
  no road to the rest of the town (a separate network component).

Points of interest (POIs) in six amenity categories sit 5-12 m from a street node, each at a
different node. Opening hours are in OpenStreetMap ``opening_hours`` syntax; two POIs have none
(missing data).

Output (``fixtures/`` by default), four GeoParquet 1.1.0 files in ``OGC:CRS84``:

- ``town_nodes.parquet``: ``node_id``, ``neighborhood_type``, Point geometry;
- ``town_edges.parquet``: ``edge_id``, ``u``, ``v``, ``length_m`` (plane length, meters),
  ``highway``, ``oneway``, ``neighborhood_type``, LineString geometry;
- ``town_pois.parquet``: ``poi_id``, ``name``, ``amenity_category``, ``opening_hours`` (null
  when missing), ``neighborhood_type``, Point geometry;
- ``town_neighborhoods.parquet``: ``neighborhood_id``, ``neighborhood_type``, Polygon geometry.

The generator is deterministic: it uses one seeded ``numpy`` generator, rounds every
coordinate, and computes with float arithmetic only (no PROJ), so the same package versions
write the same bytes on every platform. ``manifest.yaml`` records each file's SHA-256; after a
change here, or an upgrade of pyarrow (its version is written into every file), regenerate the
fixture and update the manifest:

    uv run python benchmarks/human_context/make_fixture.py
"""

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely.geometry import LineString, Point, box

SEED = 20261009
"""Seed of the only random generator."""

M_PER_DEG_LON = 6378137.0 * math.pi / 180
"""Meters per degree of longitude on the WGS 84 equator."""

M_PER_DEG_LAT = 110574.2727
"""Meters per degree of latitude at the equator (WGS 84 meridional radius of curvature)."""

COORD_DECIMALS = 7
"""Longitude and latitude are rounded to 1e-7 degrees (about 1 cm)."""

NEIGHBORHOOD_TYPES = ("grid", "mixed_use_core", "cul_de_sac_suburban", "rural_fringe")

AMENITY_CATEGORIES = ("grocery", "pharmacy", "school", "park", "transit_stop", "clinic")

FILES = {
    "nodes": "town_nodes.parquet",
    "edges": "town_edges.parquet",
    "pois": "town_pois.parquet",
    "neighborhoods": "town_neighborhoods.parquet",
}

OPENING_HOURS = {
    "grocery": ["Mo-Sa 08:00-21:00; Su 09:00-18:00", "Mo-Su 07:00-23:00", "24/7"],
    "pharmacy": ["Mo-Fr 08:30-19:00; Sa 09:00-13:00", "Mo-Su 08:00-22:00; PH off", "24/7"],
    "school": ["Mo-Fr 07:30-16:00; PH off"],
    "park": ["24/7", "Mo-Su 06:00-22:00"],
    "transit_stop": ["Mo-Fr 05:00-01:00; Sa,Su 06:00-00:30", "24/7"],
    "clinic": [
        "Mo-Fr 08:00-18:00",
        "Mo-Th 08:00-20:00; Fr 08:00-16:00",
        "Mo-Fr 08:00-12:00,13:00-17:00",
    ],
}
"""Opening hours each category draws from (OpenStreetMap ``opening_hours`` syntax)."""

POI_COUNTS = {
    "mixed_use_core": {
        "grocery": 3, "pharmacy": 2, "school": 1, "park": 1, "transit_stop": 3, "clinic": 2,
    },
    "grid": {"grocery": 2, "pharmacy": 2, "school": 2, "park": 3, "transit_stop": 4, "clinic": 1},
    "cul_de_sac_suburban": {"grocery": 1, "pharmacy": 1, "school": 2, "park": 3, "transit_stop": 2},
    "rural_fringe": {"grocery": 1, "school": 1, "park": 2, "transit_stop": 1, "clinic": 1},
}  # fmt: skip
"""POIs per neighborhood and category, on the connected network."""

HAMLET_POIS = {"grocery": 1, "park": 1}
"""POIs in the hamlet, which no road connects to the rest of the town."""

MISSING_HOURS = {"poi-036", "poi-042"}
"""POIs whose opening hours are missing (null)."""


@dataclass
class Town:
    nodes: list[tuple[int, float, float, str]] = field(default_factory=list)
    """``(node_id, x, y, neighborhood_type)`` in plane meters."""
    edges: list[tuple[int, int, str, bool, str]] = field(default_factory=list)
    """``(u, v, highway, oneway, neighborhood_type)``."""
    pois: list[tuple[str, str, str, str | None, str, float, float]] = field(default_factory=list)
    """``(poi_id, name, category, opening_hours, neighborhood_type, x, y)``."""
    neighborhoods: list[tuple[str, str, tuple[float, float, float, float]]] = field(
        default_factory=list
    )
    """``(neighborhood_id, neighborhood_type, (minx, miny, maxx, maxy))``."""

    def add_node(self, x: float, y: float, kind: str) -> int:
        node_id = len(self.nodes) + 1
        self.nodes.append((node_id, round(float(x), 2), round(float(y), 2), kind))
        return node_id

    def add_edge(self, u: int, v: int, highway: str, kind: str, *, oneway: bool = False) -> None:
        self.edges.append((u, v, highway, oneway, kind))


def _grid(
    town: Town, x0: float, y0: float, n: int, spacing: float, kind: str, highway: str
) -> dict[tuple[int, int], int]:
    ids = {
        (i, j): town.add_node(x0 + i * spacing, y0 + j * spacing, kind)
        for j in range(n)
        for i in range(n)
    }
    for j in range(n):
        for i in range(n):
            if i + 1 < n:
                town.add_edge(ids[i, j], ids[i + 1, j], highway, kind)
            if j + 1 < n:
                town.add_edge(ids[i, j], ids[i, j + 1], highway, kind)
    return ids


def build_town(seed: int = SEED) -> Town:
    """The town's nodes, edges, POIs and neighborhoods (plane meters)."""
    rng = np.random.default_rng(seed)
    town = Town()

    def jitter(scale: float) -> float:
        return float(rng.uniform(-scale, scale))

    # Grid: x 0-800, y 0-800.
    grid = _grid(town, 0, 0, 9, 100, "grid", "residential")

    # Mixed-use core: x 900-1260, y 200-560; every other row of streets is one-way.
    core = _grid(town, 900, 200, 7, 60, "mixed_use_core", "tertiary")
    first_core_edge = len(town.edges) - 84
    for index in range(first_core_edge, len(town.edges), 5):
        u, v, highway, _, kind = town.edges[index]
        town.edges[index] = (u, v, highway, True, kind)
    town.add_edge(grid[8, 2], core[0, 0], "secondary", "mixed_use_core")
    town.add_edge(grid[8, 4], core[0, 3], "secondary", "mixed_use_core")
    town.add_edge(grid[8, 5], core[0, 5], "secondary", "mixed_use_core")

    # Cul-de-sac suburb: x 0-800, y 950-1450, one access from the grid at (400, 800).
    kind = "cul_de_sac_suburban"
    previous = grid[4, 8]
    for y in (950, 1100, 1250, 1400):
        spine = town.add_node(400 + jitter(10), y + jitter(10), kind)
        town.add_edge(previous, spine, "residential", kind)
        previous = spine
        for side in (-1, 1):
            last = spine
            for step in (120, 230, 330):
                node = town.add_node(400 + side * step + jitter(12), y + 25 + jitter(12), kind)
                town.add_edge(last, node, "residential", kind)
                last = node
            end_x, end_y = 400 + side * 330, y + 25
            bulb_a = town.add_node(end_x + side * 35 + jitter(4), end_y + 25 + jitter(4), kind)
            bulb_b = town.add_node(end_x + side * 35 + jitter(4), end_y - 25 + jitter(4), kind)
            town.add_edge(last, bulb_a, "residential", kind)
            town.add_edge(bulb_a, bulb_b, "residential", kind)
            town.add_edge(bulb_b, last, "residential", kind)

    # Rural fringe: a loop road around (2000, 400) linked to the core, with four spurs.
    kind = "rural_fringe"
    ring = []
    for k in range(12):
        angle = 2 * math.pi * k / 12
        radius = 450 + jitter(40)
        ring.append(
            town.add_node(2000 - radius * math.cos(angle), 400 + radius * math.sin(angle), kind)
        )
    for k in range(12):
        town.add_edge(ring[k], ring[(k + 1) % 12], "unclassified", kind)
    link = town.add_node(1420, 395 + jitter(10), kind)
    town.add_edge(core[6, 3], link, "secondary", kind)
    town.add_edge(link, ring[0], "secondary", kind)
    for k in (2, 5, 8, 10):
        angle = 2 * math.pi * k / 12
        last = ring[k]
        for reach in (650, 820):
            node = town.add_node(
                2000 - (reach + jitter(20)) * math.cos(angle),
                400 + (reach + jitter(20)) * math.sin(angle),
                kind,
            )
            town.add_edge(last, node, "track", kind)
            last = node

    # Hamlet: no road connects it to the rest of the town.
    hamlet = [
        town.add_node(2700 + dx + jitter(5), 1150 + dy + jitter(5), kind)
        for dx, dy in ((0, 0), (110, 0), (110, 110), (0, 110))
    ]
    for k in range(4):
        town.add_edge(hamlet[k], hamlet[(k + 1) % 4], "track", kind)
    town.add_edge(hamlet[0], hamlet[2], "track", kind)

    town.neighborhoods = [
        ("nbhd-1", "grid", (-50.0, -50.0, 850.0, 850.0)),
        ("nbhd-2", "mixed_use_core", (850.0, 150.0, 1310.0, 610.0)),
        ("nbhd-3", "cul_de_sac_suburban", (-50.0, 850.0, 850.0, 1500.0)),
        ("nbhd-4", "rural_fringe", (1310.0, -450.0, 2900.0, 1350.0)),
    ]

    # POIs, each next to a different node of its neighborhood.
    used: set[int] = set()

    def place(category: str, candidates: list[tuple[int, float, float, str]]) -> None:
        free = [node for node in candidates if node[0] not in used]
        node_id, x, y, node_kind = free[int(rng.integers(len(free)))]
        used.add(node_id)
        distance = float(rng.uniform(5, 12))
        angle = float(rng.uniform(0, 2 * math.pi))
        poi_id = f"poi-{len(town.pois) + 1:03d}"
        hours = OPENING_HOURS[category]
        opening = None if poi_id in MISSING_HOURS else hours[int(rng.integers(len(hours)))]
        number = 1 + sum(1 for poi in town.pois if poi[2] == category)
        name = f"{category.replace('_', ' ').title()} {number}"
        town.pois.append(
            (
                poi_id,
                name,
                category,
                opening,
                node_kind,
                round(x + distance * math.cos(angle), 2),
                round(y + distance * math.sin(angle), 2),
            )
        )

    hamlet_ids = set(hamlet)
    for neighborhood, counts in POI_COUNTS.items():
        candidates = [n for n in town.nodes if n[3] == neighborhood and n[0] not in hamlet_ids]
        for category in AMENITY_CATEGORIES:
            for _ in range(counts.get(category, 0)):
                place(category, candidates)
    hamlet_nodes = [n for n in town.nodes if n[0] in hamlet_ids]
    for category, count in HAMLET_POIS.items():
        for _ in range(count):
            place(category, hamlet_nodes)
    _check_town(town)
    return town


def _check_town(town: Town) -> None:
    """Every POI is closest to its own node by a clear margin, so snapping is unambiguous."""
    xy = np.array([(x, y) for _, x, y, _ in town.nodes])
    for poi_id, *_, x, y in town.pois:
        distances = np.sort(np.hypot(xy[:, 0] - x, xy[:, 1] - y))
        if not (distances[0] <= 12.01 and distances[1] - distances[0] > 10):
            raise AssertionError(f"{poi_id} does not snap clearly to one node")


def to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Plane meters -> ``(lon, lat)`` degrees, rounded to ``COORD_DECIMALS``."""
    return (
        round(x / M_PER_DEG_LON, COORD_DECIMALS),
        round(y / M_PER_DEG_LAT, COORD_DECIMALS),
    )


def _geoparquet(
    path: Path, columns: dict[str, pa.Array], geometries: Sequence[Any], kind: str
) -> None:
    """Write a GeoParquet 1.1.0 file with WKB geometry in ``OGC:CRS84`` (no ``crs`` key)."""
    array = shapely.from_wkt([geometry.wkt for geometry in geometries])
    bounds = shapely.total_bounds(array).tolist()
    wkb = shapely.to_wkb(array, byte_order=1)
    table = pa.table({**columns, "geometry": pa.array(list(wkb), type=pa.binary())})
    geo = {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {"encoding": "WKB", "geometry_types": [kind], "bbox": bounds},
        },
    }
    table = table.replace_schema_metadata({"geo": json.dumps(geo, sort_keys=True)})
    pq.write_table(table, path, compression="zstd")


def write_fixture(out_dir: Path, seed: int = SEED) -> dict[str, str]:
    """Write the four GeoParquet files to ``out_dir``; return file name -> SHA-256."""
    town = build_town(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    lonlat = {node_id: to_lonlat(x, y) for node_id, x, y, _ in town.nodes}
    plane = {node_id: (x, y) for node_id, x, y, _ in town.nodes}
    kinds = {node_id: kind for node_id, _, _, kind in town.nodes}

    _geoparquet(
        out_dir / FILES["nodes"],
        {
            "node_id": pa.array([n[0] for n in town.nodes], type=pa.int64()),
            "neighborhood_type": pa.array([n[3] for n in town.nodes], type=pa.string()),
        },
        [Point(lonlat[n[0]]) for n in town.nodes],
        "Point",
    )
    lengths = [round(math.dist(plane[u], plane[v]), 2) for u, v, *_ in town.edges]
    _geoparquet(
        out_dir / FILES["edges"],
        {
            "edge_id": pa.array(range(1, len(town.edges) + 1), type=pa.int64()),
            "u": pa.array([e[0] for e in town.edges], type=pa.int64()),
            "v": pa.array([e[1] for e in town.edges], type=pa.int64()),
            "length_m": pa.array(lengths, type=pa.float64()),
            "highway": pa.array([e[2] for e in town.edges], type=pa.string()),
            "oneway": pa.array([e[3] for e in town.edges], type=pa.bool_()),
            "neighborhood_type": pa.array([e[4] for e in town.edges], type=pa.string()),
        },
        [LineString([lonlat[u], lonlat[v]]) for u, v, *_ in town.edges],
        "LineString",
    )
    _geoparquet(
        out_dir / FILES["pois"],
        {
            "poi_id": pa.array([p[0] for p in town.pois], type=pa.string()),
            "name": pa.array([p[1] for p in town.pois], type=pa.string()),
            "amenity_category": pa.array([p[2] for p in town.pois], type=pa.string()),
            "opening_hours": pa.array([p[3] for p in town.pois], type=pa.string()),
            "neighborhood_type": pa.array([p[4] for p in town.pois], type=pa.string()),
        },
        [Point(to_lonlat(p[5], p[6])) for p in town.pois],
        "Point",
    )
    _geoparquet(
        out_dir / FILES["neighborhoods"],
        {
            "neighborhood_id": pa.array([n[0] for n in town.neighborhoods], type=pa.string()),
            "neighborhood_type": pa.array([n[1] for n in town.neighborhoods], type=pa.string()),
        },
        [
            box(*to_lonlat(minx, miny), *to_lonlat(maxx, maxy))
            for _, _, (minx, miny, maxx, maxy) in town.neighborhoods
        ],
        "Polygon",
    )
    assert set(kinds.values()) == set(NEIGHBORHOOD_TYPES)
    return {
        name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest() for name in FILES.values()
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "fixtures",
        help="Output directory (default: the benchmark's fixtures/).",
    )
    args = parser.parse_args(argv)
    for name, digest in write_fixture(args.out).items():
        print(f"{digest}  {args.out / name}")


if __name__ == "__main__":
    main()
