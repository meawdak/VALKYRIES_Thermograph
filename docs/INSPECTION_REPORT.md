# THERMOGRAPH — Inspection Report (Task T0)

**Inspection Date:** 2026-09-22  
**Inspector:** Antigravity (Coding Agent)  
**Project:** THERMOGRAPH — SIH 2026, Problem Statement 26162  
**Workspace:** `/home/debasmita/Documents/SIH/thermograph`

---

## 1. Files

A complete inventory of all files present in the existing project directories prior to any pipeline modifications.

### 1.1 `output/`
| File | Size (bytes) | Lines | Notes |
|---|---|---|---|
| `output/thermal_sites.csv` | 49,814 | 570 | Legacy clustering result (568 data rows + 1 header row + 1 trailing newline) |

### 1.2 `processing/`
| File | Size (bytes) | Lines | Notes |
|---|---|---|---|
| `processing/cluster_firms.py` | 2,872 | 135 | Original clustering script using scikit-learn DBSCAN |

### 1.3 `data/` (Excluding `.venv` and `__pycache__`)
| File / Directory | Count | Total Bytes | Notes |
|---|---|---|---|
| `data/osm_industrial_facilities_gujarat.geojson` | 1 file | 257,810 | OpenStreetMap industrial facilities in Gujarat |
| `data/firms/download_gujarat.py` | 1 file | 1,254 | Download script used to fetch NASA FIRMS chunks |
| `data/firms/chunks/*.csv` | 73 files | 1,677,940 | Raw 5-day NASA FIRMS VIIRS detection CSV files |

