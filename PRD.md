# THERMOGRAPH — Prototype Product Requirements Document (PRD)

| | |
|---|---|
| Project | THERMOGRAPH — SIH 2026, Problem Statement 26162 |
| Team | VALKYRIES (Team ID 147017) |
| Document version | 1.0 |
| Status | Approved for implementation |
| Companion documents | `TECH_SPEC.md` (how), `TASKS.md` (build order), `AGENTS.md` (rules for the coding agent) |

---

## 1. Purpose

THERMOGRAPH turns anonymous satellite hotspots into **places with a history**.

The prototype must prove one idea on real data:

> **"THERMOGRAPH classifies places, not individual hotspots."**

It does this for **Gujarat**, using **12 months of real NASA FIRMS (VIIRS) detections (1 Jul 2025 – 30 Jun 2026)** and **710 OpenStreetMap industrial features**.

The prototype is a **working proof of concept**, not a national operational system.

---

## 2. What the prototype must prove

A judge watching the demo must be able to see, on real data:

1. Raw FIRMS detections are grouped into **persistent thermal sites** (places).
2. Sites are **matched to nearby OSM industrial facilities** where a match exists, and marked **unmapped** where none exists.
3. Each site has a **historical baseline** — its normal weekly heat output.
4. A site that behaves **normally** (e.g. routine flaring) is **not flagged**.
5. A site that **deviates from its own baseline** is flagged as an anomaly.
6. Every flag has a **plain-English explanation** and a **priority level** calculated by documented rules.
7. All of this is visible on **one interactive map** of Gujarat.

---

## 3. Users

| User | Role in prototype |
|---|---|
| **Primary persona:** Analyst at the Gujarat Pollution Control Board (GPCB) | The dashboard is designed for this person: "Which industrial sites behaved unusually recently, and why?" |
| Disaster management / fire services | Mentioned in pitch as future users; no dedicated features in prototype. |
| SIH judges | Audience for the demo. Must be able to verify every number shown. |

---

## 4. Reconciliation: proposed system vs prototype

The technical report and presentation describe the full intended system. The prototype implements only what the available data can scientifically support. **This table is binding** — the prototype must not claim anything in the "Proposed" column that is marked as not implemented.

| # | Proposed in report/deck | Prototype decision | Reason | Future version |
|---|---|---|---|---|
| 1 | 10+ years of historical VIIRS/FIRMS data | **12 months** (1 Jul 2025 – 30 Jun 2026) | This is the data actually collected and verified. Enough to show a baseline exists. | Extend history to 5–10 years for seasonal baselines. |
| 2 | ML classification (scikit-learn, XGBoost) | **Not implemented.** Transparent **rule-based** site classification and anomaly detection. | No labelled training data exists. A model without training data would be fake. | Train a classifier once a labelled dataset (verified industrial vs non-industrial sites) is built and validated. |
| 3 | Classify industrial / agricultural / mining / wildfire | **Coarse rule-based classes only:** persistent vs episodic, facility-matched vs unmapped (see §7.4). | Separating agriculture vs wildfire vs mining needs land-cover data and labels we do not have. | Add land-cover data + ML. |
| 4 | Sentinel-2 imagery, SAR, VIIRS Nightfire, Flaring Monitor | **Not used.** | Not collected. | Add Sentinel-2 as visual verification evidence. |
| 5 | WorldPop / GHSL population; "proximity to population" in risk score | **Removed from risk score.** Risk uses baseline deviation, FRP intensity and facility context only. | Population data not collected. | Add population exposure to risk score. |
| 6 | PostgreSQL / PostGIS | **SQLite** (single file, built into Python) + Shapely/pyproj for geometry. | Runs on a low-resource laptop with no database server. Tables have the same shape as a PostGIS design. | Migrate tables to PostGIS for national scale. |
| 7 | React + Leaflet dashboard | **Single HTML page + Leaflet + Chart.js**, no build step. | Simpler to build, run and debug. | React front end if the UI grows. |
| 8 | Live / continuous monitoring | **Replay of historical data** "as of 30 Jun 2026". | Demo must not depend on a live API or venue internet. | Scheduled FIRMS ingestion (daily). |
| 9 | Targeted alerts (email/SMS/webhook, role and jurisdiction filtering) | **Not implemented.** | Not required to prove the core idea; no recipient data. | Notification service. |
| 10 | Investigation tracking | **Not implemented.** | Not required for core demo. | Add status workflow. |
| 11 | "Confidence value" on every alert (report §6, benefit 5) | **Not shown as a THERMOGRAPH score.** Only FIRMS's own per-detection confidence (low/nominal/high) is shown as source data. | We have no validation data to compute a measured confidence. | Calibrated confidence after validation. |
| 12 | Flask REST API: `/api/anomalies`, `/api/facilities`, `/api/risk`, `/api/dashboard` | **Implemented**, plus `/api/sites` and `/api/sites/<id>` for the site registry. | Matches the architecture in the deck. | — |

