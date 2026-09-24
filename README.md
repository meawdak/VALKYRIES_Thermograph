# THERMOGRAPH

> Geospatial monitoring prototype that turns satellite thermal hotspots into location-aware, explainable intelligence on persistent industrial activity.

[![SIH 2026](https://img.shields.io/badge/SIH-2026-blue.svg)](https://www.sih.gov.in/)
[![Problem Statement 26162](https://img.shields.io/badge/Problem%20Statement-26162-orange.svg)](https://www.sih.gov.in/)
[![Team VALKYRIES](https://img.shields.io/badge/Team-VALKYRIES%20(147017)-purple.svg)](#team)
[![Theme: Disaster Management](https://img.shields.io/badge/Theme-Disaster%20Management-red.svg)](#overview)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](#setup)

---

## Overview

**THERMOGRAPH** is a geospatial monitoring prototype designed to turn satellite-detected thermal hotspots into location-aware, explainable insights regarding persistent thermal activity around industrial infrastructure.

Satellite hotspot feeds identify high-temperature anomalies across wide geographic areas, but an isolated detection lacks crucial context. THERMOGRAPH bridges this gap by aggregating thermal history over time, linking observations to mapped facility boundaries, establishing statistical baselines, and flagging meaningful deviations.

> *"Classify and monitor places, rather than treating every hotspot as an isolated event."*

## Problem

NASA FIRMS detects thermal activity from space with high temporal frequency. However, a raw hotspot coordinate does not inherently explain its origin—routine flare stacks, industrial kiln operations, seasonal agricultural residue burning, and sudden structural fires can produce indistinguishable point observations. Without spatial association and historical baseline tracking, monitoring agencies face alert fatigue and cannot reliably distinguish expected thermal operations from genuine anomalies.

## How It Works

```mermaid
flowchart LR
    A["FIRMS Detections"] --> B["Data Preparation"]
    B --> C["Spatial Clustering"]
    C --> D["Thermal Sites"]
    D --> E["OSM Matching"]
    E --> F["Historical Baseline"]
    F --> G["Anomaly Detection"]
    G --> H["Explainable Result"]
    H --> I["GIS Dashboard"]
```

- **FIRMS Detections:** Ingests satellite thermal anomaly observations (MODIS/VIIRS).
- **Data Preparation:** Normalizes timestamps, validates coordinates and Fire Radiative Power (FRP), and cleans records.
- **Spatial Clustering:** Groups recurring nearby detections into persistent thermal sites using DBSCAN.
- **Thermal Sites:** Maintains a persistent site registry rather than tracking fragmented individual hotspots.
- **OSM Matching:** Associates site centroids with OpenStreetMap industrial facility boundaries within 1,000 metres.
- **Historical Baseline:** Calculates multi-week statistical profiles (mean and standard deviation of heat output) per site.
- **Anomaly Detection:** Flags statistically significant baseline exceedances and unexpected new thermal activity.
- **Explainable Result:** Assigns transparent, rule-based priority scores with plain-English evidence summaries.
- **GIS Dashboard:** Presents an interactive map displaying sites, facility boundaries, isolated points, and weekly activity trends.

## Current Prototype

The current proof-of-concept is verified on real historical satellite and geospatial data for Gujarat, India:

| Metric / Parameter | Verified Prototype Value | Notes |
|---|---|---|
| **Geographic Scope** | Gujarat, India | Focused regional demonstration |
| **Temporal Coverage** | 1 July 2025 – 30 June 2026 | 12 months (52 consecutive weeks) |
| **NASA FIRMS Files** | 73 CSV chunks | Located in `data/firms/chunks/` |
| **Total Detections** | 21,513 records | Cleaned with zero null coordinates or FRP |
| **OSM Facilities** | 710 features | GeoJSON polygons and points in Gujarat |
| **Identified Sites | 568 persistent sites | Clustered via DBSCAN (ε = 1.0 km, min_samples = 5) |
| **Assigned Detections** | 10,539 detections | Remaining 10,974 preserved as isolated events |
| **Matched Facilities** | 13 sites | Within 1,000 m buffer (555 unmapped sites) |
| **Real Anomalies** | 160 anomalies (14 High, 146 Low) | Detected across 123 distinct sites |

## Setup

THERMOGRAPH is self-contained and requires no external database servers, Docker, or Node.js build tools.

### Prerequisites

- **Python:** Version 3.10 or newer (tested on Python 3.12)
- **Git**

### Installation & Run Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/meawdak/VALKYRIES_Thermograph.git
   cd VALKYRIES_Thermograph
   ```

2. **Create and activate a Python virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   # Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   *(Frontend libraries Leaflet 1.9.4 and Chart.js 4.4.1 are vendored locally in `app/static/vendor/`—no `npm` install is required.)*

4. **Verify data placement:**
   Ensure source files exist in their expected read-only locations:
   - FIRMS chunks: `data/firms/chunks/*.csv` (73 files)
   - OSM dataset: `data/osm_industrial_facilities_gujarat.geojson`

5. **Run the data processing pipeline:**
   ```bash
   python processing/run_pipeline.py
   ```
   This deterministically loads datasets, performs clustering and facility matching, builds weekly histories and baselines, executes anomaly scoring, generates the simulated demo event, and runs output verification checks (C1–C15).

6. **Start the application server:**
   ```bash
   python app/app.py
   ```

7. **Open the dashboard:**
   Navigate to `http://127.0.0.1:5000/` in your browser.

## Usage

### 1. Data Processing
Run the end-to-end processing pipeline to generate `output/thermograph.db` and CSV exports:
```bash
python processing/run_pipeline.py
```

To run only the verification test suite on existing outputs:
```bash
python processing/check_outputs.py
```

To run automated backend API tests:
```bash
python tests/test_api.py
```

### 2. Application & API
Start the Flask application:
```bash
python app/app.py
```
Default environment variables: `HOST=0.0.0.0`, `PORT=5000`.

Key REST API endpoints:
- `GET /` — Interactive GIS web dashboard
- `GET /api/dashboard` — Regional summary counters and status distribution
- `GET /api/sites` — List of all 568 thermal sites with classifications
- `GET /api/sites/<site_id>` — Detail for a site including 52-week activity history
- `GET /api/anomalies` — List of detected anomalies with plain-English reasons
- `GET /api/risk` — Ranked list of high-priority sites for inspection
- `GET /api/facilities` — Mapped OpenStreetMap industrial facilities

## Repository Structure

```text
VALKYRIES_Thermograph/
├── app/
│   ├── app.py                      # Flask REST API backend & static file server
│   └── static/
│       ├── app.js                  # Frontend map, chart, and UI logic
│       ├── index.html              # Interactive GIS dashboard
│       ├── style.css               # Dashboard styling
│       └── vendor/                 # Offline dependencies (Leaflet, Chart.js)
├── data/                           # Raw source datasets (read-only)
│   ├── firms/chunks/               # 73 NASA FIRMS CSV chunk files
│   └── osm_industrial_facilities_gujarat.geojson  # 710 OSM features
├── docs/
│   └── INSPECTION_REPORT.md        # Technical data audit & baseline findings
├── output/                         # Generated artifacts (derived from data/)
│   ├── exports/                    # CSV exports (sites, baselines, anomalies)
│   ├── simulated/                  # Synthetic demo detections
│   ├── thermal_sites.csv           # Legacy baseline clustering reference
│   ├── thermal_sites_matched.csv   # Matched site registry
│   └── thermograph.db              # SQLite database generated by pipeline
├── processing/                     # Data processing pipeline modules
│   ├── anomalies.py                # Rule-based anomaly detection & scoring
│   ├── baselines.py                # 39-week baselines & site classification
│   ├── check_outputs.py            # Verification suite (Checks C1–C15)
│   ├── cluster_sites.py            # DBSCAN spatial clustering
│   ├── config.py                   # Central configuration & parameters
│   ├── db.py                       # SQLite database schema and utilities
│   ├── load_facilities.py          # OSM GeoJSON ingestion & reprojection
│   ├── load_firms.py               # FIRMS CSV parsing & validation
│   ├── match_facilities.py         # Spatial matching to industrial boundaries
│   ├── run_pipeline.py             # End-to-end pipeline runner
│   ├── simulate_event.py           # Controlled demonstration event injection
│   └── site_history.py             # 52-week activity aggregation
├── tests/
│   └── test_api.py                 # Automated Flask API tests
├── AGENTS.md                       # Development guidelines & operational constraints
├── PRD.md                          # Product Requirements Document
├── requirements.txt                # Python dependencies
├── TASKS.md                        # Task implementation tracker
└── TECH_SPEC.md                    # Technical specifications & schema
```

## Data Sources

- **NASA FIRMS (VIIRS Active Fire Data):** Satellite thermal observations provided by NASA's Earth Observing System Data and Information System ([EOSDIS FIRMS](https://firms.modaps.eosdis.nasa.gov/)).
- **OpenStreetMap:** Crowdsourced open geospatial infrastructure data providing industrial facility polygons and points ([OpenStreetMap](https://www.openstreetmap.org/)).

*Note: All raw data files in `data/` remain strictly unmodified. All pipeline transformations and databases are written exclusively to `output/`.*

## Current Status

- **Completed:**
  - Ingestion, validation, and schema normalization of 12-month FIRMS Gujarat dataset.
  - Spatial clustering (DBSCAN) establishing persistent thermal site registry.
  - Ingestion and spatial matching against 710 OpenStreetMap industrial facilities.
  - 52-week activity aggregation and 39-week historical statistical baselines.
  - Rule-based anomaly detection engine with plain-English explanations.
  - Controlled synthetic demo event generation with clear labeling.
  - Offline GIS dashboard (Leaflet + Chart.js) and Flask REST API.
  - Automated verification test suite (Checks C1–C15) and API tests.
- **In Progress:**
  - Cluster extent evaluation for candidate sites spanning $> 5\text{ km}$.
  - Refinement of OSM tag mapping for industrial subtypes.
- **Planned (Future Expansion):**
  - Ingestion of multi-year FIRMS archives (5–10 years) for seasonal baseline adjustment.
  - High-resolution visual verification via Sentinel-2 MSI and SAR imagery.
  - Demographic exposure weighting using population grids (GHSL / WorldPop).
  - Supervised machine-learning classification once ground-truth labeled training sets are curated.
  - Automated notification service (SMS/Email/Webhook) for operational dispatch.

## Scientific Notes

- **Observations vs. Confirmed Fires:** Satellite thermal detections represent radiometric observations; they are not automatically confirmed structural or industrial fires.
- **Evidence-Based Matching:** Industrial facility names are linked only when spatial proximity is supported ($\le 1,000\text{ m}$). Sites without spatial evidence remain designated as `UNMAPPED`.
- **Transparent Logic:** Anomaly scoring uses documented statistical rules ($\mu + 3\sigma$) and prototype settings rather than black-box models. No unverified machine-learning accuracy claims are made.
- **Simulation Integrity:** Demonstration events are isolated in Week 52, flagged with `is_simulated = 1`, hidden by default, and explicitly prefixed with `[SIMULATED]`.

## Team

**VALKYRIES**  
Siliguri Institute of Technology, Siliguri, West Bengal  
- **Hackathon:** Smart India Hackathon 2026
- **Problem Statement ID:** 26162
- **Problem Statement Title:** *AI-Based Detection and Classification of Industrial Fires and Persistent Thermal Sources Using NASA FIRMS, OSM & Satellite Data*
- **Theme:** Disaster Management | **Category:** Software
- **Team ID:** 147017

## Disclaimer

THERMOGRAPH is an academic and research prototype developed for Smart India Hackathon 2026. Anomaly detections and priority ratings are generated for analytical assistance and research demonstration; they should not be treated as confirmed emergency incidents without independent ground verification.