#### Breakdown of the 73 FIRMS Chunk Files:
| Filename | Size (bytes) | Rows (excl. header) |
|---|---|---|
| `firms_2025-07-01_2025-07-05.csv` | 206 | 1 |
| `firms_2025-07-06_2025-07-10.csv` | 1,137 | 10 |
| `firms_2025-07-11_2025-07-15.csv` | 2,080 | 19 |
| `firms_2025-07-16_2025-07-20.csv` | 2,141 | 19 |
| `firms_2025-07-21_2025-07-25.csv` | 2,153 | 20 |
| `firms_2025-07-26_2025-07-30.csv` | 127 | 0 |
| `firms_2025-07-31_2025-08-04.csv` | 1,458 | 13 |
| `firms_2025-08-05_2025-08-09.csv` | 4,032 | 39 |
| `firms_2025-08-10_2025-08-14.csv` | 2,459 | 23 |
| `firms_2025-08-15_2025-08-19.csv` | 2,713 | 26 |
| `firms_2025-08-20_2025-08-24.csv` | 1,067 | 9 |
| `firms_2025-08-25_2025-08-29.csv` | 1,066 | 9 |
| `firms_2025-08-30_2025-09-03.csv` | 1,062 | 9 |
| `firms_2025-09-04_2025-09-08.csv` | 748 | 6 |
| `firms_2025-09-09_2025-09-13.csv` | 5,354 | 52 |
| `firms_2025-09-14_2025-09-18.csv` | 3,620 | 35 |
| `firms_2025-09-19_2025-09-23.csv` | 4,187 | 40 |
| `firms_2025-09-24_2025-09-28.csv` | 3,328 | 32 |
| `firms_2025-09-29_2025-10-03.csv` | 4,416 | 42 |
| `firms_2025-10-04_2025-10-08.csv` | 7,009 | 67 |
| `firms_2025-10-09_2025-10-13.csv` | 9,549 | 92 |
| `firms_2025-10-14_2025-10-18.csv` | 11,981 | 116 |
| `firms_2025-10-19_2025-10-23.csv` | 14,089 | 137 |
| `firms_2025-10-24_2025-10-28.csv` | 17,625 | 172 |
| `firms_2025-10-29_2025-11-02.csv` | 1,920 | 17 |
| `firms_2025-11-03_2025-11-07.csv` | 13,609 | 131 |
| `firms_2025-11-08_2025-11-12.csv` | 31,522 | 309 |
| `firms_2025-11-13_2025-11-17.csv` | 17,769 | 173 |
| `firms_2025-11-18_2025-11-22.csv` | 21,218 | 208 |
| `firms_2025-11-23_2025-11-27.csv` | 22,261 | 218 |
| `firms_2025-11-28_2025-12-02.csv` | 17,477 | 170 |
| `firms_2025-12-03_2025-12-07.csv` | 20,655 | 202 |
| `firms_2025-12-08_2025-12-12.csv` | 23,680 | 233 |
| `firms_2025-12-13_2025-12-17.csv` | 22,938 | 224 |
| `firms_2025-12-18_2025-12-22.csv` | 17,223 | 168 |
| `firms_2025-12-23_2025-12-27.csv` | 21,927 | 215 |
| `firms_2025-12-28_2026-01-01.csv` | 21,435 | 209 |
| `firms_2026-01-02_2026-01-06.csv` | 24,305 | 238 |
| `firms_2026-01-07_2026-01-11.csv` | 26,226 | 258 |
| `firms_2026-01-12_2026-01-16.csv` | 27,921 | 274 |
| `firms_2026-01-17_2026-01-21.csv` | 23,510 | 230 |
| `firms_2026-01-22_2026-01-26.csv` | 17,625 | 171 |
| `firms_2026-01-27_2026-01-31.csv` | 19,009 | 185 |
| `firms_2026-02-01_2026-02-05.csv` | 24,635 | 241 |
| `firms_2026-02-06_2026-02-10.csv` | 33,062 | 324 |
| `firms_2026-02-11_2026-02-15.csv` | 29,305 | 287 |
| `firms_2026-02-16_2026-02-20.csv` | 29,509 | 289 |
| `firms_2026-02-21_2026-02-25.csv` | 37,466 | 368 |
| `firms_2026-02-26_2026-03-02.csv` | 40,328 | 396 |
| `firms_2026-03-03_2026-03-07.csv` | 46,167 | 453 |
| `firms_2026-03-08_2026-03-12.csv` | 17,819 | 174 |
| `firms_2026-03-13_2026-03-17.csv` | 85,884 | 845 |
| `firms_2026-03-18_2026-03-22.csv` | 91,114 | 895 |
| `firms_2026-03-23_2026-03-27.csv` | 119,314 | 1,173 |
| `firms_2026-03-28_2026-04-01.csv` | 92,036 | 903 |
| `firms_2026-04-02_2026-04-06.csv` | 74,165 | 728 |
| `firms_2026-04-07_2026-04-11.csv` | 94,957 | 933 |
| `firms_2026-04-12_2026-04-16.csv` | 71,325 | 700 |
| `firms_2026-04-17_2026-04-21.csv` | 70,983 | 696 |
| `firms_2026-04-22_2026-04-26.csv` | 92,272 | 906 |
| `firms_2026-04-27_2026-05-01.csv` | 16,707 | 162 |
| `firms_2026-05-02_2026-05-06.csv` | 127 | 0 |
| `firms_2026-05-07_2026-05-11.csv` | 127 | 0 |
| `firms_2026-05-12_2026-05-16.csv` | 127 | 0 |
| `firms_2026-05-17_2026-05-21.csv` | 127 | 0 |
| `firms_2026-05-22_2026-05-26.csv` | 127 | 0 |
| `firms_2026-05-27_2026-05-31.csv` | 127 | 0 |
| `firms_2026-06-01_2026-06-05.csv` | 16,482 | 161 |
| `firms_2026-06-06_2026-06-10.csv` | 22,566 | 221 |
| `firms_2026-06-11_2026-06-15.csv` | 16,786 | 164 |
| `firms_2026-06-16_2026-06-20.csv` | 11,382 | 111 |
| `firms_2026-06-21_2026-06-25.csv` | 17,462 | 171 |
| `firms_2026-06-26_2026-06-30.csv` | 29,615 | 290 |

---

## 2. Raw Data Paths

- **FIRMS Chunks Directory:**  
  `data/firms/chunks` (relative to workspace root: `/home/debasmita/Documents/SIH/thermograph/data/firms/chunks`)
- **OSM Industrial GeoJSON File:**  
  `data/osm_industrial_facilities_gujarat.geojson` (relative to workspace root: `/home/debasmita/Documents/SIH/thermograph/data/osm_industrial_facilities_gujarat.geojson`)
