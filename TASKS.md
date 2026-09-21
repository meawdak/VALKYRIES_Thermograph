# THERMOGRAPH — Implementation Tasks

Give Antigravity **one task at a time**: "Read AGENTS.md, PRD.md and TECH_SPEC.md. Do task T1 only."
After each task, run the verification step yourself before moving on.

Order: T0 → T1 → … → T12. Do not skip. **T8 is a STOP point**: review results with Claude/ChatGPT before building the UI.

---

## T0 — Inspect the project (read-only)

**Objective:** Find out exactly what already exists before writing any code.

**Change:** Create `docs/INSPECTION_REPORT.md`, `requirements.txt`, `processing/config.py`. Modify nothing else.

**Inputs:** Everything in `data/`, `processing/`, `output/`.

**Steps:**
1. List all files in `data/`, `processing/`, `output/` with sizes.
2. Identify the folder with the 73 FIRMS CSVs and the OSM GeoJSON file. Record exact paths.
3. Count FIRMS rows across files; count GeoJSON features; list GeoJSON property names and geometry types (count per type).
4. Open the existing clustering script. Record: method, radius (eps), min_samples, distance metric, any filtering.
5. Open `output/thermal_sites.csv`: record its columns and row count.
6. Record raw data folder file count and total size in bytes (used by check C15).
7. Fill the (T0) values in `config.py`.

**Expected output:** `docs/INSPECTION_REPORT.md` with sections: Files, Raw data paths, FIRMS facts, OSM facts, Existing clustering method, Legacy output, Raw folder fingerprint, Problems found.

**Acceptance criteria:**
- FIRMS: 73 files, 21,513 rows reported.
- OSM: 710 features reported, with geometry type counts.
- Clustering parameters stated with the line of code they came from, OR the report says they could not be found and defaults 0.75 km / 5 will be used.
- No file in `data/` was changed.

**Verify:** Open the report. Check the three numbers (73, 21,513, 710). Check the clustering parameters are quoted from real code.

---

## T1 — Load FIRMS into the database

**Objective:** One clean table of all detections.

**Change:** Create `processing/db.py`, `processing/load_firms.py`, first version of `processing/check_outputs.py` (checks C1, C2).

**Inputs:** Raw FIRMS CSVs.

**Expected output:** `output/thermograph.db` with `detections` and `metadata` tables; `output/exports/detections.csv`.

**Acceptance criteria:** TECH_SPEC §5.1 implemented; C1 and C2 PASS; `acq_time` zero-padded; week 51 contains 30 Jun 2026 detections.

**Verify:** Run `python processing/load_firms.py` then `python processing/check_outputs.py`. Open `detections.csv` in Excel: 21,513 data rows; spot-check that a row with `acq_time` 845 shows `0845`.

---

## T2 — Cluster detections into sites

**Objective:** Reproduce and document the thermal sites.

**Change:** `processing/cluster_sites.py`; add checks C3–C5; append a "Clustering result" section to the inspection report.

**Inputs:** `detections` table.

**Expected output:** `sites` table (basic fields), `site_id` filled in `detections`, `exports/sites.csv`.

**Acceptance criteria:**
- TECH_SPEC §5.2 implemented. C3–C5 PASS.
- Report states new vs legacy counts (sites / assigned / isolated). If different from 568 / 10,539 / 10,974, the report explains why.
- Sites with extent > 5 km listed.
- `output/thermal_sites.csv` unchanged.

**Verify:** Compare the three numbers to the legacy result. Open `sites.csv`, sort by n_detections: `TS-0001` has the most detections. Paste the top 3 site coordinates into Google Maps satellite view — do they look like industrial areas?

---

## T3 — Load OSM facilities

**Objective:** Facilities table ready for matching.

**Change:** `processing/load_facilities.py`; add check C6.

**Expected output:** `facilities` table; `exports/facilities.csv`.

**Acceptance criteria:** TECH_SPEC §5.3; C6 PASS; script prints count of geometries that needed fixing and count per geometry type; every row has a `display_name`.

**Verify:** Open `facilities.csv`: 710 rows. Pick one named facility, search its name on openstreetmap.org — it should be in Gujarat at roughly the same coordinates.

---

## T4 — Match sites to facilities

**Objective:** Attach facility context to each site.

**Change:** `processing/match_facilities.py`; add check C7.

**Expected output:** `sites.facility_id`, `match_type`, `match_distance_m` filled.

**Acceptance criteria:** TECH_SPEC §5.4; C7 PASS; script prints counts of inside / nearby / none.

**Verify:**
- Pick 3 sites: one `inside`, one `nearby`, one `none`. Open `https://www.openstreetmap.org/?mlat=<lat>&mlon=<lon>#map=15/<lat>/<lon>` for each.
  - `inside`: the point should sit on the named facility.
  - `nearby`: a facility should be visible within ~1 km.
  - `none`: no industrial area mapped nearby.
- Check that the Jamnagar refinery area (around 22.3°N, 69.8°E) has at least one large matched site. If not, report it — do not "fix" it by changing parameters.

---

## T5 — Weekly history

**Objective:** 52-week history per site.

**Change:** `processing/site_history.py`; add checks C8, C9.