---

## 5. Scope

### 5.1 In scope

| ID | Feature |
|---|---|
| F1 | Load, validate and normalise the 73 raw FIRMS CSV files into one table (raw files untouched). |
| F2 | Group detections into candidate thermal sites using documented spatial clustering. Detections not in any site are kept as **isolated detections**. |
| F3 | Load the 710 OSM features and match each site to the nearest facility (inside or within 1 km), else mark it **unmapped**. |
| F4 | Build a weekly activity history (52 weeks) for every site. |
| F5 | Compute a per-site baseline from the **baseline period** and detect deviations in the **monitoring period**. |
| F6 | Assign a rule-based site class, anomaly type, priority score, priority level and plain-English reasons. |
| F7 | One clearly labelled **simulated** demo event (hidden by default). |
| F8 | Flask API serving the processed results. |
| F9 | Single-page Leaflet dashboard: map, site detail panel with weekly chart, ranked priority list, "About this prototype" panel. |
| F10 | A verification script that prints PASS/FAIL checks for every pipeline stage. |

### 5.2 Out of scope (do not build)

- Any machine-learning model, training, or accuracy metric.
- Data outside Gujarat, or FIRMS data outside 1 Jul 2025 – 30 Jun 2026.
- Live FIRMS API calls, scheduled ingestion, background jobs.
- Sentinel-2, SAR, population or land-cover data.
- Email/SMS/webhook sending, user accounts, login, role-based access.
- Investigation workflow, editing data through the UI.
- React, Node build tools, Docker, PostGIS, cloud deployment.
- Additional pages beyond the single dashboard page.

---

## 6. Input data (verified facts)

| Dataset | Facts |
|---|---|
| NASA FIRMS (VIIRS) | Gujarat; 1 Jul 2025 – 30 Jun 2026; 73 CSV files; **21,513 detections**; 15 columns: `latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight, type`; 0 missing coordinates; 0 missing FRP; 0 duplicate rows. |
| OSM industrial facilities | Gujarat; GeoJSON; **710 features**; fields include `@id, industrial, landuse, name, type, wikidata, @geometry`. |
| Earlier clustering result (legacy) | `output/thermal_sites.csv`: 568 candidate sites, 10,539 detections assigned, 10,974 noise. Treated as an intermediate result to be audited and reproduced, not as final. |

Exact file paths are confirmed in Task T0 and recorded in `processing/config.py`.

---

## 7. Functional requirements

Each requirement is testable. Exact algorithms and parameters are in `TECH_SPEC.md`.

### 7.1 Data loading (F1)

- **FR-01** The pipeline reads every FIRMS CSV from the raw data folder without modifying, moving or rewriting any raw file.
- **FR-02** The loaded detection table contains exactly **21,513** rows. If not, the pipeline stops with an error message showing the actual count.
- **FR-03** Every detection has a parsed UTC date-time (from `acq_date` + `acq_time`), a week index 0–51, and the name of its source file.
- **FR-04** All detections fall between 2025-07-01 and 2026-06-30 inclusive.

### 7.2 Thermal sites (F2)

- **FR-05** Detections are clustered with DBSCAN using haversine (great-circle) distance. The radius and minimum-points parameters are stored in `config.py` and recorded in the database metadata table.
- **FR-06** Each cluster becomes a site with a stable ID in the form `TS-0001` (ordered by detection count, largest first).
- **FR-07** Detections not assigned to a site are kept with `site_id = NULL` and counted as **isolated detections**. They are never deleted.
- **FR-08** Assigned + isolated detections = 21,513 exactly.
- **FR-09** The first run must either reproduce the legacy result (568 sites / 10,539 assigned / 10,974 isolated) or document in `docs/INSPECTION_REPORT.md` why the numbers differ.
- **FR-10** Any site whose spatial extent exceeds 5 km is listed in the verification output for manual review (possible chaining of unrelated fires).

### 7.3 Facility matching (F3)

