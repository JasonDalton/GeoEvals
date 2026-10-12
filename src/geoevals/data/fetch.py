"""Download a dataset that may not be committed into a gitignored path.

``geoevals data fetch <dataset_id>`` reads ``datasets/manifests/<dataset_id>.yaml``, downloads
its single asset with the fetcher registered for the dataset, and writes three files next to
the asset path (``data/raw/<dataset_id>/`` for the shipped manifests):

- the asset itself;
- ``manifest.yaml``: a copy of the committed manifest describing what was actually fetched
  (asset path, ``access_date``, ``sha256``, ``bbox``, ``time_range``), which
  ``geoevals data verify`` can check;
- ``fetch.json``: the fetch record (query, source, dates, checksum, size).

Every output path must be gitignored (or outside any git working tree); a fetch never writes
into a path git would commit. The committed manifest is never modified.

Fetchers:

- ``human_context_pilot``: an OpenStreetMap extract for a bounding box from the Overpass API,
  pinned to a snapshot date with an Overpass ``date:`` (attic) query, so that two fetches of
  the same box and date return the same data. The response is normalized (the server header is
  dropped and the elements sorted) before its checksum is taken.
- ``osm_city_<town>``: every tagged OpenStreetMap feature of a town for the graded evals, from
  the Overpass API at a snapshot date (``city_query``), with full geometry. With ``pbf``, the
  same features are read from a local dated extract instead (``geoevals.data.pbf``); its
  replication timestamp must fall on the snapshot date, and its SHA-256 is recorded.
"""

import copy
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from geoevals import __version__
from geoevals.data.verify import sha256_file
from geoevals.validation.git import GitPathState, git_path_state
from geoevals.validation.validate import load_dataset_manifest, load_yaml

DEFAULT_MANIFESTS = Path("datasets/manifests")
"""Directory of the committed dataset manifests, relative to the working directory."""

LOCAL_MANIFEST = "manifest.yaml"
FETCH_RECORD = "fetch.json"

Bbox = tuple[float, float, float, float]
"""``(min_lon, min_lat, max_lon, max_lat)`` in degrees."""

Opener = Callable[[urllib.request.Request], Any]
"""Opens a request and returns a file-like response (``urllib.request.urlopen``)."""


class FetchError(RuntimeError):
    """The dataset cannot be fetched, or the fetch would write somewhere it must not."""


@dataclass(frozen=True)
class FetchRecord:
    """What one fetch downloaded and where it wrote it."""

    dataset_id: str
    asset_id: str
    source_url: str
    query: str
    bbox: list[float]
    snapshot_date: str
    access_date: str
    osm_base: str | None
    """The server's database timestamp (Overpass ``timestamp_osm_base``)."""
    sha256: str
    bytes: int
    path: str
    """The asset file, as written."""
    source_sha256: str | None = None
    """The SHA-256 of the local ``.osm.pbf`` the asset was read from, if any."""


def ensure_ignored(path: Path) -> None:
    """Raise ``FetchError`` unless git would never commit ``path``."""
    state = git_path_state(path)
    if state in (GitPathState.TRACKED, GitPathState.UNIGNORED):
        raise FetchError(
            f"{path}: refusing to write restricted data to a path git would commit "
            f"({state.value}); use a gitignored directory such as data/raw/"
        )


def parse_bbox(text: str) -> Bbox:
    """Parse ``min_lon,min_lat,max_lon,max_lat``."""
    try:
        values = [float(part) for part in text.split(",")]
    except ValueError:
        expected = "four numbers min_lon,min_lat,max_lon,max_lat"
        raise FetchError(f"bbox {text!r}: expected {expected}") from None
    return check_bbox(values)


def check_bbox(values: Sequence[float]) -> Bbox:
    if len(values) != 4:
        raise FetchError(f"bbox {list(values)}: expected four numbers")
    min_lon, min_lat, max_lon, max_lat = (float(value) for value in values)
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise FetchError(f"bbox {list(values)}: not min_lon < max_lon, min_lat < max_lat")
    return min_lon, min_lat, max_lon, max_lat


# --- OpenStreetMap via Overpass ------------------------------------------------------------

STREET_HIGHWAYS = (
    "footway|pedestrian|path|steps|living_street|residential|service|unclassified|track|"
    "cycleway|road|tertiary|tertiary_link|secondary|secondary_link|primary|primary_link"
)
"""``highway`` values of the ways that make up the walking network."""

POI_FILTERS = (
    'nwr["shop"~"^(supermarket|convenience|greengrocer)$"]',
    'nwr["amenity"~"^(pharmacy|school|clinic|doctors)$"]',
    'nwr["leisure"="park"]',
    'nwr["highway"="bus_stop"]',
    'nwr["railway"~"^(station|halt|tram_stop)$"]',
)
"""Overpass filters of the points of interest (see ``geoevals.pilot.poi_category``)."""