**Expected output:** `site_weekly` table; `exports/site_weekly.csv`; `active_weeks_total`, `night_fraction`, `static_type_fraction` in `sites`.

**Acceptance criteria:** TECH_SPEC §5.5; C8, C9 PASS; zero weeks present as rows.

**Verify:** Filter `site_weekly.csv` to `TS-0001`: exactly 52 rows, weeks 0–51; detection counts add up to that site's `n_detections`.

---

## T6 — Baselines and site classes

**Objective:** Normal behaviour per site.

**Change:** `processing/baselines.py`; add check C10.

**Expected output:** `baselines` table; `sites.site_class` filled; `exports/baselines.csv`.

**Acceptance criteria:** TECH_SPEC §5.6; C10 PASS; script prints counts per site_class.

**Verify:** For `TS-0001`, in Excel take the 39 baseline-week `frp_sum` values (weeks 0–38) from `site_weekly.csv`: `=AVERAGE(...)` and `=STDEV.P(...)` must match `frp_sum_mean` and `frp_sum_std`; threshold = mean + 3 × std.

---

## T7 — Anomalies, priority, reasons

**Objective:** Detect deviations and explain them.

**Change:** `processing/anomalies.py`; add checks C11–C13.

**Expected output:** `anomalies` table; `sites.status`; `exports/anomalies.csv`.

**Acceptance criteria:** TECH_SPEC §5.7, §6, §7; C11–C13 PASS; script prints counts by anomaly type, priority, and site status (including how many sites are NORMAL).

**Verify:** Pick one anomaly row. Using its reasons, recompute the score by hand with the points table (TECH_SPEC §7). Check the numbers in the reason match `site_weekly` and `baselines` for that site and week.

---

## T8 — STOP: review results (no coding)

**Objective:** Make sure the results make sense before building the dashboard.

**You do:** Share the T7 printed summary and `exports/anomalies.csv` with Claude/ChatGPT. Questions to answer:
- Are there **0** real anomalies? (Then the simulated event becomes the main demo moment.)
- Are there **hundreds**? (Parameters may be too sensitive, or many are seasonal crop burning.)
- Do HIGH anomalies sit at plausible industrial locations?
- Is there at least one `PERSISTENT_INDUSTRIAL` site with status NORMAL? (Needed for "normal flaring is ignored".)

Any parameter change must be agreed, made only in `config.py`, and noted in the inspection report.

---

## T9 — Simulated demo event + pipeline runner

**Objective:** Labelled demo event; one command runs everything.

**Change:** `processing/simulate_event.py`, `processing/run_pipeline.py`; add check C14 and C15.

**Expected output:** `output/simulated/simulated_detections.csv`; simulated rows in DB; `run_pipeline.py` rebuilds the DB from scratch then runs `check_outputs.py`.

**Acceptance criteria:** TECH_SPEC §5.8; all checks C1–C15 PASS; running `python processing/run_pipeline.py` twice gives identical exports (compare file sizes/contents).

**Verify:** Open `simulated_detections.csv` — every row `is_simulated = 1`. In `anomalies.csv`, the simulated row's reasons start with `[SIMULATED]`. Real anomaly count is the same as in T7.

---

## T10 — Flask API

**Objective:** Serve results as JSON.

**Change:** `app/app.py`.

**Expected output:** Endpoints in TECH_SPEC §8.

**Acceptance criteria:** Each endpoint returns valid JSON matching the spec; `include_simulated` works; unknown site → 404; no calculations in the API.

**Verify:** Run `python app/app.py`, then open in a browser:
- `http://127.0.0.1:5000/api/dashboard` — counts match `check_outputs.py` output.
- `http://127.0.0.1:5000/api/sites/TS-0001` — 52 weekly rows.
- `http://127.0.0.1:5000/api/risk` then `...?include_simulated=1` — the second has one extra simulated row.

---

## T11 — Dashboard: map and site panel

**Objective:** Map with sites, facilities, and clickable detail panel.

**Change:** `app/static/index.html`, `app.js`, `style.css`; download Leaflet and Chart.js into `app/static/vendor/`.

**Acceptance criteria:** TECH_SPEC §9 map, layers, legend, site panel and chart; header counts from `/api/dashboard`; no numbers hard-coded in HTML/JS.

**Verify:** Open `http://127.0.0.1:5000/`. Click `TS-0001`: chart shows 52 bars; threshold line visible if established; numbers match `/api/sites/TS-0001`. Toggle "Isolated detections" on and off.

---

## T12 — Dashboard: priority list, simulation toggle, About panel

**Objective:** Complete the demo UI.

**Change:** same static files.

**Acceptance criteria:** Priority list from `/api/risk`, clicking zooms and opens panel; simulation toggle shows banner + dashed marker + simulated week in chart; About panel shows parameters and PRD §11 limitations; `README.md` explains the two commands (`python processing/run_pipeline.py`, `python app/app.py`).

**Verify:** Walk through the PRD §10 judge checklist on screen, all 8 items. Turn simulation off: banner and simulated items disappear.

---

After T12: write `DEMO_SCRIPT.md` (with Claude) based on the actual results.