- **FR-11** All 710 OSM features are loaded into a facilities table with their OSM ID, name (may be empty), `industrial`, `landuse` and geometry.
- **FR-12** Each site receives exactly one `match_type`: `inside` (site centre lies inside a facility polygon), `nearby` (nearest facility within 1,000 m), or `none` (unmapped).
- **FR-13** Distances are calculated in metres in a projected coordinate system, never in raw degrees.
- **FR-14** Matched sites store the facility ID and distance in metres. Unmapped sites store `NULL`.

### 7.4 Site history and classification (F4, F6)

- **FR-15** For every site, a weekly history of 52 rows exists (weeks with no detections are stored as zero, not skipped), each with detection count, total FRP, maximum FRP and night-time detection count.
- **FR-16** Each site receives one rule-based class:

| Class | Rule | Display label |
|---|---|---|
| `PERSISTENT_INDUSTRIAL` | Established baseline (active in ≥ 10 of 39 baseline weeks) AND facility match | Persistent source at mapped industrial facility |
| `PERSISTENT_UNMAPPED` | Established baseline AND no facility match | Persistent source, no mapped facility — needs verification |
| `EPISODIC_NEAR_FACILITY` | Not established AND facility match | Occasional activity near mapped facility |
| `EPISODIC_OTHER` | Not established AND no facility match | Occasional activity, no industrial evidence found |

- **FR-17** Each site also stores supporting evidence: first/last seen dates, number of active weeks, night-time fraction, and fraction of detections with FIRMS `type = 2`. These are shown as evidence only; they do not change the class.

### 7.5 Baseline and anomaly detection (F5)

- **FR-18** The dataset is split into a **baseline period** (weeks 0–38: 1 Jul 2025 – 30 Mar 2026, 39 weeks) and a **monitoring period** (weeks 39–51: 31 Mar 2026 – 30 Jun 2026, 13 weeks).
- **FR-19** For each site the baseline stores: mean and standard deviation of weekly total FRP over all 39 baseline weeks (including zero weeks), active week count, highest single-detection FRP, and the **threshold = mean + 3 × standard deviation**.
- **FR-20** A monitoring week is a `BASELINE_EXCEEDANCE` anomaly when: the site has an established baseline, the week has ≥ 2 detections, and the week's total FRP is greater than the threshold.
- **FR-21** A monitoring week is a `NEW_ACTIVITY` anomaly when: the site had zero detections in the baseline period and the week has ≥ 2 detections.
- **FR-22** Sites with some baseline activity but no established baseline are **not** evaluated for exceedance and are displayed as "Insufficient history to judge".
- **FR-23** An established site with no anomaly in the monitoring period is displayed as "Within normal range". The dashboard reports how many such sites exist (this is the "normal flaring is ignored" evidence).

### 7.6 Priority and explanation (F6)

