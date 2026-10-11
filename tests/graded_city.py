"""A small synthetic city for the graded-eval tests, as an Overpass ``out geom`` extract.

Coordinates are laid out in meters on a grid around (10 E, 50 N) and converted to longitude and
latitude with a spherical scale, so distances on the WGS 84 ellipsoid match the grid to about
0.5 %.

Layout (x east, y north, meters):

- The Mill River runs west to east along y = 0 (way/100, water area way/101). Bridge Road
  (way/202, x = 300) is the only crossing.
- North Street (way/200, y = 100), South Street (way/201, y = -100), West Avenue (way/203,
  x = -400, north of North Street). Main Line railway (way/300, y = 350).
- Footways: way/210 (0, 60)-(0, 100), way/211 (0, -60)-(0, -100), way/212 (-250, 140)-(-250, 100).
- Pharmacies: node/500 North Pharmacy (-250, 140), node/501 South Pharmacy (0, -60). From
  ORIGIN (0, 60), South Pharmacy is nearer in a straight line (120 m against 262 m) and North
  Pharmacy on foot (330 m against 880 m).
- Landmarks: node/502 Bridge Cafe (310, 95), node/504 post box (5, -95).
- Visibility from VIEWPOINT (100, 150): Clock Tower way/400 (40 m) is visible over Low House
  way/401 (2 levels, 6 m); School way/403 (8 m) is hidden by Tall Block way/402 (25 m); Library
  way/405 (12 m) is behind Shed way/404, whose height is unknown.
- Adjacency: way/410 and way/411 share a wall; Corner Shop way/412 touches way/411 at one corner;
  way/413 stands alone.
- Boundaries: West District relation/700 (x <= 0) and East District relation/701 (x >= 0) share
  the line x = 0; Old Town Conservation Area relation/702 (-100..100, 120..330) overlaps both.
- Riverside Park way/600; Ring Park relation/703 is a multipolygon with a hole; residential land
  use way/610.
- way/900 has no node positions (attic data) and way/901 has no tags; both are left out.
"""

import math
from pathlib import Path
from typing import Any

from geoevals.graded.city import LAYERS_DIR, convert_extract, write_layers

LON0, LAT0 = 10.0, 50.0
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(LAT0))

Point = tuple[float, float]


def lonlat(x: float, y: float) -> list[float]:
    """Longitude and latitude of grid point (x, y), in meters east and north of (10 E, 50 N)."""
    return [round(LON0 + x / M_PER_DEG_LON, 9), round(LAT0 + y / M_PER_DEG_LAT, 9)]


ORIGIN = lonlat(0, 60)
VIEWPOINT = lonlat(100, 150)
_SW, _NE = lonlat(-450, -250), lonlat(450, 400)
BBOX = (_SW[0], _SW[1], _NE[0], _NE[1])