def overpass_query(bbox: Bbox, snapshot_date: str, timeout_s: int = 180) -> str:
    """The Overpass QL query for the streets and POIs in ``bbox`` as of ``snapshot_date``.

    Streets are output with their node IDs and coordinates (``out geom``), POIs with their tags
    and a point (``out center``: a way or relation gets its center).
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    pois = "\n".join(f"  {poi};" for poi in POI_FILTERS)
    return (
        f"[out:json][timeout:{timeout_s}][bbox:{min_lat},{min_lon},{max_lat},{max_lon}]"
        f'[date:"{snapshot_date}T00:00:00Z"];\n'
        f'way["highway"~"^({STREET_HIGHWAYS})$"]->.streets;\n'
        ".streets out geom;\n"
        f"(\n{pois}\n)->.pois;\n"
        ".pois out center tags;\n"
    )


def city_query(bbox: Bbox, snapshot_date: str, timeout_s: int = 900) -> str:
    """The Overpass QL query for a whole town as of ``snapshot_date``: every tagged node, every
    way, the multipolygon relations, and the boundary relations below the county level (admin
    levels 8 to 11, or none). Country and state boundaries are left out: their geometry would
    dwarf the town's."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        f"[out:json][timeout:{timeout_s}][maxsize:2147483648]"
        f"[bbox:{min_lat},{min_lon},{max_lat},{max_lon}]"
        f'[date:"{snapshot_date}T00:00:00Z"];\n'
        "(\n"
        '  node[~"."~"."];\n'
        "  way;\n"
        '  relation["type"="multipolygon"];\n'
        '  relation["type"="boundary"]["admin_level"~"^([89]|1[01])$"];\n'
        '  relation["type"="boundary"][!"admin_level"];\n'
        ");\n"
        "out geom;\n"
    )


def normalize_overpass(document: dict[str, Any]) -> bytes:
    """Canonical bytes of an Overpass JSON response: only ``elements``, sorted, compact.

    The header (generator version, database timestamp) changes from fetch to fetch while the
    data of a dated query does not; dropping it keeps the checksum stable.
    """
    elements = document.get("elements")
    if not isinstance(elements, list):
        raise FetchError("Overpass response has no elements list")

    def key(element: dict[str, Any]) -> tuple[str, int, str]:
        return element["type"], element["id"], json.dumps(element, sort_keys=True)

    ordered = sorted(elements, key=key)
    text = json.dumps({"elements": ordered}, sort_keys=True, separators=(",", ":"))
    return text.encode("utf-8") + b"\n"


