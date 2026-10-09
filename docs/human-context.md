# Human context

The human-context pillar asks questions about how people can reach everyday places on foot:
how far, how long, how many amenities, how direct the route is, and whether a place is open at
a given time. This document defines each concept operationally, so that a case, its reference
answer and a system's answer all mean the same thing.

Every value in a human-context answer also carries an **evidence type**, so that observations,
proxies and judgments are never mixed up.

## Evidence types

| Evidence type | Meaning | Example |
| --- | --- | --- |
| `observed` | A direct measurement of the thing itself. | A walk timed with a stopwatch. |
| `proxy` | An estimate derived from other data with a stated model. | Walking time computed from mapped street length and an assumed speed. |
| `judgment` | A subjective human rating. | A resident's rating of how pleasant a walk is. |

A benchmark spec states the evidence type of each output field with `evidence_type` on the
field in `output_schema.properties` (benchmark spec schema 1.1.0):

```yaml
pillar: human_context
output_schema:
  type: object
  required: [status]
  properties:
    status: {enum: [ok, insufficient_data, invalid_request], evidence_type: proxy}
    value: {type: number, evidence_type: proxy}
    units: {const: s, evidence_type: proxy}
```

Rules:

- In a `human_context` spec, `output_schema` must list its output fields in `properties`, and
  every one of them must have an `evidence_type`. `geoevals validate` fails otherwise.
- In other pillars `evidence_type` is optional, but when present it must be one of the three
  values.
- A field that qualifies an answer rather than holding a measured value (`status`, `units`,
  `crs`) carries the evidence type of the answer it qualifies.
- A proxy stays a proxy. A report or summary may not present a `proxy` value as `observed`,
  and values with different evidence types are never averaged together.

Every pilot concept below is computed from mapped data with a stated model, so every pilot
value is a `proxy`. The pilot has no `observed` or `judgment` values: activity-intensity and
human-rating tasks are added only when credible observation data or a validated rating
protocol exists.

## Shared conventions

These apply to every concept unless its definition says otherwise.

- **Travel mode:** walking on the pedestrian-accessible street network. One-way restrictions
  are ignored for walking. Stairs, crossings, waiting at signals and slope are not modeled.
- **Walking speed:** a constant **1.33 m/s** (about 4.8 km/h), unless a case states another
  speed. Every case and result that converts distance to time records the speed it used.
- **Spatial unit:** a point (an origin or a point of interest) snapped to the nearest network
  node. A point that does not snap within the snapping tolerance is not on the network, and
  the expected answer is `insufficient_data`. The snapping tolerance and the edge weight units
  are defined in [`metrics.md`](metrics.md) with the network metrics.
- **Network snapshot:** the street network and points of interest as recorded in the
  benchmark's dataset (the synthetic fixture, or an OpenStreetMap extract with its access
  date). Answers are true for that snapshot, not for the place today.
- **Reference evidence:** the reference workflow computes every expected output from the
  dataset named in the benchmark's manifest, with shortest paths on the network weighted by
  edge length in meters.

## Concepts

### Network walking distance

The length in meters of the shortest path on the walking network between the snapped origin
node and the snapped destination node.

| Aspect | Definition |
| --- | --- |
| Spatial unit | Origin point and destination point, each snapped to its nearest network node. |
| Time window | None. The value depends only on the network snapshot. |
| Travel mode | Walking; one-way restrictions ignored. |
| Reference evidence | Shortest-path length on the benchmark's network dataset (meters). |
| Evidence type | `proxy`: mapped network geometry stands in for the route a person walks. |
| Units | `m` |

If no path connects the two nodes (they are in different network components), there is no
distance, and the expected answer is `insufficient_data`.

### Walking travel time

Network walking distance divided by the walking speed.

| Aspect | Definition |
| --- | --- |
| Spatial unit | As for network walking distance. |
| Time window | None. Time of day does not change walking time in this model. |
| Travel mode | Walking at a constant **1.33 m/s** unless the case states another speed. |
| Reference evidence | Shortest-path length on the benchmark's network dataset divided by the stated speed. |
| Evidence type | `proxy`: an assumed constant speed stands in for how fast a person walks. |
| Units | `s` |

The assumed speed is a modeling choice, not a fact about any person. People walk at different
speeds, and the value says nothing about who can make the trip.

### Amenity access within T minutes

The number, and the set, of points of interest in one amenity category whose walking travel
time from the origin is at most T minutes.