- **Auxiliary Data Scripts:**  
  `data/firms/download_gujarat.py`

---

## 3. FIRMS Facts

- **Number of CSV files:** **73**
- **Total detections (rows across all files):** **21,513** (excluding headers)
- **Columns (15):**
  1. `latitude` (float)
  2. `longitude` (float)
  3. `bright_ti4` (float, brightness temperature 375m I4)
  4. `scan` (float)
  5. `track` (float)
  6. `acq_date` (text, YYYY-MM-DD)
  7. `acq_time` (int, integer HHMM e.g. 845 or 2113)
  8. `satellite` (text, all `'N'`)
  9. `instrument` (text, all `'VIIRS'`)
  10. `confidence` (text, categorical: `'l'`, `'n'`, `'h'`)
  11. `version` (text, all `'2.0NRT'`)
  12. `bright_ti5` (float, brightness temperature 375m I5)
  13. `frp` (float, Fire Radiative Power in MW)
  14. `daynight` (text, categorical: `'D'`, `'N'`)
  15. `type` (int, categorical: `0`, `2`, `3`)

### Data Quality & Integrity Checks:
- **Missing coordinates:** 0 (0.00%)
- **Missing FRP values:** 0 (0.00%)
- **Duplicate rows:** 0
- **Date range:** `2025-07-01` to `2026-06-30` inclusive (all 21,513 detections fall within this 365-day range)
- **All 73 files share identical headers:** Yes

### Column Distribution Summary:
- **Satellite:** `N` (Suomi NPP): 21,513 (100.0%)
- **Instrument:** `VIIRS`: 21,513 (100.0%)
- **Day/Night:** Day (`D`): 14,850 (69.0%), Night (`N`): 6,663 (31.0%)
- **Confidence:**
  - Nominal (`n`): 16,668 (77.5%)
  - Low (`l`): 4,274 (19.9%)
  - High (`h`): 571 (2.7%)
- **FIRMS Type:**
  - `0` (Presumed vegetation / other): 17,489 (81.3%)
  - `2` (Other static land source / industrial): 3,995 (18.6%)
  - `3` (Offshore detection): 29 (0.1%)

---

## 4. OSM Facts

- **File:** `data/osm_industrial_facilities_gujarat.geojson`
- **File size:** 257,810 bytes
- **Feature count:** **710** features
- **GeoJSON structure:** `FeatureCollection`

### Geometry Types:
| Geometry Type | Feature Count | Percentage |
|---|---|---|
| `Point` | **710** | 100.0% |
| `Polygon` | 0 | 0.0% |
| `MultiPolygon` | 0 | 0.0% |

*Note on geometry format:* In `properties`, 560 features contain `@geometry: "center"`, indicating they represent centroids/centers extracted from OSM ways/relations, while 150 features have `@geometry: null` (native OSM node features). All feature geometry objects in the GeoJSON are of type `Point`.

### Properties Present Across Features:
- `@id`: 710 / 710 (100.0%) — OSM ID (e.g. `relation/9087557`, `way/123456`, `node/7890`)
- `name`: 211 / 710 (29.7%) — Facility name (e.g., "Mundra Port", "Reliance Jamnagar Refinery")
- `industrial`: 111 / 710 (15.6%) — OSM industrial tag (e.g., `port`, `refinery`, `chemical`, `auto_parts`)
- `landuse`: 75 / 710 (10.6%) — OSM landuse tag (e.g., `industrial`, `port`)
- `type`: 5 / 710 (0.7%) — OSM relation type tag (e.g., `multipolygon`)
- `wikidata`: 7 / 710 (1.0%) — Wikidata identifier
- `@geometry`: 560 / 710 (78.9%) — Overpass export marker (`center`)

---

## 5. Existing Clustering Method

