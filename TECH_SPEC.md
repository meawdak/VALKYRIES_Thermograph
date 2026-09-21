# THERMOGRAPH — Technical Specification (Prototype v1.0)

This document explains **how** to build what `PRD.md` requires. If this document and the PRD disagree, stop and ask the user.

---

## 1. Folder structure

Keep the existing folders. **Do not move or rename anything inside `data/`.**

```
thermograph/
├── data/                         # RAW SOURCE DATA — READ ONLY. Never modify.
│   └── (existing FIRMS CSVs and OSM GeoJSON — exact paths found in T0)
├── processing/
│   ├── config.py                 # ALL paths and parameters
│   ├── db.py                     # SQLite connection + table creation
│   ├── load_firms.py             # Stage 1
│   ├── cluster_sites.py          # Stage 2
│   ├── load_facilities.py        # Stage 3
│   ├── match_facilities.py       # Stage 4
│   ├── site_history.py           # Stage 5 (weekly history + site class)
│   ├── baselines.py              # Stage 6
│   ├── anomalies.py              # Stage 7 (detection + scoring + reasons)
│   ├── simulate_event.py         # Stage 8 (demo only)
│   ├── run_pipeline.py           # runs stages 1–8 in order
│   └── check_outputs.py          # PASS/FAIL verification
├── output/
│   ├── thermal_sites.csv         # LEGACY — keep unchanged, used for comparison only
│   ├── thermograph.db            # generated SQLite database
│   ├── exports/                  # generated CSV copies of each table (for inspection in Excel)
│   └── simulated/simulated_detections.csv
├── app/
│   ├── app.py                    # Flask API + serves the dashboard
│   └── static/
│       ├── index.html
│       ├── app.js
│       ├── style.css
│       └── vendor/               # leaflet + chart.js files, downloaded once
├── docs/
│   └── INSPECTION_REPORT.md      # written in T0/T2
├── requirements.txt
├── README.md
├── PRD.md  TECH_SPEC.md  TASKS.md  AGENTS.md
```

If existing scripts are already in `processing/`, keep them and reuse their logic; do not delete them.

---

## 2. Dependencies

Python 3.10 or newer.

| Package | Why |
|---|---|
| pandas, numpy | Tables and statistics |
| scikit-learn | DBSCAN clustering only (no ML models) |
| shapely (≥ 2.0) | Geometry: point-in-polygon, distance |
| pyproj | Convert lat/lon to metres |
| flask | API + serve dashboard |

`sqlite3`, `json`, `pathlib` are built into Python.

Front end (downloaded once into `app/static/vendor/`, not loaded from a CDN at runtime):
- Leaflet 1.9.x (`leaflet.js`, `leaflet.css`, marker images)
- Chart.js 4.x (`chart.umd.min.js`)

No other packages. Adding one requires the user's approval (see AGENTS.md).

---

## 3. Configuration (`processing/config.py`)

All parameters in one place. Values marked **(T0)** must be filled from the inspection in Task T0.

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- paths ---
RAW_FIRMS_DIR   = ROOT / "data" / "..."        # (T0) folder containing the 73 CSVs
RAW_OSM_FILE    = ROOT / "data" / "..."        # (T0) the Gujarat industrial GeoJSON
LEGACY_SITES_CSV = ROOT / "output" / "thermal_sites.csv"
DB_PATH         = ROOT / "output" / "thermograph.db"
EXPORT_DIR      = ROOT / "output" / "exports"
SIM_CSV         = ROOT / "output" / "simulated" / "simulated_detections.csv"

# --- expected input facts (pipeline stops if different) ---
EXPECTED_DETECTIONS = 21513
EXPECTED_FACILITIES = 710
EXPECTED_FIRMS_FILES = 73

# --- time ---
DATASET_START = "2025-07-01"
DATASET_END   = "2026-06-30"        # also the "status as of" date
N_WEEKS       = 52                  # weeks 0..51; week 51 = 23–30 Jun 2026 (8 days)
BASELINE_WEEKS   = range(0, 39)     # 1 Jul 2025 – 30 Mar 2026
MONITORING_WEEKS = range(39, 52)    # 31 Mar 2026 – 30 Jun 2026
SIM_WEEK      = 52                  # 1–7 Jul 2026, simulated only