| Aspect | Definition |
| --- | --- |
| Spatial unit | One origin point snapped to the network. When results are aggregated over an area, the area unit is a square grid cell, and the cell size is stated (the pilot reports 250 m and 1 km cells). |
| Time window | The threshold T, in minutes, stated in the case (the pilot uses 10 and 15). The boundary is inclusive: travel time ≤ T × 60 s. |
| Travel mode | Walking at the stated speed. |
| Reference evidence | Walking travel time to every point of interest of the category in the benchmark's dataset, with the category taken from the dataset's tags. |
| Evidence type | `proxy`: mapped points of interest and modeled travel time stand in for what a person can reach. |
| Units | `count` (and the set of point-of-interest IDs) |

A point of interest counts once, however many network nodes are near it. Opening hours are
ignored here; see time-specific availability.

### Network detour ratio (route stretch)

Network walking distance divided by the straight-line geodesic distance between the same
origin and destination points.

| Aspect | Definition |
| --- | --- |
| Spatial unit | Origin point and destination point. The network distance uses the snapped nodes. The straight-line distance uses the original points, measured on the WGS 84 ellipsoid. |
| Time window | None. |
| Travel mode | Walking for the network distance; none for the straight-line distance. |
| Reference evidence | Shortest-path length on the benchmark's network dataset and the geodesic distance between the points. |
| Evidence type | `proxy`: the ratio describes the mapped network, not how direct a walk feels. |
| Units | `ratio` (dimensionless, 1.0 or more for a well-formed network) |

The ratio is undefined when the straight-line distance is zero, so cases do not pose it for
coincident points.

### Time-specific POI availability

Whether a point of interest is open at a stated local date and time, according to its recorded
opening hours. Combined with amenity access, it answers questions such as "which pharmacies
within 15 minutes' walk are open at 21:30 on Sunday?"

| Aspect | Definition |
| --- | --- |
| Spatial unit | One point of interest (and, when combined with access, one origin). |
| Time window | One instant: an ISO date, a local time and an explicit IANA time zone, all stated in the case. Hours that cross midnight belong to the day on which they start. Public-holiday rules apply only to the holidays the case lists. |
| Travel mode | Walking, when combined with amenity access. Travel time is not added to the instant. |
| Reference evidence | The point of interest's `opening_hours` value in OpenStreetMap syntax, as recorded in the benchmark's dataset. |
| Evidence type | `proxy`: recorded opening hours stand in for whether the place is actually open. |
| Units | `bool` per point of interest (`open`, `closed` or unknown) |

A point of interest with no `opening_hours`, or with a value that cannot be parsed, is
**unknown**, not closed. Unknown hours are reported as data missingness, and a case that needs
them expects `insufficient_data` or an explicit unknown bucket.

In `human_context_access` (operation `open_amenities`), the answer counts the points of interest
within the threshold that are open at the instant (`value`, `ids`) and lists those with unknown
hours in `unknown_ids`, the explicit unknown bucket. When every point of interest within the
threshold has unknown hours, the data cannot answer, and the expected status is
`insufficient_data`.

Opening hours are evaluated by `geoevals.opening_hours`, pure Python with no network access. It
supports this subset of the OpenStreetMap syntax; any other value counts as unparseable
(unknown):

- `24/7`;
- rules separated by `;`, each an optional selector followed by `off`, `closed` or
  comma-separated `HH:MM-HH:MM` spans;
- a selector is a comma-separated list of weekdays (`Mo` to `Su`), weekday ranges (`Mo-Fr`,
  wrapping ranges such as `Fr-Mo` allowed) and `PH`. A rule without a selector applies every
  day.

For each date, the **last** rule whose selector matches it applies. Weekday selectors match
public holidays too, and `PH` matches only the holidays the case lists, so
`Mo-Su 08:00-22:00; PH off` is closed on a listed holiday. A span is open from its start
(inclusive) to its end (exclusive); an end earlier than the start crosses midnight, and the
part after midnight belongs to the day the span started on.

## What the benchmark does not claim

The benchmark makes **no claims about social relationships inferred from co-location,
mobility proxies, or demographics**. It does not infer who knows whom, who lives or travels
with whom, or anything about a group from where people are, how they move, or who they are.
No case asks for such an inference, and no output field holds one.

The benchmark also does not:

- produce a universal "place quality" score;
- say whether a particular person can or does make a trip;
- use precise personal location traces;
- measure activity intensity or collect human ratings.

A result says how well a system computes the concepts above on the benchmark's dataset. It
does not say whether a neighborhood is good, safe or well served.