- **Script:** `processing/cluster_firms.py`
- **Clustering algorithm:** Scikit-learn DBSCAN (`sklearn.cluster.DBSCAN`)
- **Parameters and source code lines:**
  - **Earth Radius:** `6371.0088` km — Line 41: `EARTH_RADIUS_KM = 6371.0088`
  - **Cluster radius (`eps`):** **1.0 km** (`DISTANCE_KM = 1.0` km, converted to radians as `DISTANCE_KM / EARTH_RADIUS_KM` = `1.0 / 6371.0088` ≈ `0.00015696` rad) — Line 44: `DISTANCE_KM = 1.0`, Line 48: `epsilon = DISTANCE_KM / EARTH_RADIUS_KM`
  - **Min samples (`min_samples`):** **5** detections — Line 45: `MIN_DETECTIONS = 5`
  - **Distance metric:** `"haversine"` — Line 53: `metric="haversine"`
  - **Algorithm:** `"ball_tree"` — Line 54: `algorithm="ball_tree"`
  - **Pre-filtering:** None (all 21,513 detections are clustered)

### Relevant Code Block (`processing/cluster_firms.py`, lines 40–58):
```python
# Earth's radius in kilometres
EARTH_RADIUS_KM = 6371.0088

# Prototype starting parameters
DISTANCE_KM = 1.0
MIN_DETECTIONS = 5

# DBSCAN's eps must be expressed in radians
epsilon = DISTANCE_KM / EARTH_RADIUS_KM

model = DBSCAN(
    eps=epsilon,
    min_samples=MIN_DETECTIONS,
    metric="haversine",
    algorithm="ball_tree"
)

df["cluster_id"] = model.fit_predict(coordinates_rad)
```

### Verification of Clustering Reproduction:
Running DBSCAN with these exact parameters reproduces the legacy output exactly:
- **Candidate thermal sites (clusters):** **568**
- **Detections assigned to clusters:** **10,539**
- **Noise / isolated detections:** **10,974**
- **Total:** 10,539 + 10,974 = **21,513**

---

## 6. Legacy Output (`output/thermal_sites.csv`)

- **File path:** `output/thermal_sites.csv`
- **File size:** 49,814 bytes
- **Row count:** **568** data rows (plus 1 header row)
- **Columns (9):**
  1. `site_id` (e.g. `SITE_00000`, `SITE_00001`, ..., `SITE_00567`)
  2. `latitude` (mean latitude of member detections)
  3. `longitude` (mean longitude of member detections)
  4. `detection_count` (number of detections in cluster)
  5. `active_dates` (distinct dates on which site was observed)
  6. `first_seen` (earliest detection date, YYYY-MM-DD)
  7. `last_seen` (latest detection date, YYYY-MM-DD)
  8. `mean_frp` (mean FRP in MW across member detections)
  9. `max_frp` (maximum single-detection FRP in MW)

### Legacy Metrics Summary:
- **Detection count range:** Minimum 3, Maximum 2,252 (Total assigned: 10,539)
- **Active dates range:** Minimum 1 day, Maximum 270 days
- **Mean FRP range:** 0.35 MW to 46.17 MW
- **Max FRP range:** 0.58 MW to 113.43 MW
- **Ordering:** Ordered by DBSCAN cluster ID (`SITE_00000` to `SITE_00567`), not by detection count.
- **Top site by detections:** `SITE_00000` (centroid ~21.10°N, 72.64°E in Surat industrial belt) with 2,252 detections over 270 active dates.

---

## 7. Raw Folder Fingerprint (Check C15)

To guarantee that raw source data is never modified, moved, renamed or deleted throughout the pipeline development:

### Entire `data/` Directory (including download venv):
- **Total file count:** **10,084** files
- **Total byte size:** **368,830,875** bytes (~351.7 MB)

### Detailed Breakdown:
| Sub-path | Files | Bytes | Notes |
|---|---|---|---|
| `data/osm_industrial_facilities_gujarat.geojson` | 1 | 257,810 | OSM Gujarat facilities |
| `data/firms/chunks/*.csv` | 73 | 1,677,940 | NASA FIRMS 5-day CSV chunks |
| **Total Source Payload** | **74** | **1,935,750** | **Pure raw data inputs** |
| `data/firms/download_gujarat.py` | 1 | 1,254 | Download script |
| `data/firms/__pycache__/` | 1 | 1,958 | Python bytecode cache |
| `data/firms/.venv/` | 10,008 | 366,891,913 | Auxiliary virtual environment |
| **Total in `data/`** | **10,084** | **368,830,875** | Complete directory fingerprint |

---

## 8. Problems and Inconsistencies Found

