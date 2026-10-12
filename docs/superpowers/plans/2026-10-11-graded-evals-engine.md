# Graded evals engine (plan 1 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build everything the agent-graded spatial-reasoning evals need that can be tested in CI on a synthetic city: the city layers, the town measurement, eval specs, reference keys, graded runs on the python track, the Opus grader, the graded leaderboard table and box plots, and the docs that separate benchmarks from graded evals.

**Architecture:** A new package `geoevals.graded` sits beside the benchmark runner and shares none of its scores, tables or directories. A city snapshot (an Overpass extract) becomes GeoParquet layers; `evals/city/reference.py` computes a hidden reference key per task from those layers; a graded run sends each task to a `claude_python_<model>` adapter with the city mounted read-only; `geoevals grade` asks Opus 5.5 twice per answer in isolated `claude -p` sessions; `geoevals leaderboard build` writes a quartile table and one SVG box plot per eval.

**Tech Stack:** Python 3.11+, GeoPandas, Shapely 2, pyproj, NetworkX, NumPy, jsonschema, Pydantic 2, matplotlib (new optional `plots` extra), the local Claude Code CLI through `geoevals.leaderboard.claude_cli`.

**Spec:** `docs/superpowers/specs/2026-10-10-graded-evals-design.md` (approved 2026-10-11). Plan 2 (written after the town is picked) covers the spec's real-city work: the town's dataset manifest, drafting the 60 tasks (checkpoint 2), the pilot and the full runs.

**Worktree:** `/Users/jason/code/GeoEvals-graded`, branch `feat/graded-evals`. Run every command from the worktree root.

## Global Constraints

- Benchmarks and graded evals are never combined: no shared score, no shared table, no shared directory.
- Graded evals run on the python track only; the direct track rejects graded prompts.
- Grader: Opus 5.5 (`claude-opus-5-5`), effort high, its own `claude -p` session with no tools, with the leaderboard's isolation (`--restricted`, stripped environment, empty working directory, subscription check): call `geoevals.leaderboard.claude_cli.run_cli`, never a new CLI wrapper.
- The grader input is the grader prompt (`grader_v1`), the task prompt, the rubric with anchors, the key and the answer. Never the answering model's name, the adapter name or the trajectory.
- Two grading passes per answer. Each criterion is an integer 0 to 4 with a justification of at most 60 words that cites the key. Task score = mean over the passes of (mean of criteria / 4), in [0, 1].
- A grader error or unparseable grade is retried once; a second failure marks the task "not graded", and a run with any ungraded task is not accepted. The usage-limit, auth and version checks of the leaderboard apply to the grader.
- The answer schema: `status` (as in the benchmarks) and `answer` (Markdown text, at most 4,000 words). A graded run writes no scores.
- Building height: the `height` tag where it parses, else `building:levels` x 3 m, else unknown.
- Nothing OSM-derived is committed (`docs/data-governance.md`): reference keys live in the gitignored data directory; `tasks.jsonl` commits only each key's SHA-256.
- Graded table columns: `| Model | Eval | Mean (95% CI) | Min | Q1 | Median | Q3 | Max |`, mean interval from `geoevals.metrics.base.bootstrap_ci` with its fixed seed.
- SVG box plots are byte-stable: fixed fonts, a fixed hash salt, no timestamps.
- Real `claude` runs are never part of the test suite; tests use `tests/fake_claude.py`.
- American spelling. Line length 100 (ruff). No attribution trailers in commit messages. Do not push.

## Decisions taken while planning

These follow from the spec and the code; each is called out for the user's plan review.

