"""
THERMOGRAPH — Database Connection and Schema Management
Provides SQLite database connection management, table definitions,
and metadata helper functions.
All paths and parameters are imported from processing/config.py.
"""

import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    DB_PATH,
    CLUSTER_EPS_KM,
    CLUSTER_MIN_SAMPLES,
    DATASET_START,
    DATASET_END,
    EXPECTED_DETECTIONS,
    EXPECTED_FACILITIES,
    EXPECTED_FIRMS_FILES,
    MATCH_RADIUS_M,
    N_WEEKS,
    PROJECTED_CRS,
)


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Get a connection to the SQLite database.
    Ensures parent directory exists and enables foreign keys.
    """
    target_path = Path(db_path or DB_PATH)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    """
    Create the complete database schema matching TECH_SPEC §4.
    Tables created:
      - detections
      - sites
      - facilities
      - site_weekly
      - baselines
      - anomalies
      - metadata
    """
    cursor = conn.cursor()

    # 1. detections table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS detections (
        detection_id INTEGER PRIMARY KEY,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        acq_date TEXT NOT NULL,
        acq_time TEXT NOT NULL,
        acq_datetime_utc TEXT NOT NULL,
        week_index INTEGER NOT NULL,
        frp REAL NOT NULL,
        bright_ti4 REAL,
        bright_ti5 REAL,
        scan REAL,
        track REAL,
        confidence TEXT,
        satellite TEXT,
        instrument TEXT,
        version TEXT,
        daynight TEXT,
        type INTEGER,
        source_file TEXT NOT NULL,
        site_id TEXT,
        is_simulated INTEGER NOT NULL DEFAULT 0
    );
    """)

    # Index on week_index and site_id for performance
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_detections_week ON detections(week_index);
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_detections_site ON detections(site_id);
    """)

    # 2. sites table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sites (
        site_id TEXT PRIMARY KEY,
        centroid_lat REAL NOT NULL,
        centroid_lon REAL NOT NULL,
        extent_km REAL NOT NULL,
        n_detections INTEGER NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        active_weeks_total INTEGER,
        night_fraction REAL,
        static_type_fraction REAL,
        mean_frp REAL,
        max_frp REAL,
        facility_id TEXT,
        match_type TEXT,
        match_distance_m REAL,
        site_class TEXT,
        status TEXT
    );
    """)

    # 3. facilities table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS facilities (
        facility_id TEXT PRIMARY KEY,
        name TEXT,
        industrial TEXT,
        landuse TEXT,
        osm_type TEXT,
        wikidata TEXT,
        geometry_type TEXT NOT NULL,
        centroid_lat REAL NOT NULL,
        centroid_lon REAL NOT NULL,
        geojson TEXT NOT NULL,
        display_name TEXT NOT NULL
    );
    """)

    # 4. site_weekly table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS site_weekly (
        site_id TEXT NOT NULL,
        week_index INTEGER NOT NULL,
        week_start TEXT NOT NULL,
        week_end TEXT NOT NULL,
        period TEXT NOT NULL,
        detection_count INTEGER NOT NULL,
        frp_sum REAL NOT NULL,
        frp_max REAL NOT NULL,
        night_count INTEGER NOT NULL,
        is_simulated INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (site_id, week_index)
    );
    """)

    # 5. baselines table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS baselines (
        site_id TEXT PRIMARY KEY,
        n_weeks INTEGER NOT NULL,
        active_weeks INTEGER NOT NULL,
        baseline_detections INTEGER NOT NULL,
        frp_sum_mean REAL NOT NULL,
        frp_sum_std REAL NOT NULL,
        threshold REAL NOT NULL,
        baseline_max_frp REAL NOT NULL,
        established INTEGER NOT NULL
    );
    """)

    # 6. anomalies table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS anomalies (
        anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_id TEXT NOT NULL,
        week_index INTEGER NOT NULL,
        week_start TEXT NOT NULL,
        week_end TEXT NOT NULL,
        anomaly_type TEXT NOT NULL,
        detection_count INTEGER NOT NULL,
        frp_sum REAL NOT NULL,
        frp_max REAL NOT NULL,
        threshold REAL,
        ratio REAL,
        score INTEGER NOT NULL,
        priority TEXT NOT NULL,
        reasons TEXT NOT NULL,
        is_simulated INTEGER NOT NULL DEFAULT 0
    );
    """)

    # 7. metadata key-value table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    conn.commit()


def set_metadata(conn: sqlite3.Connection, key: str, value: Any) -> None:
    """Store a key/value pair into the metadata table."""
    conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?);",
        (str(key), str(value)),
    )
    conn.commit()


def get_metadata(conn: sqlite3.Connection, key: str) -> Optional[str]:
    """Retrieve a value by key from the metadata table."""
    cursor = conn.execute("SELECT value FROM metadata WHERE key = ?;", (str(key),))
    row = cursor.fetchone()
    return row[0] if row else None


def get_all_metadata(conn: sqlite3.Connection) -> Dict[str, str]:
    """Retrieve all key/value pairs from the metadata table."""
    cursor = conn.execute("SELECT key, value FROM metadata ORDER BY key;")
    return {row["key"]: row["value"] for row in cursor.fetchall()}


def init_db(db_path: Optional[Path] = None, reset: bool = False) -> sqlite3.Connection:
    """
    Initialize the database, creating all tables.
    If reset is True and the database file exists, deletes it first.
    """
    target_path = Path(db_path or DB_PATH)
    if reset and target_path.exists():
        target_path.unlink()
    conn = get_connection(target_path)
    create_tables(conn)
    return conn
