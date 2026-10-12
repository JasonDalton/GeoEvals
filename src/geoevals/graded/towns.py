"""Measure candidate towns for the graded evals (checkpoint 1 of the design).

``geoevals evals measure-town`` fetches a town's extract at a snapshot date into a gitignored
directory (``fetch_candidate``, or ``read_candidate`` from a local ``.osm.pbf``), converts it
to layers and prints one row of ``stats_table``: how much a town offers the five evals
(buildings with heights for visibility, paths for proximity and directions, land use and water
for context and barriers) and how large its extract is.
"""

import datetime as dt
import json
import re
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
from pyproj import Geod
from shapely.geometry import box
from shapely.ops import unary_union

from geoevals.data.fetch import (
    FETCH_RECORD,
    Bbox,
    Opener,
    city_query,
    ensure_ignored,
    fetch_overpass,
)
from geoevals.data.verify import sha256_file

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
EXTRACT_FILE = "osm_extract.json"
GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class TownStats:
    buildings: int
    height_share: float
    """Share of buildings with a ``height`` or ``building:levels`` tag."""
    street_km: float
    path_km: float
    pois: int
    landuse_share: float
    """Share of the bounding box covered by land-use areas."""
    water_features: int
    extract_mb: float


def _length_km(frame: gpd.GeoDataFrame) -> float:
    return sum(GEOD.geometry_length(geometry) for geometry in frame.geometry) / 1000


def _area_m2(geometry) -> float:
    return abs(GEOD.geometry_area_perimeter(geometry)[0])


def measure_layers(
    layers: Mapping[str, gpd.GeoDataFrame], bbox: Bbox, extract_bytes: int
) -> TownStats:
    buildings = layers["buildings"]
    known = int((buildings["height_source"] != "unknown").sum())
    landuse = unary_union(list(layers["landuse"].geometry)) if len(layers["landuse"]) else None
    landuse_area = _area_m2(landuse.intersection(box(*bbox))) if landuse is not None else 0.0
    return TownStats(
        buildings=len(buildings),
        height_share=known / len(buildings) if len(buildings) else 0.0,
        street_km=_length_km(layers["streets"]),
        path_km=_length_km(layers["paths"]),
        pois=len(layers["pois"]),
        landuse_share=landuse_area / _area_m2(box(*bbox)),
        water_features=len(layers["water"]),
        extract_mb=extract_bytes / 1_000_000,
    )


def stats_table(rows: list[tuple[str, TownStats]]) -> str:
    """A Markdown table with one row per town."""
    lines = [
        "| Town | Buildings | With height or levels | Streets (km) | Paths (km) | POIs "
        "| Land use cover | Water features | Extract (MB) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, s in rows:
        lines.append(
            f"| {name} | {s.buildings} | {s.height_share:.0%} | {s.street_km:.1f} "
            f"| {s.path_km:.1f} | {s.pois} | {s.landuse_share:.0%} | {s.water_features} "
            f"| {s.extract_mb:.1f} |"
        )
    return "\n".join(lines)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def fetch_candidate(
    name: str,
    bbox: Bbox,
    snapshot_date: str,
    out_root: Path,
    opener: Opener = urllib.request.urlopen,
    source_url: str = OVERPASS_URL,
) -> Path:
    """Fetch a candidate town into ``out_root/<slug>/`` (``osm_extract.json`` and
    ``fetch.json``); return that directory. Refuses paths git would commit."""
    directory = out_root / slug(name)
    extract_path, record_path = directory / EXTRACT_FILE, directory / FETCH_RECORD
    for path in (extract_path, record_path):
        ensure_ignored(path)
    query = city_query(bbox, snapshot_date)
    query, extract, osm_base = fetch_overpass(source_url, bbox, snapshot_date, opener, query=query)
    directory.mkdir(parents=True, exist_ok=True)
    extract_path.write_bytes(extract)
    record = {
        "name": name,
        "source_url": source_url,
        "query": query,
        "bbox": list(bbox),
        "snapshot_date": snapshot_date,
        "access_date": dt.date.today().isoformat(),
        "osm_base": osm_base,
        "sha256": sha256_file(extract_path),
        "bytes": len(extract),
    }
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return directory


def read_candidate(name: str, bbox: Bbox, pbf: Path, out_root: Path) -> Path:
    """Read a candidate town from a local extract into ``out_root/<slug>/``, like
    ``fetch_candidate``; the snapshot date is the extract's replication date."""
    from geoevals.data.pbf import pbf_timestamp, read_pbf  # needs osmium; only this path does

    directory = out_root / slug(name)
    extract_path, record_path = directory / EXTRACT_FILE, directory / FETCH_RECORD
    for path in (extract_path, record_path):
        ensure_ignored(path)
    extract = read_pbf(pbf, bbox)
    timestamp = pbf_timestamp(pbf)
    directory.mkdir(parents=True, exist_ok=True)
    extract_path.write_bytes(extract)
    record = {
        "name": name,
        "source": str(pbf),
        "source_sha256": sha256_file(pbf),
        "bbox": list(bbox),
        "snapshot_date": timestamp[:10] if timestamp else None,
        "access_date": dt.date.today().isoformat(),
        "osm_base": timestamp,
        "sha256": sha256_file(extract_path),
        "bytes": len(extract),
    }
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return directory