# --- clustering ---
CLUSTER_EPS_KM      = None   # (T0) copy from the existing clustering script
CLUSTER_MIN_SAMPLES = None   # (T0) copy from the existing clustering script
# If T0 cannot recover the original values, use 0.75 and 5 and record this in INSPECTION_REPORT.md
SITE_EXTENT_REVIEW_KM = 5.0

# --- facility matching ---
PROJECTED_CRS  = "EPSG:32643"   # UTM zone 43N, metres. Distance error across Gujarat < 1%.
MATCH_RADIUS_M = 1000

# --- baseline & anomaly ---
BASELINE_MIN_ACTIVE_WEEKS   = 10
ANOMALY_K                   = 3.0
ANOMALY_MIN_DETECTIONS      = 2
NEW_ACTIVITY_MIN_DETECTIONS = 2

# --- priority points ---
PTS_BASELINE_EXCEEDANCE = 3
PTS_NEW_ACTIVITY        = 2
PTS_RECORD_FRP          = 2
PTS_LARGE_EXCEEDANCE    = 1     # ratio >= LARGE_EXCEEDANCE_RATIO
LARGE_EXCEEDANCE_RATIO  = 2.0
PTS_FACILITY_MATCH      = 1
PRIORITY_HIGH_MIN   = 5
PRIORITY_MEDIUM_MIN = 3