1. **Keys are not committed.** `docs/data-governance.md` says v0.1 commits no OSM-derived data, so the spec's fallback applies: `geoevals evals regenerate` writes keys to `<data dir>/keys/<eval>.jsonl` (gitignored) and records each key's SHA-256 in `tasks.jsonl`. Keys round every float to 0.1 (meters, degrees) so that the hash is the same on every platform; `--check` compares hashes.
2. **Schema file names** follow the repository's hyphen style: `schemas/eval-spec.schema.json` and `schemas/graded-result.schema.json`. `grades.json` is validated by a Pydantic model (`geoevals.graded.grader.Grades`), as it is written only by GeoEvals.
3. **A `railways` layer** is added to the spec's layer list: the proximity eval's example barrier is rail.
4. **What the model sees:** the task `prompt`, the audience and the task `location` (point and feature IDs). The task `params` (the reference script's input) and `key` stay hidden.
5. **Answers that were not given** (adapter error, model timeout, invalid output) score 0 without a grader call, recorded as `no_answer`, as the leaderboard counts a model's failed case.
6. **Graded prompt template:** `src/geoevals/adapters/prompts/graded_python_v1.md`, chosen by a new adapter config field `prompt: graded`.
7. **Two plans:** this plan is all code, testable in CI. Plan 2 holds the real-city data and content work.

## Review Focus

1. Overpass attic data with missing node positions, or a relation whose members lack geometry: the converter leaves the element out instead of crashing (Task 1, `test_elements_without_geometry_are_left_out`).
2. A task place more than 100 m from the walking network, or in a part of the network not connected to the destination: the key says `reachable: false` with a reason instead of crashing (Task 4, `test_unreachable_places_are_reported`).
3. A model answers `ok` with an empty answer or more than 4,000 words: the task is `invalid_output` and scores 0 without a grader call (Task 9, `test_run_eval_records_answers_and_invalid_outputs`; Task 10, `test_no_answer_scores_zero_without_a_call`).
4. The grader returns a missing or extra criterion, a score of 5, or a 61-word justification: retried once, then "not graded", and the run is not accepted (Task 10, `test_invalid_grade_is_retried_once`, `test_two_invalid_grades_leave_the_task_not_graded`; Task 11, `test_board_rejects_not_graded_tasks`).
5. The keys file is missing or stale against the committed `key_sha256` at grade time: `geoevals grade` refuses before any grader call (Task 10, `test_grade_refuses_missing_or_stale_keys`).

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/geoevals/graded/__init__.py` | Package docstring |
| `src/geoevals/graded/city.py` | Overpass extract -> GeoParquet layers; height rule; load and hash layers |
| `src/geoevals/graded/towns.py` | Candidate-town fetch and measurement table |
| `src/geoevals/data/fetch.py` (modify) | `city_query`, the `osm_city_*` fetcher |
| `src/geoevals/validation/eval_spec.py` | Pydantic model of `eval.yaml` |
| `src/geoevals/validation/validate.py` (modify) | Validate and load eval specs; `geoevals validate` dispatch |
| `schemas/eval-spec.schema.json` | JSON Schema of `eval.yaml` |
| `src/geoevals/graded/spec.py` | Answer schema, task and rubric models, loading |
| `evals/city/rubric_criteria.yaml` | The five shared criteria and their anchors |
| `evals/city/reference.py` | Reference keys from the layers (six key types) |
| `src/geoevals/graded/reference.py` | Loads an eval's reference script |
| `src/geoevals/graded/keys.py` | Key hashing, keys file, regenerate, load and verify |
| `src/geoevals/adapters/claude.py`, `leaderboard/sandbox.py`, `leaderboard/sandbox_mcp.py`, `leaderboard/prompting.py` (modify) | `data_mount`, graded prompt, eval specs |
| `src/geoevals/adapters/prompts/graded_python_v1.md` | System prompt of graded runs |
| `src/geoevals/graded/run.py` | Graded runs and their result |
| `schemas/graded-result.schema.json` | JSON Schema of a graded run's `result.json` |
| `src/geoevals/graded/grader.py`, `src/geoevals/graded/prompts/grader_v1.md` | The grader and `grades.json` |
| `src/geoevals/graded/board.py` | Acceptance, statistics, agreement, Markdown table |
| `src/geoevals/graded/plots.py` | Byte-stable SVG box plots |
| `src/geoevals/leaderboard/table.py`, `src/geoevals/cli.py` (modify) | Section replacement; `evals`, `run --eval`, `grade`, leaderboard commands |
| `tests/graded_city.py` | The synthetic city (Overpass-style extract) |
| `tests/graded_helpers.py` | Copy the sample eval, build a data directory, write graded results |
| `tests/fixtures/graded/sample/` | A three-task eval on the synthetic city |
| `tests/test_graded_*.py` | Tests per module |
| Docs | `README.md`, `CONTRIBUTING.md`, `docs/eval-authoring.md`, `docs/best-practices.md`, `docs/data-governance.md`, `ROADMAP.md`, `evals/README.md`, `leaderboard/README.md`, `CHANGELOG.md` |

---

### Task 1: City layers from an Overpass extract, and the synthetic city

**Files:**
- Create: `src/geoevals/graded/__init__.py`
- Create: `src/geoevals/graded/city.py`
- Create: `tests/graded_city.py`
- Test: `tests/test_graded_city.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `geoevals.graded.city.CRS = "OGC:CRS84"`, `LAYERS: tuple[str, ...]`, `LAYERS_DIR = "layers"`
  - `parse_height(value: str | None) -> float | None`
  - `building_height(tags: Mapping[str, str]) -> tuple[float | None, str]` (source `height`, `levels` or `unknown`)
  - `convert_extract(document: Mapping[str, Any]) -> dict[str, gpd.GeoDataFrame]` (every layer in `LAYERS`, columns `feature_id`, `name`, layer columns, `geometry`)
  - `write_layers(layers: Mapping[str, gpd.GeoDataFrame], out_dir: Path) -> list[Path]`
  - `load_layers(directory: Path) -> dict[str, gpd.GeoDataFrame]`
  - `layers_sha256(directory: Path) -> str`
  - `class CityError(ValueError)`
  - `tests/graded_city.py`: `lonlat(x, y) -> list[float]`, `ORIGIN`, `VIEWPOINT`, `BBOX`, `overpass_document() -> dict`, `build_data_dir(root: Path) -> Path` (writes `root/layers/`, returns `root`)

- [ ] **Step 1: Write the synthetic city**

Create `tests/graded_city.py`:

```python
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
BBOX = (*lonlat(-450, -250), *lonlat(450, 400))


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
    north = [(-400, 100), (-250, 100), (0, 100), (300, 100), (400, 100)]
    e.way(200, north, {"highway": "residential", "name": "North Street"})
    south = [(-400, -100), (0, -100), (300, -100), (400, -100)]
    e.way(201, south, {"highway": "residential", "name": "South Street"})
    bridge = [(300, 100), (300, 0), (300, -100)]
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
```

Run `uv run ruff format tests/graded_city.py` after writing it; the long lines above are wrapped by the formatter.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_graded_city.py`:

```python
import math
from pathlib import Path

import pytest
from pyproj import CRS as ProjCRS

from geoevals.graded.city import (
    CRS,
    LAYERS,
    CityError,
    building_height,
    convert_extract,
    layers_sha256,
    load_layers,
    parse_height,
    write_layers,
)
from graded_city import overpass_document


@pytest.mark.parametrize(
    ("text", "meters"),
    [
        ("12", 12.0),
        ("12 m", 12.0),
        ("12.5m", 12.5),
        ("40 ft", 40 * 0.3048),
        ("40'", 40 * 0.3048),
        ("tall", None),
        ("0", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_height(text: str | None, meters: float | None) -> None:
    assert parse_height(text) == (pytest.approx(meters) if meters is not None else None)


def test_building_height_prefers_the_height_tag() -> None:
    assert building_height({"height": "9", "building:levels": "5"}) == (9.0, "height")
    assert building_height({"building:levels": "4"}) == (12.0, "levels")
    assert building_height({"building:levels": "two"}) == (None, "unknown")
    assert building_height({}) == (None, "unknown")


def _ids(layers, name: str) -> set[str]:
    return set(layers[name]["feature_id"])


def test_layers_hold_the_expected_features() -> None:
    layers = convert_extract(overpass_document())
    assert tuple(layers) == LAYERS
    assert _ids(layers, "streets") == {"way/200", "way/201", "way/202", "way/203"}
    assert _ids(layers, "paths") == {"way/210", "way/211", "way/212"}
    assert _ids(layers, "railways") == {"way/300"}
    assert _ids(layers, "water") == {"way/100", "way/101"}
    assert _ids(layers, "parks") == {"way/600", "relation/703"}
    assert _ids(layers, "landuse") == {"way/610"}
    assert _ids(layers, "boundaries") == {"relation/700", "relation/701", "relation/702"}
    assert {"way/400", "way/404", "way/405", "way/412"} <= _ids(layers, "buildings")
    assert _ids(layers, "pois") == {
        "node/500",
        "node/501",
        "node/502",
        "node/504",
        "way/405",
        "way/412",
    }
    assert set(layers["pois"].geom_type) == {"Point"}
    for frame in layers.values():
        assert frame.crs == ProjCRS(CRS)


def test_building_heights_follow_the_rule() -> None:
    buildings = convert_extract(overpass_document())["buildings"].set_index("feature_id")
    assert buildings.loc["way/400", "height_m"] == 40.0
    assert buildings.loc["way/400", "height_source"] == "height"
    assert buildings.loc["way/401", "height_m"] == 6.0
    assert buildings.loc["way/401", "height_source"] == "levels"
    assert math.isnan(buildings.loc["way/404", "height_m"])
    assert buildings.loc["way/404", "height_source"] == "unknown"


def test_multipolygon_relation_keeps_its_hole() -> None:
    parks = convert_extract(overpass_document())["parks"].set_index("feature_id")
    ring = parks.geometry["relation/703"]
    assert ring.geom_type == "Polygon"
    assert len(ring.interiors) == 1


def test_elements_without_geometry_are_left_out() -> None:
    document = overpass_document()
    document["elements"].append(
        {
            "type": "relation",
            "id": 999,
            "members": [{"type": "way", "role": "outer"}],
            "tags": {"type": "multipolygon", "landuse": "grass"},
        }
    )
    layers = convert_extract(document)
    features = _ids(layers, "all_features")
    assert "way/900" not in features, "no node positions"
    assert "way/901" not in features, "no tags"
    assert "relation/999" not in features, "members without geometry"


def test_all_features_keeps_every_tag_as_json() -> None:
    frame = convert_extract(overpass_document())["all_features"].set_index("feature_id")
    assert frame.loc["node/500", "tags"] == '{"amenity": "pharmacy", "name": "North Pharmacy"}'


def test_extract_without_elements_is_an_error() -> None:
    with pytest.raises(CityError, match="elements"):
        convert_extract({"remark": "runtime error"})


def test_layers_round_trip_and_hash(tmp_path: Path) -> None:
    layers = convert_extract(overpass_document())
    written = write_layers(layers, tmp_path / "layers")
    assert sorted(p.name for p in written) == sorted(f"{name}.parquet" for name in LAYERS)
    loaded = load_layers(tmp_path / "layers")
    for name in LAYERS:
        assert list(loaded[name]["feature_id"]) == list(layers[name]["feature_id"]), name
        assert loaded[name].geometry.geom_equals_exact(layers[name].geometry, 0).all(), name
    digest = layers_sha256(tmp_path / "layers")
    assert digest == layers_sha256(tmp_path / "layers")
    (tmp_path / "layers" / "pois.parquet").write_bytes(b"changed")
    assert layers_sha256(tmp_path / "layers") != digest


def test_load_layers_names_missing_layers(tmp_path: Path) -> None:
    write_layers(convert_extract(overpass_document()), tmp_path)
    (tmp_path / "parks.parquet").unlink()
    with pytest.raises(CityError, match="parks"):
        load_layers(tmp_path)
```

Run `uv run ruff format tests/test_graded_city.py`.

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_city.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'geoevals.graded'`.

- [ ] **Step 4: Write the package and the converter**

Create `src/geoevals/graded/__init__.py`:

```python
"""Agent-graded spatial-reasoning evals on a real city.

Graded evals are open-ended tasks that a grading agent scores against a rubric and a reference
key computed from data. They are reported apart from the deterministic benchmarks and never
combined with them. See ``docs/eval-authoring.md``.
"""
```

Create `src/geoevals/graded/city.py`:

```python
"""A city snapshot from OpenStreetMap as GeoParquet layers, for the graded evals.

``convert_extract`` turns an Overpass JSON extract (``out geom``: tagged nodes, ways, and
multipolygon and local boundary relations of a bounding box) into layers in longitude and
latitude (``OGC:CRS84``):

- ``buildings``: ``building=*`` areas, with ``height_m`` and ``height_source`` (see below)
- ``streets``: ``highway=*`` ways for vehicles (``STREET_HIGHWAYS``)
- ``paths``: ``highway=*`` ways for walking and cycling (``PATH_HIGHWAYS``)
- ``railways``: ``railway=*`` lines (``RAIL_TYPES``)
- ``water``: ``natural=water``, ``waterway=*`` and ``water=*``
- ``parks``: parks, gardens, playgrounds, nature reserves (``PARK_LEISURE``)
- ``landuse``: ``landuse=*`` areas
- ``pois``: features with one of ``POI_KEYS``, as points (``category`` is the first such key,
  ``value`` its value)
- ``boundaries``: ``boundary=*`` areas and lines
- ``all_features``: every feature with a geometry and all its tags (JSON in ``tags``)

A feature can be in several layers: a library in a building is in ``buildings`` and ``pois``.
Every row has ``feature_id`` (``node/1``, ``way/2``, ``relation/3``) and ``name``. Rows are in
feature order (nodes, ways, relations; then by ID), so two conversions give the same layers.

Building heights: the ``height`` tag in meters (``12``, ``12 m``, ``40 ft``, ``40'``) when it
parses, else ``building:levels`` x 3 m, else unknown (``height_m`` empty, ``height_source``
``unknown``).

Elements without usable geometry are left out: attic data can lack node positions, and a
relation member can lack its geometry. Untagged elements are left out too.
"""

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

CRS = "OGC:CRS84"
LAYERS_DIR = "layers"
LAYERS = (
    "buildings",
    "streets",
    "paths",
    "railways",
    "water",
    "parks",
    "landuse",
    "pois",
    "boundaries",
    "all_features",
)
LAYER_COLUMNS: dict[str, tuple[str, ...]] = {
    "buildings": ("building", "height_m", "height_source"),
    "streets": ("highway",),
    "paths": ("highway",),
    "railways": ("railway",),
    "water": ("water_kind",),
    "parks": ("leisure",),
    "landuse": ("landuse",),
    "pois": ("category", "value"),
    "boundaries": ("boundary", "admin_level"),
    "all_features": ("tags",),
}
LEVEL_HEIGHT_M = 3.0
FEET_TO_M = 0.3048
STREET_HIGHWAYS = frozenset(
    {
        "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
        "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
        "residential", "living_street", "service", "road",
    }
)  # fmt: skip
PATH_HIGHWAYS = frozenset(
    {"footway", "path", "pedestrian", "steps", "cycleway", "track", "bridleway", "corridor"}
)
RAIL_TYPES = frozenset(
    {"rail", "light_rail", "tram", "subway", "narrow_gauge", "monorail", "funicular"}
)
PARK_LEISURE = frozenset({"park", "garden", "playground", "nature_reserve", "dog_park"})
POI_KEYS = ("amenity", "shop", "tourism", "office", "healthcare", "historic", "craft")
AREA_KEYS = frozenset(
    {"building", "landuse", "leisure", "amenity", "shop", "tourism", "water", "place", "man_made"}
)
LINEAR_NATURAL = frozenset({"coastline", "cliff", "ridge", "tree_row", "arete"})
TYPE_ORDER = {"node": 0, "way": 1, "relation": 2}

_HEIGHT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m|meters?|metres?|ft|feet|')?\s*$", re.IGNORECASE)


class CityError(ValueError):
    """The extract or the layer directory cannot be read."""


def parse_height(value: str | None) -> float | None:
    """A ``height`` tag in meters, or None when it does not parse or is not positive."""
    if value is None:
        return None
    match = _HEIGHT.match(value)
    if match is None:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "m").lower()
    meters = number * FEET_TO_M if unit in ("ft", "feet", "'") else number
    return meters if meters > 0 else None


def building_height(tags: Mapping[str, str]) -> tuple[float | None, str]:
    """The building's height in meters and its source: ``height``, ``levels`` or ``unknown``."""
    height = parse_height(tags.get("height"))
    if height is not None:
        return height, "height"
    try:
        levels = float(tags.get("building:levels", ""))
    except ValueError:
        levels = 0.0
    if math.isfinite(levels) and levels > 0:
        return levels * LEVEL_HEIGHT_M, "levels"
    return None, "unknown"


def feature_id(element: Mapping[str, Any]) -> str:
    return f"{element['type']}/{element['id']}"


def _coords(points: Iterable[Any]) -> list[tuple[float, float]]:
    return [
        (float(p["lon"]), float(p["lat"]))
        for p in points
        if isinstance(p, dict) and "lon" in p and "lat" in p
    ]


def _is_area(tags: Mapping[str, str]) -> bool:
    if tags.get("area") == "no":
        return False
    if tags.get("area") == "yes" or tags.get("waterway") == "riverbank":
        return True
    if "highway" in tags or "barrier" in tags or "railway" in tags:
        return False
    if "natural" in tags:
        return tags["natural"] not in LINEAR_NATURAL
    return any(key in tags for key in AREA_KEYS)


def _relation_geometry(members: Iterable[Any]) -> BaseGeometry | None:
    rings: dict[str, list[LineString]] = {"outer": [], "inner": []}
    for member in members:
        if not isinstance(member, dict) or member.get("type") != "way":
            continue
        coords = _coords(member.get("geometry") or [])
        if len(coords) >= 2:
            role = "inner" if member.get("role") == "inner" else "outer"
            rings[role].append(LineString(coords))
    if not rings["outer"]:
        return None
    outer = unary_union(list(polygonize(unary_union(rings["outer"]))))
    if outer.is_empty:
        return unary_union(rings["outer"])
    if rings["inner"]:
        outer = outer.difference(unary_union(list(polygonize(unary_union(rings["inner"])))))
    return outer


def element_geometry(element: Mapping[str, Any]) -> BaseGeometry | None:
    """The element's geometry in longitude and latitude, or None when it has none."""
    tags = element.get("tags") or {}
    kind = element.get("type")
    if kind == "node":
        if "lon" not in element or "lat" not in element:
            return None
        return Point(float(element["lon"]), float(element["lat"]))
    if kind == "way":
        coords = _coords(element.get("geometry") or [])
        if len(coords) < 2:
            return None
        if len(coords) >= 4 and coords[0] == coords[-1] and _is_area(tags):
            return Polygon(coords)
        return LineString(coords)
    if kind == "relation" and tags.get("type") in ("multipolygon", "boundary"):
        return _relation_geometry(element.get("members") or [])
    return None


def _layers_of(tags: Mapping[str, str], geometry: BaseGeometry) -> list[str]:
    polygonal = geometry.geom_type in ("Polygon", "MultiPolygon")
    linear = geometry.geom_type in ("LineString", "MultiLineString")
    highway = tags.get("highway")
    layers = []
    if "building" in tags and polygonal:
        layers.append("buildings")
    if highway in STREET_HIGHWAYS and linear:
        layers.append("streets")
    if highway in PATH_HIGHWAYS and linear:
        layers.append("paths")
    if tags.get("railway") in RAIL_TYPES and linear:
        layers.append("railways")
    if tags.get("natural") == "water" or "waterway" in tags or "water" in tags:
        layers.append("water")
    if tags.get("leisure") in PARK_LEISURE and polygonal:
        layers.append("parks")
    if "landuse" in tags and polygonal:
        layers.append("landuse")
    if any(key in tags for key in POI_KEYS):
        layers.append("pois")
    if "boundary" in tags and (polygonal or linear):
        layers.append("boundaries")
    return layers


def _columns(layer: str, tags: Mapping[str, str]) -> dict[str, Any]:
    if layer == "buildings":
        height, source = building_height(tags)
        return {"building": tags["building"], "height_m": height, "height_source": source}
    if layer in ("streets", "paths"):
        return {"highway": tags["highway"]}
    if layer == "railways":
        return {"railway": tags["railway"]}
    if layer == "water":
        return {"water_kind": tags.get("waterway") or tags.get("water") or tags.get("natural")}
    if layer == "parks":
        return {"leisure": tags["leisure"]}
    if layer == "landuse":
        return {"landuse": tags["landuse"]}
    if layer == "pois":
        category = next(key for key in POI_KEYS if key in tags)
        return {"category": category, "value": tags[category]}
    if layer == "boundaries":
        return {"boundary": tags["boundary"], "admin_level": tags.get("admin_level")}
    return {"tags": json.dumps(dict(tags), sort_keys=True, ensure_ascii=False)}


def _order(element: Mapping[str, Any]) -> tuple[int, int]:
    return TYPE_ORDER.get(str(element.get("type")), 3), int(element.get("id", 0))


def _frame(layer: str, rows: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    columns = ["feature_id", "name", *LAYER_COLUMNS[layer]]
    if not rows:
        empty = {column: [] for column in columns}
        return gpd.GeoDataFrame(empty, geometry=gpd.GeoSeries([], crs=CRS), crs=CRS)
    return gpd.GeoDataFrame(rows, columns=[*columns, "geometry"], geometry="geometry", crs=CRS)


def convert_extract(document: Mapping[str, Any]) -> dict[str, gpd.GeoDataFrame]:
    """The layers of an Overpass extract; see the module docstring."""
    elements = document.get("elements")
    if not isinstance(elements, list):
        raise CityError("the extract has no elements list")
    rows: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
    for element in sorted((e for e in elements if isinstance(e, dict)), key=_order):
        tags = element.get("tags") or {}
        if not tags:
            continue
        geometry = element_geometry(element)
        if geometry is None or geometry.is_empty:
            continue
        if not geometry.is_valid:
            geometry = shapely.make_valid(geometry)
        base = {"feature_id": feature_id(element), "name": tags.get("name")}
        for layer in _layers_of(tags, geometry):
            point_only = layer == "pois" and geometry.geom_type != "Point"
            shape = geometry.representative_point() if point_only else geometry
            rows[layer].append({**base, **_columns(layer, tags), "geometry": shape})
        rows["all_features"].append(
            {**base, **_columns("all_features", tags), "geometry": geometry}
        )
    return {layer: _frame(layer, rows[layer]) for layer in LAYERS}


def write_layers(layers: Mapping[str, gpd.GeoDataFrame], out_dir: Path) -> list[Path]:
    """Write each layer to ``out_dir/<layer>.parquet``; return the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in LAYERS:
        path = out_dir / f"{name}.parquet"
        layers[name].to_parquet(path, index=False)
        written.append(path)
    return written


def load_layers(directory: Path) -> dict[str, gpd.GeoDataFrame]:
    """Read every layer from ``directory``. Raises ``CityError`` naming missing layers."""
    missing = [name for name in LAYERS if not (directory / f"{name}.parquet").is_file()]
    if missing:
        raise CityError(f"{directory}: missing layer(s) {', '.join(missing)}")
    return {name: gpd.read_parquet(directory / f"{name}.parquet") for name in LAYERS}


def layers_sha256(directory: Path) -> str:
    """SHA-256 over the layer files' names and bytes, in layer order.

    Runs and grades of one eval must use the same layers; this hash, recorded in the result,
    says whether they did. It depends on the GeoParquet writer, so it is compared only between
    runs made from the same layer files.
    """
    digest = hashlib.sha256()
    for name in LAYERS:
        path = directory / f"{name}.parquet"
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_graded_city.py -q`
Expected: all pass. Then `uv run ruff check src/geoevals/graded tests/graded_city.py tests/test_graded_city.py && uv run ruff format --check . && uv run pyright src/geoevals/graded tests/graded_city.py tests/test_graded_city.py` with no errors. Tests import helper modules by bare name (`from graded_city import ...`), as they do `claude_fakes`.

- [ ] **Step 6: Commit**

```bash
git add src/geoevals/graded tests/graded_city.py tests/test_graded_city.py
git commit -m "feat: city layers from an Overpass extract for the graded evals"
```

---

### Task 2: City fetch, `evals build-city` and `evals measure-town` (checkpoint 1 tooling)

**Files:**
- Modify: `src/geoevals/data/fetch.py` (add `city_query`, `fetcher_for`; `fetch_overpass` takes a query; `fetch_dataset` dispatches)
- Create: `src/geoevals/graded/towns.py`
- Modify: `src/geoevals/cli.py` (new `evals` command group)
- Test: `tests/test_graded_towns.py`

**Interfaces:**
- Consumes: `convert_extract`, `write_layers`, `LAYERS_DIR` (Task 1); `tests/graded_city.py` (`overpass_document`, `BBOX`, `lonlat`).
- Produces:
  - `geoevals.data.fetch.city_query(bbox: Bbox, snapshot_date: str, timeout_s: int = 900) -> str`
  - `geoevals.data.fetch.fetcher_for(dataset_id: str) -> str | None` (`overpass_city` for `osm_city_*`)
  - `geoevals.data.fetch.fetch_overpass(source_url, bbox, snapshot_date, opener, query: str | None = None)`
  - `geoevals.graded.towns.TownStats` (frozen dataclass: `buildings: int`, `height_share: float`, `street_km: float`, `path_km: float`, `pois: int`, `landuse_share: float`, `water_features: int`, `extract_mb: float`)
  - `measure_layers(layers, bbox: Bbox, extract_bytes: int) -> TownStats`
  - `stats_table(rows: list[tuple[str, TownStats]]) -> str`
  - `fetch_candidate(name, bbox, snapshot_date, out_root, opener=urllib.request.urlopen, source_url=OVERPASS_URL) -> Path`
  - `EXTRACT_FILE = "osm_extract.json"`
  - CLI: `geoevals evals measure-town --name N --bbox B --date D [--out DIR] [--source DIR]`; `geoevals evals build-city DATASET_ID [--manifests DIR] [--source DIR]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graded_towns.py`:

```python
import io
import json
from pathlib import Path

import pytest
from graded_city import BBOX, overpass_document

from geoevals.cli import main
from geoevals.data.fetch import city_query, fetcher_for
from geoevals.graded.city import LAYERS, convert_extract
from geoevals.graded.towns import (
    EXTRACT_FILE,
    TownStats,
    fetch_candidate,
    measure_layers,
    stats_table,
)


def test_city_query_asks_for_every_tagged_feature_at_the_snapshot() -> None:
    query = city_query((10.0, 50.0, 10.1, 50.1), "2026-01-01")
    assert '[date:"2026-01-01T00:00:00Z"]' in query
    assert "[bbox:50.0,10.0,50.1,10.1]" in query
    assert 'node[~"."~"."];' in query
    assert "way;" in query
    assert 'relation["type"="multipolygon"];' in query
    assert query.rstrip().endswith("out geom;")


def test_city_datasets_use_the_city_fetcher() -> None:
    assert fetcher_for("osm_city_example") == "overpass_city"
    assert fetcher_for("human_context_pilot") == "overpass"
    assert fetcher_for("unknown") is None


def test_measure_layers_on_the_synthetic_city() -> None:
    stats = measure_layers(convert_extract(overpass_document()), BBOX, extract_bytes=2_500_000)
    assert stats.buildings == 10
    assert stats.height_share == pytest.approx(0.5)
    assert stats.street_km == pytest.approx(2.1, rel=0.01)
    assert stats.path_km == pytest.approx(0.12, rel=0.01)
    assert stats.pois == 6
    assert stats.water_features == 2
    assert stats.landuse_share == pytest.approx(0.2, rel=0.02)
    assert stats.extract_mb == pytest.approx(2.5)


def test_stats_table_has_one_row_per_town() -> None:
    stats = TownStats(10, 0.5, 2.1, 0.12, 6, 0.2, 2, 2.5)
    table = stats_table([("Alpha", stats), ("Beta", stats)])
    lines = table.splitlines()
    assert lines[0].startswith("| Town | Buildings |")
    assert lines[2].startswith("| Alpha | 10 | 50% |")
    assert len(lines) == 4


def _opener(document: dict):
    def open_(request):
        assert b"out+geom" in request.data
        return io.BytesIO(json.dumps(document).encode("utf-8"))

    return open_


def test_fetch_candidate_writes_extract_and_record(tmp_path: Path) -> None:
    directory = fetch_candidate(
        "Alpha Town", BBOX, "2026-01-01", tmp_path, opener=_opener(overpass_document())
    )
    assert directory == tmp_path / "alpha_town"
    extract = json.loads((directory / EXTRACT_FILE).read_text(encoding="utf-8"))
    assert len(extract["elements"]) == len(overpass_document()["elements"])
    record = json.loads((directory / "fetch.json").read_text(encoding="utf-8"))
    assert record["snapshot_date"] == "2026-01-01"
    assert record["bbox"] == list(BBOX)


def test_measure_town_cli_with_a_fetched_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "alpha"
    source.mkdir()
    (source / EXTRACT_FILE).write_text(json.dumps(overpass_document()), encoding="utf-8")
    bbox = ",".join(str(v) for v in BBOX)
    code = main(
        [
            "evals",
            "measure-town",
            "--name",
            "Alpha",
            "--bbox",
            bbox,
            "--date",
            "2026-01-01",
            "--source",
            str(source),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "| Alpha | 10 |" in out
    assert sorted(p.name for p in (source / "layers").iterdir()) == sorted(
        f"{name}.parquet" for name in LAYERS
    )
```

Run `uv run ruff format tests/test_graded_towns.py`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_towns.py -q`
Expected: `ImportError: cannot import name 'city_query'`.

- [ ] **Step 3: Add the city query and fetcher dispatch to `src/geoevals/data/fetch.py`**

Add to the module docstring's fetcher list:

```text
- ``osm_city_<town>``: every tagged OpenStreetMap feature of a town for the graded evals, from
  the Overpass API at a snapshot date (``city_query``), with full geometry.
```

Below `overpass_query`, add:

```python
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
```

Change `fetch_overpass` to take the query:

```python
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
```

and delete its old first line `query = overpass_query(bbox, snapshot_date)`.

Replace `FETCHERS` and add `fetcher_for`:

```python
FETCHERS = {"human_context_pilot": "overpass"}
"""Dataset ID -> how its asset is downloaded."""
CITY_PREFIX = "osm_city_"
"""Datasets named ``osm_city_<town>`` are whole-town extracts (``city_query``)."""


def fetcher_for(dataset_id: str) -> str | None:
    """How ``dataset_id`` is downloaded: ``overpass``, ``overpass_city`` or None (unknown)."""
    if dataset_id.startswith(CITY_PREFIX):
        return "overpass_city"
    return FETCHERS.get(dataset_id)
```

In `fetch_dataset`, replace the opening check

```python
    if dataset_id not in FETCHERS:
        known = ", ".join(sorted(FETCHERS))
        raise FetchError(f"no fetcher for dataset {dataset_id!r} (known: {known})")
```

with

```python
    kind = fetcher_for(dataset_id)
    if kind is None:
        known = ", ".join([*sorted(FETCHERS), f"{CITY_PREFIX}<town>"])
        raise FetchError(f"no fetcher for dataset {dataset_id!r} (known: {known})")
```

and the fetch line with

```python
    query = city_query(bbox, snapshot_date) if kind == "overpass_city" else None
    query, extract, osm_base = fetch_overpass(
        asset.source_url, bbox, snapshot_date, opener, query=query
    )
```

Run `uv run pytest tests -q -k fetch` to confirm the existing fetch tests still pass. If one asserts the "no fetcher" message, update its expected text to the new `known:` list.

- [ ] **Step 4: Write `src/geoevals/graded/towns.py`**

```python
"""Measure candidate towns for the graded evals (checkpoint 1 of the design).

``geoevals evals measure-town`` fetches a town's extract at a snapshot date into a gitignored
directory (``fetch_candidate``), converts it to layers and prints one row of ``stats_table``:
how much a town offers the five evals (buildings with heights for visibility, paths for
proximity and directions, land use and water for context and barriers) and how large its
extract is.
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
```

- [ ] **Step 5: Add the `evals` command group to `src/geoevals/cli.py`**

In `build_parser`, after the `leaderboard` group, add:

```python
    evals = subparsers.add_parser("evals", help="Graded eval tools (agent-graded, not benchmarks).")
    evals_commands = evals.add_subparsers(dest="evals_command", required=True)
    measure = evals_commands.add_parser(
        "measure-town",
        help="Fetch a candidate town's OpenStreetMap extract at a snapshot date into a gitignored "
        "directory, convert it to layers and print its measurement row.",
    )
    measure.add_argument("--name", required=True, help="Town name, for the table.")
    measure.add_argument(
        "--bbox", required=True, type=parse_bbox, help="min_lon,min_lat,max_lon,max_lat."
    )
    measure.add_argument("--date", required=True, help="Snapshot date, YYYY-MM-DD.")
    measure.add_argument(
        "--out",
        type=Path,
        default=Path("data/raw/town_candidates"),
        help="Parent directory of the fetch (default: data/raw/town_candidates).",
    )
    measure.add_argument(
        "--source",
        type=Path,
        help=f"Measure an existing fetch (a directory with {EXTRACT_FILE}) instead of fetching.",
    )
    build_city = evals_commands.add_parser(
        "build-city",
        help="Convert a fetched city extract (`geoevals data fetch osm_city_<town>`) into "
        "GeoParquet layers in <source>/layers/.",
    )
    build_city.add_argument("dataset_id", help="The city's dataset ID, osm_city_<town>.")
    build_city.add_argument(
        "--manifests",
        type=Path,
        default=DEFAULT_MANIFESTS,
        help=f"Directory of dataset manifests (default: {DEFAULT_MANIFESTS}).",
    )
    build_city.add_argument(
        "--source",
        type=Path,
        help="Directory of the fetched extract (default: the manifest asset's directory).",
    )
```

`parse_bbox` and `DEFAULT_MANIFESTS` are already imported from `geoevals.data.fetch` for `data fetch`; if not, add them to that import. Add imports:

```python
from geoevals.graded.city import LAYERS_DIR, convert_extract, write_layers
from geoevals.graded.towns import EXTRACT_FILE, fetch_candidate, measure_layers, stats_table
```

Add the handlers above `main`:

```python
def _evals_measure_town(name: str, bbox: Bbox, date: str, out: Path, source: Path | None) -> int:
    try:
        directory = source or fetch_candidate(name, bbox, date, out)
        extract_path = directory / EXTRACT_FILE
        layers = convert_extract(json.loads(extract_path.read_text(encoding="utf-8")))
        ensure_ignored(directory / LAYERS_DIR / "buildings.parquet")
        write_layers(layers, directory / LAYERS_DIR)
    except (OSError, ValueError, FetchError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(stats_table([(name, measure_layers(layers, bbox, extract_path.stat().st_size))]))
    return 0


def _evals_build_city(dataset_id: str, manifests: Path, source: Path | None) -> int:
    try:
        path = manifest_path(dataset_id, manifests)
        manifest = load_dataset_manifest(path)
        asset = manifest.assets[0]
        directory = source or Path(os.path.normpath(path.parent / asset.path)).parent
        extract_path = directory / Path(asset.path).name
        layers = convert_extract(json.loads(extract_path.read_text(encoding="utf-8")))
        ensure_ignored(directory / LAYERS_DIR / "buildings.parquet")
        written = write_layers(layers, directory / LAYERS_DIR)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except (OSError, ValueError, FetchError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{directory / LAYERS_DIR}: wrote {len(written)} layers")
    return 0
```

Import what the handlers use and the module lacks: `import os`; from `geoevals.data.fetch` add `Bbox`, `FetchError`, `ensure_ignored`, `manifest_path`; from `geoevals.validation` add `load_dataset_manifest`. `CityError` is a `ValueError`, so it is caught.

In `main`, before the final fallthrough, add:

```python
    if args.command == "evals" and args.evals_command == "measure-town":
        return _evals_measure_town(args.name, args.bbox, args.date, args.out, args.source)
    if args.command == "evals" and args.evals_command == "build-city":
        return _evals_build_city(args.dataset_id, args.manifests, args.source)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_graded_towns.py tests/test_cli.py -q` and the fetch tests (`uv run pytest tests -q -k "fetch or pilot"`).
Expected: all pass. Then `uv run ruff check . && uv run ruff format --check . && uv run pyright`.

- [ ] **Step 7: Commit**

```bash
git add src/geoevals/data/fetch.py src/geoevals/graded/towns.py src/geoevals/cli.py tests/test_graded_towns.py
git commit -m "feat: fetch a whole town and measure candidate towns for the graded evals"
```

After this task the user can run checkpoint 1: `uv run geoevals evals measure-town --name "<town>" --bbox <bbox> --date <date>` for two or three candidates (real Overpass calls; not part of the test suite).

---

### Task 3: Eval specs, tasks and the shared rubric

**Files:**
- Create: `schemas/eval-spec.schema.json`
- Create: `src/geoevals/validation/eval_spec.py`
- Modify: `src/geoevals/validation/validate.py` (validate and load eval specs; `validate_file` dispatch)
- Modify: `src/geoevals/validation/__init__.py` (exports)
- Create: `src/geoevals/graded/spec.py`
- Create: `evals/city/rubric_criteria.yaml`
- Create: `tests/fixtures/graded/sample/eval.yaml`, `tests/fixtures/graded/sample/tasks.jsonl`, `tests/fixtures/graded/sample/manifest.yaml`
- Test: `tests/test_graded_spec.py`

**Interfaces:**
- Consumes: `geoevals.validation.benchmark` (`_SchemaModel`, `Identifier`, `SemVer`, `NonEmptyStr`, `Provenance`), `geoevals.validation.validate.schema_issues`, `load_yaml`, `SpecValidationError`, `ValidationIssue`.
- Produces:
  - `geoevals.validation.eval_spec.EvalSpec`, `EVAL_SCHEMA_VERSION = "1.0.0"`
  - `geoevals.validation.validate_eval_document(document) -> list[ValidationIssue]`, `validate_eval_file(path) -> list[ValidationIssue]`, `load_eval_spec(path) -> EvalSpec`; `detect_document_type` returns `"eval spec"` for a mapping with `rubric_criteria`
  - `geoevals.graded.spec`: `EVAL_SPEC_FILE = "eval.yaml"`, `OUTPUT_SCHEMA: dict`, `ANSWER_STATUSES`, `KEY_TYPES`, models `Location`, `EvalTask`, `Criterion`, `RubricCriteria`; `load_tasks(spec_path: Path, spec: EvalSpec) -> list[EvalTask]`, `load_rubric(spec_path: Path, spec: EvalSpec) -> RubricCriteria`, `spec_file(path: Path, relative: str) -> Path`, `find_eval_spec(root: Path, eval_id: str) -> Path`
  - Fixture eval `tests/fixtures/graded/sample/` (id `sample`, tasks `sample-001` proximity, `sample-002` visibility, `sample-003` closure)

- [ ] **Step 1: Write the rubric criteria**

Create `evals/city/rubric_criteria.yaml`:

```yaml
# The five criteria shared by every graded eval on the city. Each is scored 0 to 4 against its
# anchors; a task's score is the mean of its criteria divided by 4. A task may add anchors of its
# own (`anchors` in tasks.jsonl). Changing this file is a minor version change of every eval.
version: 1.0.0
criteria:
  - id: relations
    title: Spatial relations correct
    description: >-
      The spatial facts the answer states (which feature is nearest, what touches what, what can
      be seen, what lies inside what, which way to go) agree with the reference key.
    anchors:
      "0": The main spatial facts contradict the key, or the answer states none.
      "1": Some facts agree with the key, but the main conclusion contradicts it.
      "2": The main conclusion agrees with the key; several supporting facts do not.
      "3": The main conclusion and most supporting facts agree with the key; one minor fact does not.
      "4": Every spatial fact stated agrees with the key, within the key's precision.
  - id: reasoning
    title: Reasoning sound
    description: >-
      The steps from the data to the conclusion are valid and use the right spatial method:
      walking versus straight-line distance, shared edges versus corner touches, line of sight
      with heights, points on boundaries, turns along a route.
    anchors:
      "0": No reasoning, or reasoning that cannot reach the conclusion.
      "1": The method is wrong for the question, for example straight-line distance where walking distance was asked.
      "2": The method is right but applied with a significant error.
      "3": The method is right and applied correctly, with a minor gap.
      "4": The method is right, applied correctly, and each step follows from the last.
  - id: assumptions
    title: Assumptions and edge cases stated
    description: >-
      The answer states the assumptions it makes (unknown building heights, where a place joins
      the path network, how close to a boundary counts as on it) and the edge cases that could
      change the conclusion.
    anchors:
      "0": Relies on unstated assumptions that change the conclusion.
      "1": Mentions an assumption, but not the one that matters most.
      "2": States the main assumption but not how it affects the conclusion.
      "3": States the main assumptions and their effect; misses a relevant edge case.
      "4": States every assumption that matters, its effect, and the relevant edge cases.
  - id: data_use
    title: Use of the data
    description: >-
      The answer uses the city data that bears on the question, names the features it relies on
      (name and feature_id), and leaves out features that do not bear on it.
    anchors:
      "0": Does not use the data, or uses data that does not bear on the question.
      "1": Uses some relevant data but misses the features that decide the answer.
      "2": Uses the deciding features without naming them, or mixes in irrelevant ones.
      "3": Uses and names the deciding features; misses one relevant layer or attribute.
      "4": Uses and names every feature that decides the answer, and nothing irrelevant.
  - id: clarity
    title: Clear for the stated audience
    description: >-
      The answer suits the audience named in the task: it leads with the conclusion, uses terms
      the audience knows, and is no longer than it needs to be.
    anchors:
      "0": The audience could not act on the answer.
      "1": The conclusion is hard to find, or wrapped in jargon the audience would not know.
      "2": The conclusion is clear, but the explanation does not suit the audience.
      "3": Clear and suited to the audience, with some unnecessary length or jargon.
      "4": Leads with the conclusion, suits the audience, and has nothing unnecessary.
```

- [ ] **Step 2: Write the sample eval fixture**

Create `tests/fixtures/graded/sample/eval.yaml`:

```yaml
schema_version: "1.0.0"
id: sample
version: 0.1.0
title: Sample graded eval on the synthetic city
concept: proximity, visibility and closures
task_statement: >-
  Answer one open-ended question about the city from its OpenStreetMap layers. Explain your
  reasoning for the audience named in the question.
intended_use: Tests of the graded-eval tooling only.
tasks: tasks.jsonl
rubric_criteria: ../../../../evals/city/rubric_criteria.yaml
reference: ../../../../evals/city/reference.py
dataset_manifest: manifest.yaml
answer_word_limit: 4000
license: MIT
provenance:
  authors: [GeoEvals contributors]
  created: 2026-10-11
limitations:
  - A synthetic city made for tests; it says nothing about any model.
```

Create `tests/fixtures/graded/sample/tasks.jsonl` (three lines; `key_sha256` is filled in by Task 7):

```json
{"task_id": "sample-001", "prompt": "I am at the marked point north of the Mill River and need a pharmacy today. Which pharmacy is nearest for me on foot, and is it the one that looks nearest on a map?", "audience": "a resident with no GIS background", "location": {"point": [10.0, 50.000538987], "feature_ids": []}, "key_type": "proximity", "params": {"from": {"point": [10.0, 50.000538987]}, "category": {"amenity": "pharmacy"}, "top": 2}, "rubric": ["relations", "reasoning", "assumptions", "data_use", "clarity"], "anchors": {}, "key_sha256": null, "strata": {"barrier": "river"}}
{"task_id": "sample-002", "prompt": "Standing at the marked point at eye level, which of the Clock Tower, the School and the Library can I see?", "audience": "a city planner", "location": {"point": [10.001397524, 50.001347467], "feature_ids": ["way/400", "way/403", "way/405"]}, "key_type": "visibility", "params": {"observer": {"point": [10.001397524, 50.001347467], "height_m": 1.6}, "targets": ["way/400", "way/403", "way/405"]}, "rubric": ["relations", "reasoning", "assumptions", "data_use", "clarity"], "anchors": {"assumptions": {"4": "Says that the Shed's height is unknown and how that leaves the Library undecided."}}, "key_sha256": null, "strata": {"unknown_heights": true}}
{"task_id": "sample-003", "prompt": "Bridge Road will be closed for repairs. Can I still walk from the marked point to South Pharmacy, and how much longer is the walk?", "audience": "a resident with no GIS background", "location": {"point": [10.0, 50.000538987], "feature_ids": ["way/202", "node/501"]}, "key_type": "closure", "params": {"from": {"point": [10.0, 50.000538987]}, "to": {"feature_id": "node/501"}, "closed": ["way/202"]}, "rubric": ["relations", "reasoning", "assumptions", "data_use", "clarity"], "anchors": {}, "key_sha256": null, "strata": {"closure": "only_crossing"}}
```

The points are `graded_city.ORIGIN` (`lonlat(0, 60)`) and `graded_city.VIEWPOINT` (`lonlat(100, 150)`). Check them: `uv run python -c "import sys; sys.path.insert(0, 'tests'); import graded_city as g; print(g.ORIGIN, g.VIEWPOINT)"` must print `[10.0, 50.000538987] [10.001397524, 50.001347467]`; if it does not, put the printed values in the three lines.

Create `tests/fixtures/graded/sample/manifest.yaml`:

```yaml
schema_version: "1.0.0"
dataset_id: graded_city_synthetic
description: >-
  The synthetic city of the graded-eval tests. tests/graded_city.py generates it at test time;
  no data file is committed.
assets:
  - asset_id: graded_city
    path: ../../../graded_city.py
    citation: GeoEvals contributors (2026). Synthetic city for the graded-eval tests.
    access_date: 2026-10-11
    license: MIT
    attribution: GeoEvals contributors
    redistributable: true
    sha256: SHA256_OF_TESTS_GRADED_CITY_PY
    crs: OGC:CRS84
    bbox: [9.993711142, 49.997754222, 10.006288858, 50.003593245]
    time_range:
      start: 2026-10-11
      end: 2026-10-11
    processing_steps:
      - Generated by tests/graded_city.py (overpass_document, then geoevals.graded.city.convert_extract).
    split: test
    known_limitations:
      - Synthetic, for tests only.
```

Replace `SHA256_OF_TESTS_GRADED_CITY_PY` with the output of `shasum -a 256 tests/graded_city.py | cut -d' ' -f1`, then run `uv run geoevals validate tests/fixtures/graded/sample/manifest.yaml` (expect "valid"). Whenever `tests/graded_city.py` changes later, update this checksum the same way.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_graded_spec.py`:

```python
import copy
import json
import shutil
from pathlib import Path

import pytest

from geoevals.graded.spec import (
    KEY_TYPES,
    OUTPUT_SCHEMA,
    find_eval_spec,
    load_rubric,
    load_tasks,
)
from geoevals.validation import (
    SpecValidationError,
    detect_document_type,
    load_eval_spec,
    validate_eval_document,
)
from geoevals.validation.eval_spec import EvalSpec
from geoevals.validation.validate import load_yaml

REPO = Path(__file__).parent.parent
SAMPLE = REPO / "tests" / "fixtures" / "graded" / "sample" / "eval.yaml"
RUBRIC = REPO / "evals" / "city" / "rubric_criteria.yaml"


def _document() -> dict:
    return copy.deepcopy(load_yaml(SAMPLE))


def test_sample_spec_loads() -> None:
    spec = load_eval_spec(SAMPLE)
    assert (spec.id, spec.version, spec.answer_word_limit) == ("sample", "0.1.0", 4000)
    assert detect_document_type(SAMPLE) == "eval spec"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.pop("rubric_criteria"),
        lambda d: d.update(version="1"),
        lambda d: d.update(answer_word_limit=0),
        lambda d: d.update(extra=True),
        lambda d: d.update(id="Sample"),
        lambda d: d.update(limitations=[]),
    ],
)
def test_schema_and_model_reject_the_same_specs(change) -> None:
    document = _document()
    change(document)
    assert validate_eval_document(document)
    with pytest.raises(ValueError):
        EvalSpec.model_validate(document)


def test_tasks_and_rubric_load() -> None:
    spec = load_eval_spec(SAMPLE)
    tasks = load_tasks(SAMPLE, spec)
    assert [t.task_id for t in tasks] == ["sample-001", "sample-002", "sample-003"]
    assert {t.key_type for t in tasks} <= set(KEY_TYPES)
    rubric = load_rubric(SAMPLE, spec)
    assert [c.id for c in rubric.criteria] == [
        "relations",
        "reasoning",
        "assumptions",
        "data_use",
        "clarity",
    ]
    assert all(set(c.anchors) == {"0", "1", "2", "3", "4"} for c in rubric.criteria)


def _with_tasks(tmp_path: Path, edit) -> Path:
    directory = tmp_path / "sample"
    shutil.copytree(SAMPLE.parent, directory)
    document = load_yaml(directory / "eval.yaml")
    document["rubric_criteria"] = str(RUBRIC)
    (directory / "eval.yaml").write_text(json.dumps(document), encoding="utf-8")
    lines = [json.loads(line) for line in (directory / "tasks.jsonl").read_text().splitlines()]
    edit(lines)
    (directory / "tasks.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))
    return directory / "eval.yaml"


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda ls: ls.append(dict(ls[0])), "duplicate task_id"),
        (lambda ls: ls[0].update(task_id="other-001"), "must start with 'sample-'"),
        (lambda ls: ls[0].update(rubric=["relations", "style"]), "unknown criterion 'style'"),
        (lambda ls: ls[0].update(key_type="guess"), "key_type"),
        (
            lambda ls: ls[1].update(rubric=["relations"], anchors={"clarity": {"4": "x"}}),
            "not in the task's rubric",
        ),
        (lambda ls: ls[1].update(anchors={"assumptions": {"5": "x"}}), "score 5"),
        (lambda ls: ls[0].update(prompt=""), "prompt"),
    ],
)
def test_invalid_tasks_are_reported(tmp_path: Path, edit, message: str) -> None:
    spec_path = _with_tasks(tmp_path, edit)
    with pytest.raises(SpecValidationError, match=message):
        load_tasks(spec_path, load_eval_spec(spec_path))


def test_output_schema_is_status_and_answer() -> None:
    assert OUTPUT_SCHEMA["required"] == ["status", "answer"]
    assert OUTPUT_SCHEMA["properties"]["status"]["enum"][0] == "ok"


def test_find_eval_spec(tmp_path: Path) -> None:
    (tmp_path / "proximity").mkdir()
    (tmp_path / "proximity" / "eval.yaml").write_text("id: proximity\n")
    assert find_eval_spec(tmp_path, "proximity") == tmp_path / "proximity" / "eval.yaml"
```

Run `uv run ruff format tests/test_graded_spec.py`.

- [ ] **Step 4: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_spec.py -q`
Expected: `ModuleNotFoundError: No module named 'geoevals.graded.spec'`.

- [ ] **Step 5: Write the JSON Schema**

Create `schemas/eval-spec.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GeoEvals graded eval spec",
  "description": "An open-ended spatial-reasoning eval whose answers a grading agent scores against a rubric and a reference key computed from data. Graded evals are reported apart from benchmarks.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "id", "version", "title", "concept", "task_statement", "intended_use",
    "tasks", "rubric_criteria", "reference", "dataset_manifest", "answer_word_limit", "license",
    "provenance", "limitations"
  ],
  "properties": {
    "schema_version": {"description": "Version of this schema that the spec targets.", "const": "1.0.0"},
    "id": {"description": "eval ID (lowercase letters, digits, underscores)", "type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
    "version": {
      "description": "semantic version",
      "type": "string",
      "pattern": "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)(\\.(0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*))?(\\+([0-9a-zA-Z-]+(\\.[0-9a-zA-Z-]+)*))?$"
    },
    "title": {"type": "string", "minLength": 1},
    "concept": {"description": "The spatial concept the eval tests.", "type": "string", "minLength": 1},
    "task_statement": {"description": "Sent to the model as the task.", "type": "string", "minLength": 1},
    "intended_use": {"type": "string", "minLength": 1},
    "tasks": {"description": "JSONL task file, relative to the spec.", "type": "string", "minLength": 1},
    "rubric_criteria": {"description": "Shared rubric criteria (YAML), relative to the spec.", "type": "string", "minLength": 1},
    "reference": {"description": "Reference script that computes the keys, relative to the spec.", "type": "string", "minLength": 1},
    "dataset_manifest": {"description": "Dataset manifest of the city, relative to the spec.", "type": "string", "minLength": 1},
    "answer_word_limit": {"description": "Longest answer, in words.", "type": "integer", "minimum": 1},
    "license": {"type": "string", "minLength": 1},
    "provenance": {
      "type": "object",
      "additionalProperties": false,
      "required": ["authors", "created"],
      "properties": {
        "authors": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        "created": {"description": "date (YYYY-MM-DD)", "type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
        "reference_workflow": {"type": "string", "minLength": 1},
        "notes": {"type": "string", "minLength": 1}
      }
    },
    "limitations": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}
  }
}
```

Before writing it, compare the `provenance` block and the `version` pattern with `schemas/benchmark.schema.json`; if the benchmark schema's versions differ in wording or fields, match the benchmark schema so that `Provenance` (reused below) and the JSON Schema agree.

- [ ] **Step 6: Write the Pydantic model and the validation functions**

Create `src/geoevals/validation/eval_spec.py`:

```python
"""Pydantic v2 model mirroring ``schemas/eval-spec.schema.json`` (graded eval specs).

Keep the model and the JSON Schema in step: ``tests/test_graded_spec.py`` asserts that both
reject the same documents.
"""

from typing import Annotated, Literal

from pydantic import Field

from geoevals.validation.benchmark import (
    Identifier,
    NonEmptyStr,
    Provenance,
    SemVer,
    _SchemaModel,
)

EVAL_SCHEMA_VERSION = "1.0.0"


class EvalSpec(_SchemaModel):
    schema_version: Literal["1.0.0"]
    id: Identifier
    version: SemVer
    title: NonEmptyStr
    concept: NonEmptyStr
    task_statement: NonEmptyStr
    intended_use: NonEmptyStr
    tasks: NonEmptyStr
    rubric_criteria: NonEmptyStr
    reference: NonEmptyStr
    dataset_manifest: NonEmptyStr
    answer_word_limit: Annotated[int, Field(ge=1)]
    license: NonEmptyStr
    provenance: Provenance
    limitations: Annotated[list[NonEmptyStr], Field(min_length=1)]
```

In `src/geoevals/validation/validate.py`, import the model (`from geoevals.validation.eval_spec import EvalSpec`) and add after the benchmark functions:

```python
# --- graded eval specs -----------------------------------------------------------------------


def validate_eval_document(document: Any) -> list[ValidationIssue]:
    """Validate a parsed graded eval spec. Returns an empty list when the spec is valid."""
    return schema_issues(document, "eval-spec.schema.json")


def validate_eval_file(path: Path) -> list[ValidationIssue]:
    """Load a YAML graded eval spec and validate it."""
    try:
        document = load_yaml(path)
    except yaml.YAMLError as exc:
        return [ValidationIssue("<root>", f"invalid YAML: {exc}")]
    return validate_eval_document(document)


def load_eval_spec(path: Path) -> EvalSpec:
    """Load and validate a graded eval spec. Raises ``SpecValidationError`` if it is invalid."""
    issues = validate_eval_file(path)
    if issues:
        raise SpecValidationError(path, issues)
    return EvalSpec.model_validate(load_yaml(path))
```

Change the document-type dispatch:

```python
DocumentType = Literal["benchmark spec", "dataset manifest", "run result", "eval spec"]
```

In `detect_document_type`, before the final `return "benchmark spec"`, add:

```python
    if isinstance(document, dict) and "rubric_criteria" in document:
        return "eval spec"
```

and update its docstring ("mappings with ``rubric_criteria`` are graded eval specs"). In `validate_file`, add before the final return:

```python
    if kind == "eval spec":
        return kind, validate_eval_file(path)
```

In `src/geoevals/validation/__init__.py`, import and add to `__all__`: `EVAL_SCHEMA_VERSION`, `EvalSpec`, `load_eval_spec`, `validate_eval_document`, `validate_eval_file`.

- [ ] **Step 7: Write the task and rubric loader**

Create `src/geoevals/graded/spec.py`:

```python
"""Graded eval tasks, the shared rubric, and the answer schema.

An eval is a directory with ``eval.yaml`` (``geoevals.validation.eval_spec.EvalSpec``), a JSONL
task file and pointers to the shared rubric criteria and reference script. A task line:

- ``task_id``: ``<eval id>-NNN``
- ``prompt``, ``audience``: what the model is asked, and for whom it writes
- ``location``: a point and feature IDs, sent to the model with the prompt
- ``key_type``, ``params``: how ``evals/city/reference.py`` computes the task's key; hidden
  from the model
- ``rubric``: the criterion IDs that score the task; ``anchors``: extra anchors per criterion
  and score
- ``key_sha256``: SHA-256 of the key (``geoevals evals regenerate``); null until computed
- ``strata``: labels for slicing results
"""

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator

from geoevals.validation import EvalSpec, SpecValidationError, ValidationIssue
from geoevals.validation.benchmark import Identifier, NonEmptyStr, SemVer, _SchemaModel
from geoevals.validation.validate import load_yaml

EVAL_SPEC_FILE = "eval.yaml"
SCORES = ("0", "1", "2", "3", "4")
ANSWER_STATUSES = ("ok", "needs_clarification", "insufficient_data", "invalid_request")
KEY_TYPES = ("proximity", "containment", "adjacency", "closure", "visibility", "direction")
TASK_ID_PATTERN = r"^[a-z][a-z0-9_]*-[0-9]{3}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "answer"],
    "properties": {
        "status": {
            "description": (
                "ok when you answer the question; needs_clarification, insufficient_data or "
                "invalid_request when it cannot be answered as asked."
            ),
            "enum": list(ANSWER_STATUSES),
        },
        "answer": {
            "description": "Your answer in Markdown, at most the word limit stated in the task.",
            "type": "string",
            "minLength": 1,
        },
    },
}
"""The answer every graded task asks for (status, as in the benchmarks, and Markdown text)."""


class Location(_SchemaModel):
    point: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    feature_ids: list[NonEmptyStr] = Field(default_factory=list)


class EvalTask(_SchemaModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    prompt: NonEmptyStr
    audience: NonEmptyStr
    location: Location
    key_type: Literal["proximity", "containment", "adjacency", "closure", "visibility", "direction"]
    params: dict[str, Any]
    rubric: Annotated[list[Identifier], Field(min_length=1)]
    anchors: dict[Identifier, dict[str, NonEmptyStr]] = Field(default_factory=dict)
    key_sha256: Annotated[str, Field(pattern=SHA256_PATTERN)] | None = None
    strata: dict[Identifier, str | bool | int] = Field(default_factory=dict)


class Criterion(_SchemaModel):
    id: Identifier
    title: NonEmptyStr
    description: NonEmptyStr
    anchors: dict[str, NonEmptyStr]

    @field_validator("anchors")
    @classmethod
    def _every_score(cls, anchors: dict[str, str]) -> dict[str, str]:
        if tuple(sorted(anchors)) != SCORES:
            raise ValueError(f"anchors must cover the scores {', '.join(SCORES)} exactly")
        return anchors


class RubricCriteria(_SchemaModel):
    version: SemVer
    criteria: Annotated[list[Criterion], Field(min_length=1)]

    @field_validator("criteria")
    @classmethod
    def _unique(cls, criteria: list[Criterion]) -> list[Criterion]:
        ids = [c.id for c in criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("criterion IDs must be unique")
        return criteria


def spec_file(spec_path: Path, relative: str) -> Path:
    """A file named in the spec, relative to the spec's directory."""
    return (spec_path.parent / relative).resolve()


def find_eval_spec(root: Path, eval_id: str) -> Path:
    """``<root>/<eval_id>/eval.yaml``."""
    return root / eval_id / EVAL_SPEC_FILE


def _issues(error: ValidationError, prefix: str) -> list[ValidationIssue]:
    return [
        ValidationIssue(f"{prefix}.{'.'.join(map(str, e['loc']))}".rstrip("."), e["msg"])
        for e in error.errors()
    ]


def load_rubric(spec_path: Path, spec: EvalSpec) -> RubricCriteria:
    """The spec's rubric criteria. YAML integer score keys are read as strings."""
    path = spec_file(spec_path, spec.rubric_criteria)
    document = load_yaml(path)
    for criterion in document.get("criteria", []) if isinstance(document, dict) else []:
        if isinstance(criterion, dict) and isinstance(criterion.get("anchors"), dict):
            criterion["anchors"] = {str(k): v for k, v in criterion["anchors"].items()}
    try:
        return RubricCriteria.model_validate(document)
    except ValidationError as exc:
        raise SpecValidationError(path, _issues(exc, "criteria")) from exc


def load_tasks(spec_path: Path, spec: EvalSpec) -> list[EvalTask]:
    """The spec's tasks. Raises ``SpecValidationError`` listing every problem."""
    path = spec_file(spec_path, spec.tasks)
    criteria = {c.id for c in load_rubric(spec_path, spec).criteria}
    tasks: list[EvalTask] = []
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"line {number}"
        try:
            task = EvalTask.model_validate(json.loads(line))
        except json.JSONDecodeError as exc:
            issues.append(ValidationIssue(where, f"invalid JSON: {exc}"))
            continue
        except ValidationError as exc:
            issues.extend(_issues(exc, where))
            continue
        if task.task_id in seen:
            issues.append(ValidationIssue(where, f"duplicate task_id {task.task_id!r}"))
        seen.add(task.task_id)
        if not task.task_id.startswith(f"{spec.id}-"):
            issues.append(ValidationIssue(where, f"task_id must start with '{spec.id}-'"))
        for criterion in task.rubric:
            if criterion not in criteria:
                issues.append(ValidationIssue(where, f"unknown criterion {criterion!r}"))
        for criterion, anchors in task.anchors.items():
            if criterion not in task.rubric:
                issues.append(
                    ValidationIssue(where, f"anchors for {criterion!r}, not in the task's rubric")
                )
            for score in anchors:
                if score not in SCORES:
                    issues.append(ValidationIssue(where, f"anchor for score {score}, not 0 to 4"))
        tasks.append(task)
    if not tasks and not issues:
        issues.append(ValidationIssue("<root>", "no tasks"))
    if issues:
        raise SpecValidationError(path, issues)
    return tasks
```

`SpecValidationError`'s message joins every issue, so `pytest.raises(..., match=...)` finds each text. The test for `prompt=""` matches the Pydantic issue path `line 1.prompt`.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_graded_spec.py tests/test_benchmark_validation.py tests/test_cli.py -q`
Expected: all pass. Then `uv run ruff check . && uv run ruff format --check . && uv run pyright`.

- [ ] **Step 9: Commit**

```bash
git add schemas/eval-spec.schema.json src/geoevals/validation src/geoevals/graded/spec.py evals/city/rubric_criteria.yaml tests/fixtures/graded tests/test_graded_spec.py
git commit -m "feat: graded eval specs, tasks and the shared rubric"
```

---

### Task 4: Reference keys, part 1: the walking network, proximity and containment

**Files:**
- Create: `evals/city/reference.py`
- Create: `src/geoevals/graded/reference.py`
- Test: `tests/test_graded_reference.py`

**Interfaces:**
- Consumes: `convert_extract` (Task 1), `load_eval_spec` (Task 3), `tests/graded_city.py`.
- Produces:
  - `evals/city/reference.py`: `compute_key(key_type: str, params: Mapping[str, Any], layers: Mapping[str, gpd.GeoDataFrame]) -> dict[str, Any]`, `class KeyComputationError(ValueError)`, `class WalkGraph` (`WalkGraph(layers, closed=frozenset())`, `.route(start: Point, end: Point) -> dict` with `reachable`, `walking_m`, `snap_from_m`, `snap_to_m`, `nodes`, and `reason` when unreachable), `MAX_SNAP_M = 100.0`, key functions `proximity_key`, `containment_key` (this task) and `adjacency_key`, `closure_key`, `visibility_key`, `direction_key` (Tasks 5 and 6), `KEY_FUNCTIONS: dict[str, Callable]`
  - `geoevals.graded.reference.ComputeKey` (type alias), `load_reference(spec_path: Path, spec: EvalSpec) -> ComputeKey`, `class ReferenceLoadError(RuntimeError)`

Every key is plain JSON (dicts, lists, strings, numbers, booleans, null), floats rounded to 0.1, and holds no `nodes` or other internal fields.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graded_reference.py`:

```python
from pathlib import Path

import pytest
from graded_city import ORIGIN, lonlat, overpass_document

from geoevals.graded.city import convert_extract
from geoevals.graded.reference import load_reference
from geoevals.validation import load_eval_spec

REPO = Path(__file__).parent.parent
SAMPLE = REPO / "tests" / "fixtures" / "graded" / "sample" / "eval.yaml"
LAYERS = convert_extract(overpass_document())
compute_key = load_reference(SAMPLE, load_eval_spec(SAMPLE))
module = compute_key.__globals__  # the reference module's namespace


def test_proximity_separates_straight_line_and_walking() -> None:
    key = compute_key(
        "proximity",
        {"from": {"point": ORIGIN}, "category": {"amenity": "pharmacy"}, "top": 2},
        LAYERS,
    )
    assert key["straight_line_nearest"] == "node/501"
    assert key["walking_nearest"] == "node/500"
    assert key["same_nearest"] is False
    by_walk = {row["feature_id"]: row for row in key["by_walking"]}
    assert by_walk["node/500"]["walking_m"] == pytest.approx(330, rel=0.01)
    assert by_walk["node/501"]["walking_m"] == pytest.approx(880, rel=0.01)
    by_line = {row["feature_id"]: row for row in key["by_straight_line"]}
    assert by_line["node/501"]["straight_line_m"] == pytest.approx(120, rel=0.01)
    assert key["unreachable"] == []


def test_keys_round_floats_to_one_decimal() -> None:
    key = compute_key(
        "proximity", {"from": {"point": ORIGIN}, "category": {"amenity": "pharmacy"}}, LAYERS
    )

    def floats(value):
        if isinstance(value, float):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from floats(v)
        elif isinstance(value, list):
            for v in value:
                yield from floats(v)

    assert all(round(v, 1) == v for v in floats(key))


def test_unreachable_places_are_reported() -> None:
    far = lonlat(0, 1000)  # over 700 m from every network vertex
    key = compute_key(
        "proximity", {"from": {"point": far}, "category": {"amenity": "pharmacy"}}, LAYERS
    )
    assert key["walking_nearest"] is None
    assert key["unreachable"] == ["node/500", "node/501"]
    route = module["WalkGraph"](LAYERS).route(module["Point"](*far), module["Point"](*ORIGIN))
    assert route["reachable"] is False and route["reason"] == "too_far_from_network"


def test_proximity_without_candidates_is_an_error() -> None:
    with pytest.raises(module["KeyComputationError"], match="no feature tagged"):
        compute_key(
            "proximity", {"from": {"point": ORIGIN}, "category": {"amenity": "bank"}}, LAYERS
        )


def test_containment_points_inside_and_on_boundaries() -> None:
    key = compute_key(
        "containment",
        {
            "points": [
                {"label": "P1", "point": lonlat(0, 150)},
                {"label": "P2", "point": lonlat(-50, 200)},
                {"label": "P3", "point": lonlat(350, -150)},
            ],
            "features": ["way/410", "way/400"],
        },
        LAYERS,
    )
    assert key["points"]["P1"] == {
        "inside": ["relation/702"],
        "on_boundary": ["relation/700", "relation/701"],
    }
    assert key["points"]["P2"] == {"inside": ["relation/700", "relation/702"], "on_boundary": []}
    assert key["points"]["P3"] == {"inside": ["relation/701"], "on_boundary": []}
    assert key["features"]["way/410"] == {"within": ["relation/700"], "overlaps": [], "touches": []}
    assert key["features"]["way/400"] == {
        "within": ["relation/701"],
        "overlaps": ["relation/702"],
        "touches": [],
    }


def test_unknown_key_type_and_feature_are_errors() -> None:
    with pytest.raises(module["KeyComputationError"], match="unknown key type"):
        compute_key("guess", {}, LAYERS)
    with pytest.raises(module["KeyComputationError"], match="no feature 'way/1'"):
        compute_key("containment", {"features": ["way/1"]}, LAYERS)
```

Run `uv run ruff format tests/test_graded_reference.py`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_reference.py -q`
Expected: `ModuleNotFoundError: No module named 'geoevals.graded.reference'`.

- [ ] **Step 3: Write the loader**

Create `src/geoevals/graded/reference.py`:

```python
"""Load an eval's reference script (``reference`` in ``eval.yaml``).

The script defines ``compute_key(key_type, params, layers) -> dict``. It is loaded from its
file, as a benchmark's ``reference.py`` is (``geoevals.regenerate``), so that it lives with the
evals it serves instead of in the package.
"""

import importlib.util
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import geopandas as gpd

from geoevals.graded.spec import spec_file
from geoevals.validation import EvalSpec

ComputeKey = Callable[[str, Mapping[str, Any], Mapping[str, gpd.GeoDataFrame]], dict[str, Any]]


class ReferenceLoadError(RuntimeError):
    """The reference script cannot be loaded or has no ``compute_key``."""


def load_reference(spec_path: Path, spec: EvalSpec) -> ComputeKey:
    path = spec_file(spec_path, spec.reference)
    if not path.is_file():
        raise ReferenceLoadError(f"{path}: reference script not found")
    module_spec = importlib.util.spec_from_file_location(f"geoevals_eval_reference_{spec.id}", path)
    if module_spec is None or module_spec.loader is None:
        raise ReferenceLoadError(f"{path}: cannot be loaded as a Python module")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    compute = getattr(module, "compute_key", None)
    if not callable(compute):
        raise ReferenceLoadError(f"{path}: defines no compute_key(key_type, params, layers)")
    return cast(ComputeKey, compute)
```

- [ ] **Step 4: Write the reference script (helpers, proximity, containment)**

Create `evals/city/reference.py`:

```python
"""Reference keys of the graded evals on the city, computed from its layers.

``compute_key(key_type, params, layers)`` returns the key of one task: the facts a correct answer
must agree with. The grader sees the key; the model never does. Keys are computed, never written
by hand (``geoevals evals regenerate``), and are not committed (OpenStreetMap-derived data).

Distances are geodesic meters on WGS 84. Walking distances use the ``streets`` and ``paths``
layers as an undirected graph whose nodes are the lines' shared vertices; a place joins the
network at its nearest vertex, and a place more than ``MAX_SNAP_M`` from every vertex is
unreachable. Local geometry (shared edges, lines of sight, distance to a boundary) is measured in
an azimuthal equidistant projection centered on the features involved. Every float in a key is
rounded to 0.1 (meters, degrees), so the key and its hash are the same on every platform.

Key types and their params:

- ``proximity``: ``from`` (a place), ``category`` (one tag, ``{key: value}``), ``top`` (default 3)
- ``containment``: ``points`` (``[{label, point}]``), ``features`` (feature IDs), ``layers``
  (default ``["boundaries"]``), ``boundary_tolerance_m`` (default 1, at most 50)
- ``adjacency``: ``features`` (two or more feature IDs), ``layer`` (default ``buildings``),
  ``edge_min_m`` (default 0.5)
- ``closure``: ``from``, ``to`` (places), ``closed`` (feature IDs of streets or paths)
- ``visibility``: ``observer`` (a place and ``height_m``, the eye height above the ground, or
  above the roof when the place is a building), ``targets`` (building feature IDs)
- ``direction``: ``from``, ``to`` (places), ``landmark_radius_m`` (default 30),
  ``turn_threshold_deg`` (default 30)

A place is ``{"point": [lon, lat]}`` or ``{"feature_id": "way/1"}`` (the feature's
representative point).
"""

import itertools
import json
import math
from collections.abc import Callable, Mapping
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from pyproj import CRS, Geod, Transformer
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

WGS84 = "OGC:CRS84"
GEOD = Geod(ellps="WGS84")
MAX_SNAP_M = 100.0
NEAR_DEG = 0.001
"""Prefilter: features farther than this (about 70 to 110 m) cannot be within a tolerance."""
NETWORK_LAYERS = ("streets", "paths")
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

Layers = Mapping[str, gpd.GeoDataFrame]
Node = tuple[float, float]


class KeyComputationError(ValueError):
    """The params do not describe a computable key (an unknown feature, a bad place)."""


# --- helpers ---------------------------------------------------------------------------------


def _rounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 1) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    return value


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _row(layers: Layers, feature_id: str, layer: str = "all_features") -> Any:
    frame = layers[layer]
    match = frame[frame["feature_id"] == feature_id]
    if match.empty:
        raise KeyComputationError(f"no feature {feature_id!r} in layer {layer!r}")
    return match.iloc[0]


def _place(layers: Layers, place: Mapping[str, Any]) -> Point:
    if "point" in place:
        lon, lat = place["point"]
        return Point(float(lon), float(lat))
    if "feature_id" in place:
        return _row(layers, place["feature_id"]).geometry.representative_point()
    raise KeyComputationError(f"a place needs 'point' or 'feature_id', got {dict(place)!r}")


def _distance_m(a: Point, b: Point) -> float:
    return float(GEOD.inv(a.x, a.y, b.x, b.y)[2])


def _aeqd(center: Point) -> CRS:
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={center.y} +lon_0={center.x} +datum=WGS84 +units=m +no_defs +type=crs"
    )


def _projector(center: Point) -> Callable[[BaseGeometry], BaseGeometry]:
    transformer = Transformer.from_crs(WGS84, _aeqd(center), always_xy=True)

    def project(geometry: BaseGeometry) -> BaseGeometry:
        return shapely.transform(
            geometry, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
        )

    return project


def _lines(geometry: BaseGeometry) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    return []


class WalkGraph:
    """The walking network of the ``streets`` and ``paths`` layers, without ``closed`` features.

    Each edge keeps its geodesic ``length``, its ``feature_id`` and its street ``name``.
    """

    def __init__(self, layers: Layers, closed: frozenset[str] = frozenset()) -> None:
        self.graph = nx.Graph()
        for layer in NETWORK_LAYERS:
            frame = layers[layer]
            for feature_id, name, geometry in zip(
                frame["feature_id"], frame["name"], frame.geometry, strict=True
            ):
                if feature_id in closed:
                    continue
                for line in _lines(geometry):
                    for a, b in itertools.pairwise(line.coords):
                        length = float(GEOD.inv(a[0], a[1], b[0], b[1])[2])
                        if length == 0:
                            continue
                        u, v = (a[0], a[1]), (b[0], b[1])
                        existing = self.graph.get_edge_data(u, v)
                        if existing is None or existing["length"] > length:
                            self.graph.add_edge(
                                u, v, length=length, feature_id=feature_id, name=_text(name)
                            )
        self._nodes: list[Node] = list(self.graph.nodes)
        self._lons = np.array([node[0] for node in self._nodes])
        self._lats = np.array([node[1] for node in self._nodes])

    def snap(self, point: Point) -> tuple[Node | None, float]:
        """The nearest network vertex and its distance in meters."""
        if not self._nodes:
            return None, math.inf
        n = len(self._nodes)
        _, _, distances = GEOD.inv(np.full(n, point.x), np.full(n, point.y), self._lons, self._lats)
        index = int(np.argmin(distances))
        return self._nodes[index], float(distances[index])

    def route(self, start: Point, end: Point) -> dict[str, Any]:
        """The shortest walk from ``start`` to ``end``, snap distances included."""
        a, snap_a = self.snap(start)
        b, snap_b = self.snap(end)
        result: dict[str, Any] = {
            "reachable": False,
            "walking_m": None,
            "snap_from_m": snap_a if math.isfinite(snap_a) else None,
            "snap_to_m": snap_b if math.isfinite(snap_b) else None,
            "nodes": [],
        }
        if a is None or b is None:
            return {**result, "reason": "no_network"}
        if snap_a > MAX_SNAP_M or snap_b > MAX_SNAP_M:
            return {**result, "reason": "too_far_from_network"}
        try:
            nodes = nx.shortest_path(self.graph, a, b, weight="length")
        except nx.NetworkXNoPath:
            return {**result, "reason": "not_connected"}
        length = sum(self.graph.edges[u, v]["length"] for u, v in itertools.pairwise(nodes))
        return {**result, "reachable": True, "walking_m": snap_a + length + snap_b, "nodes": nodes}


# --- proximity -------------------------------------------------------------------------------


def _tagged(layers: Layers, category: Mapping[str, str]) -> list[tuple[str, str | None, Point]]:
    if len(category) != 1:
        raise KeyComputationError("category must hold one tag, as {key: value}")
    ((key, value),) = category.items()
    frame = layers["all_features"]
    needle = json.dumps({key: value}, ensure_ascii=False)[1:-1]  # '"amenity": "pharmacy"'
    candidates = frame[frame["tags"].str.contains(needle, regex=False)]
    found = []
    for feature_id, name, tags, geometry in zip(
        candidates["feature_id"],
        candidates["name"],
        candidates["tags"],
        candidates.geometry,
        strict=True,
    ):
        if json.loads(tags).get(key) == value:
            found.append((feature_id, _text(name), geometry.representative_point()))
    return found


def proximity_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    origin = _place(layers, params["from"])
    candidates = _tagged(layers, params["category"])
    if not candidates:
        raise KeyComputationError(f"no feature tagged {dict(params['category'])}")
    top = int(params.get("top", 3))
    graph = WalkGraph(layers)
    rows = []
    for feature_id, name, point in candidates:
        route = graph.route(origin, point)
        rows.append(
            {
                "feature_id": feature_id,
                "name": name,
                "straight_line_m": _distance_m(origin, point),
                "walking_m": route["walking_m"],
            }
        )
    by_line = sorted(rows, key=lambda r: (r["straight_line_m"], r["feature_id"]))
    by_walk = sorted(
        (r for r in rows if r["walking_m"] is not None),
        key=lambda r: (r["walking_m"], r["feature_id"]),
    )
    return {
        "straight_line_nearest": by_line[0]["feature_id"],
        "walking_nearest": by_walk[0]["feature_id"] if by_walk else None,
        "same_nearest": bool(by_walk) and by_walk[0]["feature_id"] == by_line[0]["feature_id"],
        "by_straight_line": by_line[:top],
        "by_walking": by_walk[:top],
        "unreachable": sorted(r["feature_id"] for r in rows if r["walking_m"] is None),
    }


# --- containment -----------------------------------------------------------------------------


def _polygons(layers: Layers, names: list[str]) -> list[tuple[str, BaseGeometry]]:
    found = []
    for name in names:
        frame = layers[name]
        for feature_id, geometry in zip(frame["feature_id"], frame.geometry, strict=True):
            if geometry.geom_type in ("Polygon", "MultiPolygon"):
                found.append((feature_id, geometry))
    return found


def containment_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    tolerance = float(params.get("boundary_tolerance_m", 1.0))
    if tolerance > 50:
        raise KeyComputationError("boundary_tolerance_m must be at most 50")
    polygons = _polygons(layers, list(params.get("layers", ["boundaries"])))
    points: dict[str, Any] = {}
    for entry in params.get("points", []):
        point = Point(*map(float, entry["point"]))
        project = _projector(point)
        local_point = project(point)
        inside, on_boundary = [], []
        for feature_id, polygon in polygons:
            if polygon.distance(point) > NEAR_DEG:
                continue
            local = project(polygon)
            if local.boundary.distance(local_point) <= tolerance:
                on_boundary.append(feature_id)
            elif local.contains(local_point):
                inside.append(feature_id)
        points[entry["label"]] = {"inside": sorted(inside), "on_boundary": sorted(on_boundary)}
    features: dict[str, Any] = {}
    for feature_id in params.get("features", []):
        geometry = _row(layers, feature_id).geometry
        within, overlaps, touches = [], [], []
        for other_id, polygon in polygons:
            if other_id == feature_id or not polygon.intersects(geometry):
                continue
            if polygon.covers(geometry):
                within.append(other_id)
            elif polygon.relate_pattern(geometry, "T********"):
                overlaps.append(other_id)
            else:
                touches.append(other_id)
        features[feature_id] = {
            "within": sorted(within),
            "overlaps": sorted(overlaps),
            "touches": sorted(touches),
        }
    return {"points": points, "features": features}


# --- dispatch --------------------------------------------------------------------------------

KEY_FUNCTIONS: dict[str, Callable[[Mapping[str, Any], Layers], dict[str, Any]]] = {
    "proximity": proximity_key,
    "containment": containment_key,
}


def compute_key(key_type: str, params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    """The key of one task, floats rounded to 0.1. Raises ``KeyComputationError``."""
    function = KEY_FUNCTIONS.get(key_type)
    if function is None:
        known = ", ".join(sorted(KEY_FUNCTIONS))
        raise KeyComputationError(f"unknown key type {key_type!r} (known: {known})")
    try:
        return _rounded(function(params, layers))
    except KeyError as exc:
        raise KeyComputationError(f"{key_type} params lack {exc}") from exc
```

Run `uv run ruff format evals/city/reference.py && uv run ruff check evals/city/reference.py`. Pyright does not check `evals/` (its `include` is `src` and `tests`), as for the benchmarks' reference scripts.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_graded_reference.py -q`
Expected: all pass. P1 at (0, 150) lies on the West/East line, so both districts are `on_boundary`; the Clock Tower (x 90 to 110) crosses the conservation area's east edge (x = 100), so it `overlaps` it.

- [ ] **Step 6: Commit**

```bash
git add evals/city/reference.py src/geoevals/graded/reference.py tests/test_graded_reference.py
git commit -m "feat: reference keys for proximity and containment on the city layers"
```

---

### Task 5: Reference keys, part 2: adjacency and closures

**Files:**
- Modify: `evals/city/reference.py` (add `adjacency_key`, `closure_key`; register them)
- Test: `tests/test_graded_reference.py` (append)

**Interfaces:**
- Consumes: `WalkGraph`, `_row`, `_place`, `_projector`, `KeyComputationError` (Task 4).
- Produces: key types `adjacency` (`{"pairs": [{"a", "b", "relation", "shared_m"}]}`, relation one of `shared_edge`, `corner`, `overlap`, `disjoint`) and `closure` (`{"closed", "before", "after", "disconnected_by_closure", "added_m"}`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_graded_reference.py`:

```python
def test_adjacency_tells_shared_walls_from_corners() -> None:
    key = compute_key(
        "adjacency", {"features": ["way/410", "way/411", "way/412", "way/413"]}, LAYERS
    )
    relations = {(p["a"], p["b"]): p for p in key["pairs"]}
    assert relations["way/410", "way/411"]["relation"] == "shared_edge"
    assert relations["way/410", "way/411"]["shared_m"] == pytest.approx(20, abs=0.5)
    assert relations["way/411", "way/412"]["relation"] == "corner"
    assert relations["way/410", "way/412"]["relation"] == "disjoint"
    assert relations["way/412", "way/413"]["relation"] == "disjoint"
    assert len(key["pairs"]) == 6


def test_adjacency_needs_two_features() -> None:
    with pytest.raises(module["KeyComputationError"], match="at least two"):
        compute_key("adjacency", {"features": ["way/410"]}, LAYERS)


def test_closing_the_only_bridge_disconnects_the_banks() -> None:
    key = compute_key(
        "closure",
        {"from": {"point": ORIGIN}, "to": {"feature_id": "node/501"}, "closed": ["way/202"]},
        LAYERS,
    )
    assert key["before"]["reachable"] is True
    assert key["before"]["walking_m"] == pytest.approx(880, rel=0.01)
    assert key["after"] == {"reachable": False, "walking_m": None, "reason": "not_connected"}
    assert key["disconnected_by_closure"] is True
    assert key["added_m"] is None


def test_closing_a_side_path_adds_no_distance() -> None:
    key = compute_key(
        "closure",
        {"from": {"point": ORIGIN}, "to": {"feature_id": "node/500"}, "closed": ["way/211"]},
        LAYERS,
    )
    assert key["disconnected_by_closure"] is False
    assert key["added_m"] == 0.0


def test_closure_rejects_features_that_are_not_streets_or_paths() -> None:
    with pytest.raises(module["KeyComputationError"], match="not streets or paths"):
        compute_key(
            "closure",
            {"from": {"point": ORIGIN}, "to": {"feature_id": "node/501"}, "closed": ["way/400"]},
            LAYERS,
        )
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_reference.py -q -k "adjacency or closure or closing"`
Expected: FAIL with `unknown key type 'adjacency'`.

- [ ] **Step 3: Add the key functions**

In `evals/city/reference.py`, add above `# --- dispatch`:

```python
# --- adjacency -------------------------------------------------------------------------------

SNAP_M = 0.05
"""Walls drawn 5 cm apart still count as touching."""
OVERLAP_M2 = 0.01


def adjacency_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    layer = params.get("layer", "buildings")
    edge_min = float(params.get("edge_min_m", 0.5))
    ids = list(params["features"])
    if len(ids) < 2:
        raise KeyComputationError("adjacency needs at least two features")
    geometries = {feature_id: _row(layers, feature_id, layer).geometry for feature_id in ids}
    project = _projector(shapely.union_all(list(geometries.values())).centroid)
    local = {feature_id: project(geometry) for feature_id, geometry in geometries.items()}
    pairs = []
    for a, b in itertools.combinations(ids, 2):
        ga, gb = local[a], local[b]
        shared = ga.boundary.intersection(gb.buffer(SNAP_M)).length
        if ga.intersection(gb).area > OVERLAP_M2:
            relation = "overlap"
        elif ga.distance(gb) > SNAP_M:
            relation = "disjoint"
        elif shared >= edge_min:
            relation = "shared_edge"
        else:
            relation = "corner"
        pairs.append({"a": a, "b": b, "relation": relation, "shared_m": shared})
    return {"pairs": pairs}


# --- closures --------------------------------------------------------------------------------


def _route_summary(route: Mapping[str, Any]) -> dict[str, Any]:
    summary = {"reachable": route["reachable"], "walking_m": route["walking_m"]}
    if "reason" in route:
        summary["reason"] = route["reason"]
    return summary


def closure_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    start, end = _place(layers, params["from"]), _place(layers, params["to"])
    closed = frozenset(params["closed"])
    network = set(layers["streets"]["feature_id"]) | set(layers["paths"]["feature_id"])
    unknown = sorted(closed - network)
    if unknown:
        raise KeyComputationError(f"closed features are not streets or paths: {unknown}")
    before = WalkGraph(layers).route(start, end)
    after = WalkGraph(layers, closed).route(start, end)
    both = before["reachable"] and after["reachable"]
    return {
        "closed": sorted(closed),
        "before": _route_summary(before),
        "after": _route_summary(after),
        "disconnected_by_closure": before["reachable"] and not after["reachable"],
        "added_m": after["walking_m"] - before["walking_m"] if both else None,
    }
```

Register them in `KEY_FUNCTIONS`:

```python
KEY_FUNCTIONS: dict[str, Callable[[Mapping[str, Any], Layers], dict[str, Any]]] = {
    "proximity": proximity_key,
    "containment": containment_key,
    "adjacency": adjacency_key,
    "closure": closure_key,
}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_graded_reference.py -q`
Expected: all pass. The shared wall measures 20 m plus up to 0.1 m from the 5 cm buffer at each end, hence `abs=0.5`. Then `uv run ruff check evals && uv run ruff format --check evals`.

- [ ] **Step 5: Commit**

```bash
git add evals/city/reference.py tests/test_graded_reference.py
git commit -m "feat: reference keys for adjacency and street closures"
```

---

### Task 6: Reference keys, part 3: visibility and directions

**Files:**
- Modify: `evals/city/reference.py` (add `visibility_key`, `direction_key`; register them)
- Test: `tests/test_graded_reference.py` (append)

**Interfaces:**
- Consumes: Task 4 helpers.
- Produces: key types `visibility` (`{"observer_height_m", "targets": {id: {"visible": true|false|null, "distance_m", "target_height_m", "blocked_by", "unknown_height_on_path"}}}`) and `direction` (`{"bearing_deg", "compass", "straight_line_m", "reachable", "walking_m", "steps": [{"street", "distance_m", "turn", "landmark"}]}`, plus `reason` when unreachable).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_graded_reference.py`:

```python
from graded_city import VIEWPOINT  # noqa: E402


def test_visibility_uses_heights_and_flags_unknown_ones() -> None:
    key = compute_key(
        "visibility",
        {
            "observer": {"point": VIEWPOINT, "height_m": 1.6},
            "targets": ["way/400", "way/403", "way/405"],
        },
        LAYERS,
    )
    assert key["observer_height_m"] == 1.6
    tower, school, library = (key["targets"][t] for t in ("way/400", "way/403", "way/405"))
    assert tower["visible"] is True and tower["blocked_by"] == []
    assert tower["distance_m"] == pytest.approx(150, rel=0.01)
    assert school["visible"] is False and school["blocked_by"] == ["way/402"]
    assert library["visible"] is None
    assert library["unknown_height_on_path"] == ["way/404"]
    assert library["target_height_m"] == 12.0


def test_visibility_from_a_roof() -> None:
    key = compute_key(
        "visibility",
        {"observer": {"feature_id": "way/402", "height_m": 1.6}, "targets": ["way/403"]},
        LAYERS,
    )
    assert key["observer_height_m"] == 26.6
    assert key["targets"]["way/403"]["visible"] is True


def test_directions_give_turns_landmarks_and_a_misleading_bearing() -> None:
    key = compute_key(
        "direction", {"from": {"point": ORIGIN}, "to": {"feature_id": "node/501"}}, LAYERS
    )
    assert key["compass"] == "S"
    assert key["walking_m"] == pytest.approx(880, rel=0.01)
    steps = [(s["street"], s["turn"]) for s in key["steps"]]
    assert steps == [
        (None, "start"),
        ("North Street", "right"),
        ("Bridge Road", "right"),
        ("South Street", "right"),
        (None, "right"),
    ]
    assert [round(s["distance_m"] / 10) * 10 for s in key["steps"]] == [40, 300, 200, 300, 40]
    landmarks = [s["landmark"] and s["landmark"]["feature_id"] for s in key["steps"]]
    assert landmarks == [None, None, "node/502", None, "node/504"]


def test_directions_without_a_route_say_why() -> None:
    key = compute_key(
        "direction", {"from": {"point": lonlat(0, 1000)}, "to": {"feature_id": "node/501"}}, LAYERS
    )
    assert key["reachable"] is False
    assert key["reason"] == "too_far_from_network"
    assert key["steps"] == []
```

Move the `from graded_city import VIEWPOINT` into the file's top import line (`from graded_city import ORIGIN, VIEWPOINT, lonlat, overpass_document`) instead of the mid-file import, then run `uv run ruff format tests/test_graded_reference.py`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_reference.py -q -k "visibility or directions"`
Expected: FAIL with `unknown key type 'visibility'`.

- [ ] **Step 3: Add the key functions**

In `evals/city/reference.py`, add above `# --- dispatch`:

```python
# --- visibility ------------------------------------------------------------------------------


def _height(row: Any) -> float | None:
    value = row["height_m"]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def _coordinates(geometry: BaseGeometry) -> list[tuple[float, ...]]:
    if hasattr(geometry, "geoms"):
        return [c for part in geometry.geoms for c in _coordinates(part)]
    return list(geometry.coords)


def visibility_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    """Lines of sight from an eye point to the top of each target building.

    A building on the line blocks it when its height exceeds the line's height where the line
    crosses it (the lower of the entry and exit heights, as the line is straight). A building of
    unknown height on the line leaves the target undecided (``visible`` null). A target of
    unknown height is sighted at ground level.
    """
    observer = params["observer"]
    eye = float(observer.get("height_m", 1.6))
    observer_id = observer.get("feature_id")
    origin = _place(layers, observer)
    observer_height = eye
    if observer_id is not None:
        observer_height += _height(_row(layers, observer_id, "buildings")) or 0.0
    project = _projector(origin)
    buildings = layers["buildings"].to_crs(_aeqd(origin))
    index = buildings.sindex
    eye_point = project(origin)
    targets: dict[str, Any] = {}
    for target_id in params["targets"]:
        target = _row(layers, target_id, "buildings")
        target_height = _height(target)
        top = target_height if target_height is not None else 0.0
        sight = LineString([eye_point, project(target.geometry.representative_point())])
        length = sight.length
        blocked, unknown = [], []
        for position in index.query(sight, predicate="intersects"):
            other = buildings.iloc[int(position)]
            if other["feature_id"] in (target_id, observer_id):
                continue
            crossing = other.geometry.intersection(sight)
            if crossing.is_empty:
                continue
            along = [sight.project(Point(c[0], c[1])) for c in _coordinates(crossing)]
            lowest = min(
                observer_height + (top - observer_height) * d / length
                for d in (min(along), max(along))
            )
            height = _height(other)
            if height is None:
                unknown.append(other["feature_id"])
            elif height > lowest:
                blocked.append(other["feature_id"])
        visible = False if blocked else (None if unknown else True)
        targets[target_id] = {
            "visible": visible,
            "distance_m": length,
            "target_height_m": target_height,
            "blocked_by": sorted(blocked),
            "unknown_height_on_path": sorted(unknown),
        }
    return {"observer_height_m": observer_height, "targets": targets}


# --- directions ------------------------------------------------------------------------------


def _bearing(a: Node, b: Node) -> float:
    return float(GEOD.inv(a[0], a[1], b[0], b[1])[0]) % 360


def _turn(before: float, after: float, threshold: float) -> str:
    delta = (after - before + 540) % 360 - 180
    if delta > threshold:
        return "right"
    if delta < -threshold:
        return "left"
    return "straight"


def _landmark(pois: gpd.GeoDataFrame, node: Point, radius: float) -> dict[str, Any] | None:
    best: tuple[float, str, str | None] | None = None
    for feature_id, name, geometry in zip(
        pois["feature_id"], pois["name"], pois.geometry, strict=True
    ):
        if geometry.distance(node) > NEAR_DEG:
            continue
        distance = _distance_m(node, geometry)
        if distance <= radius and (best is None or (distance, feature_id) < best[:2]):
            best = (distance, feature_id, _text(name))
    if best is None:
        return None
    return {"feature_id": best[1], "name": best[2], "distance_m": best[0]}


def direction_key(params: Mapping[str, Any], layers: Layers) -> dict[str, Any]:
    """Turn-by-turn directions along the shortest walk, with the nearest landmark (a POI within
    ``landmark_radius_m``) where each step after the first begins, and the straight-line bearing
    from start to end."""
    start, end = _place(layers, params["from"]), _place(layers, params["to"])
    radius = float(params.get("landmark_radius_m", 30.0))
    threshold = float(params.get("turn_threshold_deg", 30.0))
    graph = WalkGraph(layers)
    route = graph.route(start, end)
    azimuth = float(GEOD.inv(start.x, start.y, end.x, end.y)[0]) % 360
    result: dict[str, Any] = {
        "bearing_deg": azimuth,
        "compass": COMPASS[round(azimuth / 45) % 8],
        "straight_line_m": _distance_m(start, end),
        "reachable": route["reachable"],
        "walking_m": route["walking_m"],
        "steps": [],
    }
    if not route["reachable"]:
        return {**result, "reason": route["reason"]}
    steps: list[dict[str, Any]] = []
    last_bearing = 0.0
    for u, v in itertools.pairwise(route["nodes"]):
        edge = graph.graph.edges[u, v]
        bearing = _bearing(u, v)
        if steps and steps[-1]["street"] == edge["name"]:
            steps[-1]["distance_m"] += edge["length"]
        else:
            turn = "start" if not steps else _turn(last_bearing, bearing, threshold)
            steps.append(
                {"street": edge["name"], "distance_m": edge["length"], "turn": turn, "_at": u}
            )
        last_bearing = bearing
    pois = layers["pois"]
    for number, step in enumerate(steps):
        at = step.pop("_at")
        step["landmark"] = _landmark(pois, Point(at), radius) if number else None
    return {**result, "steps": steps}
```

Register them in `KEY_FUNCTIONS`:

```python
KEY_FUNCTIONS: dict[str, Callable[[Mapping[str, Any], Layers], dict[str, Any]]] = {
    "proximity": proximity_key,
    "containment": containment_key,
    "adjacency": adjacency_key,
    "closure": closure_key,
    "visibility": visibility_key,
    "direction": direction_key,
}
```

Check against the synthetic city (from the `tests/graded_city.py` docstring): the sight line to the Clock Tower crosses Low House where it is about 19.5 m high (above 6 m); the line to the School crosses Tall Block at about 5 m (below 25 m); the line to the Library crosses the Shed, whose height is unknown. From Tall Block's roof (26.6 m) the School is visible. The walk from ORIGIN to South Pharmacy heads north, east, south, west and north again, so every turn is to the right, while the straight-line bearing is south.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_graded_reference.py -q`
Expected: all pass. Then `uv run ruff check evals tests && uv run ruff format --check evals tests`.

- [ ] **Step 5: Commit**

```bash
git add evals/city/reference.py tests/test_graded_reference.py
git commit -m "feat: reference keys for lines of sight and turn-by-turn directions"
```

---

### Task 7: Key hashes, the keys file and `geoevals evals regenerate`

**Files:**
- Create: `src/geoevals/graded/keys.py`
- Create: `tests/graded_helpers.py`
- Modify: `src/geoevals/cli.py` (`evals regenerate`)
- Modify: `tests/fixtures/graded/sample/tasks.jsonl` (fill in `key_sha256`)
- Test: `tests/test_graded_keys.py`

**Interfaces:**
- Consumes: `load_layers`, `LAYERS_DIR` (Task 1); `load_eval_spec`, `load_tasks`, `spec_file` (Task 3); `load_reference` (Task 4); `geoevals.data.fetch.ensure_ignored`.
- Produces:
  - `geoevals.graded.keys`: `KEYS_DIR = "keys"`, `canonical_key(key) -> str`, `key_sha256(key) -> str`, `keys_path(data_dir: Path, eval_id: str) -> Path`, `compute_keys(spec_path: Path, data_dir: Path) -> dict[str, dict]`, `regenerate_keys(spec_path: Path, data_dir: Path, write: bool = True) -> list[str]` (task IDs whose committed hash is stale), `load_keys(spec_path: Path, data_dir: Path) -> dict[str, dict]`, `default_data_dir(spec_path: Path) -> Path`, `class KeysError(RuntimeError)`
  - `tests/graded_helpers.py`: `SAMPLE: Path`, `copy_sample_eval(root: Path) -> Path` (returns the copied `eval.yaml`), `sample_data(root: Path) -> Path` (a data directory with the synthetic city's layers)
  - CLI: `geoevals evals regenerate EVAL_ID [--root evals] [--data DIR] [--check]`

- [ ] **Step 1: Write the test helpers**

Create `tests/graded_helpers.py`:

```python
"""Helpers for the graded-eval tests: a writable copy of the sample eval and a data directory
with the synthetic city's layers."""

import shutil
from pathlib import Path

import yaml
from graded_city import build_data_dir

from geoevals.validation.validate import load_yaml

REPO = Path(__file__).parent.parent
SAMPLE = REPO / "tests" / "fixtures" / "graded" / "sample" / "eval.yaml"
PATH_FIELDS = ("rubric_criteria", "reference", "dataset_manifest")


def copy_sample_eval(root: Path) -> Path:
    """Copy the sample eval to ``root/sample/`` with absolute paths to the shared files, so that
    tests can rewrite its tasks; return the copy's ``eval.yaml``."""
    directory = root / "sample"
    directory.mkdir(parents=True)
    shutil.copy(SAMPLE.parent / "tasks.jsonl", directory / "tasks.jsonl")
    document = load_yaml(SAMPLE)
    for field in PATH_FIELDS:
        document[field] = str((SAMPLE.parent / document[field]).resolve())
    path = directory / "eval.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def sample_data(root: Path) -> Path:
    """A data directory (``layers/``) holding the synthetic city."""
    return build_data_dir(root / "data")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_graded_keys.py`:

```python
import json
from pathlib import Path

import pytest
from graded_helpers import copy_sample_eval, sample_data

from geoevals.cli import main
from geoevals.graded.keys import (
    KeysError,
    canonical_key,
    key_sha256,
    keys_path,
    load_keys,
    regenerate_keys,
)


def test_canonical_key_sorts_keys_and_is_compact() -> None:
    assert canonical_key({"b": 1, "a": [0.5, None]}) == '{"a":[0.5,null],"b":1}'
    assert key_sha256({"b": 1, "a": 2}) == key_sha256({"a": 2, "b": 1})


def _tasks(spec_path: Path) -> list[dict]:
    lines = spec_path.parent.joinpath("tasks.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _write_tasks(spec_path: Path, tasks: list[dict]) -> None:
    spec_path.parent.joinpath("tasks.jsonl").write_text(
        "".join(json.dumps(t) + "\n" for t in tasks), encoding="utf-8"
    )


def _unhashed_copy(tmp_path: Path) -> Path:
    """A copy of the sample eval whose tasks have no key_sha256 yet."""
    spec_path = copy_sample_eval(tmp_path)
    _write_tasks(spec_path, [{**t, "key_sha256": None} for t in _tasks(spec_path)])
    return spec_path


def test_regenerate_writes_keys_and_hashes(tmp_path: Path) -> None:
    spec_path, data = _unhashed_copy(tmp_path), sample_data(tmp_path)
    stale = regenerate_keys(spec_path, data, write=True)
    assert stale == ["sample-001", "sample-002", "sample-003"], "hashes start null"
    keys = load_keys(spec_path, data)
    assert keys["sample-001"]["walking_nearest"] == "node/500"
    assert keys["sample-003"]["disconnected_by_closure"] is True
    for task in _tasks(spec_path):
        assert task["key_sha256"] == key_sha256(keys[task["task_id"]])
    assert regenerate_keys(spec_path, data, write=False) == []
    lines = keys_path(data, "sample").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["task_id"] for line in lines] == [
        "sample-001",
        "sample-002",
        "sample-003",
    ]


def test_check_reports_a_changed_task(tmp_path: Path) -> None:
    spec_path, data = copy_sample_eval(tmp_path), sample_data(tmp_path)
    regenerate_keys(spec_path, data)
    tasks = _tasks(spec_path)
    tasks[0]["params"]["top"] = 1
    _write_tasks(spec_path, tasks)
    assert regenerate_keys(spec_path, data, write=False) == ["sample-001"]


def test_load_keys_refuses_missing_and_stale_keys(tmp_path: Path) -> None:
    spec_path, data = _unhashed_copy(tmp_path), sample_data(tmp_path)
    with pytest.raises(KeysError, match="evals regenerate"):
        load_keys(spec_path, data)
    regenerate_keys(spec_path, data)
    path = keys_path(data, "sample")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    lines[1]["key"]["targets"]["way/400"]["visible"] = False
    path.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
    with pytest.raises(KeysError, match="sample-002"):
        load_keys(spec_path, data)


def test_regenerate_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path, data = _unhashed_copy(tmp_path), sample_data(tmp_path)
    root = str(spec_path.parent.parent)
    args = ["evals", "regenerate", "sample", "--root", root, "--data", str(data)]
    assert main([*args, "--check"]) == 1
    assert "sample-001: out of date" in capsys.readouterr().out
    assert main(args) == 0
    assert main([*args, "--check"]) == 0
    assert "keys are up to date" in capsys.readouterr().out
```

Run `uv run ruff format tests/graded_helpers.py tests/test_graded_keys.py`.

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_keys.py -q`
Expected: `ModuleNotFoundError: No module named 'geoevals.graded.keys'`.

- [ ] **Step 4: Write `src/geoevals/graded/keys.py`**

```python
"""Reference keys: computed from the city, kept out of git, checked by their hashes.

A task's key is OpenStreetMap-derived, so it is never committed (``docs/data-governance.md``).
``regenerate_keys`` computes every key of an eval with its reference script, writes them to
``<data dir>/keys/<eval id>.jsonl`` (a gitignored path), and records each key's SHA-256 in the
committed ``tasks.jsonl`` (``key_sha256``). A key's hash is the SHA-256 of its canonical JSON
(sorted keys, no spaces); keys round floats to 0.1, so the hash is the same on every platform.

``load_keys`` reads the keys file for grading and refuses a missing file or a key whose hash
differs from the committed one: the grader must see the keys the tasks were reviewed with.

The data directory holds ``layers/`` (``geoevals evals build-city``) and ``keys/``. By default
it is the directory of the city's dataset manifest asset (``data/raw/osm_city_<town>/``).
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from geoevals.data.fetch import ensure_ignored
from geoevals.graded.city import LAYERS_DIR, load_layers
from geoevals.graded.reference import load_reference
from geoevals.graded.spec import load_tasks, spec_file
from geoevals.validation import load_dataset_manifest, load_eval_spec

KEYS_DIR = "keys"


class KeysError(RuntimeError):
    """Keys cannot be computed, or the keys file is missing or stale."""


def canonical_key(key: Any) -> str:
    return json.dumps(
        key, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def key_sha256(key: Any) -> str:
    return hashlib.sha256(canonical_key(key).encode("utf-8")).hexdigest()


def keys_path(data_dir: Path, eval_id: str) -> Path:
    return data_dir / KEYS_DIR / f"{eval_id}.jsonl"


def default_data_dir(spec_path: Path) -> Path:
    """The directory of the city's dataset manifest asset."""
    spec = load_eval_spec(spec_path)
    manifest_path = spec_file(spec_path, spec.dataset_manifest)
    asset = load_dataset_manifest(manifest_path).assets[0]
    return Path(os.path.normpath(manifest_path.parent / asset.path)).parent


def compute_keys(spec_path: Path, data_dir: Path) -> dict[str, dict[str, Any]]:
    """Every task's key, by task ID. Raises ``KeysError`` naming the task that failed."""
    spec = load_eval_spec(spec_path)
    compute = load_reference(spec_path, spec)
    layers = load_layers(data_dir / LAYERS_DIR)
    keys = {}
    for task in load_tasks(spec_path, spec):
        try:
            keys[task.task_id] = compute(task.key_type, task.params, layers)
        except ValueError as exc:
            raise KeysError(f"{task.task_id}: {exc}") from exc
    return keys


def regenerate_keys(spec_path: Path, data_dir: Path, write: bool = True) -> list[str]:
    """Compute the keys; return the IDs of tasks whose committed ``key_sha256`` is stale.

    With ``write``, write the keys file and update the stale hashes in ``tasks.jsonl`` (each line
    keeps its key order).
    """
    spec = load_eval_spec(spec_path)
    tasks = load_tasks(spec_path, spec)
    keys = compute_keys(spec_path, data_dir)
    stale = [t.task_id for t in tasks if t.key_sha256 != key_sha256(keys[t.task_id])]
    if not write:
        return stale
    path = keys_path(data_dir, spec.id)
    ensure_ignored(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps({"task_id": t.task_id, "key": keys[t.task_id]}, ensure_ascii=False) + "\n"
            for t in tasks
        ),
        encoding="utf-8",
    )
    if stale:
        tasks_file = spec_file(spec_path, spec.tasks)
        lines = []
        for line in tasks_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            task = json.loads(line)
            task["key_sha256"] = key_sha256(keys[task["task_id"]])
            lines.append(json.dumps(task, ensure_ascii=False) + "\n")
        tasks_file.write_text("".join(lines), encoding="utf-8")
    return stale


def load_keys(spec_path: Path, data_dir: Path) -> dict[str, dict[str, Any]]:
    """The keys of every task, checked against the committed hashes. Raises ``KeysError``."""
    spec = load_eval_spec(spec_path)
    path = keys_path(data_dir, spec.id)
    if not path.is_file():
        raise KeysError(f"{path}: no keys file; run `geoevals evals regenerate {spec.id}`")
    stored = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            stored[entry["task_id"]] = entry["key"]
    keys = {}
    for task in load_tasks(spec_path, spec):
        key = stored.get(task.task_id)
        if key is None or task.key_sha256 is None or key_sha256(key) != task.key_sha256:
            raise KeysError(
                f"{task.task_id}: the key in {path} does not match key_sha256 in the tasks; run "
                f"`geoevals evals regenerate {spec.id}` and review the change"
            )
        keys[task.task_id] = key
    return keys
```

- [ ] **Step 5: Add `evals regenerate` to the CLI**

In `build_parser`, in the `evals` group:

```python
    regen_keys = evals_commands.add_parser(
        "regenerate",
        help="Compute an eval's reference keys from the city layers, write them to the gitignored "
        "data directory and update key_sha256 in its tasks.jsonl.",
    )
    regen_keys.add_argument("eval_id", help="The eval ID (a directory under --root).")
    regen_keys.add_argument(
        "--root", type=Path, default=Path("evals"), help="Directory of evals (default: evals)."
    )
    regen_keys.add_argument(
        "--data",
        type=Path,
        help="Data directory with layers/ (default: the city manifest asset's directory).",
    )
    regen_keys.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; exit 1 when a committed key_sha256 is out of date.",
    )
```

Add the handler and its dispatch (`if args.command == "evals" and args.evals_command == "regenerate": return _evals_regenerate(args.eval_id, args.root, args.data, args.check)`):

```python
def _evals_regenerate(eval_id: str, root: Path, data: Path | None, check: bool) -> int:
    spec_path = find_eval_spec(root, eval_id)
    try:
        data_dir = data or default_data_dir(spec_path)
        stale = regenerate_keys(spec_path, data_dir, write=not check)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    for task_id in stale:
        print(f"{task_id}: {'out of date' if check else 'key_sha256 written'}")
    if not stale:
        print(f"{spec_path}: keys are up to date")
    return 1 if check and stale else 0
```

Imports: `from geoevals.graded.keys import default_data_dir, regenerate_keys` and `from geoevals.graded.spec import find_eval_spec`. `KeysError`, `ReferenceLoadError` and `FetchError` are `RuntimeError`s; `CityError` and `KeyComputationError` are `ValueError`s.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_graded_keys.py -q`
Expected: all pass.

- [ ] **Step 7: Fill in the sample fixture's hashes**

Run the regenerate into a scratch data directory and copy the hashes into the committed fixture:

```bash
uv run python - <<'EOF'
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "tests")
from graded_helpers import SAMPLE, copy_sample_eval, sample_data
from geoevals.graded.keys import regenerate_keys
with tempfile.TemporaryDirectory() as tmp:
    spec = copy_sample_eval(Path(tmp))
    regenerate_keys(spec, sample_data(Path(tmp)))
    hashes = {json.loads(l)["task_id"]: json.loads(l)["key_sha256"]
              for l in spec.parent.joinpath("tasks.jsonl").read_text().splitlines()}
lines = [json.loads(l) for l in SAMPLE.parent.joinpath("tasks.jsonl").read_text().splitlines()]
for task in lines:
    task["key_sha256"] = hashes[task["task_id"]]
SAMPLE.parent.joinpath("tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in lines))
print(hashes)
EOF
```

Expected: three 64-hex hashes printed; `git diff tests/fixtures/graded/sample/tasks.jsonl` shows only the `key_sha256` values changing. Then append a test that keeps the committed fixture current:

```python
def test_committed_sample_hashes_are_current(tmp_path: Path) -> None:
    spec_path, data = copy_sample_eval(tmp_path), sample_data(tmp_path)
    assert regenerate_keys(spec_path, data, write=False) == []
```

Run `uv run pytest tests/test_graded_keys.py tests/test_graded_spec.py -q`; all pass. If `evals/city/reference.py` or `tests/graded_city.py` changes later, this test fails until the fixture's hashes are refilled with the script above.

- [ ] **Step 8: Commit**

```bash
git add src/geoevals/graded/keys.py src/geoevals/cli.py tests/graded_helpers.py tests/test_graded_keys.py tests/fixtures/graded/sample/tasks.jsonl
git commit -m "feat: geoevals evals regenerate computes keys and records their hashes"
```

---

### Task 8: The python adapter mounts the city (`data_mount`) and takes the graded prompt

**Files:**
- Modify: `src/geoevals/adapters/claude.py` (config fields `prompt`, `data_mount`; template choice; `--data` for the MCP server)
- Modify: `src/geoevals/leaderboard/sandbox.py` (`DATA_MOUNT`; `start_container(..., data=None)`)
- Modify: `src/geoevals/leaderboard/sandbox_mcp.py` (`--data`)
- Modify: `src/geoevals/leaderboard/prompting.py` (`_spec` reads `eval.yaml`)
- Create: `src/geoevals/adapters/prompts/graded_python_v1.md`
- Test: `tests/test_claude_adapters.py`, `tests/test_sandbox.py` (append)

**Interfaces:**
- Consumes: `OUTPUT_SCHEMA`, `EVAL_SPEC_FILE` (Task 3); `load_eval_spec`.
- Produces:
  - `ClaudeAdapterConfig.prompt: Literal["benchmark", "graded"] = "benchmark"`, `ClaudeAdapterConfig.data_mount: str | None = None`
  - `geoevals.leaderboard.sandbox.DATA_MOUNT = "/bench/data"`; `start_container(image: str, name: str, fixtures: Path | None, data: Path | None = None) -> None`
  - `sandbox_mcp` flag `--data DIR`
  - `prompting.spec_for(case_input)` returns `(eval task_statement, OUTPUT_SCHEMA)` when `case_input["benchmark_dir"]` holds `eval.yaml`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_adapters.py` (it already imports `sandbox`, `claude_module`, `CliCall`, `ClaudePythonAdapter`, `ClaudeDirectAdapter`, `FAKE_COMMAND`, `pytest`, `Path`; add any that are missing):

```python
GRADED_SAMPLE = Path(__file__).parent / "fixtures" / "graded" / "sample"


def _graded_case() -> dict:
    return {
        "case_id": "sample-001",
        "prompt": "Which pharmacy is nearest on foot?\n\nWrite for: a resident",
        "inputs": {"files": {}, "params": {"point": [10.0, 50.0], "feature_ids": []}},
        "benchmark_dir": str(GRADED_SAMPLE),
    }


def test_graded_python_adapter_mounts_the_city(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[CliCall] = []
    answer = {"status": "ok", "answer": "North Pharmacy (node/500)."}
    result = CliResult(answer, 10, 5, (MODEL,), 2, "9.9.9", [])
    monkeypatch.setattr(claude_module, "run_cli", lambda call: calls.append(call) or result)
    monkeypatch.setattr(sandbox, "docker_available", lambda: True)
    monkeypatch.setattr(sandbox, "remove_container", lambda name: None)
    adapter = ClaudePythonAdapter("haiku_5_5")
    adapter.setup(
        {
            "claude_command": list(FAKE_COMMAND),
            "sandbox_image": "img:1",
            "prompt": "graded",
            "data_mount": str(tmp_path),
        }
    )
    response = adapter.predict(_graded_case())
    assert response.output == answer
    [call] = calls
    args = call.mcp_config["mcpServers"]["sandbox"]["args"]
    assert args[args.index("--data") + 1] == str(tmp_path)
    assert "/bench/data" in call.system_prompt
    assert "Answer one open-ended question" in call.system_prompt, "the eval's task statement"
    assert call.json_schema["required"] == ["status", "answer"]
    assert "Which pharmacy is nearest on foot?" in call.user_message


def test_direct_track_rejects_graded_prompts() -> None:
    adapter = ClaudeDirectAdapter("haiku_5_5")
    with pytest.raises(ValueError, match="python track"):
        adapter.setup({"claude_command": list(FAKE_COMMAND), "prompt": "graded"})
    with pytest.raises(ValueError, match="python track"):
        adapter.setup({"claude_command": list(FAKE_COMMAND), "data_mount": "/tmp"})
```

Append to `tests/test_sandbox.py` (it tests `sandbox` with a monkeypatched `_docker`; reuse its style and imports):

```python
def test_start_container_mounts_the_data_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(sandbox, "_docker", docker)
    sandbox.start_container("img:1", "c1", None, data=tmp_path)
    [args] = calls
    assert f"{tmp_path.resolve()}:/bench/data:ro" in args
    assert not any(":/bench/fixtures:ro" in a for a in args)


def test_mcp_server_passes_the_data_mount(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    started: list[tuple] = []
    monkeypatch.setattr(sandbox_mcp, "start_container", lambda *a, **k: started.append((a, k)))
    monkeypatch.setattr(
        sandbox_mcp, "exec_python", lambda *a: sandbox.ExecResult(0, "ok", "", False)
    )
    monkeypatch.setattr(sandbox_mcp, "remove_container", lambda name: None)
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "run_python", "arguments": {"code": "print(1)"}},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(call) + "\n"))
    sandbox_mcp.main(["--image", "img:1", "--name", "c1", "--data", str(tmp_path)])
    [(args, kwargs)] = started
    assert args == ("img:1", "c1", None)
    assert kwargs == {"data": tmp_path}
```

Add `import io`, `import json`, `import subprocess` and `from geoevals.leaderboard import sandbox, sandbox_mcp` to `tests/test_sandbox.py` if they are missing. Run `uv run ruff format tests/test_claude_adapters.py tests/test_sandbox.py`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_claude_adapters.py tests/test_sandbox.py -q -k "graded or data"`
Expected: FAIL (`extra inputs are not permitted` for `prompt`, `unexpected keyword argument 'data'`).

- [ ] **Step 3: Mount the data in the sandbox**

In `src/geoevals/leaderboard/sandbox.py`, add `DATA_MOUNT = f"{MOUNT}/data"` below `FIXTURES_MOUNT`, extend the module docstring ("For a graded eval, the city's layers are mounted read-only at ``/bench/data`` instead."), and change `start_container`:

```python
def start_container(image: str, name: str, fixtures: Path | None, data: Path | None = None) -> None:
    """Start the case's container. ``fixtures`` is mounted read-only at ``/bench/fixtures`` and
    ``data`` (a graded eval's city layers) at ``/bench/data``."""
    args = ["run", "-d", "--rm", "--name", name, "--label", LABEL, *RUN_LIMITS]
    args += ["-e", "HOME=/tmp", "-e", "MPLCONFIGDIR=/tmp", "-w", MOUNT]
    if fixtures is not None:
        args += ["-v", f"{fixtures.resolve()}:{FIXTURES_MOUNT}:ro"]
    if data is not None:
        args += ["-v", f"{data.resolve()}:{DATA_MOUNT}:ro"]
    started = _docker(*args, image, "sleep", "infinity")
    if started.returncode != 0:
        raise SandboxError(f"docker run failed: {started.stderr.strip()}")
```

In `src/geoevals/leaderboard/sandbox_mcp.py`, add `parser.add_argument("--data", type=Path)` after `--fixtures`, call `start_container(args.image, args.name, args.fixtures, data=args.data)`, and add `[--data <dir>]` to the module docstring's usage line.

- [ ] **Step 4: Teach the adapter and prompting about graded evals**

In `src/geoevals/adapters/claude.py`:

Add to the config docstring:

```text
    prompt: benchmark       # graded: the graded-eval template (python track only)
    data_mount: null        # python track: a directory mounted read-only at /bench/data
```

Add the fields to `ClaudeAdapterConfig`:

```python
    prompt: Literal["benchmark", "graded"] = "benchmark"
    data_mount: str | None = None
```

In `_ClaudeAdapter.setup`, replace the template line with:

```python
        if self.track != "python" and (
            self._config.prompt == "graded" or self._config.data_mount is not None
        ):
            raise ClaudeConfigError(
                f"{self.name}: graded evals and data_mount need the python track; the direct "
                "track cannot hold a city in its prompt"
            )
        template = f"graded_{self.track}" if self._config.prompt == "graded" else self.track
        self._template = prompting.load_template(template, self._config.prompt_version)
```

(`ClaudeConfigError` is a `ValueError`, which the test matches.) In `ClaudePythonAdapter._predict`, after the fixtures lines:

```python
        if self._config.data_mount is not None:
            args += ["--data", self._config.data_mount]
```

In `src/geoevals/leaderboard/prompting.py`, add `EVAL_SPEC_FILE = "eval.yaml"` and replace `_spec`:

```python
@cache
def _spec(benchmark_dir: str) -> tuple[str, str]:
    directory = Path(benchmark_dir)
    if (directory / EVAL_SPEC_FILE).is_file():
        # A graded eval: its task statement and the fixed answer schema.
        from geoevals.graded.spec import OUTPUT_SCHEMA
        from geoevals.validation import load_eval_spec

        spec = load_eval_spec(directory / EVAL_SPEC_FILE)
        return spec.task_statement, json.dumps(OUTPUT_SCHEMA)
    spec = load_benchmark_spec(directory / SPEC_FILE)
    return spec.task_statement, json.dumps(spec.output_schema)
```

Update the module docstring: "``benchmark_dir`` is a benchmark's directory, or a graded eval's (with ``eval.yaml``)".

- [ ] **Step 5: Write the graded prompt template**

Create `src/geoevals/adapters/prompts/graded_python_v1.md`:

```markdown
You are completing one task from GeoEvals, an evaluation of spatial reasoning on real city data.

The task: {task_statement}

The user message holds the question, the audience to write for, and the place it is about (a
point as longitude and latitude, and feature IDs). The city's OpenStreetMap data is in
/bench/data, read-only, as GeoParquet layers in longitude and latitude (OGC:CRS84): buildings,
streets, paths, railways, water, parks, landuse, pois, boundaries, and all_features (every
mapped feature, with all its OpenStreetMap tags as JSON in the tags column). Every row has a
feature_id such as way/123 and a name where one is mapped. Building heights are in height_m: the
height tag where mapped, else building:levels times 3 m; height_source says which, and unknown
heights are empty. The data is a whole city, so most of it does not bear on the question.

You have a run_python tool that runs Python 3.12 code in a sandbox with GeoPandas, Shapely,
pyproj, NetworkX and SciPy installed, and no network access. /tmp is writable. Each call starts a
new Python process (files you write to /tmp stay for this task), so print() everything you need
to see.

Give your final answer only through the structured-output tool: a status and your answer as
Markdown text. Lead with the conclusion, write for the stated audience, name the features you
rely on by name and feature_id, and state the assumptions you make. Keep the answer under the
word limit in the task.

Use status "ok" when you answer the question. When it cannot be answered as asked, do not
guess: use "needs_clarification" when the question is ambiguous, "insufficient_data" when the
data cannot answer it, and "invalid_request" when it is impossible or malformed; explain why in
the answer.
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_claude_adapters.py tests/test_sandbox.py tests/test_leaderboard.py -q`
Expected: all pass, the existing benchmark-track tests included. Then `uv run ruff check . && uv run ruff format --check . && uv run pyright`.

- [ ] **Step 7: Commit**

```bash
git add src/geoevals/adapters src/geoevals/leaderboard/sandbox.py src/geoevals/leaderboard/sandbox_mcp.py src/geoevals/leaderboard/prompting.py tests/test_claude_adapters.py tests/test_sandbox.py
git commit -m "feat: graded prompt and a read-only city mount for the python track"
```

---

### Task 9: Graded runs (`geoevals run --eval`) and their result schema

**Files:**
- Create: `schemas/graded-result.schema.json`
- Create: `src/geoevals/graded/run.py`
- Modify: `src/geoevals/cli.py` (`run --eval`, `--data`)
- Test: `tests/test_graded_run.py`

**Interfaces:**
- Consumes: `layers_sha256`, `LAYERS_DIR` (Task 1); `load_eval_spec`, `load_tasks`, `spec_file`, `OUTPUT_SCHEMA`, `EvalTask` (Task 3); `default_data_dir` (Task 7); `geoevals.runner` (`RunConfig`, `config_hash`, `canonical_config`, `Worker`, `WorkerSetupError`, `make_run_id`, `environment_fingerprint`, `RunError`, `write_result`, `write_config`, `run_logging`); `geoevals.metrics.base.percentile`; `geoevals.adapters.registry.adapter_factory`.
- Produces:
  - `geoevals.graded.run`: `GRADED_RESULT_SCHEMA_VERSION = "1.0.0"`, `SPLIT = "test"`, `TASK_STATUSES`, `word_count(text) -> int`, `answer_problem(output, word_limit) -> str | None`, `case_input(task: EvalTask, spec_path: Path, word_limit: int) -> dict`, `run_eval(spec_path, adapter_name, config: RunConfig, data_dir: Path, on_start=None) -> dict`, `validate_graded_result(document) -> list[ValidationIssue]`, `load_graded_result(path: Path) -> dict` (raises `SpecValidationError`)
  - A graded result: `run_id`, `schema_version`, `eval {id, version}`, `adapter {name, version, config}`, `config_hash`, `dataset_manifest_hash`, `data_sha256`, `environment`, `started_at`, `finished_at`, `efficiency`, `tasks[]` with `task_id`, `status` (`answered`, `invalid_output`, `adapter_error`, `timeout`, `skipped`), `output`, `latency_s`, `retries`, `tokens`, `error`, optional `trajectory`
  - CLI: `geoevals run --eval SPEC --adapter A --config C --out DIR [--data DIR]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graded_run.py`:

```python
import json
from pathlib import Path

import pytest
import yaml
from graded_helpers import SAMPLE, copy_sample_eval, sample_data

from geoevals.cli import main
from geoevals.graded.city import layers_sha256
from geoevals.graded.run import (
    answer_problem,
    case_input,
    load_graded_result,
    run_eval,
    validate_graded_result,
)
from geoevals.graded.spec import load_tasks
from geoevals.runner.config import RunConfig
from geoevals.runner.run import RunError
from geoevals.validation import load_eval_spec

ANSWERS = {
    "sample-001": {"status": "ok", "answer": "North Pharmacy (node/500) is nearest on foot."},
    "sample-002": {"status": "ok", "answer": "word " * 4001},
    "sample-003": {"status": "insufficient_data", "answer": "The data holds no closure dates."},
}


def test_run_eval_records_answers_and_invalid_outputs(tmp_path: Path) -> None:
    spec_path, data = copy_sample_eval(tmp_path), sample_data(tmp_path)
    config = RunConfig(split="test", adapter={"references": ANSWERS})
    result = run_eval(spec_path, "mock", config, data)
    statuses = {t["task_id"]: t["status"] for t in result["tasks"]}
    assert statuses == {
        "sample-001": "answered",
        "sample-002": "invalid_output",
        "sample-003": "answered",
    }
    assert "4001 words" in result["tasks"][1]["error"]["message"]
    assert result["eval"] == {"id": "sample", "version": "0.1.0"}
    assert result["data_sha256"] == layers_sha256(data / "layers")
    assert validate_graded_result(result) == []
    assert "summary_metrics" not in result
    assert all("metrics" not in task for task in result["tasks"])


def test_answer_problem() -> None:
    assert answer_problem({"status": "ok", "answer": "a b c"}, 3) is None
    assert answer_problem({"status": "ok", "answer": "a b c d"}, 3) == (
        "the answer has 4 words; the limit is 3"
    )
    assert answer_problem({"status": "ok", "answer": "   "}, 3) == "the answer is empty"
    assert "answer" in (answer_problem({"status": "ok"}, 3) or "")
    assert "status" in (answer_problem({"status": "maybe", "answer": "x"}, 3) or "")
    assert answer_problem(["not", "an", "object"], 3) is not None


def test_case_input_hides_params_and_keys() -> None:
    spec = load_eval_spec(SAMPLE)
    task = load_tasks(SAMPLE, spec)[0]
    case = case_input(task, SAMPLE, 4000)
    assert case["case_id"] == "sample-001"
    assert case["inputs"] == {
        "files": {},
        "params": {"point": [10.0, 50.000538987], "feature_ids": []},
    }
    assert case["benchmark_dir"] == str(SAMPLE.parent.resolve())
    assert "Write for: a resident with no GIS background." in case["prompt"]
    assert "at most 4,000 words" in case["prompt"]
    text = json.dumps(case)
    assert "category" not in text and "key_sha256" not in text and "strata" not in text


def test_run_eval_refuses_other_splits_and_missing_layers(tmp_path: Path) -> None:
    spec_path = copy_sample_eval(tmp_path)
    with pytest.raises(RunError, match="one split"):
        run_eval(spec_path, "mock", RunConfig(split="dev"), sample_data(tmp_path))
    with pytest.raises(RunError, match="no city layers"):
        run_eval(spec_path, "mock", RunConfig(split="test"), tmp_path / "empty")


def test_run_eval_cli(tmp_path: Path) -> None:
    spec_path, data = copy_sample_eval(tmp_path), sample_data(tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"split": "test", "adapter": {"references": ANSWERS}}))
    out = tmp_path / "runs"
    code = main(
        [
            "run",
            "--eval",
            str(spec_path),
            "--adapter",
            "mock",
            "--config",
            str(config),
            "--out",
            str(out),
            "--data",
            str(data),
        ]
    )
    assert code == 0
    [run_dir] = list(out.iterdir())
    result = load_graded_result(run_dir / "result.json")
    assert result["adapter"]["name"] == "mock"
    assert (run_dir / "config.yaml").is_file() and (run_dir / "run.log").is_file()


def test_run_needs_a_benchmark_or_an_eval(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["run", "--adapter", "mock", "--config", "c.yaml", "--out", "o"])
```

Run `uv run ruff format tests/test_graded_run.py`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_run.py -q`
Expected: `ModuleNotFoundError: No module named 'geoevals.graded.run'`.

- [ ] **Step 3: Write the JSON Schema**

Create `schemas/graded-result.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GeoEvals graded run result",
  "description": "The answers of one adapter to every task of a graded eval. It holds no scores: `geoevals grade` writes them to grades.json.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "run_id", "schema_version", "eval", "adapter", "config_hash", "dataset_manifest_hash",
    "data_sha256", "environment", "started_at", "finished_at", "efficiency", "tasks"
  ],
  "properties": {
    "run_id": {"type": "string", "minLength": 1},
    "schema_version": {"const": "1.0.0"},
    "eval": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "version"],
      "properties": {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "version": {"type": "string", "minLength": 1}
      }
    },
    "adapter": {
      "type": "object",
      "additionalProperties": false,
      "required": ["name", "version", "config"],
      "properties": {
        "name": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "config": {"type": "object"}
      }
    },
    "config_hash": {"$ref": "#/$defs/sha256"},
    "dataset_manifest_hash": {"$ref": "#/$defs/sha256"},
    "data_sha256": {"description": "SHA-256 of the city layers the run used.", "$ref": "#/$defs/sha256"},
    "environment": {"type": "object"},
    "started_at": {"type": "string", "minLength": 1},
    "finished_at": {"type": "string", "minLength": 1},
    "efficiency": {
      "type": "object",
      "additionalProperties": false,
      "required": ["wall_clock_s", "latency_p50_s", "latency_p90_s", "tokens_input_total", "tokens_output_total"],
      "properties": {
        "wall_clock_s": {"type": "number", "minimum": 0},
        "latency_p50_s": {"type": ["number", "null"]},
        "latency_p90_s": {"type": ["number", "null"]},
        "tokens_input_total": {"type": "integer", "minimum": 0},
        "tokens_output_total": {"type": "integer", "minimum": 0}
      }
    },
    "tasks": {"type": "array", "items": {"$ref": "#/$defs/task"}}
  },
  "$defs": {
    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "task": {
      "type": "object",
      "additionalProperties": false,
      "required": ["task_id", "status", "output", "latency_s", "retries", "tokens", "error"],
      "properties": {
        "task_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*-[0-9]{3}$"},
        "status": {"enum": ["answered", "invalid_output", "adapter_error", "timeout", "skipped"]},
        "output": {"type": ["object", "null"]},
        "latency_s": {"type": ["number", "null"], "minimum": 0},
        "retries": {"type": "integer", "minimum": 0},
        "tokens": {
          "oneOf": [
            {"type": "null"},
            {
              "type": "object",
              "additionalProperties": false,
              "required": ["input", "output"],
              "properties": {
                "input": {"type": "integer", "minimum": 0},
                "output": {"type": "integer", "minimum": 0}
              }
            }
          ]
        },
        "error": {
          "oneOf": [
            {"type": "null"},
            {
              "type": "object",
              "additionalProperties": false,
              "required": ["type", "message"],
              "properties": {"type": {"type": "string", "minLength": 1}, "message": {"type": "string"}}
            }
          ]
        },
        "trajectory": {"type": "array", "items": {"type": "object"}}
      },
      "if": {"properties": {"status": {"const": "answered"}}},
      "then": {"properties": {"output": {"type": "object"}, "error": {"type": "null"}}}
    }
  }
}
```

- [ ] **Step 4: Write `src/geoevals/graded/run.py`**

```python
"""Graded runs: one answer per task from an adapter, with the city mounted. No scores.

``run_eval`` sends every task of an eval to an adapter, as ``geoevals.runner.run`` sends
benchmark cases (one worker process, the run config's timeout and retries), and returns a result
that matches ``schemas/graded-result.schema.json``. Grading is a separate step, ``geoevals
grade``.

The adapter's case input for a task:

- ``case_id``: the task ID
- ``prompt``: the task prompt, the audience and the word limit
- ``inputs``: ``{"files": {}, "params": <the task location>}``
- ``benchmark_dir``: the eval's directory (the Claude adapters read ``eval.yaml`` from it)

The task's ``params`` and key are never sent. A Claude adapter also gets ``prompt: graded`` and
``data_mount`` (the city's ``layers/``, mounted read-only at ``/bench/data``); they are not part
of the recorded config, because the mount path is local to the machine.

Task statuses: ``answered``; ``invalid_output`` (not the answer schema, an empty answer, or
longer than the eval's word limit); ``adapter_error``; ``timeout``; ``skipped``.
"""

