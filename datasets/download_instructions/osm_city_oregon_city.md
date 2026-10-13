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
