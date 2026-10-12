# Oregon City Graded Evals Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin Oregon City, Oregon, as the graded evals' city, add a review-sheet tool, and draft the five evals (60 tasks) for the user's review at checkpoint 2. After the user's review and go-ahead, run the pilot.

**Architecture:** The city comes from the Geofabrik extract `oregon-261011.osm.pbf` through the existing `geoevals data fetch osm_city_<town> --pbf` path (PR #7). Its manifest pins the derived `osm_extract.json` by SHA-256. A new `geoevals evals review` command writes a gitignored Markdown review sheet with a map per task and automatic warnings. Task drafting uses uncommitted finder scripts that call `evals/city/reference.py`. Only `eval.yaml` and `tasks.jsonl` (prompts, params, key hashes) are committed. Keys, layers and review sheets stay in `data/raw/`.

**Tech Stack:** Python 3.11, geopandas, shapely, networkx, pyosmium, matplotlib (the `plots` extra), pytest, ruff, pyright, uv.

**Spec:** `docs/superpowers/specs/2026-10-10-graded-evals-design.md` (approved 2026-10-11). Engine plan: `docs/superpowers/plans/2026-10-11-graded-evals-engine.md`. Authoring guide: `docs/eval-authoring.md`.

## Global Constraints

- Work in the worktree `/Users/jason/code/GeoEvals-graded` on branch `feat/oregon-city-evals`. Never rewrite history (no rebase, amend or force-push).
- No attribution trailers (Co-Authored-By etc.) in commits or PR bodies. American English everywhere.
- Do not change `evals/city/reference.py`, `evals/city/rubric_criteria.yaml`, the walk-barrier rules or any benchmark without the user's explicit approval. If a task cannot be written without such a change, stop and report.
- Nothing OpenStreetMap-derived is committed except task prompts and params that name OSM features by name and ID (maintainer decision 2026-10-12, `docs/data-governance.md`). Layers, keys, extracts and review sheets stay under the gitignored `data/raw/`.
- No model runs (`geoevals run`, `geoevals grade`) without the user's go-ahead, per run.
- The city: `osm_city_oregon_city`, OSM relation 186594, bbox `-122.6400863,45.3110543,-122.5430931,45.3805715`, snapshot `2026-10-11` (replication timestamp `2026-10-11T20:21:06Z`).
- The source file: `oregon-261011.osm.pbf`, 254,366,080 bytes, SHA-256 `7f70f5800df8e49155bf2b253fb731e1789ef1b83c0683358e37960b08864000`, URL `https://download.geofabrik.de/north-america/us/oregon-261011.osm.pbf`.
- Spec values: 12 tasks per eval, 60 in total; each eval at version `0.1.0`; `answer_word_limit: 4000`; rubric = the five shared criteria `relations`, `reasoning`, `assumptions`, `data_use`, `clarity`.
- Checks before every commit: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, and the touched tests. Run the full `uv run pytest` before each PR.

## Review Focus

These are the failure modes most likely to bite the user that no unit test on the synthetic city catches. Each one has a warning in `geoevals evals review` (Task 2) or a manual check in the drafting tasks.

- A key that depends on a connection OSM lacks, such as an unmapped crosswalk, the Municipal Elevator or a private path. The walk then detours absurdly and the key contradicts reality. Warn when a walk is more than 3 times the straight line, and check it on the map.
- A task near the edge of the city box, where streets are cut off and walks detour around the missing network. Warn when a task's location is within 300 m of the box edge.
- Two tasks with the same key type and params. They duplicate each other and double-weight one fact. Warn on duplicates within an eval.
- A visibility task where every target is undecided because heights are unknown. It's only useful when that's the point of the task (tier `infer`). Warn when every target is `null`.
- A prompt that gives away the key, by stating the distance, the answer or the blocking building. This is a manual check in each drafting task's review step. It can't be automated.

---

## Drafting conventions (apply to Tasks 3 to 7)

**Tiers** (from the Waterloo study's use of Piaget's levels; one per task, in `strata.tier`). Each eval has 4 tasks of each tier.

| Tier | The answer needs | Example |
| --- | --- | --- |
| `describe` | One spatial fact read correctly from the data | "Which pharmacy is nearest to me on foot?" |
| `analyze` | Two measures or relations compared | "Is the pharmacy that looks nearest on the map also nearest on foot?" |
| `infer` | A conclusion beyond the computed facts: a consequence, a judgment under missing data, a recommendation | "The Oregon City Bridge is closing for a month. Should I still walk to the West Linn library?" |

**Traps** (`strata.trap`: `none`, `layer` or `ambiguity`). Each eval has at least 2 `layer` tasks and at least 1 `ambiguity` task.

- `layer`: a tempting wrong layer exists. Examples: residential land use against actual buildings, a protected area against an administrative boundary, or a park polygon against the park's `leisure=playground` inside it. Add an anchor on `data_use` naming the right layer.
- `ambiguity`: the prompt leaves one term open ("near", "closest", "coffee"). The key uses the most natural reading. Add an anchor on `assumptions`: a 4 needs the reading stated, or both readings answered.

**Other strata:** each eval adds one label of its own (listed in its task), for example `barrier: river | rail | none`.

**Prompts:**
- Write 1 to 3 sentences in a real person's voice.
- Name features by their OSM `name` as they appear in the data. Never state a distance, a feature ID or the answer.
- The `location` carries the point and the feature IDs the model needs. Prompts can say "the marked point".

**Audiences** (vary them; each eval uses at least 4): "a resident with no GIS background", "a visitor to Oregon City", "a city planner", "a high school geography class", "an emergency dispatcher", "a real estate agent", "a wheelchair user's caregiver".

**Avoid:**
- tasks whose real-world answer uses a connection the network lacks (see Review Focus)
- tasks within 300 m of the box edge
- features whose name is missing, unless the location gives their ID

**Task line format** (one JSON object per line, keys in this order). `key_sha256` is `null` until `regenerate`:

```json
{"task_id": "proximity-001", "prompt": "...", "audience": "...", "location": {"point": [lon, lat], "feature_ids": []}, "key_type": "proximity", "params": {...}, "rubric": ["relations", "reasoning", "assumptions", "data_use", "clarity"], "anchors": {}, "key_sha256": null, "strata": {"tier": "describe", "trap": "none", "barrier": "river"}}
```

`location.point` uses 7 decimals. Write points with `drafting.lonlat()`.

---

### Task 1: Pin `osm_city_oregon_city`

**Files:**
- Create: `datasets/manifests/osm_city_oregon_city.yaml`
- Create: `datasets/download_instructions/osm_city_oregon_city.md`
- Modify: `datasets/README.md` (regenerated by `geoevals data inventory`)
- Modify: `ROADMAP.md` (the "no town is pinned yet" sentence)
- Modify: `docs/data-governance.md` (the `osm_city_<town>` paragraph)
- Modify: `docs/eval-authoring.md` ("Compute the keys")

**Interfaces:**
- Consumes: `geoevals data fetch <id> --pbf FILE`, `geoevals evals build-city <id>`, `geoevals data inventory` (all existing).
- Produces: `data/raw/osm_city_oregon_city/{osm_extract.json,fetch.json,manifest.yaml,layers/*.parquet}` in the worktree; the committed manifest with the real `sha256`.

- [ ] **Step 1: Move the source extract to a neutral place in the main checkout**

```bash
mkdir -p /Users/jason/code/GeoEvals/data/raw/oregon
mv /Users/jason/code/GeoEvals/data/raw/osm_city_bend/oregon-261011.osm.pbf /Users/jason/code/GeoEvals/data/raw/oregon/
rm /Users/jason/code/GeoEvals/data/raw/osm_city_bend/bend-261011.osm.pbf
rmdir /Users/jason/code/GeoEvals/data/raw/osm_city_bend
shasum -a 256 /Users/jason/code/GeoEvals/data/raw/oregon/oregon-261011.osm.pbf
```

Expected: `7f70f5800df8e49155bf2b253fb731e1789ef1b83c0683358e37960b08864000`. Stop if it differs.

- [ ] **Step 2: Write the manifest with a placeholder checksum**

`datasets/manifests/osm_city_oregon_city.yaml`:

```yaml
schema_version: "1.0.0"
dataset_id: osm_city_oregon_city
description: >-
  Every tagged OpenStreetMap feature of Oregon City, Oregon, USA (OSM relation 186594, its
  bounding box), for the graded spatial-reasoning evals. Read from Geofabrik's dated Oregon
  extract of 2026-10-11 by `geoevals data fetch osm_city_oregon_city --pbf <extract>`. Licensed
  under the ODbL and never committed: the extract, the layers and the reference keys stay in the
  gitignored data/raw/osm_city_oregon_city/. See
  datasets/download_instructions/osm_city_oregon_city.md.
assets:
  - asset_id: osm_extract
    path: ../../data/raw/osm_city_oregon_city/osm_extract.json
    source_url: https://download.geofabrik.de/north-america/us/oregon-261011.osm.pbf
    citation: OpenStreetMap contributors. OpenStreetMap data, Geofabrik extract oregon-261011.osm.pbf, https://www.openstreetmap.org/copyright
    access_date: 2026-10-12
    license: ODbL-1.0
    attribution: © OpenStreetMap contributors
    redistributable: false
    sha256: "0000000000000000000000000000000000000000000000000000000000000000"
    crs: EPSG:4326
    bbox: [-122.6400863, 45.3110543, -122.5430931, 45.3805715]
    time_range:
      start: 2026-10-11
      end: 2026-10-11
    processing_steps:
      - Downloaded oregon-261011.osm.pbf from Geofabrik (254,366,080 bytes, SHA-256 7f70f5800df8e49155bf2b253fb731e1789ef1b83c0683358e37960b08864000, replication timestamp 2026-10-11T20:21:06Z).
      - Read by geoevals.data.pbf.read_pbf for the bounding box (tagged nodes in the box; ways with a node in the box or crossing it, with full geometry; multipolygon relations and boundary relations of admin level 8 to 11 or none with a member in the box) and normalized by geoevals.data.fetch.normalize_overpass before the SHA-256 is taken.
    split: test
    known_limitations:
      - Geofabrik keeps dated daily extracts for a limited time; the SHA-256 above identifies the file if it has to be obtained elsewhere.
      - The bounding box of the city limits also covers parts of West Linn, Gladstone and unincorporated Clackamas County.
      - OpenStreetMap completeness varies; most buildings have no height or levels tag, so many visibility questions are undecidable from the data by design.
```

Check the placeholder passes validation: `uv run geoevals validate datasets/manifests/osm_city_oregon_city.yaml`. If the schema rejects all zeros, use any 64-hex string. Step 4 replaces it anyway.

- [ ] **Step 3: Fetch from the extract**

```bash
cd /Users/jason/code/GeoEvals-graded
uv run geoevals data fetch osm_city_oregon_city --pbf /Users/jason/code/GeoEvals/data/raw/oregon/oregon-261011.osm.pbf
```

Expected:
- it prints `data/raw/osm_city_oregon_city/osm_extract.json: <bytes> bytes, sha256 <hex>`
- a warning that the committed manifest records a different sha256, which is expected with the placeholder

The command takes about 90 seconds.

- [ ] **Step 4: Record the checksum and confirm a second read gives the same bytes**

Put the printed `<hex>` into the manifest's `sha256`. Then run the fetch again (same command):

Expected: the same sha256 and **no warning**. If the second read differs, stop: the read isn't reproducible and the design requires it.

- [ ] **Step 5: Build the layers and spot-check them**

```bash
uv run geoevals evals build-city osm_city_oregon_city
uv run python -c "
import geopandas as gpd
d='data/raw/osm_city_oregon_city/layers/'
b=gpd.read_parquet(d+'buildings.parquet'); print(len(b), (b.height_source!='unknown').sum())
print(sorted(gpd.read_parquet(d+'water.parquet').query('water_kind==\"river\"').name.dropna().unique()))
"
```

Expected:
- `wrote 10 layers`
- 26212 buildings, 1993 with height or levels
- rivers `['Clackamas River', 'Willamette Falls Canal', 'Willamette River']`

These numbers come from the 2026-10-12 measurement. A difference means the read changed; stop and report.

- [ ] **Step 6: Write the download instructions**

`datasets/download_instructions/osm_city_oregon_city.md`:

````markdown
# Download instructions: `osm_city_oregon_city`

The graded evals run on Oregon City, Oregon, USA, read from an OpenStreetMap (OSM) extract. OSM
data is licensed under the Open Database License (`ODbL-1.0`) and must be attributed as
"© OpenStreetMap contributors". Neither the extract nor anything built from it (layers, keys)
is committed; all of it stays in the gitignored `data/raw/`.

## What is used

| Field | Value |
| --- | --- |
| Source | Geofabrik, `https://download.geofabrik.de/north-america/us/oregon-261011.osm.pbf` (254,366,080 bytes, SHA-256 `7f70f5800df8e49155bf2b253fb731e1789ef1b83c0683358e37960b08864000`) |
| Snapshot | Replication timestamp 2026-10-11T20:21:06Z |
| Area | The bounding box of OSM relation 186594 (Oregon City): `[-122.6400863, 45.3110543, -122.5430931, 45.3805715]` |
| Contents | Every tagged feature in the box (see `geoevals.data.pbf`) |
| License | `ODbL-1.0`, attribution "© OpenStreetMap contributors", `redistributable: false` |

## Steps

```sh
curl -o data/raw/oregon/oregon-261011.osm.pbf \
  https://download.geofabrik.de/north-america/us/oregon-261011.osm.pbf
shasum -a 256 data/raw/oregon/oregon-261011.osm.pbf     # must match the SHA-256 above
uv run geoevals data fetch osm_city_oregon_city --pbf data/raw/oregon/oregon-261011.osm.pbf
uv run geoevals evals build-city osm_city_oregon_city
uv run geoevals evals regenerate <eval id> --check      # every eval's keys match its tasks
```

Geofabrik keeps dated daily extracts for a limited time. If the file is gone, any copy with the
same SHA-256 gives the same city.
````

- [ ] **Step 7: Update the docs that say no town is pinned**

- `ROADMAP.md`: replace "but no town is pinned yet; this benchmark can reuse that fetch." with "and the graded evals pin Oregon City, Oregon (`osm_city_oregon_city`, from Geofabrik's 2026-10-11 extract); this benchmark can reuse that fetch."
- `docs/data-governance.md`: append to the paragraph starting "The graded evals will use a whole-town OpenStreetMap extract": "The town is Oregon City, Oregon (`datasets/manifests/osm_city_oregon_city.yaml`), read from Geofabrik's dated Oregon extract."
- `docs/eval-authoring.md`, section "Compute the keys": after the `uv run geoevals data fetch osm_city_<town>` line, add `uv run geoevals data fetch osm_city_<town> --pbf <extract>   # or read a local dated .osm.pbf`.

- [ ] **Step 8: Regenerate the inventory, validate, test**

```bash
uv run geoevals data inventory
uv run geoevals data inventory --check
uv run geoevals validate datasets/manifests/osm_city_oregon_city.yaml
uv run pytest -q tests/test_docs.py tests/test_dataset_manifest.py tests/test_inventory.py
git status --short   # data/raw/ must not appear
```

Expected: everything passes, and `git status` lists only the five files above plus `datasets/README.md`.

- [ ] **Step 9: Commit**

```bash
git add datasets/manifests/osm_city_oregon_city.yaml datasets/download_instructions/osm_city_oregon_city.md datasets/README.md ROADMAP.md docs/data-governance.md docs/eval-authoring.md
git commit -m "data: pin Oregon City from Geofabrik's 2026-10-11 Oregon extract"
```

---

### Task 2: `geoevals evals review`, the review sheet

**Files:**
- Create: `src/geoevals/graded/review.py`
- Modify: `src/geoevals/cli.py` (a `review` subcommand under `evals`, next to `regenerate`)
- Modify: `docs/eval-authoring.md` (a "Review the drafts" section after "Compute the keys")
- Test: `tests/test_graded_review.py`

**Interfaces:**
- Consumes: `geoevals.graded.keys.load_keys(spec_path, data_dir) -> dict[str, dict]` (raises `KeysError`), `geoevals.graded.spec.load_tasks(spec_path, spec)`, `spec_file`, `geoevals.validation.load_eval_spec`, `load_dataset_manifest`, `geoevals.graded.city.load_layers`, `LAYERS_DIR`, `geoevals.data.fetch.ensure_ignored`.
- Produces:
  - `key_warnings(key_type: str, key: dict) -> list[str]`
  - `task_warnings(tasks: list[EvalTask], bbox: tuple[float, float, float, float]) -> dict[str, list[str]]`
  - `review_sheet(spec_path: Path, data_dir: Path) -> Path`, which writes `<data_dir>/review/<eval id>.md` and `<data_dir>/review/<eval id>/<task id>.png`
  - CLI: `geoevals evals review <eval id> [--root evals] [--data DIR]`

- [ ] **Step 1: Write the failing tests**

`tests/test_graded_review.py`:

```python
import json
from pathlib import Path

import pytest

from geoevals.cli import main
from geoevals.graded.keys import regenerate_keys
from geoevals.graded.review import key_warnings, review_sheet, task_warnings
from geoevals.graded.spec import load_tasks
from geoevals.validation import load_eval_spec
from graded_city import BBOX
from graded_helpers import copy_sample_eval, sample_data


def _reviewed(tmp_path: Path) -> tuple[Path, Path]:
    spec_path = copy_sample_eval(tmp_path / "evals")
    data = sample_data(tmp_path)
    regenerate_keys(spec_path, data)
    return spec_path, data


def test_review_sheet_lists_every_task_with_its_key_and_a_map(tmp_path: Path) -> None:
    spec_path, data = _reviewed(tmp_path)
    sheet = review_sheet(spec_path, data)
    assert sheet == data / "review" / "sample.md"
    text = sheet.read_text(encoding="utf-8")
    for task_id in ("sample-001", "sample-002", "sample-003"):
        assert f"## {task_id}" in text
        assert (data / "review" / "sample" / f"{task_id}.png").stat().st_size > 0
    assert "North Pharmacy" in text, "the key is shown"
    assert "© OpenStreetMap contributors" in text


@pytest.mark.parametrize(
    ("key_type", "key", "warning"),
    [
        (
            "proximity",
            {"walking_nearest": None, "unreachable": ["node/1"], "by_walking": [],
             "by_straight_line": [{"straight_line_m": 100.0}]},
            "no candidate is reachable on foot",
        ),
        (
            "proximity",
            {"walking_nearest": "node/1", "unreachable": [],
             "by_walking": [{"feature_id": "node/1", "walking_m": 900.0, "straight_line_m": 200.0}],
             "by_straight_line": []},
            "more than 3x the straight line",
        ),
        ("containment", {"points": {"a": {"inside": [], "on_boundary": []}}, "features": {}},
         "point 'a' is in no polygon"),
        ("adjacency", {"pairs": [{"a": "way/1", "b": "way/2", "relation": "disjoint"}]},
         "no pair of features touches"),
        ("closure", {"before": {"reachable": True, "walking_m": 100.0},
                     "after": {"reachable": True, "walking_m": 100.0}, "added_m": 0.0},
         "the closure does not change the walk"),
        ("visibility", {"targets": {"way/1": {"visible": None}, "way/2": {"visible": None}}},
         "every target is undecided"),
        ("direction", {"reachable": True, "walking_m": 1000.0, "straight_line_m": 200.0,
                       "steps": [{}, {}]}, "more than 3x the straight line"),
        ("direction", {"reachable": True, "walking_m": 100.0, "straight_line_m": 90.0,
                       "steps": [{}]}, "a one-step route"),
    ],
)
def test_key_warnings(key_type: str, key: dict, warning: str) -> None:
    assert any(warning in w for w in key_warnings(key_type, key))


def test_a_sound_key_has_no_warning() -> None:
    key = {"walking_nearest": "node/1", "unreachable": [],
           "by_walking": [{"feature_id": "node/1", "walking_m": 300.0, "straight_line_m": 250.0}],
           "by_straight_line": []}
    assert key_warnings("proximity", key) == []


def test_task_warnings_flag_duplicates_and_the_box_edge(tmp_path: Path) -> None:
    spec_path = copy_sample_eval(tmp_path / "evals")
    lines = spec_path.parent.joinpath("tasks.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    duplicate = {**first, "task_id": "sample-004"}
    edge = {**json.loads(lines[1]), "task_id": "sample-005",
            "location": {"point": [BBOX[0] + 0.0001, BBOX[1] + 0.0001], "feature_ids": []}}
    spec_path.parent.joinpath("tasks.jsonl").write_text(
        "".join(line + "\n" for line in lines) + json.dumps(duplicate) + "\n"
        + json.dumps(edge) + "\n", encoding="utf-8")
    tasks = load_tasks(spec_path, load_eval_spec(spec_path))
    warnings = task_warnings(tasks, BBOX)
    assert any("same key type and params as sample-001" in w for w in warnings["sample-004"])
    assert any("within 300 m of the city box edge" in w for w in warnings["sample-005"])


def test_review_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path, data = _reviewed(tmp_path)
    root = str(spec_path.parent.parent)
    assert main(["evals", "review", "sample", "--root", root, "--data", str(data)]) == 0
    assert "sample.md" in capsys.readouterr().out


def test_review_cli_needs_current_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path = copy_sample_eval(tmp_path / "evals")
    data = sample_data(tmp_path)  # no keys regenerated
    root = str(spec_path.parent.parent)
    assert main(["evals", "review", "sample", "--root", root, "--data", str(data)]) == 1
    assert "regenerate" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest -q tests/test_graded_review.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'geoevals.graded.review'`.

- [ ] **Step 3: Write `src/geoevals/graded/review.py`**

```python
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
    detour = f"a walk more than {DETOUR_FACTOR:g}x the straight line: check the map for a missing connection"
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
        return set().union(*(_feature_ids(v) for v in value.values()), *(_feature_ids(k) for k in value))
    if isinstance(value, list):
        return set().union(*(_feature_ids(v) for v in value))
    return set()


def _draw(layers: Mapping[str, Any], task: EvalTask, key: Mapping[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    features = layers["all_features"].set_index("feature_id")
    ids = sorted((_feature_ids(task.params) | _feature_ids(key) | set(task.location.feature_ids)) & set(features.index))
    shapes = [features.geometry[i] for i in ids]
    points = [task.location.point] if task.location.point else []
    xs = [c for s in shapes for c in (s.bounds[0], s.bounds[2])] + [p[0] for p in points]
    ys = [c for s in shapes for c in (s.bounds[1], s.bounds[3])] + [p[1] for p in points]
    if not xs:
        return
    box = (min(xs) - MAP_PAD_DEG, min(ys) - MAP_PAD_DEG, max(xs) + MAP_PAD_DEG, max(ys) + MAP_PAD_DEG)
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
        axes.plot(*shape.representative_point().xy, "o", color="#e6550d", markersize=3)
        series = layers["all_features"][layers["all_features"]["feature_id"] == feature_id]
        if shape.geom_type in ("Polygon", "MultiPolygon"):
            series.boundary.plot(ax=axes, color="#e6550d", linewidth=1.2)
        elif shape.geom_type in ("LineString", "MultiLineString"):
            series.plot(ax=axes, color="#e6550d", linewidth=1.2)
        axes.annotate(feature_id, shape.representative_point().coords[0], fontsize=6)
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
            json.dumps({"params": task.params, "anchors": task.anchors, "key": key}, indent=1, ensure_ascii=False),
            "```",
            "",
            "</details>",
            "",
        ]
    sheet.write_text("\n".join(lines), encoding="utf-8")
    return sheet