1. **OSM Geometries are All `Point` (No Polygons):**  
   `TECH_SPEC.md` §5.3 and §5.4 specify handling facility polygons via Shapely containment (`polygon.contains(site_centre)` for `match_type = 'inside'`). However, in `data/osm_industrial_facilities_gujarat.geojson`, all 710 features are `Point` geometries (OSM ways/relations were extracted as center points with property `@geometry = "center"`). Consequently, point-in-polygon containment cannot occur unless distance is 0. All facility matches within 1,000 m will fall under `nearby`, and `inside` will only trigger if distance is 0.0 m. This must be taken into account in `match_facilities.py`.
2. **Cluster Detection Count vs Minimum Samples (`CLUSTER_MIN_SAMPLES = 5`):**  
   In `output/thermal_sites.csv` (and reproduced identically by scikit-learn DBSCAN with `min_samples=5`), two clusters have fewer than 5 member detections:
   - `SITE_00412`: 3 detections (`detection_count = 3`)
   - `SITE_00444`: 4 detections (`detection_count = 4`)  
   In scikit-learn's DBSCAN, a core point must have $\ge 5$ points within its 1.0 km radius, but border points within its neighborhood that were already claimed by earlier clusters remain with those earlier clusters, leaving the remaining core cluster with 3 or 4 points.
   Check C4 in `TECH_SPEC.md` §10 states: *"every site has >= CLUSTER_MIN_SAMPLES detections"*. If strictly implemented as `site.n_detections >= CLUSTER_MIN_SAMPLES`, Check C4 would fail for these 2 sites. Check C4 or the clustering stage should account for this known DBSCAN property.
3. **Auxiliary `.venv` Inside `data/`:**  
   The `data/firms/` directory contains an embedded virtual environment (`.venv/`) with 10,008 files (366.9 MB). Under AGENTS.md Rule 5, nothing in `data/` may be deleted or modified. The raw data fingerprint for Check C15 tracks both the full directory (10,084 files, 368,830,875 bytes) and the pure source payload (74 files, 1,935,750 bytes).
4. **Broken Pip Shebang in Root `.venv`:**  
   The virtual environment at `/home/debasmita/Documents/SIH/thermograph/.venv` has hard-coded shebang paths in `.venv/bin/pip` pointing to `/home/debasmita/Documents/thermograph/.venv/bin/python3` (from before the directory was moved into `SIH/`). Direct calls like `python3 -m pip` or `.venv/bin/python -m pip` function properly, but running `.venv/bin/pip` fails.
5. **Missing Python Dependencies in Local Environment:**  
   The environment currently has `pandas`, `numpy`, and `scikit-learn` in `data/firms/.venv`, but lacks `shapely`, `pyproj`, and `flask` as specified in `requirements.txt`. These will be required starting with T3/T4/T10.
6. **Site ID Scheme Difference:**  
   The legacy script generated `SITE_00000`–`SITE_00567` ordered by arbitrary DBSCAN cluster index. `TECH_SPEC.md` §5.2 requires `TS-0001` ordered by detection count descending (ties broken by higher centroid latitude). This change is planned for Stage 2.

---

## 9. Acceptance Criteria Verification

- [x] **FIRMS: 73 files, 21,513 rows reported.** (Confirmed: exactly 73 CSV files, exactly 21,513 detection rows, 0 null coordinates, 0 null FRP, 0 duplicate rows).
- [x] **OSM: 710 features reported, with geometry type counts.** (Confirmed: exactly 710 features, 710 Point geometries, 0 Polygon, 0 MultiPolygon).
- [x] **Clustering parameters stated with line of code:** (Confirmed: `DISTANCE_KM = 1.0` on Line 44, `MIN_DETECTIONS = 5` on Line 45, `EARTH_RADIUS_KM = 6371.0088` on Line 41, `metric="haversine"` on Line 53, `algorithm="ball_tree"` on Line 54 of `processing/cluster_firms.py`).
- [x] **No file in `data/` was changed.** (Confirmed: `data/` was accessed read-only; file count and total size remain 10,084 files and 368,830,875 bytes).
- [x] **`output/thermal_sites.csv` was not modified or deleted.** (Confirmed: size remains 49,814 bytes, 568 data rows).