- **FR-24** Every anomaly receives a priority score as the sum of documented points (TECH_SPEC §7) and a level: HIGH (≥ 5), MEDIUM (3–4), LOW (1–2).
- **FR-25** Every point awarded produces one plain-English reason containing the actual numbers used (e.g. the week's value, the threshold, the facility name and distance).
- **FR-26** A judge must be able to recompute any score by hand from the reasons shown.

### 7.7 Simulated demo event (F7)

- **FR-27** One simulated event is generated for week 52 (1–7 Jul 2026) at one `PERSISTENT_INDUSTRIAL` site that had no real anomaly, using fixed rules and a fixed random seed.
- **FR-28** Simulated detections are stored only in `output/`, flagged `is_simulated = 1`, and never written to the raw data folder.
- **FR-29** Simulated data is hidden by default. When shown, the dashboard displays a visible "SIMULATED — not a real observation" banner, and every simulated reason starts with `[SIMULATED]`.
- **FR-30** Real results (counts, baselines, anomalies) are identical whether or not the simulated event exists.

### 7.8 API (F8)

- **FR-31** Endpoints `/api/dashboard`, `/api/sites`, `/api/sites/<site_id>`, `/api/facilities`, `/api/anomalies`, `/api/risk` return JSON as specified in TECH_SPEC §8.
- **FR-32** Every endpoint excludes simulated data unless `?include_simulated=1` is passed.
- **FR-33** The API only reads from the database. It never recalculates or invents values.

### 7.9 Dashboard (F9)

- **FR-34** One page shows a map of Gujarat with all sites as circle markers coloured by status (HIGH / MEDIUM / LOW / normal / insufficient history).
- **FR-35** Toggleable layers: OSM facilities (outlines, on), isolated detections (off by default), simulated event (off by default).
- **FR-36** Clicking a site opens a side panel with: site ID, class label, facility match (name/tags/distance or "Unmapped"), evidence stats, a 52-week chart of weekly total FRP with the threshold line and the monitoring period shaded, and the list of anomalies with reasons.
- **FR-37** A ranked priority list shows one row per anomalous site (highest score first). Clicking a row zooms to the site and opens its panel.
- **FR-38** A header shows: dataset period, "Status as of 30 Jun 2026", total detections, sites, isolated detections, matched sites, anomalous sites, sites within normal range.
- **FR-39** An "About this prototype" panel lists the method, parameters and the limitations in §11.

### 7.10 Verification (F10)

- **FR-40** `python processing/check_outputs.py` prints one PASS/FAIL line per check listed in TECH_SPEC §10 and exits with an error if any check fails.

---

## 8. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | Full pipeline runs with **one command** in under 5 minutes on a low-resource laptop. |
| NFR-02 | Dashboard runs with **one command** and loads in under 5 seconds on the local machine. |
| NFR-03 | Only the dependencies listed in TECH_SPEC §2. No database server, no build tools. |
| NFR-04 | The pipeline makes no internet requests. (The map background tiles need internet; see §11.) |
| NFR-05 | Re-running the pipeline produces identical results (deterministic). |
| NFR-06 | All tunable numbers live in `processing/config.py` only. |
| NFR-07 | Code is commented in plain English so a beginner can follow each step. |

---

## 9. Scientific integrity rules

1. Every number shown in the UI comes from the database, computed from real data (or the labelled simulation).
2. No ML model, accuracy, precision, recall, or "confidence %" is shown or claimed.
3. Site classes are called **rule-based classes**, never "AI predictions".
4. Parameters (radius, thresholds, points) are called **prototype settings**, not calibrated or validated values.
5. "Unmapped" means "no OSM facility within 1 km", never "illegal" or "confirmed non-industrial".
6. Simulated data is always labelled.
7. Thresholds must not be changed to make results look better without the user's explicit approval, and any change is recorded in the metadata table.

---

## 10. Success criteria (judge checklist)

| # | Judge can see | Delivered by |
|---|---|---|
| 1 | A Gujarat map | FR-34 |
| 2 | FIRMS-derived thermal sites | FR-05–FR-10, FR-34, FR-35 (isolated detections toggle shows "dots → places") |
| 3 | Facility information where a match exists | FR-11–FR-14, FR-36 |
| 4 | Historical activity of a selected site | FR-15, FR-36 (52-week chart) |
| 5 | A baseline representing normal behaviour | FR-19, threshold line on chart |
| 6 | Detection of unusual activity when supported by data | FR-20–FR-23; simulated event only if needed, labelled |
| 7 | A simple explanation | FR-25, FR-36 |
| 8 | A priority level from documented rules | FR-24, FR-37, About panel |

---

## 11. Known limitations (state these openly in the About panel and pitch)

1. **12 months only.** The baseline cannot separate seasonal patterns (e.g. crop-burning seasons, monsoon cloud cover in Jul–Sep) from true anomalies.
2. **Cloud cover.** Satellites cannot see heat through thick cloud; monsoon weeks may undercount activity, which can make the baseline lower than reality.
3. **OSM is incomplete.** Unmapped does not mean non-industrial.
4. **Site centre matching.** Large complexes may have a site centre outside the mapped polygon; the 1 km rule partly handles this.
5. **Summed FRP** is used as a simple weekly activity indicator. It depends on how many satellite passes observed the site that week.
6. **Rule-based classes** are not validated against ground truth.
7. **Map background tiles** require internet. A screen recording of the demo is the backup.

---

## 12. Terminology

| Term | Meaning |
|---|---|
| Detection | One row of FIRMS data (one hot pixel seen by a satellite at one time). |
| Site | A group of detections close together in space, treated as one place. ID `TS-xxxx`. |
| Isolated detection | A detection not belonging to any site. |
| Facility | One OSM industrial feature. |
| Baseline period | Weeks 0–38 (1 Jul 2025 – 30 Mar 2026). |
| Monitoring period | Weeks 39–51 (31 Mar – 30 Jun 2026). |
| Established baseline | Site active in ≥ 10 of the 39 baseline weeks. |
| Threshold | Baseline mean + 3 × standard deviation of weekly total FRP. |
| FRP | Fire Radiative Power, in megawatts (MW), reported by FIRMS for each detection. |
| Anomaly | A monitoring week where a site broke the rules in §7.5. |