```

Ruff will want the long lines wrapped. Run `uv run ruff format src/geoevals/graded/review.py` and fix any remaining E501 by hand.

- [ ] **Step 4: Add the CLI subcommand**

In `src/geoevals/cli.py`, after the `regen_keys` parser block, add:

```python
    review = evals_commands.add_parser(
        "review",
        help="Write an eval's review sheet (prompts, keys, warnings, a map per task) into the "
        "gitignored data directory, for checking drafted tasks.",
    )
    review.add_argument("eval_id", help="The eval ID (a directory under --root).")
    review.add_argument(
        "--root", type=Path, default=Path("evals"), help="Directory of evals (default: evals)."
    )
    review.add_argument(
        "--data",
        type=Path,
        help="Data directory with layers/ and keys/ (default: the city manifest asset's directory).",
    )
```

Next to `_evals_regenerate`, add the handler:

```python
def _evals_review(eval_id: str, root: Path, data: Path | None) -> int:
    from geoevals.graded.keys import KeysError
    from geoevals.graded.review import review_sheet

    spec_path = find_eval_spec(root, eval_id)
    try:
        sheet = review_sheet(spec_path, data or default_data_dir(spec_path))
    except SpecValidationError as exc:
        _print_issues(exc.path, exc.issues)
        return 1
    except KeysError as exc:
        print(f"{exc}; run `geoevals evals regenerate {eval_id}` first", file=sys.stderr)
        return 1
    except (OSError, ValueError, FetchError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{sheet}: written")
    return 0
```

In the dispatch, after the `regenerate` branch:

```python
    if args.command == "evals" and args.evals_command == "review":
        return _evals_review(args.eval_id, args.root, args.data)
```

Check whether `KeysError` subclasses `ValueError`. If it does, its `except` clause must come before `(OSError, ValueError, FetchError)`, as written above.

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `uv run pytest -q tests/test_graded_review.py`
Expected: 13 passed (1 sheet test, 8 parametrized warnings, 1 sound key, 1 task-warnings test, 2 CLI tests).

- [ ] **Step 6: Document it**

In `docs/eval-authoring.md`, after "Compute the keys", add:

````markdown
## Review the drafts

```sh
uv run geoevals evals review <eval id>   # writes data/raw/osm_city_<town>/review/<eval id>.md
```

The review sheet shows each task's prompt, audience, strata, params and key, with a map of the
features it names, and warns about keys that are probably not what the author meant: a walk more
than 3 times the straight line (often a connection OpenStreetMap lacks), a location within 300 m
of the edge of the city box, duplicate tasks, and keys with nothing to answer. The sheet holds
the keys, so it stays in the gitignored data directory.
````

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest -q tests/test_graded_review.py tests/test_docs.py tests/test_cli.py
git add src/geoevals/graded/review.py src/geoevals/cli.py docs/eval-authoring.md tests/test_graded_review.py
git commit -m "graded: geoevals evals review writes a review sheet with keys, warnings and maps"
```

---

### Task 3: The drafting helper and the proximity eval

**Files:**
- Create (uncommitted): `/private/tmp/claude-502/-Users-jason-code-GeoEvals/c0cc2166-a4c7-49cb-822b-b905f0e8b6d2/scratchpad/drafting/drafting.py`
- Create: `evals/proximity/eval.yaml`, `evals/proximity/tasks.jsonl`

**Interfaces:**
- Consumes: Task 1's layers; Task 2's `geoevals evals review`.
- Produces: `drafting.py` with `LAYERS`, `reference`, `graph()`, `key(key_type, params)`, `utm(frame)`, `lonlat(point)`, `show(obj)`. Tasks 4 to 7 import it.

- [ ] **Step 1: Write the drafting helper**

Write `drafting.py` in the scratchpad (path above, abbreviated `$DRAFT` below). Run it with `PYTHONPATH=$DRAFT uv run python ...` from the worktree.

```python
"""Helpers for drafting the Oregon City tasks. Not committed: it reads OSM-derived layers."""

import importlib.util
import json
from functools import cache
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import Point

from geoevals.graded.city import load_layers

REPO = Path("/Users/jason/code/GeoEvals-graded")
DATA = REPO / "data/raw/osm_city_oregon_city"
LAYERS = load_layers(DATA / "layers")
UTM = 32610  # UTM zone 10N, for meters

_spec = importlib.util.spec_from_file_location("reference", REPO / "evals/city/reference.py")
assert _spec is not None and _spec.loader is not None
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)


@cache
def graph() -> Any:
    """The walking network, built once (building it takes seconds)."""
    return reference.WalkGraph(LAYERS)


def key(key_type: str, params: dict[str, Any]) -> dict[str, Any]:
    return reference.compute_key(key_type, params, LAYERS)


def utm(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return frame.to_crs(UTM)


def lonlat(point: Point) -> list[float]:
    """A point in WGS 84 as [lon, lat] with 7 decimals (the task format)."""
    return [round(point.x, 7), round(point.y, 7)]


def show(value: Any, limit: int = 3000) -> None:
    print(json.dumps(value, indent=1, ensure_ascii=False)[:limit])
```

Check: `PYTHONPATH=$DRAFT uv run python -c "import drafting; print(len(drafting.LAYERS['buildings']))"` prints `26212`.

- [ ] **Step 2: Find proximity candidates (barrier cases first)**

```python
import pandas as pd
from drafting import LAYERS, graph, reference, utm, lonlat

water, rail = LAYERS["water"], LAYERS["railways"]
barriers = utm(pd.concat([water[water.walk_barrier], rail[rail.walk_barrier]]))
homes = LAYERS["buildings"][LAYERS["buildings"].building.isin(["house", "residential", "apartments", "detached", "yes"])]
near = utm(homes)[utm(homes).geometry.distance(barriers.union_all()) < 400]
origins = near.sample(min(60, len(near)), random_state=0)
categories = [{"amenity": v} for v in ("pharmacy", "cafe", "school", "toilets", "fuel", "bank", "restaurant", "library")]
g = graph()
for cat in categories:
    candidates = reference._tagged(LAYERS, cat)
    for fid in origins.feature_id:
        origin = homes.set_index("feature_id").geometry[fid].representative_point()
        rows = []
        for cid, name, point in candidates:
            route = g.route(origin, point)
            rows.append((reference._distance_m(origin, point), route["walking_m"], cid, name))
        by_line = min(rows)
        walkable = [r for r in rows if r[1] is not None]
        if not walkable:
            continue
        by_walk = min(walkable, key=lambda r: r[1])
        if by_walk[2] != by_line[2] and by_walk[1] < 3 * by_walk[0]:
            print(cat, fid, lonlat(origin), "line:", by_line[3], round(by_line[0]), "walk:", by_walk[3], round(by_walk[1]))
```

Save the output to `$DRAFT/proximity_candidates.txt`. If a category has fewer than 2 tagged features in the city, skip it.

- [ ] **Step 3: Choose 12 tasks**

Spread the 12 tasks across:
- Tiers: 4 `describe` (nearest on foot, no trick), 4 `analyze` (looks nearest versus is nearest across the Willamette, Clackamas or the rail line), 4 `infer` (a recommendation or consequence, e.g. "which of two homes gives the better walk to a school", or "is the nearest one reachable at all").
- Strata `barrier`: at least 3 `river`, at least 2 `rail`, the rest `none`.
- Traps: at least 2 `layer` and at least 1 `ambiguity`. For a layer trap, the key uses the right tag; examples: `amenity=library` versus a building named "Library", or `amenity=school` versus `landuse=education`. For ambiguity, use for example "coffee" with the key on `amenity=cafe`.
- At least 5 distinct categories and at least 8 distinct origins.
- Params: `{"from": {"point": lonlat(...)} or {"feature_id": ...}, "category": {...}, "top": 3}`. `location.point` equals the `from` point (or the feature's representative point), and `location.feature_ids` lists the origin feature if one is used.

- [ ] **Step 4: Write `evals/proximity/eval.yaml`**

```yaml
schema_version: "1.0.0"
id: proximity
version: 0.1.0
title: Proximity on foot in Oregon City
concept: >-
  Nearness on foot against nearness on the map: walking distance over the street and path
  network, rivers and rail as barriers, and which place is nearest for a person on foot.
task_statement: >-
  Answer one open-ended question about Oregon City, Oregon, from its OpenStreetMap layers.
  Explain your reasoning for the audience named in the question.
intended_use: >-
  Comparing models' spatial reasoning about proximity on real, noisy city data. Not a measure
  of routing accuracy: the reference walk ignores slope, crossings and access restrictions.
tasks: tasks.jsonl
rubric_criteria: ../city/rubric_criteria.yaml
reference: ../city/reference.py
dataset_manifest: ../../datasets/manifests/osm_city_oregon_city.yaml
answer_word_limit: 4000
license: MIT
provenance:
  authors: [GeoEvals contributors]
  created: 2026-10-12
limitations:
  - One town, one snapshot (2026-10-11); OpenStreetMap completeness limits what is reachable.
  - Walking distance is network length; slope, crossings and private paths are ignored.
  - A real town can be known to the models; Oregon City is not world famous, but memorization cannot be ruled out.
```

- [ ] **Step 5: Write `evals/proximity/tasks.jsonl`, compute the keys, write the review sheet**

Write the 12 lines (`proximity-001` to `proximity-012`) in the format under "Drafting conventions". Then run:

```bash
uv run geoevals validate evals/proximity/eval.yaml
uv run geoevals evals regenerate proximity
uv run geoevals evals review proximity
```

Expected: valid; `proximity-001: key_sha256 written` and so on for all 12; the sheet written.

- [ ] **Step 6: Self-review the sheet**

Open `data/raw/osm_city_oregon_city/review/proximity.md` and look at every map. For each task:
- clear every warning, by fixing or replacing the task
- confirm the prompt doesn't state the answer, a distance or an ID
- confirm the key's `walking_nearest` is what the prompt's question is about
- confirm the tier matches the definition

Re-run `regenerate` and `review` after every edit. Expected at the end: no task has a warning, unless it's a deliberate `infer` task about an unreachable place. Explain that case in the task's anchors.

- [ ] **Step 7: Commit**

```bash
uv run pytest -q tests/test_docs.py
git add evals/proximity/eval.yaml evals/proximity/tasks.jsonl
git commit -m "evals: draft the proximity eval on Oregon City (12 tasks, for review)"
```

---

### Task 4: The adjacency eval (shared walls and closures)

**Files:**
- Create: `evals/adjacency/eval.yaml`, `evals/adjacency/tasks.jsonl`

**Interfaces:**
- Consumes: `drafting.py` (Task 3: `LAYERS`, `key`, `graph`, `utm`, `lonlat`, `show`); `geoevals evals review` (Task 2).
- Produces: 12 tasks: 6 with `key_type: adjacency`, 6 with `key_type: closure`.

- [ ] **Step 1: Find building groups with shared walls and corner touches**

```python
import geopandas as gpd
from drafting import LAYERS, key, utm, lonlat

b = utm(LAYERS["buildings"])[["feature_id", "name", "geometry"]]
touch = gpd.sjoin(b, b.assign(geometry=b.geometry.buffer(0.05)), predicate="intersects")
touch = touch[touch.feature_id_left < touch.feature_id_right]
print(len(touch), "touching pairs")
# groups of 3 to 5 buildings with at least one shared edge and one corner
seen = set()
for left, group in touch.groupby("feature_id_left"):
    ids = [left, *group.feature_id_right.tolist()][:5]
    if len(ids) < 3 or tuple(ids) in seen:
        continue
    seen.add(tuple(ids))
    k = key("adjacency", {"features": ids})
    relations = {p["relation"] for p in k["pairs"]}
    if {"shared_edge", "corner"} <= relations:
        point = LAYERS["buildings"].set_index("feature_id").geometry[left].representative_point()
        print(ids, lonlat(point), sorted(relations), group.name_right.dropna().tolist()[:3])
```

Prefer groups on or near Main Street, downtown (around 45.357 N, -122.606 E), where named buildings help the prompts.

- [ ] **Step 2: Find closures that matter**

```python
from drafting import LAYERS, graph, key, utm, lonlat
import json

af = LAYERS["all_features"]
network = set(LAYERS["streets"].feature_id) | set(LAYERS["paths"].feature_id)
crossings = [
    (fid, name) for fid, name, tags in zip(af.feature_id, af.name, af.tags)
    if fid in network and json.loads(tags).get("bridge", "no") != "no"
]
print(len(crossings), "bridges on the network")
b = LAYERS["buildings"]
for fid, name in crossings:
    line = af.set_index("feature_id").geometry[fid]
    a, z = line.coords[0], line.coords[-1]
    ua = utm(b[b.geometry.distance(gpd.points_from_xy([a[0]], [a[1]], crs=4326)[0]) < 0.003])
    uz = utm(b[b.geometry.distance(gpd.points_from_xy([z[0]], [z[1]], crs=4326)[0]) < 0.003])
    if ua.empty or uz.empty:
        continue
    start = ua.iloc[0].feature_id
    end = uz.iloc[-1].feature_id
    k = key("closure", {"from": {"feature_id": start}, "to": {"feature_id": end}, "closed": [fid]})
    if k["disconnected_by_closure"] or (k["added_m"] or 0) > 200:
        print(fid, name, start, end, k["before"], k["after"], k["added_m"])
```

Add `import geopandas as gpd` at the top. Also try closing the Oregon City Bridge (to West Linn), the Abernethy Bridge, and a footbridge over a creek. For each candidate, look up the bridge's feature IDs by name in `LAYERS["streets"]` and `LAYERS["paths"]`: a bridge is often several ways, and all of them must be in `closed`.

- [ ] **Step 3: Choose 12 tasks**

- 6 adjacency: 2 `describe` ("do these two share a wall?"), 2 `analyze` ("which of these buildings share walls and which only touch at a corner?"), 2 `infer` (a consequence, e.g. "a fire wall is needed where buildings share a wall; which of these need one?").
- 6 closure: 2 `describe` ("can I still walk there?"), 2 `analyze` ("how much longer is the walk?"), 2 `infer` (a recommendation under the closure, or which closure disconnects a place).
- Strata `relation`: `shared_edge`, `corner`, `closure_detour` or `closure_disconnect`.
- Traps: at least 2 `layer`. Examples: a building part (`building:part`) or a roof against the building; a closed street with a parallel footway that the key correctly still uses. At least 1 `ambiguity`, e.g. "next to each other".
- Adjacency params: `{"features": [...], "layer": "buildings", "edge_min_m": 0.5}`. Closure params: `{"from": ..., "to": ..., "closed": [...]}`.

- [ ] **Step 4: Write `evals/adjacency/eval.yaml`**

Use the same text as `evals/proximity/eval.yaml` (Task 3, Step 4) except:

```yaml
id: adjacency
title: Adjacency and closures in Oregon City
concept: >-
  Topology of the built environment: buildings that share walls against those that only touch
  at a corner, and what closing a street, path or bridge does to a walk.
intended_use: >-
  Comparing models' reasoning about adjacency and network connectivity on real, noisy city data.
limitations:
  - One town, one snapshot (2026-10-11); building outlines in OpenStreetMap are approximate.
  - Walls up to 5 cm apart count as touching; a shared wall needs at least 0.5 m of common edge.
  - Walking distance is network length; slope, crossings and private paths are ignored.
  - A real town can be known to the models; Oregon City is not world famous, but memorization cannot be ruled out.
```

- [ ] **Step 5: Write the tasks, compute the keys, write the review sheet**

```bash
uv run geoevals validate evals/adjacency/eval.yaml
uv run geoevals evals regenerate adjacency
uv run geoevals evals review adjacency
```

Expected: valid; 12 `key_sha256 written`; the sheet written.

- [ ] **Step 6: Self-review the sheet**

Same checks as Task 3, Step 6. Also:
- On the map, the shared walls in each adjacency task must look shared, and the corner touches must look like corners.
- Each closure task's `closed` list must cover every way of the closed bridge or street. If half a bridge stays open, the closure means nothing.

- [ ] **Step 7: Commit**

```bash
git add evals/adjacency/eval.yaml evals/adjacency/tasks.jsonl
git commit -m "evals: draft the adjacency eval on Oregon City (12 tasks, for review)"
```

---

### Task 5: The visibility eval

**Files:**
- Create: `evals/visibility/eval.yaml`, `evals/visibility/tasks.jsonl`

**Interfaces:**
- Consumes: `drafting.py` (Task 3); `geoevals evals review` (Task 2).
- Produces: 12 tasks with `key_type: visibility`.

- [ ] **Step 1: Find observers with a mix of visible, blocked and undecided targets**

```python
from drafting import LAYERS, key, utm, lonlat

b = LAYERS["buildings"]
bu = utm(b)
known = bu[bu.height_source != "unknown"]
tall = known[known.height_m >= 12]
print(len(known), "with heights,", len(tall), "at least 12 m")
for obs in tall.itertuples():
    distance = known.geometry.distance(obs.geometry)
    near = known[(distance > 40) & (distance < 400)]
    if len(near) < 4:
        continue
    targets = near.sample(min(6, len(near)), random_state=0).feature_id.tolist()
    k = key("visibility", {"observer": {"feature_id": obs.feature_id, "height_m": 1.6}, "targets": targets})
    outcomes = sorted({str(t["visible"]) for t in k["targets"].values()})
    if len(outcomes) >= 2:
        point = b.set_index("feature_id").geometry[obs.feature_id].representative_point()
        print(obs.feature_id, obs.name, round(obs.height_m), lonlat(point), outcomes, targets)
```

Check the observer format against `tests/fixtures/graded/sample/tasks.jsonl` (task `sample-002`) and `evals/city/reference.py` (`visibility_key`) before writing the tasks. The observer is a place plus `height_m`, the eye height above the ground, or above the roof when the place is a building.

Also try point observers on streets and at viewpoints (the McLoughlin Promenade, the top of the Municipal Elevator) with `height_m: 1.6`.

- [ ] **Step 2: Choose 12 tasks**

- 4 `describe`: one target, a decided answer (`visible` true or false).
- 4 `analyze`: several targets, some visible and some blocked, with the blocking building named in the key.
- 4 `infer`: at least 2 where the honest answer is "can't tell" (`visible: null` from unknown heights), plus judgments such as "would a 3-story addition to X block the view?". Phrase the latter as which buildings stand on the sight line, so the key's `blocked_by` and `unknown_height_on_path` carry the answer.
- Strata `heights`: `known` (every building that matters has a height) or `partly_unknown`.
- Traps: at least 2 `layer`. Examples: a `building:part` with its own height; a building whose `height` is missing but whose `building:levels` gives a height. At least 1 `ambiguity`, e.g. "see the top of" against "see any part of".
- Add an anchor on `assumptions` to every `partly_unknown` task: a 4 says which heights are unknown and that the answer depends on them.

- [ ] **Step 3: Write `evals/visibility/eval.yaml`**

Use the same text as `evals/proximity/eval.yaml` (Task 3, Step 4) except:

```yaml
id: visibility
title: Lines of sight in Oregon City
concept: >-
  Line of sight between places and buildings with heights: which buildings block a view, and
  when missing heights leave the answer undecided.
intended_use: >-
  Comparing models' reasoning about visibility and missing data on real, noisy city data.
limitations:
  - One town, one snapshot (2026-10-11); most buildings have no height in OpenStreetMap.
  - Heights are the height tag, else building:levels x 3 m, else unknown; terrain is ignored (flat ground), which matters on Oregon City's bluff.
  - A real town can be known to the models; Oregon City is not world famous, but memorization cannot be ruled out.
```

- [ ] **Step 4: Write the tasks, compute the keys, write the review sheet**

```bash
uv run geoevals validate evals/visibility/eval.yaml
uv run geoevals evals regenerate visibility
uv run geoevals evals review visibility
```

- [ ] **Step 5: Self-review the sheet**

Same checks as Task 3, Step 6. Also:
- Terrain is ignored. Don't draft a view across the bluff (downtown against the upper town) whose real answer depends on elevation, unless the task is an `infer` task that asks the model to say what the flat-ground data cannot tell.
- The "every target is undecided" warning is allowed only on `infer` tasks with `heights: partly_unknown`.

- [ ] **Step 6: Commit**

```bash
git add evals/visibility/eval.yaml evals/visibility/tasks.jsonl
git commit -m "evals: draft the visibility eval on Oregon City (12 tasks, for review)"
```

---

### Task 6: The containment eval

**Files:**
- Create: `evals/containment/eval.yaml`, `evals/containment/tasks.jsonl`

**Interfaces:**
- Consumes: `drafting.py` (Task 3); `geoevals evals review` (Task 2).
- Produces: 12 tasks with `key_type: containment`.

- [ ] **Step 1: Survey the boundaries and find boundary points**

```python
from drafting import LAYERS, key, utm, lonlat
import geopandas as gpd

bd = LAYERS["boundaries"]
print(bd.groupby(["boundary", "admin_level"], dropna=False).size())
hoods = utm(bd[(bd.boundary == "administrative") & (bd.admin_level == "10")])
cities = utm(bd[(bd.boundary == "administrative") & (bd.admin_level == "8")])
print(sorted(hoods.name.dropna()), sorted(cities.name.dropna()))
# shared edges between neighborhoods: points exactly on, and 5 m inside each side
for a, b in [(x, y) for i, x in enumerate(hoods.itertuples()) for y in list(hoods.itertuples())[i + 1:]]:
    edge = a.geometry.boundary.intersection(b.geometry.boundary)
    if edge.length < 100:
        continue
    on = edge.interpolate(0.5, normalized=True)
    inside_a = a.geometry.buffer(-5).boundary.interpolate(a.geometry.buffer(-5).boundary.project(on))
    pts = gpd.GeoSeries([on, inside_a], crs=32610).to_crs(4326)
    print(a.name, "|", b.name, lonlat(pts[0]), lonlat(pts[1]), round(edge.length))
```

The 2026-10-12 survey found:
- 21 neighborhoods (admin level 10)
- the Oregon City, West Linn and Gladstone city limits (admin level 8)
- 8 admin-level-7 boundaries
- 3 protected areas, among them the McLoughlin House site
- 2 census boundaries and 1 special district (Metro)

- [ ] **Step 2: Choose 12 tasks**

- 4 `describe`: "which neighborhood (and city) is this point in?".
- 4 `analyze`: a point on a shared boundary (key `on_boundary`), and overlapping areas (a park or protected area against neighborhoods, via `features` with `layers: ["boundaries", "parks"]`).
- 4 `infer`: for example, which city a point mid-span on the Oregon City Bridge is in; whether a park belongs to one neighborhood association or two; which areas a long building straddles.
- Strata `case`: `inside`, `on_boundary`, `overlap` or `across_river`.
- Traps: at least 2 `layer` (an admin-level-7 boundary or the Metro special district against the city limits; `landuse=residential` against a neighborhood) and at least 1 `ambiguity` ("in Oregon City": the city limits, or the postal city).
- Params: `{"points": [{"label": "A", "point": [...]}], "features": [...], "layers": ["boundaries"], "boundary_tolerance_m": 1}`. Use a tolerance above 1 m only for a reason stated in the task's anchors, never above 50.

- [ ] **Step 3: Write `evals/containment/eval.yaml`**

Use the same text as `evals/proximity/eval.yaml` (Task 3, Step 4) except:

```yaml
id: containment
title: Containment and boundaries in Oregon City
concept: >-
  Which areas contain a place: nested and overlapping boundaries, points on a boundary, and
  boundaries that run along a river.
intended_use: >-
  Comparing models' reasoning about containment and boundary edge cases on real, noisy city data.
limitations:
  - One town, one snapshot (2026-10-11); boundaries in OpenStreetMap are not legal descriptions.
  - A point within the stated tolerance of an edge counts as on the boundary.
  - A real town can be known to the models; Oregon City is not world famous, but memorization cannot be ruled out.
```

- [ ] **Step 4: Write the tasks, compute the keys, write the review sheet**

```bash
uv run geoevals validate evals/containment/eval.yaml
uv run geoevals evals regenerate containment
uv run geoevals evals review containment
```

- [ ] **Step 5: Self-review the sheet**

Same checks as Task 3, Step 6. Also:
- For each `on_boundary` point, check on the map that the point sits on the drawn edge.
- The prompt must not say "on the boundary"; finding that is the task.

- [ ] **Step 6: Commit**

```bash
git add evals/containment/eval.yaml evals/containment/tasks.jsonl
git commit -m "evals: draft the containment eval on Oregon City (12 tasks, for review)"
```

---

### Task 7: The direction eval

**Files:**
- Create: `evals/direction/eval.yaml`, `evals/direction/tasks.jsonl`

**Interfaces:**
- Consumes: `drafting.py` (Task 3); `geoevals evals review` (Task 2).
- Produces: 12 tasks with `key_type: direction`.

- [ ] **Step 1: Check what the network models around the bluff**

```python
import json
from drafting import LAYERS

af = LAYERS["all_features"]
for fid, name, tags in zip(af.feature_id, af.name, af.tags):
    t = json.loads(tags)
    if "Elevator" in (name or "") or t.get("highway") in ("elevator", "steps"):
        print(fid, name, t.get("highway"), t.get("railway"))
```

The network is the `streets` and `paths` layers only. Steps are in the network; an elevator node or `highway=elevator` way is not. Whatever this prints decides it: if the Municipal Elevator itself isn't a network edge, no task's real-world answer may depend on riding it. Note this in the task authoring notes in Step 5.

- [ ] **Step 2: Find routes with several steps, landmarks and misleading bearings**

```python
from drafting import LAYERS, key, lonlat

pois = LAYERS["pois"]
named = pois[pois.name.notna() & pois.category.isin(["amenity", "tourism", "historic", "shop"])]
starts = named.sample(min(40, len(named)), random_state=0)
for s in starts.itertuples():
    for e in named.sample(8, random_state=1).itertuples():
        if s.feature_id == e.feature_id:
            continue
        k = key("direction", {"from": {"feature_id": s.feature_id}, "to": {"feature_id": e.feature_id}})
        if not k["reachable"] or not (300 < k["walking_m"] < 2000):
            continue
        landmarks = sum(1 for step in k["steps"] if step["landmark"])
        ratio = k["walking_m"] / k["straight_line_m"]
        if len(k["steps"]) >= 4 and landmarks >= 1:
            print(s.name, "->", e.name, len(k["steps"]), "steps", landmarks, "landmarks", k["compass"], round(ratio, 2))
```

The direction key builds a walk graph on every call, so this loop is slow; keep the sample small. A ratio from 1.6 to 3 is a "misleading bearing" candidate: the place looks close in one direction, but the walk goes around.

- [ ] **Step 3: Choose 12 tasks**

- 4 `describe`: short directions (3 to 5 steps).
- 4 `analyze`: directions with landmarks for a stated audience (a visitor, a dispatcher).
- 4 `infer`: misleading bearings ("it looks like it's just north; is it a short walk?"), or which way to set off when the straight-line bearing points the wrong way.
- Strata `route`: `short`, `landmarks` or `misleading_bearing`.
- Traps: at least 2 `layer` (a footway that's a better walk than the street the map labels; a `highway=steps` shortcut the key uses) and at least 1 `ambiguity` ("the library": two candidates; the key uses the one named in the location).
- Params: `{"from": ..., "to": ..., "landmark_radius_m": 30, "turn_threshold_deg": 30}`.

- [ ] **Step 4: Write `evals/direction/eval.yaml`**

Use the same text as `evals/proximity/eval.yaml` (Task 3, Step 4) except:

```yaml
id: direction
title: Directions and orientation in Oregon City
concept: >-
  Turn-by-turn walking directions with landmarks, and orientation when the straight-line
  bearing misleads.
intended_use: >-
  Comparing models' reasoning about routes, turns and orientation on real, noisy city data.
limitations:
  - One town, one snapshot (2026-10-11); slope is ignored, which matters on Oregon City's bluff.
  - A turn is a change of bearing over 30 degrees; a landmark is a point of interest within 30 m of where a step begins.
  - A real town can be known to the models; Oregon City is not world famous, but memorization cannot be ruled out.
```

- [ ] **Step 5: Write the tasks, compute the keys, write the review sheet**

```bash
uv run geoevals validate evals/direction/eval.yaml
uv run geoevals evals regenerate direction
uv run geoevals evals review direction
```

- [ ] **Step 6: Self-review the sheet**

Same checks as Task 3, Step 6. Also:
- Trace every route on its map and confirm the walk is one a person would take. Watch for walks through private service roads or parking aisles; a parking aisle is fine if it's what a person would do.

- [ ] **Step 7: Commit**

```bash
git add evals/direction/eval.yaml evals/direction/tasks.jsonl
git commit -m "evals: draft the direction eval on Oregon City (12 tasks, for review)"
```

---

### Task 8: Docs, a whole-branch check and checkpoint 2

**Files:**
- Modify: `evals/README.md` (the five evals)
- Modify: `CHANGELOG.md` (Unreleased, Added)
- Modify: `ROADMAP.md` ("Graded evals on a real city": drafted, under review)

**Interfaces:**
- Consumes: Tasks 1 to 7.
- Produces: a pushed branch, an open PR **marked draft**, and five review sheets for the user.

- [ ] **Step 1: Document the evals**

In `evals/README.md`, after the table, add:

```markdown
The evals on Oregon City, Oregon (`datasets/manifests/osm_city_oregon_city.yaml`), each 12 tasks
in three tiers (describe, analyze, infer):

| Eval | Concept |
| --- | --- |
| [`proximity`](proximity/eval.yaml) | Nearness on foot against nearness on the map, across rivers and rail |
| [`adjacency`](adjacency/eval.yaml) | Shared walls against corner touches; what a closure does to a walk |
| [`visibility`](visibility/eval.yaml) | Lines of sight between buildings with heights; undecided views |
| [`containment`](containment/eval.yaml) | Nested and overlapping boundaries; points on a boundary |
| [`direction`](direction/eval.yaml) | Turn-by-turn directions with landmarks; misleading bearings |
```

In `CHANGELOG.md`, under `## Unreleased` / `### Added`, add a `#### Graded evals` subsection if there isn't one, with:

```markdown
- `proximity`, `adjacency`, `visibility`, `containment` and `direction` 0.1.0 (drafts, under
  review): 60 open-ended tasks on Oregon City, Oregon, from Geofabrik's 2026-10-11 extract.
- `geoevals evals review`: a review sheet with keys, warnings and a map per task.
```

In `ROADMAP.md`, in "Graded evals on a real city", replace "They arrive with the town's dataset manifest and the task drafting." with "The town is Oregon City, Oregon; the 60 tasks are drafted and under review."

- [ ] **Step 2: Whole-branch checks**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest -q
for e in proximity adjacency visibility containment direction; do uv run geoevals validate evals/$e/eval.yaml && uv run geoevals evals regenerate $e --check; done
uv run geoevals data inventory --check
git status --short    # nothing under data/raw/
```

Expected: everything passes; every eval reports `keys are up to date`.

- [ ] **Step 3: Count strata per eval**

```bash
uv run python -c "
import json, collections
for e in ['proximity','adjacency','visibility','containment','direction']:
    tasks=[json.loads(l) for l in open(f'evals/{e}/tasks.jsonl')]
    print(e, len(tasks), dict(collections.Counter(t['strata']['tier'] for t in tasks)), dict(collections.Counter(t['strata']['trap'] for t in tasks)), len({t['audience'] for t in tasks}), 'audiences')
"
```

Expected per eval: 12 tasks; tiers 4/4/4; at least 2 `layer` and 1 `ambiguity`; at least 4 audiences. Fix any eval that misses.

- [ ] **Step 4: Commit, push, open a draft PR**

```bash
git add evals/README.md CHANGELOG.md ROADMAP.md
git commit -m "docs: the five Oregon City evals, drafted for review"
git push -u origin feat/oregon-city-evals
gh pr create --draft --base main --title "Graded evals on Oregon City (drafts for review)" --body "Plan 2 (docs/superpowers/plans/2026-10-12-oregon-city-evals.md): pins osm_city_oregon_city from Geofabrik's 2026-10-11 Oregon extract, adds geoevals evals review, and drafts the five evals (60 tasks, tiers describe/analyze/infer). Draft until the maintainer reviews the tasks (checkpoint 2). Keys, layers and review sheets are local only (ODbL)."
```

- [ ] **Step 5: Checkpoint 2: hand the review sheets to the user**

Stop here. Tell the user where the sheets are:

```
data/raw/osm_city_oregon_city/review/{proximity,adjacency,visibility,containment,direction}.md
```

Do this in the worktree `/Users/jason/code/GeoEvals-graded`. Say they open in any Markdown viewer that shows images, for example VS Code's preview. Ask the user to review the prompts, audiences, tiers and anchors, and to mark tasks to change or drop. Do not publish the sheets anywhere: they hold the keys.

---

### Task 9: Apply the review and merge (after the user's review)

**Files:**
- Modify: `evals/<id>/tasks.jsonl` as the user asks

- [ ] **Step 1: Apply each requested change** to the task lines. Then re-run, for each changed eval:

```bash
uv run geoevals evals regenerate <id>
uv run geoevals evals review <id>
```

Clear any new warnings, then show the user the changed tasks.

- [ ] **Step 2: When the user approves,** run Task 8, Step 2 again, then commit:

```bash
git add evals/*/tasks.jsonl
git commit -m "evals: apply the maintainer's review of the Oregon City tasks"
git push
```

- [ ] **Step 3: Merge with the user's OK**

```bash
gh pr ready
gh pr checks --watch
gh pr merge --merge
```

Then in the main checkout, `git pull --ff-only`. The evals are frozen at 0.1.0 from here: any later change to a task, key, the rubric or the reference script is a minor version change (`docs/eval-authoring.md`, "Review and versions").

---

### Task 10: The pilot (only with the user's go-ahead)

**Files:**
- Create: `leaderboard/configs/pilot-graded.yaml`

- [ ] **Step 1: Write the pilot config** (one task per eval; the claude adapter declines the rest, so a pilot is never accepted on the leaderboard):

```yaml
# Pilot, graded evals: one task per eval; every other task is skipped, so a pilot run is never
# accepted on the leaderboard. See leaderboard/README.md.
split: test
seed: 0
timeout_s: 900
max_retries: 0
workers: 1
adapter:
  effort: high
  prompt_version: v1
  case_timeout_s: 840
  max_case_usd: 5
  max_tool_calls: 20
  only_cases:
    - proximity-005
    - adjacency-005
    - visibility-005
    - containment-005
    - direction-005
```

Choose `-005` (an `analyze` task) unless the user names others. If task `-005` of an eval isn't `analyze`, use that eval's first `analyze` task.

- [ ] **Step 2: Validate and commit**

```bash
uv run pytest -q tests/test_docs.py
git checkout -b feat/graded-pilot origin/main
git add leaderboard/configs/pilot-graded.yaml
git commit -m "leaderboard: pilot config for the graded evals"
```

- [ ] **Step 3: Ask the user for the go-ahead.** Say that the pilot is 5 answers from Opus 5.5 plus 10 grading sessions (2 passes each), all on the subscription. Don't run anything without a yes.

- [ ] **Step 4: Run the pilot** (after the yes):

```bash
for e in proximity adjacency visibility containment direction; do
  uv run geoevals run --eval evals/$e/eval.yaml --adapter claude_python_opus_5_5 \
    --config leaderboard/configs/pilot-graded.yaml --out runs/pilot-graded
done
for run in runs/pilot-graded/*/; do uv run geoevals grade "$run"; done
```

- [ ] **Step 5: Report** each answered task's status, latency, tokens, tool calls used against the limit of 20, the two grades and their agreement, quoting the files in each run directory. Ask whether `max_tool_calls: 20` is enough before any full run. Changing it changes the run config, so it needs the user's decision. Full runs need a separate go-ahead per model.