import hashlib
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from geoevals.adapters.registry import adapter_factory
from geoevals.graded.city import LAYERS_DIR, layers_sha256
from geoevals.graded.spec import OUTPUT_SCHEMA, EvalTask, load_tasks, spec_file
from geoevals.metrics.base import percentile
from geoevals.runner.config import RunConfig, canonical_config, config_hash
from geoevals.runner.environment import environment_fingerprint
from geoevals.runner.layout import make_run_id
from geoevals.runner.run import RunError
from geoevals.runner.worker import Worker, WorkerSetupError
from geoevals.validation import (
    SpecValidationError,
    ValidationIssue,
    load_dataset_manifest,
    load_eval_spec,
)
from geoevals.validation.validate import schema_issues

logger = logging.getLogger(__name__)

GRADED_RESULT_SCHEMA_VERSION = "1.0.0"
SPLIT = "test"
TASK_STATUSES = ("answered", "invalid_output", "adapter_error", "timeout", "skipped")
_ATTEMPT_STATUS = {"timeout": "timeout", "skipped": "skipped", "error": "adapter_error"}


def word_count(text: str) -> int:
    return len(text.split())


def answer_problem(output: Any, word_limit: int) -> str | None:
    """Why ``output`` is not a valid answer, or None."""
    errors = sorted(
        Draft202012Validator(OUTPUT_SCHEMA).iter_errors(output),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        return "; ".join(
            f"{'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors
        )
    if not output["answer"].strip():
        return "the answer is empty"
    words = word_count(output["answer"])
    if words > word_limit:
        return f"the answer has {words} words; the limit is {word_limit}"
    return None


def case_input(task: EvalTask, spec_path: Path, word_limit: int) -> dict[str, Any]:
    """What the adapter receives for ``task``; see the module docstring."""
    prompt = (
        f"{task.prompt}\n\nWrite for: {task.audience}.\nAnswer in at most {word_limit:,} words."
    )
    return {
        "case_id": task.task_id,
        "prompt": prompt,
        "inputs": {"files": {}, "params": task.location.model_dump(exclude_none=True)},
        "benchmark_dir": str(spec_path.parent.resolve()),
    }


def _run_task(
    worker: Worker, task: EvalTask, case: dict[str, Any], config: RunConfig, word_limit: int
) -> dict[str, Any]:
    attempts = 0
    while True:
        attempts += 1
        attempt = worker.predict(case, f"{config.seed}:{task.task_id}", config.timeout_s)
        if attempt.kind != "error" or attempts > config.max_retries:
            break
        logger.warning(
            "task %s attempt %d: %s: %s; retrying",
            task.task_id, attempts, attempt.error_type, attempt.error_message,
        )  # fmt: skip
    record: dict[str, Any] = {
        "task_id": task.task_id,
        "status": "answered",
        "output": None,
        "latency_s": attempt.latency_s,
        "retries": attempts - 1,
        "tokens": None,
        "error": None,
    }
    if attempt.tokens is not None:
        record["tokens"] = {"input": attempt.tokens[0], "output": attempt.tokens[1]}
    if attempt.trajectory is not None:
        record["trajectory"] = attempt.trajectory
    if attempt.kind == "ok":
        problem = answer_problem(attempt.output, word_limit)
        record["output"] = attempt.output if isinstance(attempt.output, dict) else None
        if problem is not None:
            record["status"] = "invalid_output"
            record["error"] = {"type": "InvalidOutput", "message": problem}
    else:
        record["status"] = _ATTEMPT_STATUS[attempt.kind]
        record["error"] = {
            "type": attempt.error_type or "Error",
            "message": attempt.error_message or "",
        }
    log = logger.info if record["status"] == "answered" else logger.warning
    log("task %s: %s", task.task_id, record["status"])
    return record


def _efficiency(records: list[dict[str, Any]], wall_clock_s: float) -> dict[str, Any]:
    latencies = sorted(r["latency_s"] for r in records if r["latency_s"] is not None)
    return {
        "wall_clock_s": wall_clock_s,
        "latency_p50_s": percentile(latencies, 0.5) if latencies else None,
        "latency_p90_s": percentile(latencies, 0.9) if latencies else None,
        "tokens_input_total": sum(r["tokens"]["input"] for r in records if r["tokens"]),
        "tokens_output_total": sum(r["tokens"]["output"] for r in records if r["tokens"]),
    }


def _timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_graded_result(document: Any) -> list[ValidationIssue]:
    issues = schema_issues(document, "graded-result.schema.json")
    if issues:
        return issues
    seen: set[str] = set()
    for i, task in enumerate(document["tasks"]):
        if task["task_id"] in seen:
            issues.append(ValidationIssue(f"tasks[{i}].task_id", f"duplicate {task['task_id']!r}"))
        seen.add(task["task_id"])
    return issues


def load_graded_result(path: Path) -> dict[str, Any]:
    """A graded run's ``result.json`` (or its directory). Raises ``SpecValidationError``."""
    import json

    path = path / "result.json" if path.is_dir() else path
    document = json.loads(path.read_text(encoding="utf-8"))
    issues = validate_graded_result(document)
    if issues:
        raise SpecValidationError(path, issues)
    return document


def run_eval(
    spec_path: Path,
    adapter_name: str,
    config: RunConfig,
    data_dir: Path,
    on_start: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run ``adapter_name`` on every task of the eval at ``spec_path``; return the result.

    Raises ``SpecValidationError`` for an invalid spec, tasks or manifest, and ``RunError`` when
    the run cannot start. Failing tasks never raise; they get a failure status.
    """
    spec = load_eval_spec(spec_path)
    tasks = load_tasks(spec_path, spec)
    if config.split != SPLIT:
        raise RunError(
            f"graded evals have one split, {SPLIT!r}; the config asks for {config.split!r}"
        )
    manifest_path = spec_file(spec_path, spec.dataset_manifest)
    load_dataset_manifest(manifest_path)
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    layers_dir = data_dir / LAYERS_DIR
    try:
        data_sha256 = layers_sha256(layers_dir)
    except OSError:
        raise RunError(
            f"{layers_dir}: no city layers; run `geoevals evals build-city` first"
        ) from None
    factory = adapter_factory(adapter_name)
    adapter = factory()
    adapter_config = dict(config.adapter)
    if adapter_name.startswith("claude_"):
        adapter_config.update(prompt="graded", data_mount=str(layers_dir.resolve()))
    digest = config_hash(config)
    started = datetime.now(UTC)
    run_id = make_run_id(spec.id, adapter_name, started, digest)
    if on_start is not None:
        on_start(run_id)
    logger.info(
        "running %d task(s) of eval %s %s with adapter %s %s",
        len(tasks), spec.id, spec.version, adapter.name, adapter.version,
    )  # fmt: skip
    clock = time.perf_counter()
    worker = Worker(factory, adapter_config)
    records: list[dict[str, Any]] = []
    try:
        for task in tasks:
            case = case_input(task, spec_path, spec.answer_word_limit)
            records.append(_run_task(worker, task, case, config, spec.answer_word_limit))
    except WorkerSetupError as exc:
        raise RunError(str(exc)) from exc
    finally:
        worker.close()
    wall_clock_s = time.perf_counter() - clock
    result: dict[str, Any] = {
        "run_id": run_id,
        "schema_version": GRADED_RESULT_SCHEMA_VERSION,
        "eval": {"id": spec.id, "version": spec.version},
        "adapter": {
            "name": adapter.name,
            "version": adapter.version,
            "config": canonical_config(config)["adapter"],
        },
        "config_hash": digest,
        "dataset_manifest_hash": manifest_hash,
        "data_sha256": data_sha256,
        "environment": environment_fingerprint(),
        "started_at": _timestamp(started),
        "finished_at": _timestamp(datetime.now(UTC)),
        "efficiency": _efficiency(records, wall_clock_s),
        "tasks": records,
    }
    issues = validate_graded_result(result)
    if issues:
        raise RunError("graded result is invalid: " + "; ".join(map(str, issues)))
    return result
```

Move `import json` to the module's imports (it is shown inside `load_graded_result` only to keep the listing short).

- [ ] **Step 5: Add `--eval` to `geoevals run`**

In `build_parser`, replace the `run.add_argument("--benchmark", ...)` line with a required group:

```python
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--benchmark", type=Path, help="Benchmark spec (YAML).")
    target.add_argument(
        "--eval",
        type=Path,
        help="Graded eval spec (eval.yaml): answers only; score them with `geoevals grade`.",
    )
```

and after `--out`:

```python
    run.add_argument(
        "--data",
        type=Path,
        help="Graded evals: the data directory with layers/ (default: the city manifest asset's "
        "directory).",
    )
```

Add the handler next to `_run_to_dir`:

```python
def _run_eval(
    spec_path: Path, adapter_name: str, config_path: Path, out: Path, data: Path | None, level: str
) -> int:
    for path in (spec_path, config_path):
        if not path.is_file():
            print(f"{path}: file not found", file=sys.stderr)
            return 1
    try:
        config = load_run_config(config_path)
        data_dir = data or default_data_dir(spec_path)
    except (RunConfigError, SpecValidationError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    run_dir: Path | None = None
    with run_logging(level) as run_log:

        def start(run_id: str) -> None:
            nonlocal run_dir
            run_dir = out / run_id
            try:
                run_dir.mkdir(parents=True)
            except FileExistsError:
                raise RunError(f"{run_dir} already exists; not overwriting it") from None
            run_log.attach(run_dir / LOG_FILE)
            write_config(config, run_dir / CONFIG_FILE)
            logger.info("writing graded run %s to %s", run_id, run_dir)

        try:
            result = run_eval(spec_path, adapter_name, config, data_dir, on_start=start)
        except SpecValidationError as exc:
            for issue in exc.issues:
                logger.error("%s: %s", exc.path, issue)
            return 1
        except (RunError, ValueError) as exc:
            logger.error("run failed: %s", exc)
            return 1
        assert run_dir is not None
        write_result(result, run_dir / RESULT_FILE)
    print(run_dir)
    return 0
```

In `main`, at the top of the `run` branch:

```python
    if args.command == "run" and args.eval is not None:
        return _run_eval(args.eval, args.adapter, args.config, args.out, args.data, args.log_level)
```

Imports: `from geoevals.graded.run import run_eval`; `logger` is the CLI module's logger (`logging.getLogger(__name__)`; add it if the module has none). If `_run` passes `args.benchmark` positionally, it is unchanged: argparse guarantees exactly one of `--benchmark` and `--eval`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_graded_run.py tests/test_cli.py tests/test_runner.py -q`
Expected: all pass. Then `uv run ruff check . && uv run ruff format --check . && uv run pyright`.

- [ ] **Step 7: Commit**

```bash
git add schemas/graded-result.schema.json src/geoevals/graded/run.py src/geoevals/cli.py tests/test_graded_run.py
git commit -m "feat: geoevals run --eval records graded answers, with no scores"
```

---

### Task 10: The grader and `geoevals grade`

**Files:**
- Create: `src/geoevals/graded/prompts/grader_v1.md`
- Create: `src/geoevals/graded/grader.py`
- Modify: `src/geoevals/cli.py` (`grade`)
- Modify: `tests/fake_claude.py`, `tests/claude_fakes.py` (a sequence of scenarios, one per call)
- Modify: `tests/graded_helpers.py` (`graded_run_dir`)
- Test: `tests/test_graded_grader.py`

**Interfaces:**
- Consumes: `load_graded_result` (Task 9); `load_keys`, `default_data_dir`, `KeysError` (Task 7); `load_eval_spec`, `load_tasks`, `load_rubric`, `find_eval_spec`, `EvalTask`, `Criterion`, `RubricCriteria` (Task 3); `geoevals.leaderboard.claude_cli` (`CliCall`, `run_cli`, `claude_code_version`, the `Claude*` errors).
- Produces:
  - `geoevals.graded.grader`: `GRADER_MODEL = "claude-opus-5-5"`, `GRADER_EFFORT = "high"`, `GRADER_PROMPT_VERSION = "grader_v1"`, `MAX_JUSTIFICATION_WORDS = 60`, `GRADES_FILE = "grades.json"`, `GRADES_SCHEMA_VERSION = "1.0.0"`
  - `GraderConfig` (frozen dataclass: `passes: int = 2`, `command: tuple[str, ...] = ("claude",)`, `timeout_s: float = 600.0`, `max_budget_usd: float = 5.0`, `evals_root: Path = Path("evals")`)
  - `grade_schema(criterion_ids: list[str]) -> dict`, `grader_message(task: EvalTask, criteria: list[Criterion], key: dict, output: dict) -> str`, `check_grade(grade: Any, criterion_ids: list[str]) -> str | None`, `task_score(passes: list[dict]) -> float`
  - `grade_run(run_dir: Path, data_dir: Path | None, config: GraderConfig) -> Grades`
  - Pydantic models `CriterionGrade`, `GradePass`, `TaskGrade`, `GraderInfo`, `Grades` (`Grades.model_dump(mode="json")` is what `grades.json` holds); `load_grades(path: Path) -> Grades`
  - `class GradeError(RuntimeError)`
  - Task grade statuses: `graded`, `no_answer` (score 0, no call), `not_graded` (score null)
  - CLI: `geoevals grade RUN_DIR [--data DIR] [--evals evals] [--passes 2]`
  - `tests/graded_helpers.py`: `graded_run_dir(root: Path, statuses: dict[str, str], adapter: str = "claude_python_haiku_5_5") -> tuple[Path, Path]` (run directory, data directory, keys regenerated)

- [ ] **Step 1: Let the fake CLI replay a sequence**

In `tests/fake_claude.py`, after loading the scenario, add:

```python
    sequence = scenario.get("sequence")
    if sequence is not None:
        counter = os.environ["FAKE_CLAUDE_SCENARIO"] + ".count"
        calls = int(open(counter).read()) if os.path.exists(counter) else 0
        with open(counter, "w", encoding="utf-8") as file:
            file.write(str(calls + 1))
        scenario = sequence[min(calls, len(sequence) - 1)]
```

and describe it in the docstring ("``{"sequence": [scenario, ...]}`` replays one scenario per call, repeating the last"). When `FAKE_CLAUDE_RECORD` is set, append every call to a list instead of overwriting: read the existing JSON list if the file exists, append the record, write the list back. Then in `tests/claude_fakes.py` change `FakeClaude.record` to return the last element and add:

```python
@property
def records(self) -> list[dict[str, Any]]:
    return json.loads(self.record_path.read_text(encoding="utf-8"))


def set_sequence(self, scenarios: list[list[dict[str, Any]]]) -> None:
    """One list of events per call; the last repeats."""
    sequence = [{"events": events} for events in scenarios]
    self.scenario_path.write_text(json.dumps({"sequence": sequence}), encoding="utf-8")
    self.scenario_path.with_name(self.scenario_path.name + ".count").unlink(missing_ok=True)
```

`set` also unlinks the counter. `record` becomes `return self.records[-1]`. Run `uv run pytest tests/test_claude_cli.py tests/test_claude_adapters.py -q` to confirm the existing fakes still work.

- [ ] **Step 2: Add the graded-run helper**

Append to `tests/graded_helpers.py`:

```python
import json

from geoevals.graded.keys import regenerate_keys

ANSWER = {"status": "ok", "answer": "North Pharmacy (node/500) is nearest on foot: 330 m."}


def graded_run_dir(
    root: Path, statuses: dict[str, str], adapter: str = "claude_python_haiku_5_5"
) -> tuple[Path, Path]:
    """A graded run of the sample eval with the given task statuses, its eval under
    ``root/evals/sample/`` and keys regenerated; return (run directory, data directory)."""
    spec_path = copy_sample_eval(root / "evals")
    data = sample_data(root)
    regenerate_keys(spec_path, data)
    tasks = []
    for task_id, status in statuses.items():
        answered = status == "answered"
        tasks.append(
            {
                "task_id": task_id,
                "status": status,
                "output": ANSWER if answered else None,
                "latency_s": 1.0,
                "retries": 0,
                "tokens": {"input": 10, "output": 5},
                "error": None if answered else {"type": "ClaudeTimeout", "message": "slow"},
            }
        )
    from geoevals.graded.city import layers_sha256

    result = {
        "run_id": "sample-" + adapter + "-20261011T000000Z-00000000",
        "schema_version": "1.0.0",
        "eval": {"id": "sample", "version": "0.1.0"},
        "adapter": {"name": adapter, "version": "0.1.0+cc.9.9.9", "config": {"effort": "high"}},
        "config_hash": "0" * 64,
        "dataset_manifest_hash": "1" * 64,
        "data_sha256": layers_sha256(data / "layers"),
        "environment": {},
        "started_at": "2026-10-11T00:00:00.000000Z",
        "finished_at": "2026-10-11T00:01:00.000000Z",
        "efficiency": {
            "wall_clock_s": 60.0,
            "latency_p50_s": 1.0,
            "latency_p90_s": 1.0,
            "tokens_input_total": 10 * len(tasks),
            "tokens_output_total": 5 * len(tasks),
        },
        "tasks": tasks,
    }
    run_dir = root / "runs" / result["run_id"]
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return run_dir, data
```

Move the two inner imports to the module top. Run `uv run ruff format tests/graded_helpers.py`.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_graded_grader.py`:

```python
import json
from pathlib import Path

import pytest
from claude_fakes import FAKE_COMMAND, FakeClaude, init_event, result_event
from graded_helpers import graded_run_dir

from geoevals.cli import main
from geoevals.graded.grader import (
    GRADER_MODEL,
    GradeError,
    GraderConfig,
    check_grade,
    grade_run,
    load_grades,
    task_score,
)
from geoevals.graded.run import load_graded_result

IDS = ["relations", "reasoning", "assumptions", "data_use", "clarity"]
USAGE = {GRADER_MODEL: {"inputTokens": 5, "outputTokens": 50}}


def grade(score: int = 3, words: int = 5) -> dict:
    return {
        "criteria": {i: {"score": score, "justification": " ".join(["key"] * words)} for i in IDS}
    }


def events(answer: dict | None, **fields) -> list[dict]:
    return [init_event(), result_event(answer, model_usage=USAGE, **fields)]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    return FakeClaude(tmp_path, monkeypatch)


def _config(root: Path) -> GraderConfig:
    return GraderConfig(command=FAKE_COMMAND, evals_root=root / "evals")


def test_check_grade() -> None:
    assert check_grade(grade(), IDS) is None
    assert "missing" in check_grade({"criteria": {}}, IDS)
    extra = grade()
    extra["criteria"]["style"] = {"score": 1, "justification": "x"}
    assert "unexpected" in check_grade(extra, IDS)
    high = grade()
    high["criteria"]["clarity"]["score"] = 5
    assert "0 to 4" in check_grade(high, IDS)
    assert "60 words" in check_grade(grade(words=61), IDS)
    assert check_grade("not json", IDS) is not None


def test_task_score_is_the_mean_over_passes_of_mean_criteria_over_4() -> None:
    passes = [grade(4)["criteria"], grade(2)["criteria"]]
    assert task_score(passes) == pytest.approx(0.75)


def test_grade_run_grades_answered_tasks_twice(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered", "sample-002": "answered"})
    fake.set(events(grade(3)))
    grades = grade_run(run_dir, data, _config(tmp_path))
    assert [t.status for t in grades.tasks] == ["graded", "graded"]
    assert all(len(t.passes) == 2 and t.score == pytest.approx(0.75) for t in grades.tasks)
    assert grades.grader.model == GRADER_MODEL
    assert grades.grader.claude_code_version == "9.9.9"
    assert grades.grader.passes == 2
    assert grades.stopped is None
    assert len(fake.records) == 4


def test_no_answer_scores_zero_without_a_call(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(
        tmp_path, {"sample-001": "invalid_output", "sample-003": "timeout"}
    )
    grades = grade_run(run_dir, data, _config(tmp_path))
    assert [(t.status, t.score) for t in grades.tasks] == [("no_answer", 0.0), ("no_answer", 0.0)]
    assert not fake.called


def test_invalid_grade_is_retried_once(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set_sequence([events({"criteria": {}}), events(grade(4)), events(grade(4))])
    [task] = grade_run(run_dir, data, _config(tmp_path)).tasks
    assert task.status == "graded" and task.score == 1.0
    assert len(fake.records) == 3


def test_two_invalid_grades_leave_the_task_not_graded(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set(events(grade(words=61)))
    [task] = grade_run(run_dir, data, _config(tmp_path)).tasks
    assert task.status == "not_graded" and task.score is None
    assert "60 words" in (task.error or "")


def test_usage_limit_stops_grading(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered", "sample-002": "answered"})
    fake.set(events(None, is_error=True, subtype="error_during_execution", api_error_status=429))
    grades = grade_run(run_dir, data, _config(tmp_path))
    assert grades.stopped is not None and "usage limit" in grades.stopped
    assert [t.status for t in grades.tasks] == ["not_graded", "not_graded"]


def test_wrong_model_stops_grading(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    other = {"claude-sonnet-5-5": {"inputTokens": 5, "outputTokens": 50}}
    fake.set([init_event(), result_event(grade(), model_usage=other)])
    grades = grade_run(run_dir, data, _config(tmp_path))
    assert grades.stopped is not None and "ClaudeUnexpectedModel" in grades.stopped


def test_grader_never_sees_who_answered(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set(events(grade()))
    grade_run(run_dir, data, _config(tmp_path))
    record = fake.records[0]
    sent = record["stdin"] + " ".join(record["argv"])
    for name in ("haiku", "claude_python", load_graded_result(run_dir)["run_id"]):
        assert name.lower() not in sent.lower(), name
    assert "walking_nearest" in record["stdin"], "the key is sent"
    assert "North Pharmacy (node/500)" in record["stdin"], "the answer is sent"
    argv = record["argv"]
    assert argv[argv.index("--model") + 1] == GRADER_MODEL
    assert argv[argv.index("--tools") + 1] == ""


def test_grade_refuses_missing_or_stale_keys(tmp_path: Path, fake: FakeClaude) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    keys = data / "keys" / "sample.jsonl"
    keys.write_text(keys.read_text().replace("node/500", "node/999"), encoding="utf-8")
    with pytest.raises(GradeError, match="sample-001"):
        grade_run(run_dir, data, _config(tmp_path))
    keys.unlink()
    with pytest.raises(GradeError, match="no keys file"):
        grade_run(run_dir, data, _config(tmp_path))
    assert not fake.called


def test_grade_cli_writes_grades_json(
    tmp_path: Path, fake: FakeClaude, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, data = graded_run_dir(tmp_path, {"sample-001": "answered"})
    fake.set(events(grade()))
    monkeypatch.setattr("geoevals.cli.GRADER_COMMAND", FAKE_COMMAND)
    code = main(["grade", str(run_dir), "--data", str(data), "--evals", str(tmp_path / "evals")])
    assert code == 0
    grades = load_grades(run_dir / "grades.json")
    assert grades.run_id == load_graded_result(run_dir)["run_id"]
    assert json.loads((run_dir / "grades.json").read_text())["schema_version"] == "1.0.0"
```

Run `uv run ruff format tests/test_graded_grader.py`.

- [ ] **Step 4: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_grader.py -q`
Expected: `ModuleNotFoundError: No module named 'geoevals.graded.grader'`.

- [ ] **Step 5: Write the grader prompt**

Create `src/geoevals/graded/prompts/grader_v1.md`:

```markdown
You grade answers to open-ended spatial-reasoning tasks about a real city, for GeoEvals.

The user message holds the task, the rubric, a reference key and the answer to grade. The
reference key lists facts computed from the city's OpenStreetMap data by a reference script:
treat them as correct. You are not told who or what wrote the answer, and it must not matter.

Score each rubric criterion with an integer from 0 to 4, choosing the anchor that fits best;
when the answer falls between two anchors, choose the lower. Judge only what the answer says,
not what it might have meant. An answer whose status is not "ok" (needs_clarification,
insufficient_data, invalid_request) can earn credit only when the key shows that the task cannot
be answered as asked; otherwise it scores low on spatial relations.

For each criterion, give a justification of at most 60 words that cites the reference key where
it applies, for example "key: walking_nearest is node/500, the answer names node/501". Give
your grades only through the structured-output tool, following its schema exactly.
```

- [ ] **Step 6: Write `src/geoevals/graded/grader.py`**

```python
"""Grade a graded run's answers with Claude Opus 5.5, twice per answer.

``grade_run`` reads a run's ``result.json``, the eval's tasks and rubric, and the verified keys
(``geoevals.graded.keys.load_keys``: a missing or stale keys file stops grading before any
call). For every answered task it runs ``passes`` separate ``claude -p`` sessions through
``geoevals.leaderboard.claude_cli.run_cli``: model ``GRADER_MODEL``, effort high, no tools,
``--restricted``, a stripped environment, an empty working directory and the subscription
check. The input is the grader prompt (``prompts/grader_v1.md``), the task prompt and audience,
the rubric with anchors, the key and the answer; never the answering model, the adapter, the run
ID or the trajectory.

A grade is valid when it scores exactly the task's criteria with integers 0 to 4, each with a
justification of at most 60 words. An error or an invalid grade is retried once; a second
failure leaves the task ``not_graded``. The usage limit, an auth failure, an unexpected model or
a Claude Code version change stops grading: every task not yet graded is ``not_graded`` and
``stopped`` says why. A task that was not answered (``invalid_output``, errors, timeouts) is
``no_answer`` with score 0, without a call.

Task score = mean over the passes of (mean of criteria / 4).
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from geoevals.graded.keys import KeysError, default_data_dir, load_keys
from geoevals.graded.run import load_graded_result, word_count
from geoevals.graded.spec import Criterion, EvalTask, find_eval_spec, load_rubric, load_tasks
from geoevals.leaderboard.claude_cli import (
    ClaudeAuthError,
    ClaudeCliError,
    ClaudeUnexpectedModel,
    ClaudeUsageLimit,
    ClaudeVersionChanged,
    CliCall,
    claude_code_version,
    run_cli,
)
from geoevals.validation import load_eval_spec

GRADER_MODEL = "claude-opus-5-5"
GRADER_EFFORT = "high"
GRADER_PROMPT_VERSION = "grader_v1"
MAX_JUSTIFICATION_WORDS = 60
GRADES_FILE = "grades.json"
GRADES_SCHEMA_VERSION = "1.0.0"
PROMPTS_DIR = Path(__file__).parent / "prompts"
STOPPING_ERRORS = (ClaudeUsageLimit, ClaudeAuthError, ClaudeUnexpectedModel, ClaudeVersionChanged)


class GradeError(RuntimeError):
    """The run cannot be graded (unreadable run, unknown eval, missing or stale keys)."""


class InvalidGrade(ValueError):
    """The grader's answer does not meet the grade rules."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CriterionGrade(_Model):
    score: Annotated[int, Field(ge=0, le=4)]
    justification: str


class GradePass(_Model):
    criteria: dict[str, CriterionGrade]


class TaskGrade(_Model):
    task_id: str
    status: Literal["graded", "no_answer", "not_graded"]
    score: float | None
    passes: list[GradePass]
    error: str | None = None


class GraderInfo(_Model):
    model: str
    effort: str
    prompt_version: str
    claude_code_version: str
    passes: int


class Grades(_Model):
    schema_version: Literal["1.0.0"]
    run_id: str
    eval: dict[str, str]
    rubric_version: str
    grader: GraderInfo
    graded_at: str
    stopped: str | None
    tasks: list[TaskGrade]


@dataclass(frozen=True)
class GraderConfig:
    passes: int = 2
    command: tuple[str, ...] = ("claude",)
    timeout_s: float = 600.0
    max_budget_usd: float = 5.0
    evals_root: Path = field(default_factory=lambda: Path("evals"))


def grade_schema(criterion_ids: list[str]) -> dict[str, Any]:
    """The ``--json-schema`` of a grade: one score and justification per criterion."""
    criterion = {
        "type": "object",
        "additionalProperties": False,
        "required": ["score", "justification"],
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 4},
            "justification": {"type": "string", "minLength": 1},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["criteria"],
        "properties": {
            "criteria": {
                "type": "object",
                "additionalProperties": False,
                "required": list(criterion_ids),
                "properties": {cid: criterion for cid in criterion_ids},
            }
        },
    }


def check_grade(grade: Any, criterion_ids: list[str]) -> str | None:
    """Why ``grade`` breaks the grade rules, or None."""
    if not isinstance(grade, dict) or not isinstance(grade.get("criteria"), dict):
        return "the grade has no criteria object"
    criteria = grade["criteria"]
    missing = sorted(set(criterion_ids) - set(criteria))
    if missing:
        return f"missing criteria: {', '.join(missing)}"
    unexpected = sorted(set(criteria) - set(criterion_ids))
    if unexpected:
        return f"unexpected criteria: {', '.join(unexpected)}"
    for cid in criterion_ids:
        entry = criteria[cid]
        score = entry.get("score") if isinstance(entry, dict) else None
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 4:
            return f"{cid}: the score must be an integer from 0 to 4"
        justification = entry.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            return f"{cid}: no justification"
        if word_count(justification) > MAX_JUSTIFICATION_WORDS:
            return f"{cid}: the justification is longer than {MAX_JUSTIFICATION_WORDS} words"
    return None


def task_score(passes: list[dict[str, Any]]) -> float:
    """Mean over the passes of (mean of criteria / 4)."""
    per_pass = [
        sum(c["score"] for c in criteria.values()) / len(criteria) / 4 for criteria in passes
    ]
    return sum(per_pass) / len(per_pass)


def grader_message(
    task: EvalTask, criteria: list[Criterion], key: dict[str, Any], output: dict[str, Any]
) -> str:
    """The user message of a grading session; see the module docstring for what it holds."""
    lines = ["# Task", "", task.prompt, "", f"Audience: {task.audience}", "", "# Rubric", ""]
    lines.append("Score each criterion from 0 to 4 using its anchors.")
    for criterion in criteria:
        lines += ["", f"## {criterion.id}: {criterion.title}", "", criterion.description, ""]
        lines += [f"- {score}: {text}" for score, text in sorted(criterion.anchors.items())]
        extra = task.anchors.get(criterion.id, {})
        if extra:
            lines += ["", "Anchors for this task:"]
            lines += [f"- {score}: {text}" for score, text in sorted(extra.items())]
    lines += [
        "",
        "# Reference key",
        "",
        "Facts computed from the city's data. Distances are in meters and bearings in degrees, "
        "rounded to 0.1.",
        "",
        "```json",
        json.dumps(key, indent=2, ensure_ascii=False),
        "```",
        "",
        "# Answer to grade",
        "",
        f"Status: {output['status']}",
        "",
        output["answer"],
    ]
    return "\n".join(lines)


def _grade_once(call: CliCall, version: str, criterion_ids: list[str]) -> dict[str, Any]:
    result = run_cli(call)
    if result.claude_code_version != version:
        raise ClaudeVersionChanged(
            f"graded on Claude Code {result.claude_code_version}, not {version}"
        )
    problem = check_grade(result.structured_output, criterion_ids)
    if problem is not None:
        raise InvalidGrade(problem)
    assert result.structured_output is not None
    return result.structured_output["criteria"]


def _grade_pass(call: CliCall, version: str, criterion_ids: list[str]) -> dict[str, Any]:
    """One pass, retried once. Raises a stopping error, or the second failure."""
    for attempt in (1, 2):
        try:
            return _grade_once(call, version, criterion_ids)
        except STOPPING_ERRORS:
            raise
        except (ClaudeCliError, InvalidGrade):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def load_grades(path: Path) -> Grades:
    return Grades.model_validate(json.loads(path.read_text(encoding="utf-8")))


def grade_run(run_dir: Path, data_dir: Path | None, config: GraderConfig) -> Grades:
    """Grade every task of a graded run; see the module docstring."""
    try:
        result = load_graded_result(run_dir)
    except (OSError, ValueError) as exc:
        raise GradeError(f"{run_dir}: {exc}") from exc
    spec_path = find_eval_spec(config.evals_root, result["eval"]["id"])
    spec = load_eval_spec(spec_path)
    if spec.version != result["eval"]["version"]:
        raise GradeError(
            f"the run answered {spec.id} {result['eval']['version']}; {spec_path} is {spec.version}"
        )
    tasks = {task.task_id: task for task in load_tasks(spec_path, spec)}
    rubric = load_rubric(spec_path, spec)
    by_id = {criterion.id: criterion for criterion in rubric.criteria}
    try:
        keys = load_keys(spec_path, data_dir or default_data_dir(spec_path))
    except KeysError as exc:
        raise GradeError(str(exc)) from exc
    version = claude_code_version(config.command)
    system_prompt = (PROMPTS_DIR / f"{GRADER_PROMPT_VERSION}.md").read_text(encoding="utf-8")
    stopped: str | None = None
    graded: list[TaskGrade] = []
    for record in result["tasks"]:
        task = tasks[record["task_id"]]
        if record["status"] != "answered":
            graded.append(TaskGrade(task_id=task.task_id, status="no_answer", score=0.0, passes=[]))
            continue
        if stopped is not None:
            graded.append(
                TaskGrade(
                    task_id=task.task_id, status="not_graded", score=None, passes=[], error=stopped
                )
            )
            continue
        criteria = [by_id[cid] for cid in task.rubric]
        call = CliCall(
            model=GRADER_MODEL,
            system_prompt=system_prompt,
            user_message=grader_message(task, criteria, keys[task.task_id], record["output"]),
            json_schema=grade_schema(task.rubric),
            effort=GRADER_EFFORT,
            max_budget_usd=config.max_budget_usd,
            timeout_s=config.timeout_s,
            command=tuple(config.command),
        )
        passes: list[dict[str, Any]] = []
        error: str | None = None
        try:
            for _ in range(config.passes):
                passes.append(_grade_pass(call, version, task.rubric))
        except STOPPING_ERRORS as exc:
            stopped = f"{type(exc).__name__}: {exc}"
            error = stopped
        except (ClaudeCliError, InvalidGrade) as exc:
            error = f"{type(exc).__name__}: {exc}"
        if error is None:
            graded.append(
                TaskGrade(
                    task_id=task.task_id,
                    status="graded",
                    score=task_score(passes),
                    passes=[GradePass.model_validate({"criteria": p}) for p in passes],
                )
            )
        else:
            graded.append(
                TaskGrade(
                    task_id=task.task_id, status="not_graded", score=None, passes=[], error=error
                )
            )
    return Grades(
        schema_version=GRADES_SCHEMA_VERSION,
        run_id=result["run_id"],
        eval=dict(result["eval"]),
        rubric_version=rubric.version,
        grader=GraderInfo(
            model=GRADER_MODEL,
            effort=GRADER_EFFORT,
            prompt_version=GRADER_PROMPT_VERSION,
            claude_code_version=version,
            passes=config.passes,
        ),
        graded_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        stopped=stopped,
        tasks=graded,
    )
```

The usage-limit test's events carry `api_error_status: 429`; `claude_cli.check_result` raises `ClaudeUsageLimit` for it, whose message starts "usage limit reached", so `stopped` holds "ClaudeUsageLimit: usage limit reached: ...".

- [ ] **Step 7: Add `geoevals grade` to the CLI**

In `build_parser`:

```python
    grade = subparsers.add_parser(
        "grade",
        help="Grade a graded run's answers with Claude Opus 5.5 (two passes per answer, on the "
        "local Claude subscription) and write grades.json into the run directory.",
    )
    grade.add_argument("run_dir", type=Path, help="Graded run directory (with result.json).")
    grade.add_argument(
        "--data",
        type=Path,
        help="Data directory with keys/ (default: the city manifest asset's directory).",
    )
    grade.add_argument(
        "--evals", type=Path, default=Path("evals"), help="Directory of evals (default: evals)."
    )
    grade.add_argument("--passes", type=int, default=2, help="Grading passes per answer (default: 2).")
```

Add a module constant `GRADER_COMMAND: tuple[str, ...] = ("claude",)` (tests replace it), the handler and its dispatch (`if args.command == "grade": return _grade(args.run_dir, args.data, args.evals, args.passes)`):

```python
def _grade(run_dir: Path, data: Path | None, evals: Path, passes: int) -> int:
    if passes < 2:
        print(
            "--passes must be at least 2: the report states the grader's agreement with itself",
            file=sys.stderr,
        )
        return 1
    config = GraderConfig(passes=passes, command=GRADER_COMMAND, evals_root=evals)
    try:
        grades = grade_run(run_dir, data, config)
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except (GradeError, OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    path = run_dir / GRADES_FILE
    path.write_text(json.dumps(grades.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for task in grades.tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    print(f"{path}: " + ", ".join(f"{status} {n}" for status, n in sorted(counts.items())))
    if grades.stopped:
        print(f"grading stopped: {grades.stopped}", file=sys.stderr)
        return 1
    return 0
```

Imports: `from geoevals.graded.grader import GRADES_FILE, GradeError, GraderConfig, grade_run`.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_graded_grader.py tests/test_claude_cli.py tests/test_claude_adapters.py -q`
Expected: all pass. Then `uv run ruff check . && uv run ruff format --check . && uv run pyright`.

- [ ] **Step 9: Commit**

```bash
git add src/geoevals/graded/grader.py src/geoevals/graded/prompts src/geoevals/cli.py tests/fake_claude.py tests/claude_fakes.py tests/graded_helpers.py tests/test_graded_grader.py
git commit -m "feat: geoevals grade scores answers with Opus 5.5, twice, blind to the model"
```

---

### Task 11: The graded leaderboard: acceptance, quartiles, agreement and the README table

**Files:**
- Create: `src/geoevals/graded/board.py`
- Modify: `src/geoevals/leaderboard/table.py` (`replace_section`)
- Modify: `src/geoevals/cli.py` (`leaderboard add` takes graded runs; `leaderboard build` writes the graded section)
- Modify: `README.md` (graded markers), `tests/test_docs.py` (pass `--graded`)
- Test: `tests/test_graded_board.py`

**Interfaces:**
- Consumes: `load_graded_result` (Task 9); `Grades`, `load_grades`, `GRADES_FILE` (Task 10); `geoevals.leaderboard.table` (`MODEL_NAMES`, `HARNESS_ERRORS` via `claude_cli`, `update_readme`); `geoevals.adapters.claude.MODELS`; `geoevals.metrics.base.bootstrap_ci`.
- Produces:
  - `geoevals.leaderboard.table.replace_section(text: str, start: str, end: str, body: str) -> str` (`update_readme` calls it)
  - `geoevals.graded.board`: `GRADED_START = "<!-- graded:start -->"`, `GRADED_END = "<!-- graded:end -->"`, `DEFAULT_GRADED = Path("leaderboard/graded")`, `PLOTS_DIR = "plots"`, `class GradedError(ValueError)`, `GradedRow` (frozen dataclass: `eval_id`, `eval_version`, `model`, `scores: tuple[float, ...]`, `mean`, `ci_low`, `ci_high`, `minimum`, `q1`, `median`, `q3`, `maximum`, `n`, `comparable: tuple[str, ...]`, `grader: GraderInfo`), `Agreement` (frozen dataclass: `within_one: float`, `mean_abs_diff: float`, `pairs: int`)
  - `quartiles(scores: list[float]) -> tuple[float, float, float]`, `graded_row(result: dict, grades: Grades, where: str) -> GradedRow`, `agreement(grades: list[Grades]) -> Agreement`, `load_graded(results_dir: Path) -> tuple[list[GradedRow], dict[str, Agreement]]`, `render_graded(rows, agreements) -> str`, `add_graded_run(run_dir: Path, results_dir: Path) -> Path`, `is_graded_result(document: dict) -> bool`
  - CLI: `geoevals leaderboard add RUN_DIR [--graded DIR]` (graded runs go to `<graded>/<eval>/<adapter>/`); `geoevals leaderboard build [--graded DIR]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graded_board.py`:

```python
import json
from pathlib import Path

import pytest

from geoevals.graded.board import (
    GRADED_END,
    GRADED_START,
    GradedError,
    agreement,
    graded_row,
    load_graded,
    quartiles,
    render_graded,
)
from geoevals.graded.grader import Grades

GRADER = {
    "model": "claude-opus-5-5",
    "effort": "high",
    "prompt_version": "grader_v1",
    "claude_code_version": "9.9.9",
    "passes": 2,
}


def _grades(scores_per_task: list[tuple[int, int]], statuses: list[str] | None = None) -> dict:
    statuses = statuses or ["graded"] * len(scores_per_task)
    tasks = []
    for i, ((first, second), status) in enumerate(zip(scores_per_task, statuses, strict=True)):
        passes = [
            {
                "criteria": {
                    "relations": {"score": first, "justification": "key"},
                    "clarity": {"score": first, "justification": "key"},
                }
            },
            {
                "criteria": {
                    "relations": {"score": second, "justification": "key"},
                    "clarity": {"score": second, "justification": "key"},
                }
            },
        ]
        graded = status == "graded"
        tasks.append(
            {
                "task_id": f"proximity-{i + 1:03d}",
                "status": status,
                "score": (first + second) / 8
                if graded
                else (0.0 if status == "no_answer" else None),
                "passes": passes if graded else [],
                "error": None,
            }
        )
    return {
        "schema_version": "1.0.0",
        "run_id": "r",
        "eval": {"id": "proximity", "version": "0.1.0"},
        "rubric_version": "1.0.0",
        "grader": GRADER,
        "graded_at": "2026-10-11T00:00:00Z",
        "stopped": None,
        "tasks": tasks,
    }


def _result(
    adapter: str = "claude_python_opus_5_5",
    n: int = 4,
    statuses: list[str] | None = None,
    data: str = "d" * 64,
    errors: dict[int, str] | None = None,
) -> dict:
    statuses = statuses or ["answered"] * n
    errors = errors or {}
    return {
        "run_id": "r",
        "schema_version": "1.0.0",
        "eval": {"id": "proximity", "version": "0.1.0"},
        "adapter": {
            "name": adapter,
            "version": "0.1.0+cc.9.9.9",
            "config": {"effort": "high", "prompt_version": "v1"},
        },
        "config_hash": "0" * 64,
        "dataset_manifest_hash": "1" * 64,
        "data_sha256": data,
        "environment": {},
        "started_at": "s",
        "finished_at": "f",
        "efficiency": {
            "wall_clock_s": 1.0,
            "latency_p50_s": 1.0,
            "latency_p90_s": 1.0,
            "tokens_input_total": 1,
            "tokens_output_total": 1,
        },
        "tasks": [
            {
                "task_id": f"proximity-{i + 1:03d}",
                "status": s,
                "output": {"status": "ok", "answer": "x"} if s == "answered" else None,
                "latency_s": 1.0,
                "retries": 0,
                "tokens": None,
                "error": {"type": errors[i], "message": "m"} if i in errors else None,
            }
            for i, s in enumerate(statuses)
        ],
    }


def _write(root: Path, result: dict, grades: dict) -> None:
    target = root / result["eval"]["id"] / result["adapter"]["name"]
    target.mkdir(parents=True)
    (target / "result.json").write_text(json.dumps(result))
    (target / "grades.json").write_text(json.dumps(grades))


def test_quartiles() -> None:
    assert quartiles([0.0, 0.25, 0.5, 0.75, 1.0]) == (0.25, 0.5, 0.75)
    assert quartiles([0.4]) == (0.4, 0.4, 0.4)


def test_graded_row_statistics() -> None:
    grades = Grades.model_validate(_grades([(4, 4), (2, 2), (0, 0), (4, 0)]))
    row = graded_row(_result(), grades, "w")
    assert row.scores == (1.0, 0.5, 0.0, 0.5)
    assert row.mean == pytest.approx(0.5)
    assert (row.minimum, row.median, row.maximum) == (0.0, 0.5, 1.0)
    assert row.n == 4
    assert row.ci_low <= row.mean <= row.ci_high


def test_agreement_counts_criterion_pairs_within_one_point() -> None:
    grades = Grades.model_validate(_grades([(4, 4), (4, 2)]))
    result = agreement([grades])
    assert result.pairs == 4
    assert result.within_one == pytest.approx(0.5)
    assert result.mean_abs_diff == pytest.approx(0.25)  # task 2: |1.0 - 0.5|, task 1: 0


def test_board_rejects_not_graded_tasks() -> None:
    grades = Grades.model_validate(_grades([(4, 4), (0, 0)], ["graded", "not_graded"]))
    with pytest.raises(GradedError, match="not graded"):
        graded_row(_result(n=2), grades, "w")


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (_result(adapter="claude_direct_opus_5_5", n=1), "python"),
        (_result(n=1, statuses=["skipped"]), "skipped"),
        (_result(n=1, statuses=["timeout"]), "runner's timeout"),
        (_result(n=1, statuses=["adapter_error"], errors={0: "ClaudeUsageLimit"}), "harness"),
    ],
)
def test_board_rejects_incomplete_runs(result: dict, message: str) -> None:
    grades = Grades.model_validate(
        _grades([(4, 4)], ["no_answer"] if result["tasks"][0]["status"] != "answered" else None)
    )
    with pytest.raises(GradedError, match=message):
        graded_row(result, grades, "w")


def test_load_graded_rejects_mixed_data(tmp_path: Path) -> None:
    _write(tmp_path, _result(), _grades([(4, 4)] * 4))
    _write(
        tmp_path, _result(adapter="claude_python_haiku_5_5", data="e" * 64), _grades([(2, 2)] * 4)
    )
    with pytest.raises(GradedError, match="not comparable"):
        load_graded(tmp_path)


def test_render_graded(tmp_path: Path) -> None:
    _write(tmp_path, _result(), _grades([(4, 4), (2, 2), (0, 0), (4, 0)]))
    _write(tmp_path, _result(adapter="claude_python_haiku_5_5"), _grades([(2, 2)] * 4))
    rows, agreements = load_graded(tmp_path)
    text = render_graded(rows, agreements)
    lines = text.splitlines()
    assert lines[0] == "| Model | Eval | Mean (95% CI) | Min | Q1 | Median | Q3 | Max |"
    assert lines[2].startswith("| Opus 5.5 | `proximity` 0.1.0 | 0.500 [")
    assert lines[3].startswith("| Haiku 5.5 | `proximity` 0.1.0 | 0.500 [")
    assert "![proximity: task scores by model](leaderboard/graded/plots/proximity.svg)" in text
    assert "Opus 5.5 also answered" in text
    assert "never combined" in text


def test_render_with_no_graded_runs() -> None:
    assert "No graded runs" in render_graded([], {})


def test_markers_are_distinct_from_the_benchmark_table() -> None:
    from geoevals.leaderboard.table import END, START

    assert {GRADED_START, GRADED_END}.isdisjoint({START, END})
```

Run `uv run ruff format tests/test_graded_board.py`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_board.py -q`
Expected: `ModuleNotFoundError: No module named 'geoevals.graded.board'`.

- [ ] **Step 3: Generalize the README section replacement**

In `src/geoevals/leaderboard/table.py`, replace `update_readme` with:

```python
def replace_section(text: str, start: str, end: str, body: str) -> str:
    """``text`` with everything between the ``start`` and ``end`` markers replaced by ``body``."""
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise LeaderboardError(f"the README must hold {start} and then {end}, once each")
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    return f"{before}{start}\n{body}\n{end}{after}"


def update_readme(text: str, table: str) -> str:
    """``text`` with the benchmark leaderboard table replaced by ``table``."""
    return replace_section(text, START, END, table)
```

- [ ] **Step 4: Write `src/geoevals/graded/board.py`**

```python
"""The graded-eval leaderboard: accepted runs, per-model score distributions, and the README
section between ``<!-- graded:start -->`` and ``<!-- graded:end -->``.

An accepted run is ``leaderboard/graded/<eval>/<adapter>/`` with ``result.json``,
``grades.json`` and ``config.yaml``, copied there by ``geoevals leaderboard add``. A run is
accepted only if it comes from a ``claude_python_<model>`` adapter with the default CLI, no task
was skipped, stopped by the runner's timeout or failed in the harness, its grades belong to it,
grading did not stop, every answered task was graded, and there are at least two passes. Tasks
that were not answered score 0.

All runs of an eval must share its version, the city layers (``data_sha256``), the dataset
manifest, the answering effort and prompt version, the rubric version, and the grader (model,
effort, prompt version, Claude Code version, passes). Runs graded by different versions are not
comparable, so the build rejects a mix.

Per model and eval the table shows the mean task score with its 95% bootstrap interval
(``geoevals.metrics.base.bootstrap_ci``, fixed seed), and the minimum, quartiles and maximum
(linear interpolation, as matplotlib's box plot draws them). Grader agreement per eval: the
share of criterion scores on which the first two passes differ by at most 1 point, and the mean
absolute difference of the passes' task scores.
"""

import json
import shutil
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from geoevals.adapters.claude import MODELS
from geoevals.graded.grader import GRADES_FILE, GraderInfo, Grades, load_grades
from geoevals.graded.run import load_graded_result
from geoevals.leaderboard.claude_cli import HARNESS_ERRORS
from geoevals.leaderboard.table import MODEL_NAMES
from geoevals.metrics.base import bootstrap_ci

GRADED_START = "<!-- graded:start -->"
GRADED_END = "<!-- graded:end -->"
DEFAULT_GRADED = Path("leaderboard/graded")
PLOTS_DIR = "plots"
README_PLOTS = "leaderboard/graded/plots"
RESULT_FILE = "result.json"
CONFIG_FILE = "config.yaml"
PREFIX = "claude_python_"


class GradedError(ValueError):
    """A graded run cannot go on the leaderboard."""


@dataclass(frozen=True)
class Agreement:
    within_one: float
    mean_abs_diff: float
    pairs: int


@dataclass(frozen=True)
class GradedRow:
    eval_id: str
    eval_version: str
    model: str
    scores: tuple[float, ...]
    mean: float
    ci_low: float
    ci_high: float
    minimum: float
    q1: float
    median: float
    q3: float
    maximum: float
    n: int
    comparable: tuple[str, ...]
    grader: GraderInfo

    def sort_key(self) -> tuple[str, int]:
        return self.eval_id, list(MODELS).index(self.model)


def quartiles(scores: list[float]) -> tuple[float, float, float]:
    if len(scores) == 1:
        return scores[0], scores[0], scores[0]
    q1, median, q3 = statistics.quantiles(scores, n=4, method="inclusive")
    return q1, median, q3


def is_graded_result(document: dict[str, Any]) -> bool:
    return "eval" in document and "tasks" in document


def graded_row(result: dict[str, Any], grades: Grades, where: str) -> GradedRow:
    """The table row of one graded run. Raises ``GradedError`` when it is not accepted."""
    adapter = result["adapter"]
    model = adapter["name"].removeprefix(PREFIX)
    if not adapter["name"].startswith(PREFIX) or model not in MODELS:
        raise GradedError(f"{where}: {adapter['name']!r} is not a claude_python_<model> adapter")
    config = adapter.get("config") or {}
    if "claude_command" in config:
        raise GradedError(f"{where}: runs with a custom claude_command are not accepted")
    tasks = result["tasks"]
    problems = {
        "skipped": [t for t in tasks if t["status"] == "skipped"],
        "stopped by the runner's timeout": [t for t in tasks if t["status"] == "timeout"],
        "failed in the harness": [
            t for t in tasks
            if t["status"] == "adapter_error" and (t.get("error") or {}).get("type") in HARNESS_ERRORS
        ],
    }  # fmt: skip
    for reason, bad in problems.items():
        if bad:
            raise GradedError(f"{where}: {len(bad)} of {len(tasks)} task(s) {reason}")
    if grades.run_id != result["run_id"] or grades.eval != result["eval"]:
        raise GradedError(f"{where}: grades.json belongs to another run")
    if [t.task_id for t in grades.tasks] != [t["task_id"] for t in tasks]:
        raise GradedError(f"{where}: grades.json does not cover the run's tasks")
    if grades.stopped is not None:
        raise GradedError(f"{where}: grading stopped: {grades.stopped}")
    ungraded = [t.task_id for t in grades.tasks if t.status == "not_graded"]
    if ungraded:
        raise GradedError(f"{where}: {len(ungraded)} task(s) not graded (first: {ungraded[0]})")
    if grades.grader.passes < 2:
        raise GradedError(f"{where}: graded in {grades.grader.passes} pass(es); at least 2")
    scores = [t.score if t.score is not None else 0.0 for t in grades.tasks]
    ci = bootstrap_ci(scores) or (scores[0], scores[0])
    q1, median, q3 = quartiles(scores)
    comparable = (
        result["eval"]["version"],
        result["data_sha256"],
        result["dataset_manifest_hash"],
        str(config.get("effort", "high")),
        str(config.get("prompt_version", "v1")),
        grades.rubric_version,
        json.dumps(grades.grader.model_dump(), sort_keys=True),
    )
    return GradedRow(
        eval_id=result["eval"]["id"],
        eval_version=result["eval"]["version"],
        model=model,
        scores=tuple(scores),
        mean=sum(scores) / len(scores),
        ci_low=ci[0],
        ci_high=ci[1],
        minimum=min(scores),
        q1=q1,
        median=median,
        q3=q3,
        maximum=max(scores),
        n=len(scores),
        comparable=comparable,
        grader=grades.grader,
    )


def agreement(all_grades: list[Grades]) -> Agreement:
    """Agreement between the first two passes over every graded task of ``all_grades``."""
    close = pairs = 0
    differences: list[float] = []
    for grades in all_grades:
        for task in grades.tasks:
            if task.status != "graded" or len(task.passes) < 2:
                continue
            first, second = task.passes[0].criteria, task.passes[1].criteria
            for cid in first:
                pairs += 1
                close += abs(first[cid].score - second[cid].score) <= 1
            mean = [sum(c.score for c in p.values()) / len(p) / 4 for p in (first, second)]
            differences.append(abs(mean[0] - mean[1]))
    return Agreement(
        within_one=close / pairs if pairs else 0.0,
        mean_abs_diff=sum(differences) / len(differences) if differences else 0.0,
        pairs=pairs,
    )


def load_graded(results_dir: Path) -> tuple[list[GradedRow], dict[str, Agreement]]:
    """Every accepted graded run under ``results_dir`` and each eval's grader agreement."""
    rows: list[GradedRow] = []
    by_eval: dict[str, list[Grades]] = {}
    for path in sorted(results_dir.glob(f"*/*/{RESULT_FILE}")):
        try:
            result = load_graded_result(path)
            grades = load_grades(path.parent / GRADES_FILE)
        except (OSError, ValueError) as exc:
            raise GradedError(f"{path.parent}: cannot be read: {exc}") from exc
        rows.append(graded_row(result, grades, str(path.parent)))
        by_eval.setdefault(result["eval"]["id"], []).append(grades)
    for eval_id in sorted({row.eval_id for row in rows}):
        variants = {row.comparable for row in rows if row.eval_id == eval_id}
        if len(variants) > 1:
            raise GradedError(
                f"runs of {eval_id} are not comparable: they differ in eval version, city data, "
                "manifest, effort, prompt version, rubric version or grader"
            )
    agreements = {eval_id: agreement(grades) for eval_id, grades in by_eval.items()}
    return sorted(rows, key=GradedRow.sort_key), agreements


def _model_name(model_id: str) -> str:
    """``claude-opus-5-5`` -> ``Opus 5.5``."""
    return MODEL_NAMES.get(model_id.removeprefix("claude-").replace("-", "_"), model_id)


def render_graded(rows: list[GradedRow], agreements: dict[str, Agreement]) -> str:
    """The Markdown between the graded markers."""
    if not rows:
        return "No graded runs have been added yet. See [`evals/README.md`](evals/README.md)."
    lines = [
        "| Model | Eval | Mean (95% CI) | Min | Q1 | Median | Q3 | Max |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {MODEL_NAMES[row.model]} | `{row.eval_id}` {row.eval_version} "
            f"| {row.mean:.3f} [{row.ci_low:.2f}, {row.ci_high:.2f}] | {row.minimum:.2f} "
            f"| {row.q1:.2f} | {row.median:.2f} | {row.q3:.2f} | {row.maximum:.2f} |"
        )
    evals = sorted({row.eval_id for row in rows})
    lines.append("")
    for eval_id in evals:
        lines.append(f"![{eval_id}: task scores by model]({README_PLOTS}/{eval_id}.svg)")
    grader = rows[0].grader
    agreement_text = "; ".join(
        f"`{e}` {agreements[e].within_one:.0%} of criterion scores within 1 point, mean task-score "
        f"difference {agreements[e].mean_abs_diff:.2f}"
        for e in evals
    )
    answered_by_grader = "opus_5_5" in {row.model for row in rows}
    notes = [
        "",
        f"Graded by Claude {_model_name(grader.model)} (effort {grader.effort}, grader prompt "
        f"{grader.prompt_version}, Claude Code {grader.claude_code_version}) in "
        f"{grader.passes} passes per answer. The grader saw the task, the rubric, the reference "
        "key and the answer, never which model answered. "
        f"Agreement between passes: {agreement_text}.",
    ]
    if answered_by_grader:
        notes.append(
            "Opus 5.5 also answered these tasks, so its own rows may be biased in its favor."
        )
    notes += [
        "",
        "A task score is the mean of the rubric criteria (0 to 4) divided by 4, averaged over the "
        "passes, from 0 to 1. Tasks without an answer (errors, model timeouts, invalid output) "
        "score 0. Graded scores are not comparable with benchmark scores and are never combined "
        "with them.",
    ]
    return "\n".join(lines + notes)


def add_graded_run(run_dir: Path, results_dir: Path) -> Path:
    """Copy an accepted graded run to ``results_dir/<eval>/<adapter>/``."""
    result = load_graded_result(run_dir)
    grades = load_grades(run_dir / GRADES_FILE)
    graded_row(result, grades, str(run_dir))
    target = results_dir / result["eval"]["id"] / result["adapter"]["name"]
    target.mkdir(parents=True, exist_ok=True)
    for name in (RESULT_FILE, GRADES_FILE, CONFIG_FILE):
        if (run_dir / name).is_file():
            shutil.copyfile(run_dir / name, target / name)
    return target
```


- [ ] **Step 5: Wire the CLI and the README**

In `src/geoevals/cli.py`:

- `leaderboard add` and `leaderboard build` get `--graded` (`type=Path, default=DEFAULT_GRADED`, help "Graded leaderboard directory (default: leaderboard/graded).").
- `_leaderboard_add(run_dir, results, graded)`: read the result JSON; if `is_graded_result(document)`, call `add_graded_run(run_dir, graded)` and catch `GradedError` and `SpecValidationError` like `LeaderboardError`; else the existing path.
- `_leaderboard_build(results, readme, check, graded)`: after `updated = update_readme(...)`, add

```python
        rows, agreements = load_graded(graded)
        updated = replace_section(updated, GRADED_START, GRADED_END, render_graded(rows, agreements))
```

  and catch `GradedError` with `LeaderboardError`. (Task 12 adds the plots to this function.)

In `README.md`, after the `<!-- leaderboard:end -->` line and the leaderboard section's text, add (Task 13 writes the section's prose):

```markdown
## Graded evals (agent-graded)

<!-- graded:start -->
<!-- graded:end -->
```

Run `uv run geoevals leaderboard build` to fill it ("No graded runs have been added yet ...").

In `tests/test_docs.py::test_readme_leaderboard_is_up_to_date`, add `"--graded", str(REPO / "leaderboard" / "graded")` to the command.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_graded_board.py tests/test_leaderboard.py tests/test_docs.py -q`
Expected: all pass. Then `uv run ruff check . && uv run ruff format --check . && uv run pyright`.

- [ ] **Step 7: Commit**

```bash
git add src/geoevals/graded/board.py src/geoevals/leaderboard/table.py src/geoevals/cli.py README.md tests/test_docs.py tests/test_graded_board.py
git commit -m "feat: graded leaderboard with score quartiles and grader agreement"
```

---

### Task 12: Byte-stable SVG box plots

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (`plots` extra and dev group: matplotlib)
- Create: `src/geoevals/graded/plots.py`
- Modify: `src/geoevals/cli.py` (`leaderboard build` writes and checks the plots)
- Modify: `docs/dependency-licenses.md` (regenerated)
- Test: `tests/test_graded_plots.py`

**Interfaces:**
- Consumes: `GradedRow`, `PLOTS_DIR` (Task 11); `MODEL_NAMES`.
- Produces: `geoevals.graded.plots.box_plot_svg(title: str, series: list[tuple[str, list[float]]]) -> str`, `plot_files(rows: list[GradedRow], graded_dir: Path) -> dict[Path, str]`

- [ ] **Step 1: Add matplotlib**

Run:

```bash
uv add --optional plots "matplotlib>=3.9"
uv add --dev "matplotlib>=3.9"
```

Expected: `pyproject.toml` gains `plots = ["matplotlib>=3.9"]` under `[project.optional-dependencies]` and matplotlib in the `dev` group; `uv.lock` updates. The sandbox image hash covers `uv.lock`, so the next python-track run builds a new image (`uv export --extra network` still leaves matplotlib out of it).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_graded_plots.py`:

```python
from pathlib import Path

from geoevals.graded.plots import box_plot_svg, plot_files


def test_box_plot_svg_is_byte_stable() -> None:
    series = [("Opus 5.5", [0.2, 0.5, 0.9, 1.0]), ("Haiku 5.5", [0.1, 0.3, 0.4, 0.8])]
    first = box_plot_svg("proximity", series)
    assert first == box_plot_svg("proximity", series)
    assert first.startswith("<?xml")
    assert "<dc:date>" not in first
    assert "Opus 5.5" in first and "Haiku 5.5" in first


def test_plot_files_one_per_eval(tmp_path: Path) -> None:
    from test_graded_board import _grades, _result

    from geoevals.graded.board import graded_row
    from geoevals.graded.grader import Grades

    row = graded_row(_result(), Grades.model_validate(_grades([(4, 4)] * 4)), "w")
    files = plot_files([row], tmp_path)
    assert list(files) == [tmp_path / "plots" / "proximity.svg"]
```

Run `uv run ruff format tests/test_graded_plots.py`.

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/test_graded_plots.py -q`
Expected: `ModuleNotFoundError: No module named 'geoevals.graded.plots'`.

- [ ] **Step 4: Write `src/geoevals/graded/plots.py`**

```python
"""One SVG box plot per graded eval, every model side by side, byte-stable.

The whiskers reach the minimum and maximum (``whis=(0, 100)``) and the box spans the quartiles,
so the plot shows the same numbers as the table; a triangle marks the mean. The SVG is the same
bytes on every build: text stays text (``svg.fonttype: none``) in DejaVu Sans, which matplotlib
ships, element IDs come from a fixed hash salt, and the date and creator metadata are left out.
Needs the ``plots`` extra (``uv sync --extra plots``).
"""

import io
from pathlib import Path
from typing import Any

from geoevals.graded.board import PLOTS_DIR, GradedRow
from geoevals.leaderboard.table import MODEL_NAMES

RC: dict[str, Any] = {
    "svg.hashsalt": "geoevals",
    "svg.fonttype": "none",
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "path.simplify": False,
}
FIGSIZE = (6.4, 3.6)


def box_plot_svg(title: str, series: list[tuple[str, list[float]]]) -> str:
    """The SVG text of a box plot of ``series`` (label, task scores in [0, 1])."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with matplotlib.rc_context(RC):
        fig, ax = plt.subplots(figsize=FIGSIZE)
        ax.boxplot(
            [scores for _, scores in series],
            tick_labels=[label for label, _ in series],
            whis=(0, 100),
            showmeans=True,
        )
        ax.set_ylim(0, 1)
        ax.set_ylabel("Task score")
        ax.set_title(f"{title}: task scores by model")
        buffer = io.StringIO()
        fig.savefig(buffer, format="svg", metadata={"Date": None, "Creator": None})
        plt.close(fig)
    return buffer.getvalue()


def plot_files(rows: list[GradedRow], graded_dir: Path) -> dict[Path, str]:
    """``graded_dir/plots/<eval>.svg`` -> its SVG text, for every eval in ``rows``."""
    files: dict[Path, str] = {}
    for eval_id in sorted({row.eval_id for row in rows}):
        series = [(MODEL_NAMES[r.model], list(r.scores)) for r in rows if r.eval_id == eval_id]
        files[graded_dir / PLOTS_DIR / f"{eval_id}.svg"] = box_plot_svg(eval_id, series)
    return files
```

- [ ] **Step 5: Write and check the plots in `leaderboard build`**

In `_leaderboard_build`, after rendering the graded section:

```python
        plots = plot_files(rows, graded) if rows else {}
        stale = [
            path for path, svg in plots.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != svg
        ]  # fmt: skip
```

Treat the build as out of date when `updated != text or stale`; with `--check`, print each stale plot (`f"{path}: plot is out of date"`); otherwise write the README and each stale plot (`path.parent.mkdir(parents=True, exist_ok=True)`). Import `plot_files` inside the function so that the CLI works without the `plots` extra when there are no graded rows; if the import fails with rows present, print "the graded box plots need matplotlib: uv sync --extra plots" and return 1.

- [ ] **Step 6: Regenerate the dependency license report**

Run: `uv run geoevals data licenses --out docs/dependency-licenses.md`
Expected: exit 0 (matplotlib and its dependencies are permissively licensed). If it fails on an unrecognized license string, read the report: an allowed license that the tool does not recognize is a tool fix in `geoevals.data.licenses` (add the string to its allowed list); a GPL or AGPL dependency means stop and ask the user.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_graded_plots.py tests/test_graded_board.py tests/test_docs.py tests/test_dependency_licenses.py -q`
Expected: all pass. Then `uv run ruff check . && uv run ruff format --check . && uv run pyright`.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/geoevals/graded/plots.py src/geoevals/cli.py docs/dependency-licenses.md tests/test_graded_plots.py
git commit -m "feat: byte-stable SVG box plots of graded scores"
```

---

### Task 13: Docs and policy: benchmarks versus graded evals

**Files:**
- Create: `docs/eval-authoring.md`, `evals/README.md`
- Modify: `README.md`, `CONTRIBUTING.md`, `docs/best-practices.md`, `docs/data-governance.md`, `ROADMAP.md`, `leaderboard/README.md`, `CHANGELOG.md`, `.github/workflows/ci.yml`
- Modify: `tests/test_docs.py` (`REQUIRED_DOCS` gains `eval-authoring.md`; README section checks)

**Interfaces:**
- Consumes: the commands and files of Tasks 1 to 12.
- Produces: the written policy (the spec's five graded-eval rules) in `docs/eval-authoring.md`, `CONTRIBUTING.md` and `docs/best-practices.md`.

- [ ] **Step 1: Write the failing docs tests**

In `tests/test_docs.py`, add `"eval-authoring.md"` to `REQUIRED_DOCS`, and add:

```python
GRADED_RULES = [
    "Use a benchmark when a task has one checkable answer",
    "reference key of facts computed from the data",
    "never averaged with them",
    "graded at least twice",
    "its own rows may be biased",
]


def test_graded_eval_rules_are_written_down() -> None:
    authoring = (REPO / "docs" / "eval-authoring.md").read_text(encoding="utf-8")
    contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for rule in GRADED_RULES:
        assert rule in authoring, rule
    assert "docs/eval-authoring.md" in contributing
    practices = (REPO / "docs" / "best-practices.md").read_text(encoding="utf-8")
    assert "Do not use an LLM judge as the only evaluator" not in practices
    assert "graded eval" in practices


def test_readme_separates_benchmarks_and_graded_evals() -> None:
    headings = re.findall(r"^## (.+)$", README.read_text(encoding="utf-8"), re.M)
    assert "Benchmarks (deterministic)" in headings
    assert "Graded evals (agent-graded)" in headings
    assert headings.index("Graded evals (agent-graded)") > headings.index("Leaderboard")
```

Run: `uv run pytest tests/test_docs.py -q`
Expected: FAIL (`eval-authoring.md` missing, headings missing).

- [ ] **Step 2: Write `docs/eval-authoring.md`**

```markdown
# Graded eval authoring

GeoEvals has two kinds of evaluation. This guide covers the second.

| | Benchmark | Graded eval |
| --- | --- | --- |
| Task | One checkable answer | An open-ended answer |
| Scored by | Code: deterministic metrics against an expected output and tolerances | A grading agent, against a rubric and a reference key computed from data |
| Lives in | `benchmarks/` ([`benchmark-authoring.md`](benchmark-authoring.md)) | `evals/` (this guide) |
| Reported in | The leaderboard table | The graded-evals table and box plots |

The two are never combined: no shared score, no shared table, no shared directory.

## Rules

1. Use a benchmark when a task has one checkable answer. Use a graded eval only when the answer
   is open-ended.
2. Every graded task has a rubric with written anchors for each score, and a reference key of
   facts computed from the data by a committed reference script, never written by hand.
3. Graded scores are reported apart from benchmark scores and never averaged with them.
4. Each answer is graded at least twice, and the report states the grader's agreement with
   itself, the grader model, its effort, the grader prompt version and the Claude Code version.
5. When the grader is one of the graded models, the report says so: its own rows may be biased.

## What an eval holds

An eval is a directory `evals/<id>/` with:

- `eval.yaml`: the spec (`schemas/eval-spec.schema.json`): ID, version, concept, task
  statement, word limit, and the paths of its tasks, the shared rubric criteria, the reference
  script and the city's dataset manifest.
- `tasks.jsonl`: one task per line: `task_id`, `prompt`, `audience`, `location` (sent to the
  model), `key_type` and `params` (the reference script's input, hidden from the model),
  `rubric` (criterion IDs), optional `anchors` for the task, `key_sha256` and `strata`.

The evals on the city share `evals/city/rubric_criteria.yaml` (five criteria, each 0 to 4 with
written anchors) and `evals/city/reference.py` (six key types: proximity, containment,
adjacency, closure, visibility, direction).

## Write a task

1. Pick a place in the city and a question whose answer needs spatial reasoning, not lookup.
   The data is a whole city, so the model has to find what bears on the question.
2. Write the `prompt` as a person would ask it, and name the `audience`.
3. Choose the `key_type` and write the `params` that compute the facts a correct answer must
   agree with. Check the key against a map before relying on it.
4. List the criteria that score the task (usually all five) and add task `anchors` where the
   shared ones are too general, for example what a 4 on assumptions needs here.

## Compute the keys

Keys come from OpenStreetMap data, so they are not committed (see
[`data-governance.md`](data-governance.md)). Fetch the city and build its layers, then compute
the keys:

```sh
uv run geoevals data fetch osm_city_<town>
uv run geoevals evals build-city osm_city_<town>
uv run geoevals evals regenerate <eval id>          # writes data/raw/osm_city_<town>/keys/
uv run geoevals evals regenerate <eval id> --check  # exit 1 when a key_sha256 is stale
```

`regenerate` records each key's SHA-256 in `tasks.jsonl`. Grading refuses keys whose hash does
not match, so a reviewer always grades against the keys the tasks were reviewed with.

## Run and grade

```sh
uv run geoevals run --eval evals/<id>/eval.yaml --adapter claude_python_opus_5_5 \
  --config leaderboard/configs/python.yaml --out runs/graded
uv run geoevals grade runs/graded/<run_id>
uv run geoevals leaderboard add runs/graded/<run_id>
uv run geoevals leaderboard build
```

Graded evals run on the python track only: the city is mounted read-only in the sandbox at
`/bench/data`. `geoevals grade` runs Claude Opus 5.5 (effort high) in its own `claude -p`
session per answer and pass, with no tools and the leaderboard's isolation. The grader sees the
task, the rubric, the key and the answer, never which model answered. Each answer is graded
twice; an error or invalid grade is retried once, and a task that still has no grade leaves the
run off the leaderboard.

## Review and versions

The rubric, the tasks and their keys are reviewed before an eval's first version is frozen.
A change to a task, a key, the rubric or the reference script changes scores, so it is a minor
version change of the eval, as for benchmarks
([`reproducibility.md`](reproducibility.md#version-rules)). Runs graded by different grader
versions are not comparable, and the leaderboard build rejects a mix.
```

- [ ] **Step 3: Write `evals/README.md`**

```markdown
# Graded evals

Open-ended spatial-reasoning tasks on one real city, scored by a grading agent (Claude Opus
5.5) against a rubric and a reference key computed from the city's OpenStreetMap data. They are
reported apart from the deterministic benchmarks in `benchmarks/` and never combined with them.

| Directory | What it holds |
| --- | --- |
| `city/rubric_criteria.yaml` | The five criteria every task is scored on, each 0 to 4 with anchors |
| `city/reference.py` | Computes each task's reference key from the city's layers |
| `<eval>/eval.yaml`, `<eval>/tasks.jsonl` | One eval: its spec and its tasks |

The city's data and the keys are not committed (ODbL); `geoevals data fetch` and `geoevals
evals regenerate` recreate them. How to write, run and grade an eval:
[`docs/eval-authoring.md`](../docs/eval-authoring.md).
```

- [ ] **Step 4: Update the README**

- Rename `## Available benchmarks` to `## Benchmarks (deterministic)` and add as its first paragraph: "Each benchmark task has one checkable answer, scored by code against an expected output and stated tolerances. Open-ended tasks are graded evals instead (see [Graded evals](#graded-evals-agent-graded))."
- Under `## Graded evals (agent-graded)` (added in Task 11), above the markers, add:

```markdown
Open-ended spatial-reasoning tasks on a real city (proximity, adjacency, visibility,
containment, direction), answered by Claude models on the python track with the whole city
mounted, and scored by Claude Opus 5.5 against a rubric and a reference key computed from the
data. Each answer is graded twice. The table shows each model's distribution of task scores
(0 to 1); the box plots show the same numbers. Graded scores measure something different from
benchmark scores and are never combined with them. How evals are written and graded:
[`docs/eval-authoring.md`](docs/eval-authoring.md).
```

- In `## Documentation`, add a line for `docs/eval-authoring.md` in the list's style.
- In `## Add a benchmark, metric, adapter or dataset manifest`, add: "- **Graded eval:** an open-ended task set under `evals/`; see [`docs/eval-authoring.md`](docs/eval-authoring.md). Use one only when a task has no single checkable answer."

- [ ] **Step 5: Update CONTRIBUTING, best practices, governance, roadmap, leaderboard README**

- `CONTRIBUTING.md`: add a section `## Benchmark or graded eval?` before `## Benchmark definition of done`:

```markdown
## Benchmark or graded eval?

Contribute a **benchmark** when every task has one checkable answer: code scores it, and it is
the default. Contribute a **graded eval** only when the answer is open-ended (an explanation,
directions, a judgment about what can be seen or reached); a grading agent scores it against a
rubric and a reference key computed from data. Graded evals follow the rules in
[`docs/eval-authoring.md`](docs/eval-authoring.md#rules), and their scores are never combined
with benchmark scores.
```

- `docs/best-practices.md`: in the metric-choice table row `| Agent success | Exact output checks, task completion, valid artifact rate | Do not use an LLM judge as the only evaluator. |`, replace the last cell with `Use deterministic checks when there is one checkable answer. An LLM grader is allowed only in a graded eval that follows the graded-eval rules ([eval-authoring.md](eval-authoring.md#rules)).`
- `docs/data-governance.md`: in `## Restricted data`, add after the OSM paragraph: "The graded evals use a whole-town OpenStreetMap extract (`osm_city_<town>`). Its layers and the evals' reference keys are derived data, so they stay in `data/raw/osm_city_<town>/`; `tasks.jsonl` commits only each key's SHA-256. Task prompts name features by their OSM name and ID, as a citation would." In `## Secrets and personal data`, extend the Claude paragraph: "In a graded eval, the python-track model also reads the town's OpenStreetMap layers in its sandbox, and what it prints is sent to Anthropic as part of the conversation; OpenStreetMap data is public and ODbL licensed, and no personal data is sent."
- `ROADMAP.md`: in `### Vector benchmark on OpenStreetMap data`, add: "The graded evals already pin and fetch a whole-town OpenStreetMap snapshot (`geoevals data fetch osm_city_<town>`, `geoevals evals build-city`); this benchmark reuses that fetch." Add a `### Graded evals on a real city` item: "Five agent-graded evals (proximity, adjacency, visibility, containment, direction) on one pinned town, 12 tasks each, graded by Claude Opus 5.5; see `docs/eval-authoring.md`." Then update `tests/test_docs.py::test_roadmap_lists_the_phase_5_items` only if it requires an exact list (it checks membership, so a new item passes).
- `leaderboard/README.md`: add a section `## Graded evals` after `## What the numbers mean`: how to run (`geoevals run --eval`), grade (`geoevals grade`), add (`geoevals leaderboard add` puts graded runs in `leaderboard/graded/<eval>/<adapter>/` with `grades.json`) and build; the acceptance rules from `geoevals.graded.board`'s docstring; and that a full graded run of one model is 60 answers and 120 grading sessions on the subscription.

- [ ] **Step 6: Changelog and CI**

`CHANGELOG.md`, under `## Unreleased`, add an `### Added` entry list (or extend the existing `### Added`):

```markdown
#### Graded evals

- Agent-graded spatial-reasoning evals, reported apart from the benchmarks: `geoevals evals
  measure-town`, `evals build-city`, `evals regenerate`, `geoevals run --eval`, `geoevals
  grade`, and a graded section in `geoevals leaderboard build` (quartile table and SVG box
  plots). Schemas `schemas/eval-spec.schema.json` 1.0.0 and `schemas/graded-result.schema.json`
  1.0.0. The python-track adapters take `prompt: graded` and `data_mount`. New optional extra
  `plots` (matplotlib). See `docs/eval-authoring.md`.
```

`.github/workflows/ci.yml`: in the "Validate benchmark specs and dataset manifests" step, add `evals` to the `find` roots and `-o -name 'eval.yaml'` to the name filter, and rename the step "Validate benchmark specs, eval specs and dataset manifests". With no eval directories yet the step still finds the benchmark files. The step's own error message stays.

- [ ] **Step 7: Run the docs tests and the full suite**

Run: `uv run pytest -q`
Expected: all pass. Then `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run geoevals leaderboard build --check`.

- [ ] **Step 8: Commit**

```bash
git add docs/eval-authoring.md evals/README.md README.md CONTRIBUTING.md docs/best-practices.md docs/data-governance.md ROADMAP.md leaderboard/README.md CHANGELOG.md .github/workflows/ci.yml tests/test_docs.py
git commit -m "docs: separate deterministic benchmarks from agent-graded evals"
```

---

### Task 14: End-to-end check on the synthetic city

**Files:**
- Test: `tests/test_graded_end_to_end.py`

**Interfaces:**
- Consumes: everything above.
- Produces: one test that runs the whole chain with the mock adapter and the fake CLI.

- [ ] **Step 1: Write the test**

Create `tests/test_graded_end_to_end.py`:

```python
import json
from pathlib import Path

import pytest
import yaml
from claude_fakes import FAKE_COMMAND, FakeClaude, init_event, result_event
from graded_helpers import copy_sample_eval, sample_data

from geoevals.cli import main
from geoevals.graded.board import load_graded
from geoevals.graded.grader import GRADER_MODEL
from geoevals.graded.keys import regenerate_keys

IDS = ["relations", "reasoning", "assumptions", "data_use", "clarity"]
ANSWER = {"status": "ok", "answer": "North Pharmacy (node/500) is nearest on foot."}


def test_run_grade_add_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec_path = copy_sample_eval(tmp_path / "evals")
    data = sample_data(tmp_path)
    regenerate_keys(spec_path, data)
    config = tmp_path / "config.yaml"
    references = {f"sample-00{i}": ANSWER for i in (1, 2, 3)}
    config.write_text(yaml.safe_dump({"split": "test", "adapter": {"references": references}}))
    assert (
        main(
            [
                "run",
                "--eval",
                str(spec_path),
                "--adapter",
                "mock",
                "--config",
                str(config),
                "--out",
                str(tmp_path / "runs"),
                "--data",
                str(data),
            ]
        )
        == 0
    )
    [run_dir] = list((tmp_path / "runs").iterdir())

    fake = FakeClaude(tmp_path, monkeypatch)
    grade = {"criteria": {i: {"score": 3, "justification": "key agrees"} for i in IDS}}
    fake.set([init_event(), result_event(grade, model_usage={GRADER_MODEL: {"outputTokens": 9}})])
    monkeypatch.setattr("geoevals.cli.GRADER_COMMAND", FAKE_COMMAND)
    assert (
        main(["grade", str(run_dir), "--data", str(data), "--evals", str(tmp_path / "evals")]) == 0
    )
    grades = json.loads((run_dir / "grades.json").read_text())
    assert [t["score"] for t in grades["tasks"]] == [0.75, 0.75, 0.75]
    assert len(fake.records) == 6

    # The mock adapter is not a leaderboard adapter: the board rejects it by name.
    graded = tmp_path / "board"
    assert main(["leaderboard", "add", str(run_dir), "--graded", str(graded)]) == 1
    result = json.loads((run_dir / "result.json").read_text())
    result["adapter"]["name"] = "claude_python_haiku_5_5"
    (run_dir / "result.json").write_text(json.dumps(result))
    assert main(["leaderboard", "add", str(run_dir), "--graded", str(graded)]) == 0
    rows, agreements = load_graded(graded)
    assert [(r.model, r.mean) for r in rows] == [("haiku_5_5", 0.75)]
    assert agreements["sample"].within_one == 1.0
```

Run `uv run ruff format tests/test_graded_end_to_end.py`.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_graded_end_to_end.py -q`
Expected: PASS. A failure here means two tasks disagree about a name or a type; fix the producing task's code to match its **Interfaces** block, not the test.

- [ ] **Step 3: Run the whole suite and the checks CI runs**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run geoevals leaderboard build --check && uv run geoevals data inventory --check`
Expected: all pass, with no change to the benchmark leaderboard table.

- [ ] **Step 4: Commit**

```bash
git add tests/test_graded_end_to_end.py
git commit -m "test: graded evals end to end on the synthetic city"
```

---

## After this plan

- **Checkpoint 1 (user):** run `geoevals evals measure-town` for two or three candidate towns (20,000 to 100,000 people, no world-famous landmarks) and pick one.
- **Plan 2** (written after the pick): the town's dataset manifest `datasets/manifests/osm_city_<town>.yaml` and its download instructions; the five `evals/<concept>/eval.yaml`; drafting the 60 tasks and computing their keys (checkpoint 2: the user reviews prompts, rubrics and anchors before 0.1.0); the pilot (Opus, one task per eval, two-pass grading); then the full runs, Opus first, Sonnet and Haiku each on the user's go-ahead.
