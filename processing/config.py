"""
THERMOGRAPH — Central Configuration
All paths, parameters, thresholds, and scoring constants are defined here.
Values derived from T0 inspection are recorded below.
"""

from pathlib import Path

# Project root directory
ROOT = Path(__file__).resolve().parent.parent

# --- Paths ---
RAW_FIRMS_DIR = ROOT / "data" / "firms" / "chunks"
RAW_OSM_FILE = ROOT / "data" / "osm_industrial_facilities_gujarat.geojson"
LEGACY_SITES_CSV = ROOT / "output" / "thermal_sites.csv"
DB_PATH = ROOT / "output" / "thermograph.db"
EXPORT_DIR = ROOT / "output" / "exports"
SIM_CSV = ROOT / "output" / "simulated" / "simulated_detections.csv"
MATCHED_SITES_CSV = ROOT / "output" / "thermal_sites_matched.csv"
FACILITIES_EXPORT_CSV = EXPORT_DIR / "facilities.csv"
SITES_EXPORT_CSV = EXPORT_DIR / "sites.csv"
SITE_WEEKLY_EXPORT_CSV = EXPORT_DIR / "site_weekly.csv"
BASELINES_EXPORT_CSV = EXPORT_DIR / "baselines.csv"
ANOMALIES_EXPORT_CSV = EXPORT_DIR / "anomalies.csv"

# --- Expected Input Facts (pipeline stops if different) ---
EXPECTED_DETECTIONS = 21513
EXPECTED_FACILITIES = 710
EXPECTED_FIRMS_FILES = 73

# --- Time Periods ---
DATASET_START = "2025-07-01"
DATASET_END = "2026-06-30"  # Also the "status as of" date
N_WEEKS = 52  # Weeks 0..51; week 51 = 23–30 Jun 2026 (8 days)
BASELINE_WEEKS = range(0, 39)  # 1 Jul 2025 – 30 Mar 2026 (39 weeks)
MONITORING_WEEKS = range(39, 52)  # 31 Mar 2026 – 30 Jun 2026 (13 weeks)
SIM_WEEK = 52  # 1–7 Jul 2026, simulated only

# --- Spatial Clustering (from processing/cluster_firms.py lines 41, 44, 45) ---
EARTH_RADIUS_KM = 6371.0088
CLUSTER_EPS_KM = 1.0  # DISTANCE_KM = 1.0 in processing/cluster_firms.py line 44
CLUSTER_MIN_SAMPLES = 5  # MIN_DETECTIONS = 5 in processing/cluster_firms.py line 45
SITE_EXTENT_REVIEW_KM = 5.0

# --- Facility Matching ---
PROJECTED_CRS = "EPSG:32643"  # UTM zone 43N, metres (<1% distance distortion in Gujarat)
MATCH_RADIUS_M = 1000  # 1,000 metres search radius for nearby facilities
MATCH_RADIUS_KM = MATCH_RADIUS_M / 1000.0  # 1.0 km search radius

# --- Baseline & Anomaly Detection ---
BASELINE_MIN_ACTIVE_WEEKS = 10  # Minimum active baseline weeks to establish baseline
ANOMALY_K = 3.0  # Multiplier for standard deviation: threshold = mean + 3 * std
ANOMALY_MIN_DETECTIONS = 2  # Minimum detections in week to trigger baseline exceedance
NEW_ACTIVITY_MIN_DETECTIONS = 2  # Minimum detections in week to trigger new activity

# --- Priority Scoring Points (Prototype Settings) ---
PTS_BASELINE_EXCEEDANCE = 3
PTS_NEW_ACTIVITY = 2
PTS_RECORD_FRP = 2
PTS_LARGE_EXCEEDANCE = 1  # Awarded when ratio >= LARGE_EXCEEDANCE_RATIO
LARGE_EXCEEDANCE_RATIO = 2.0
PTS_FACILITY_MATCH = 1  # Awarded when site matched to inside or nearby facility
PRIORITY_HIGH_MIN = 5
PRIORITY_MEDIUM_MIN = 3

# --- Simulation Parameters ---
SIM_SEED = 42
SIM_N_DETECTIONS = 12
SIM_FRP_MULTIPLIER = 1.5
SIM_JITTER_M = 200

# --- Raw Data Fingerprint (Check C15) ---
# Total data directory including auxiliary download environment in data/firms/.venv
RAW_DATA_FILE_COUNT = 10084
RAW_DATA_TOTAL_BYTES = 368830875
# Specific raw source payload files (73 FIRMS CSV chunks + 1 OSM GeoJSON)
RAW_PAYLOAD_FILE_COUNT = 74
RAW_PAYLOAD_TOTAL_BYTES = 1935750