def rect(x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


class _Extract:
    def __init__(self) -> None:
        self.elements: list[dict[str, Any]] = []
        self._nodes: dict[Point, int] = {}

    def _node_id(self, point: Point) -> int:
        return self._nodes.setdefault(point, 10_000 + len(self._nodes))

    @staticmethod
    def _geometry(points: list[Point]) -> list[dict[str, float]]:
        return [{"lat": lonlat(x, y)[1], "lon": lonlat(x, y)[0]} for x, y in points]

    def node(self, id_: int, x: float, y: float, tags: dict[str, str]) -> None:
        lon, lat = lonlat(x, y)
        self.elements.append({"type": "node", "id": id_, "lat": lat, "lon": lon, "tags": tags})

    def way(self, id_: int, points: list[Point], tags: dict[str, str]) -> None:
        self.elements.append(
            {
                "type": "way",
                "id": id_,
                "nodes": [self._node_id(p) for p in points],
                "geometry": self._geometry(points),
                "tags": tags,
            }
        )

    def relation(
        self, id_: int, rings: list[tuple[str, list[Point]]], tags: dict[str, str]
    ) -> None:
        members = [
            {"type": "way", "ref": id_ * 10 + i, "role": role, "geometry": self._geometry(ring)}
            for i, (role, ring) in enumerate(rings)
        ]
        self.elements.append({"type": "relation", "id": id_, "members": members, "tags": tags})


def overpass_document() -> dict[str, Any]:
    """The synthetic city as an Overpass JSON response."""
    e = _Extract()
    e.way(100, [(-450, 0), (450, 0)], {"waterway": "river", "name": "Mill River"})
    e.way(
        101, rect(-450, -10, 450, 10), {"natural": "water", "water": "river", "name": "Mill River"}
    )
    north: list[Point] = [(-400, 100), (-250, 100), (0, 100), (300, 100), (400, 100)]
    e.way(200, north, {"highway": "residential", "name": "North Street"})
    south: list[Point] = [(-400, -100), (0, -100), (300, -100), (400, -100)]
    e.way(201, south, {"highway": "residential", "name": "South Street"})
    bridge: list[Point] = [(300, 100), (300, 0), (300, -100)]
    e.way(202, bridge, {"highway": "tertiary", "name": "Bridge Road", "bridge": "yes"})
    e.way(203, [(-400, 100), (-400, 400)], {"highway": "residential", "name": "West Avenue"})
    e.way(210, [(0, 60), (0, 100)], {"highway": "footway"})
    e.way(211, [(0, -60), (0, -100)], {"highway": "footway"})
    e.way(212, [(-250, 140), (-250, 100)], {"highway": "footway"})
    e.way(300, [(-450, 350), (450, 350)], {"railway": "rail", "name": "Main Line"})
    e.way(400, rect(90, 290, 110, 310), {"building": "yes", "height": "40", "name": "Clock Tower"})
    e.way(
        401,
        rect(90, 220, 110, 230),
        {"building": "house", "building:levels": "2", "name": "Low House"},
    )
    e.way(
        402,
        rect(170, 200, 190, 220),
        {"building": "apartments", "height": "25 m", "name": "Tall Block"},
    )
    e.way(403, rect(230, 250, 250, 270), {"building": "school", "height": "8", "name": "School"})
    e.way(404, rect(15, 195, 35, 215), {"building": "shed", "name": "Shed"})
    library = {"building": "yes", "amenity": "library", "height": "12", "name": "Library"}
    e.way(405, rect(-60, 250, -40, 270), library)
    e.way(410, rect(-300, -200, -280, -180), {"building": "house", "name": "1 Terrace Row"})
    e.way(411, rect(-280, -200, -260, -180), {"building": "house", "name": "2 Terrace Row"})
    shop = {"building": "retail", "shop": "convenience", "name": "Corner Shop"}
    e.way(412, rect(-260, -220, -240, -200), shop)
    e.way(413, rect(-200, -200, -180, -180), {"building": "house", "name": "Detached House"})
    e.node(500, -250, 140, {"amenity": "pharmacy", "name": "North Pharmacy"})
    e.node(501, 0, -60, {"amenity": "pharmacy", "name": "South Pharmacy"})
    e.node(502, 310, 95, {"amenity": "cafe", "name": "Bridge Cafe"})
    e.node(504, 5, -95, {"amenity": "post_box"})
    e.way(600, rect(-400, 15, -200, 90), {"leisure": "park", "name": "Riverside Park"})
    e.way(610, rect(-450, -250, 450, -120), {"landuse": "residential"})
    district = {"type": "boundary", "boundary": "administrative", "admin_level": "10"}
    e.relation(700, [("outer", rect(-450, -250, 0, 400))], {**district, "name": "West District"})
    e.relation(701, [("outer", rect(0, -250, 450, 400))], {**district, "name": "East District"})
    conservation = {"type": "boundary", "boundary": "protected_area"}
    e.relation(
        702,
        [("outer", rect(-100, 120, 100, 330))],
        {**conservation, "name": "Old Town Conservation Area"},
    )
    e.relation(
        703,
        [("outer", rect(200, -240, 300, -140)), ("inner", rect(230, -210, 270, -170))],
        {"type": "multipolygon", "leisure": "park", "name": "Ring Park"},
    )
    e.elements.append(
        {
            "type": "way",
            "id": 900,
            "nodes": [1, 2],
            "geometry": [None, None],
            "tags": {"building": "yes"},
        }
    )
    e.way(901, [(-10, -150), (10, -150)], {})
    return {"version": 0.6, "elements": e.elements}


def build_data_dir(root: Path) -> Path:
    """Write the synthetic city's layers to ``root/layers/`` and return ``root``."""
    write_layers(convert_extract(overpass_document()), root / LAYERS_DIR)
    return root