def fetch_overpass(
    source_url: str,
    bbox: Bbox,
    snapshot_date: str,
    opener: Opener,
    query: str | None = None,
) -> tuple[str, bytes, str | None]:
    """Run ``query`` (default: ``overpass_query``); return it, the normalized extract and the
    server's database timestamp."""
    query = query or overpass_query(bbox, snapshot_date)
    request = urllib.request.Request(
        source_url,
        data=urllib.parse.urlencode({"data": query}).encode("utf-8"),
        headers={"User-Agent": f"geoevals/{__version__} (data fetch)"},
    )
    try:
        with opener(request) as response:
            raw = response.read()
    except OSError as exc:
        raise FetchError(f"{source_url}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FetchError(f"{source_url}: response is not JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise FetchError(f"{source_url}: response is not a JSON object")
    # Overpass reports a timeout or memory error as a 200 response with a remark.
    remark = document.get("remark")
    if isinstance(remark, str) and "error" in remark.lower():
        raise FetchError(f"{source_url}: {remark}")
    osm_base = document.get("osm3s", {}).get("timestamp_osm_base")
    return query, normalize_overpass(document), osm_base


FETCHERS = {"human_context_pilot": "overpass"}
"""Dataset ID -> how its asset is downloaded."""
CITY_PREFIX = "osm_city_"
"""Datasets named ``osm_city_<town>`` are whole-town extracts (``city_query``)."""


def fetcher_for(dataset_id: str) -> str | None:
    """How ``dataset_id`` is downloaded: ``overpass``, ``overpass_city`` or None (unknown)."""
    if dataset_id.startswith(CITY_PREFIX):
        return "overpass_city"
    return FETCHERS.get(dataset_id)


# --- fetch ---------------------------------------------------------------------------------


def manifest_path(dataset_id: str, manifests_dir: Path = DEFAULT_MANIFESTS) -> Path:
    return manifests_dir / f"{dataset_id}.yaml"


def fetch_dataset(
    dataset_id: str,
    manifests_dir: Path = DEFAULT_MANIFESTS,
    out_dir: Path | None = None,
    bbox: Bbox | None = None,
    snapshot_date: str | None = None,
    today: dt.date | None = None,
    opener: Opener = urllib.request.urlopen,
    pbf: Path | None = None,
) -> FetchRecord:
    """Download the asset of ``dataset_id`` and record it; see the module docstring.

    ``bbox`` and ``snapshot_date`` default to the committed manifest's asset ``bbox`` and
    ``time_range.end``. ``out_dir`` defaults to the directory of the asset path. ``pbf`` reads a
    city from a local extract instead of the Overpass API.
    """
    kind = fetcher_for(dataset_id)
    if kind is None:
        known = ", ".join([*sorted(FETCHERS), f"{CITY_PREFIX}<town>"])
        raise FetchError(f"no fetcher for dataset {dataset_id!r} (known: {known})")
    path = manifest_path(dataset_id, manifests_dir)
    if not path.is_file():
        raise FetchError(f"{path}: dataset manifest not found")
    manifest = load_dataset_manifest(path)
    if manifest.dataset_id != dataset_id:
        raise FetchError(f"{path}: dataset_id is {manifest.dataset_id!r}, not {dataset_id!r}")
    if len(manifest.assets) != 1:
        raise FetchError(f"{path}: expected exactly one asset, found {len(manifest.assets)}")
    asset = manifest.assets[0]
    if asset.source_url is None:
        raise FetchError(f"{path}: asset {asset.asset_id!r} has no source_url")
    if pbf is not None and kind != "overpass_city":
        raise FetchError(f"{dataset_id}: only {CITY_PREFIX}<town> datasets read a local extract")

    bbox = check_bbox(asset.bbox) if bbox is None else bbox
    snapshot_date = snapshot_date or asset.time_range.end
    try:
        dt.date.fromisoformat(snapshot_date)
    except ValueError:
        raise FetchError(f"snapshot date {snapshot_date!r}: expected YYYY-MM-DD") from None
    asset_file = Path(asset.path).name
    if out_dir is None:
        out_dir = Path(os.path.normpath(path.parent / asset.path)).parent
    outputs = [out_dir / asset_file, out_dir / LOCAL_MANIFEST, out_dir / FETCH_RECORD]
    for output in outputs:
        ensure_ignored(output)

    source_sha256 = None
    if pbf is not None:
        query, extract, osm_base = _read_local_extract(pbf, bbox, snapshot_date)
        source_sha256 = sha256_file(pbf)
    else:
        query = city_query(bbox, snapshot_date) if kind == "overpass_city" else None
        query, extract, osm_base = fetch_overpass(
            asset.source_url, bbox, snapshot_date, opener, query=query
        )
    access_date = (today or dt.date.today()).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs[0].write_bytes(extract)
    record = FetchRecord(
        dataset_id=dataset_id,
        asset_id=asset.asset_id,
        source_url=asset.source_url,
        query=query,
        bbox=list(bbox),
        snapshot_date=snapshot_date,
        access_date=access_date,
        osm_base=osm_base,
        sha256=sha256_file(outputs[0]),
        bytes=len(extract),
        path=str(outputs[0]),
        source_sha256=source_sha256,
    )
    document = load_yaml(path)
    outputs[1].write_text(_local_manifest(document, asset_file, record), encoding="utf-8")
    outputs[2].write_text(json.dumps(asdict(record), indent=2) + "\n", encoding="utf-8")
    return record


def _read_local_extract(pbf: Path, bbox: Bbox, snapshot_date: str) -> tuple[str, bytes, str | None]:
    """Read a city from a local extract dated ``snapshot_date``; return a description of the
    read, the normalized extract and the extract's replication timestamp."""
    from geoevals.data.pbf import pbf_timestamp, read_pbf  # needs osmium; only this path does

    if not pbf.is_file():
        raise FetchError(f"{pbf}: no such file")
    timestamp = pbf_timestamp(pbf)
    if timestamp is None or not timestamp.startswith(snapshot_date):
        raise FetchError(
            f"{pbf}: replication timestamp {timestamp} is not on the snapshot date {snapshot_date}"
        )
    query = f"geoevals.data.pbf.read_pbf({pbf.name}, bbox={list(bbox)})"
    return query, read_pbf(pbf, bbox), timestamp


def _local_manifest(document: dict[str, Any], asset_file: str, record: FetchRecord) -> str:
    """The committed manifest, with the asset entry describing what was fetched."""
    local = copy.deepcopy(document)
    entry = local["assets"][0]
    entry["path"] = asset_file
    entry["access_date"] = record.access_date
    entry["sha256"] = record.sha256
    entry["bbox"] = record.bbox
    entry["time_range"] = {"start": record.snapshot_date, "end": record.snapshot_date}
    if record.source_sha256 is not None:
        step = (
            f"Read by `geoevals data fetch {record.dataset_id} --pbf` on {record.access_date} "
            f"from a local extract (sha256 {record.source_sha256}, replication timestamp "
            f"{record.osm_base}); details in {FETCH_RECORD}."
        )
    else:
        step = (
            f"Fetched by `geoevals data fetch {record.dataset_id}` on {record.access_date} "
            f"(server database timestamp {record.osm_base}); query in {FETCH_RECORD}."
        )
    entry["processing_steps"] = [*entry.get("processing_steps", []), step]
    return yaml.safe_dump(local, sort_keys=False, allow_unicode=True, width=100)
