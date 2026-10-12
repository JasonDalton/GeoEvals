"""Read a town's OpenStreetMap features from a local ``.osm.pbf`` extract.

A dated regional extract (Geofabrik's ``<region>-YYMMDD.osm.pbf``) is a fixed file, so a town cut
from it is reproducible from the file's SHA-256 alone. ``read_pbf(path, bbox)`` returns the same
elements as the Overpass city query (``geoevals.data.fetch.city_query``) in the shape of an
Overpass ``out geom`` response, so ``geoevals.graded.city.convert_extract`` reads either:

- every tagged node in the box;
- every way with a node in the box or a segment crossing it, with its full geometry;
- the multipolygon relations, and the boundary relations below the county level (admin levels
  8 to 11, or none), with a member in the box; every way member carries its full geometry.

Node members of a relation are listed without coordinates; the layers use only way members.
The response is normalized like an Overpass one (``normalize_overpass``) before it is hashed.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import osmium
import osmium.io
import osmium.osm
from shapely.geometry import LineString, box

from geoevals.data.fetch import Bbox, FetchError, normalize_overpass

TIMESTAMP_OPTION = "osmosis_replication_timestamp"
"""The header option holding the extract's database timestamp."""
BOUNDARY_LEVELS = frozenset({"8", "9", "10", "11"})
MEMBER_TYPES = {"n": "node", "w": "way", "r": "relation"}

Coords = list[tuple[float, float] | None]


def pbf_timestamp(path: Path) -> str | None:
    """The extract's replication timestamp (``2026-10-11T20:21:06Z``), or None."""
    reader = osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING)
    try:
        return reader.header().get(TIMESTAMP_OPTION) or None
    finally:
        reader.close()


def _wanted_relation(tags: dict[str, str]) -> bool:
    kind = tags.get("type")
    if kind == "multipolygon":
        return True
    if kind == "boundary":
        level = tags.get("admin_level")
        return level is None or level in BOUNDARY_LEVELS
    return False


def _geometry(coords: Coords) -> list[dict[str, float] | None]:
    return [None if c is None else {"lat": c[1], "lon": c[0]} for c in coords]


def _crosses(coords: Coords, bbox: Bbox) -> bool:
    """Whether a line with no vertex in the box still crosses it."""
    points = [c for c in coords if c is not None]
    if len(points) < 2:
        return False
    lons, lats = [p[0] for p in points], [p[1] for p in points]
    min_lon, min_lat, max_lon, max_lat = bbox
    if max(lons) < min_lon or min(lons) > max_lon or max(lats) < min_lat or min(lats) > max_lat:
        return False
    return LineString(points).intersects(box(*bbox))


def _relations(path: Path) -> dict[int, dict[str, Any]]:
    """The wanted relations, by ID, with their tags and members."""
    relations: dict[int, dict[str, Any]] = {}
    for relation in osmium.FileProcessor(str(path), osmium.osm.RELATION):
        if not isinstance(relation, osmium.osm.Relation):
            continue
        tags = dict(relation.tags)
        if _wanted_relation(tags):
            members = [(MEMBER_TYPES[m.type], m.ref, m.role) for m in relation.members]
            relations[relation.id] = {"tags": tags, "members": members}
    return relations


def read_pbf(path: Path, bbox: Bbox) -> bytes:
    """The town's elements as a normalized Overpass ``out geom`` response; see the module
    docstring. Raises ``FetchError`` when the file cannot be read."""
    if not path.is_file():
        raise FetchError(f"{path}: no such file")
    min_lon, min_lat, max_lon, max_lat = bbox

    def inside(lon: float, lat: float) -> bool:
        return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat

    try:
        relations = _relations(path)
        member_ways = {
            ref for r in relations.values() for kind, ref, _ in r["members"] if kind == "way"
        }
        member_nodes = {
            ref for r in relations.values() for kind, ref, _ in r["members"] if kind == "node"
        }
        elements: list[dict[str, Any]] = []
        ways_in: set[int] = set()
        nodes_in: set[int] = set()
        way_coords: dict[int, Coords] = {}
        processor = osmium.FileProcessor(str(path), osmium.osm.NODE | osmium.osm.WAY)
        for obj in processor.with_locations():
            if isinstance(obj, osmium.osm.Node):
                lon, lat = obj.location.lon, obj.location.lat
                if not inside(lon, lat):
                    continue
                if obj.id in member_nodes:
                    nodes_in.add(obj.id)
                if len(obj.tags):
                    node = {"type": "node", "id": obj.id, "lat": lat, "lon": lon}
                    elements.append({**node, "tags": dict(obj.tags)})
            elif isinstance(obj, osmium.osm.Way):
                coords: Coords = [(n.lon, n.lat) if n.location.valid() else None for n in obj.nodes]
                if obj.id in member_ways:
                    way_coords[obj.id] = coords
                if any(c is not None and inside(*c) for c in coords) or _crosses(coords, bbox):
                    ways_in.add(obj.id)
                    way = {"type": "way", "id": obj.id, "nodes": [n.ref for n in obj.nodes]}
                    elements.append({**way, "geometry": _geometry(coords), "tags": dict(obj.tags)})
    except (RuntimeError, ValueError) as exc:  # pyosmium reports bad files as RuntimeError
        raise FetchError(f"{path}: {exc}") from exc
    elements.extend(_relation_elements(relations, ways_in, nodes_in, way_coords))
    return normalize_overpass({"elements": elements})


def _relation_elements(
    relations: dict[int, dict[str, Any]],
    ways_in: set[int],
    nodes_in: set[int],
    way_coords: dict[int, Coords],
) -> Iterable[dict[str, Any]]:
    for relation_id, relation in relations.items():
        members = relation["members"]
        if not any(
            (kind == "way" and ref in ways_in) or (kind == "node" and ref in nodes_in)
            for kind, ref, _ in members
        ):
            continue
        listed = []
        for kind, ref, role in members:
            member: dict[str, Any] = {"type": kind, "ref": ref, "role": role}
            if kind == "way" and ref in way_coords:
                member["geometry"] = _geometry(way_coords[ref])
            listed.append(member)
        yield {"type": "relation", "id": relation_id, "members": listed, "tags": relation["tags"]}