# --- simulation ---
SIM_SEED             = 42
SIM_N_DETECTIONS     = 6
SIM_FRP_MULTIPLIER   = 1.5
SIM_JITTER_M         = 200
```

---

## 4. Database schema (`output/thermograph.db`)

The pipeline deletes and rebuilds the database on every run (it is a generated file, not raw data).

### `detections`
| Column | Type | Notes |
|---|---|---|
| detection_id | INTEGER PK | 1..N in load order |
| latitude, longitude | REAL | |
| acq_date | TEXT | `YYYY-MM-DD` |
| acq_time | TEXT | `HHMM`, zero-padded (raw `845` → `0845`) |
| acq_datetime_utc | TEXT | ISO `YYYY-MM-DDTHH:MM:00Z` |
| week_index | INTEGER | see §5.1 |
| frp | REAL | MW |
| bright_ti4, bright_ti5, scan, track | REAL | kept as-is |
| confidence | TEXT | as in source (VIIRS: l / n / h) |
| satellite, instrument, version, daynight | TEXT | as in source |
| type | INTEGER | as in source |
| source_file | TEXT | CSV filename |
| site_id | TEXT NULL | `TS-xxxx` or NULL (isolated) |
| is_simulated | INTEGER | 0 real, 1 simulated |

### `sites`
| Column | Type | Notes |
|---|---|---|
| site_id | TEXT PK | `TS-0001` … |
| centroid_lat, centroid_lon | REAL | mean of member coordinates |
| extent_km | REAL | max distance from centroid to any member × 2 |
| n_detections | INTEGER | real detections only |
| first_seen, last_seen | TEXT | dates |
| active_weeks_total | INTEGER | weeks (0–51) with ≥1 detection |
| night_fraction | REAL | share with `daynight = 'N'` |
| static_type_fraction | REAL | share with `type = 2` |
| mean_frp, max_frp | REAL | |
| facility_id | TEXT NULL | OSM `@id` |
| match_type | TEXT | `inside` / `nearby` / `none` |
| match_distance_m | REAL NULL | 0 for inside |
| site_class | TEXT | see PRD FR-16 |
| status | TEXT | `HIGH` / `MEDIUM` / `LOW` / `NORMAL` / `INSUFFICIENT_HISTORY` / `NEW_SITE_NO_ANOMALY` (real data only) |

### `facilities`
| Column | Type | Notes |
|---|---|---|
| facility_id | TEXT PK | OSM `@id` (e.g. `way/123`) |
| name | TEXT NULL | |
| industrial, landuse, osm_type, wikidata | TEXT NULL | from properties |
| geometry_type | TEXT | Point / Polygon / MultiPolygon / … |
| centroid_lat, centroid_lon | REAL | |
| geojson | TEXT | the feature geometry as GeoJSON text |
| display_name | TEXT | name, or `Unnamed <industrial or landuse> site (OSM <id>)` |

### `site_weekly`
| Column | Type |
|---|---|
| site_id | TEXT |
| week_index | INTEGER (0–51, 52 only for simulated) |
| week_start, week_end | TEXT |
| period | TEXT (`baseline` / `monitoring` / `simulated`) |
| detection_count | INTEGER |
| frp_sum, frp_max | REAL (0 when no detections) |
| night_count | INTEGER |
| is_simulated | INTEGER |

Primary key: (site_id, week_index).

### `baselines`
| Column | Type |
|---|---|
| site_id | TEXT PK |
| n_weeks | INTEGER (always 39) |
| active_weeks | INTEGER |
| baseline_detections | INTEGER |
| frp_sum_mean, frp_sum_std | REAL |
| threshold | REAL |
| baseline_max_frp | REAL (highest single detection; 0 if none) |
| established | INTEGER (0/1) |

### `anomalies`
| Column | Type |
|---|---|
| anomaly_id | INTEGER PK |
| site_id | TEXT |
| week_index, week_start, week_end | |
| anomaly_type | TEXT (`BASELINE_EXCEEDANCE` / `NEW_ACTIVITY`) |
| detection_count | INTEGER |
| frp_sum, frp_max | REAL |
| threshold | REAL NULL (NULL for NEW_ACTIVITY) |
| ratio | REAL NULL (frp_sum / threshold) |
| score | INTEGER |
| priority | TEXT (`HIGH` / `MEDIUM` / `LOW`) |
| reasons | TEXT (JSON list of strings) |
| is_simulated | INTEGER |

### `metadata`
Key/value table: every config parameter, run timestamp, row counts, legacy comparison numbers.

---

## 5. Pipeline stages

### 5.1 Stage 1 — Load FIRMS (`load_firms.py`)
1. List all `*.csv` in `RAW_FIRMS_DIR`. Check count = 73.
2. Read each with pandas; add `source_file`.
3. Check all 15 expected columns exist. Stop with a clear message if not.
4. Concatenate; check row count = 21,513.
5. `acq_time` → zero-padded 4-digit string. Build `acq_datetime_utc`.
6. `week_index = min((acq_date − 2025-07-01).days // 7, 51)`.
7. Check all dates are within the dataset period.
8. Insert into `detections` with `site_id = NULL`, `is_simulated = 0`.

Week dates: `week_start = 2025-07-01 + 7 × week_index`; `week_end = week_start + 6 days`, except week 51 ends 2026-06-30.

### 5.2 Stage 2 — Cluster sites (`cluster_sites.py`)
1. Take all real detections. Coordinates → radians.
2. `DBSCAN(eps = CLUSTER_EPS_KM / 6371.0088, min_samples = CLUSTER_MIN_SAMPLES, metric = "haversine", algorithm = "ball_tree")`.
3. Label −1 → isolated (site_id stays NULL).
4. Order clusters by detection count descending (ties: higher centroid latitude first); assign `TS-0001`, `TS-0002`, ….
5. Compute site fields: centroid, extent_km (haversine), n_detections, first/last seen, mean/max FRP, night_fraction, static_type_fraction.
6. Write legacy comparison to `metadata`: legacy site count, new site count, assigned and isolated counts.

Note: clustering uses the full 12 months. A site that appears only in the monitoring period is therefore still a site — it becomes `NEW_ACTIVITY` in Stage 7.

### 5.3 Stage 3 — Load facilities (`load_facilities.py`)
1. Read GeoJSON with `json`. Check feature count = 710.
2. For each feature: `shapely.geometry.shape(feature["geometry"])`; if invalid, apply `.buffer(0)` for polygons and count how many needed fixing.
3. Read properties: `@id`, `name`, `industrial`, `landuse`, `type`, `wikidata` (missing → NULL). Confirm the actual property names in T0 — the geometry may be in the standard `geometry` field even if a `@geometry` property also exists.
4. Store centroid and GeoJSON text. Build `display_name`.

### 5.4 Stage 4 — Match sites to facilities (`match_facilities.py`)
1. Build a pyproj `Transformer.from_crs("EPSG:4326", PROJECTED_CRS, always_xy=True)`.
2. Project all facility geometries and site centroids to metres.
3. For each site:
   - Find facilities whose polygon **contains** the site centre. If one or more: `match_type = inside`, distance 0. If several, prefer one with a name; then the smallest area.
   - Else compute distance to every facility (568 × 710 comparisons is fine without spatial indexing). If the nearest is ≤ 1,000 m: `match_type = nearby`, store distance rounded to the nearest metre.
   - Else `match_type = none`.

### 5.5 Stage 5 — Weekly history and site class (`site_history.py`)
1. For every site × week 0–51, aggregate: detection_count, frp_sum, frp_max, night_count. Fill missing weeks with zeros (568 sites → 29,536 rows if 568 sites).
2. Set `period` = baseline for weeks 0–38, monitoring for 39–51.
3. `active_weeks_total` = weeks with detection_count > 0.
4. `site_class` is set after Stage 6 (needs `established`), using PRD FR-16.

### 5.6 Stage 6 — Baselines (`baselines.py`)
For each site, using baseline weeks 0–38 (all 39, zeros included):
- `frp_sum_mean` = mean of weekly frp_sum
- `frp_sum_std` = standard deviation (`ddof = 0`, i.e. population)
- `threshold` = mean + 3 × std
- `active_weeks` = weeks with detections
- `baseline_detections` = total detections in baseline
- `baseline_max_frp` = highest single-detection FRP in baseline (0 if none)
- `established` = 1 if active_weeks ≥ 10 else 0

Then fill `sites.site_class`.

### 5.7 Stage 7 — Anomalies, priority, reasons (`anomalies.py`)
For each site and each monitoring week (39–51):

| Condition | Result |
|---|---|
| established = 1 AND detection_count ≥ 2 AND frp_sum > threshold | `BASELINE_EXCEEDANCE`, ratio = frp_sum / threshold |
| baseline_detections = 0 AND detection_count ≥ 2 | `NEW_ACTIVITY` |
| otherwise | no anomaly |

Then score it (§7) and write reasons (§6).

Site `status` (real data only):
- Has anomalies → the priority of its highest-scoring anomaly (`HIGH`/`MEDIUM`/`LOW`)
- established, no anomalies → `NORMAL`
- baseline_detections = 0, no anomaly → `NEW_SITE_NO_ANOMALY`
- otherwise → `INSUFFICIENT_HISTORY`

### 5.8 Stage 8 — Simulated event (`simulate_event.py`)
1. Choose the site: `site_class = PERSISTENT_INDUSTRIAL`, status `NORMAL`, highest `active_weeks` (ties: most detections).
2. Generate `SIM_N_DETECTIONS` detections in week 52 (dates spread across 1–7 Jul 2026, night-time), located at the centroid plus random offsets ≤ `SIM_JITTER_M` metres (seed `SIM_SEED`).
3. Each FRP = `baseline_max_frp × SIM_FRP_MULTIPLIER`.
4. Save to `SIM_CSV`; insert into `detections` with `is_simulated = 1`; add a `site_weekly` row for week 52 with `period = simulated`, `is_simulated = 1`.
5. Run the same Stage 7 rules on week 52; store the anomaly with `is_simulated = 1` and every reason prefixed `[SIMULATED] `.
6. Do not change the site's real `status`.

Stages 1–8 must never let simulated rows affect real baselines, counts or statuses.

---

## 6. Explanation templates

Numbers: FRP to 1 decimal, ratio to 1 decimal, distances in whole metres. Dates like `31 Mar 2026`.

| Trigger | Reason text |
|---|---|
| BASELINE_EXCEEDANCE | `Weekly heat output {frp_sum} MW ({week_start}–{week_end}) exceeded this site's normal upper limit of {threshold} MW (baseline average {mean} MW + 3 × variation {std} MW, from 39 weeks, 1 Jul 2025–30 Mar 2026).` |
| NEW_ACTIVITY | `No detections at this location during the 39-week baseline period; {detection_count} detections in the week {week_start}–{week_end}.` |
| Record FRP | `Strongest single detection this week ({frp_max} MW) is higher than anything seen here in the baseline period (previous highest {baseline_max_frp} MW).` |
| Large exceedance | `Heat output was {ratio}× the normal upper limit.` |
| Facility inside | `Located inside mapped industrial facility: {display_name}{tag_text}.` |
| Facility nearby | `Located {distance} m from mapped industrial facility: {display_name}{tag_text}.` |
| No facility (no points) | `No mapped OSM industrial facility within 1 km — source needs manual verification.` |

`tag_text` = ` (industrial={industrial})` if present, else ` (landuse={landuse})` if present, else empty. Units note: "weekly heat output" = sum of FRP of all detections in that week (MW).

---

## 7. Priority scoring

| Rule | Points |
|---|---|
| Anomaly type BASELINE_EXCEEDANCE | +3 |
| Anomaly type NEW_ACTIVITY | +2 |
| Week's frp_max > site's baseline_max_frp (BASELINE_EXCEEDANCE only) | +2 |
| ratio ≥ 2.0 | +1 |
| Site matched to a facility (inside or nearby) | +1 |

Level: score ≥ 5 → HIGH; 3–4 → MEDIUM; 1–2 → LOW.

Maps to the deck's "weighted sum": baseline deviation (+3, +1), FRP intensity (+2), proximity to infrastructure (+1). Population proximity is not included (no data). These points are **prototype settings**, not calibrated weights.

Worked examples:
- Exceedance at matched site, new record FRP, ratio 2.4 → 3+2+1+1 = 7 → HIGH
- Exceedance at matched site, no record, ratio 1.3 → 3+1 = 4 → MEDIUM
- New activity, unmapped → 2 → LOW (with "needs manual verification" reason)

---

## 8. API contract (`app/app.py`)

- Flask, host `127.0.0.1`, port `5000`. `GET /` serves `static/index.html`.
- Opens the SQLite DB read-only. No calculations beyond filtering/sorting.
- `include_simulated` query parameter: `0` (default) or `1` on every endpoint.
- Errors: unknown site → 404 `{"error": "site not found"}`.

### `GET /api/dashboard`
```json
{
  "dataset_start": "2025-07-01", "dataset_end": "2026-06-30",
  "status_as_of": "2026-06-30",
  "baseline_period": ["2025-07-01", "2026-03-30"],
  "monitoring_period": ["2026-03-31", "2026-06-30"],
  "counts": {
    "detections": 21513, "sites": 568, "isolated_detections": 10974,
    "facilities": 710, "sites_matched": 0, "sites_unmapped": 0,
    "sites_by_class": {"PERSISTENT_INDUSTRIAL": 0, "PERSISTENT_UNMAPPED": 0, "EPISODIC_NEAR_FACILITY": 0, "EPISODIC_OTHER": 0},
    "sites_by_status": {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "NORMAL": 0, "INSUFFICIENT_HISTORY": 0, "NEW_SITE_NO_ANOMALY": 0}
  },
  "parameters": { "...": "all config values from metadata" },
  "simulated_included": false
}
```
(Numbers above are placeholders showing the shape; real values come from the DB.)

### `GET /api/sites`
List of `{site_id, lat, lon, site_class, status, n_detections, facility_display_name, match_type}`.

### `GET /api/sites/<site_id>`
```json
{
  "site": { "...all sites columns..." },
  "facility": { "facility_id": "...", "display_name": "...", "industrial": "...", "landuse": "...", "distance_m": 0, "osm_url": "https://www.openstreetmap.org/way/..." },
  "baseline": { "...baselines columns..." },
  "weekly": [ {"week_index": 0, "week_start": "...", "period": "baseline", "detection_count": 0, "frp_sum": 0.0, "frp_max": 0.0} ],
  "anomalies": [ {"week_start": "...", "anomaly_type": "...", "score": 0, "priority": "...", "reasons": ["..."], "is_simulated": false} ]
}
```
`facility` is `null` when unmapped.

### `GET /api/facilities`
GeoJSON FeatureCollection of all 710 facilities with properties `facility_id, display_name, industrial, landuse`.

### `GET /api/anomalies`
All anomaly rows, newest week first. Optional `?site_id=`.

### `GET /api/risk`
One row per anomalous site (its top-scoring anomaly), sorted by score descending, then frp_sum descending: `{rank, site_id, lat, lon, priority, score, anomaly_type, week_start, facility_display_name, top_reason}`.

### `GET /api/detections/isolated`
`[[lat, lon], ...]` for isolated real detections (compact, for the toggle layer).

---

## 9. Dashboard (`app/static/`)

Layout (desktop, one page, no router):

```
┌──────────────────────────────── Header: title · dataset period · "Status as of 30 Jun 2026" · counts ───────────┐
│  Priority list (left, ~25%)  │            Map (center)             │   Site panel (right, ~30%, opens on click)   │
│  rank · site · level · reason│  circle markers + layer toggles     │   class · facility · stats · chart · reasons │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
Footer link: "About this prototype"
```

- Map centred on Gujarat (approx. 22.5°N, 71.5°E, zoom 7). Basemap: OpenStreetMap tiles with attribution. Use `preferCanvas: true`.
- Site markers (`L.circleMarker`): HIGH `#d62728`, MEDIUM `#ff7f0e`, LOW `#e6c229`, NORMAL `#2ca02c`, INSUFFICIENT_HISTORY / NEW_SITE_NO_ANOMALY `#9e9e9e`. Radius 5–12 px scaled by log of n_detections. Legend in map corner.
- Layers control: "Thermal sites" (on), "OSM industrial facilities" (outlines, on), "Isolated detections" (small grey dots, off), "Show simulated demo event" (off).
- When simulated is on: re-fetch with `include_simulated=1`; show a fixed red banner "SIMULATED EVENT SHOWN — not a real observation"; simulated marker has a dashed outline.
- Site panel chart (Chart.js bar chart): x = 52 weeks (plus week 52 if simulated shown), y = weekly total FRP (MW); horizontal dashed line = threshold (only if established); monitoring weeks shaded; anomalous weeks coloured by priority; simulated week hatched or labelled.
- Site panel text: class label (PRD FR-16 display labels), facility (name, tags, distance, link to openstreetmap.org), evidence (detections, active weeks, first/last seen, night fraction %, FIRMS type-2 fraction %), baseline numbers, anomaly list with all reasons, and score breakdown.
- About panel: short method description, table of parameters from `/api/dashboard`, limitations from PRD §11.
- No frameworks. Plain JavaScript `fetch()`.

---

## 10. Verification checks (`processing/check_outputs.py`)

Prints `PASS`/`FAIL` for each; exit code 1 if any fail.

| # | Check |
|---|---|
| C1 | detections (real) = 21,513 |
| C2 | all real detection dates within 2025-07-01 … 2026-06-30; week_index in 0–51 |
| C3 | assigned + isolated = 21,513 |
| C4 | every site has ≥ CLUSTER_MIN_SAMPLES detections |
| C5 | sum of sites.n_detections = assigned detections |
| C6 | facilities = 710 |
| C7 | every site has match_type in {inside, nearby, none}; nearby distances ≤ 1,000; inside distances = 0; none has NULL facility_id |
| C8 | site_weekly real rows = number of sites × 52 |
| C9 | sum of site_weekly.detection_count (real) = assigned detections |
| C10 | every baseline has n_weeks = 39 and threshold = mean + 3 × std (within 0.001) |
| C11 | every BASELINE_EXCEEDANCE has established = 1, count ≥ 2, frp_sum > threshold; every NEW_ACTIVITY has baseline_detections = 0 |
| C12 | every anomaly score equals the recomputed points; priority matches score |
| C13 | every anomaly has ≥ 1 reason; every simulated reason starts with `[SIMULATED]` |
| C14 | no simulated row has week_index < 52; real statuses unchanged after Stage 8 |
| C15 | raw data folder unchanged (file count and total size same as recorded in T0) |

Also print (information, not pass/fail): legacy vs new cluster counts, sites with extent > 5 km, counts by class, status, match_type, anomaly type and priority.
