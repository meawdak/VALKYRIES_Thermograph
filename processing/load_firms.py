"""
THERMOGRAPH — Stage 1: Load NASA FIRMS Hotspots
Loads, validates, normalises, and stores all FIRMS VIIRS detections
into SQLite (output/thermograph.db) and exports detections.csv.

Specifications implemented: TECH_SPEC §5.1, PRD FR-01 through FR-04.
"""

import datetime
import sqlite3
import sys
from pathlib import Path
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    DATASET_START,
    DATASET_END,
    DB_PATH,
    EXPECTED_DETECTIONS,
    EXPECTED_FIRMS_FILES,
    EXPORT_DIR,
    N_WEEKS,
    RAW_FIRMS_DIR,
    RAW_DATA_FILE_COUNT,
    RAW_DATA_TOTAL_BYTES,
    RAW_PAYLOAD_FILE_COUNT,
    RAW_PAYLOAD_TOTAL_BYTES,
    CLUSTER_EPS_KM,
    CLUSTER_MIN_SAMPLES,
    MATCH_RADIUS_M,
    PROJECTED_CRS,
    BASELINE_MIN_ACTIVE_WEEKS,
    ANOMALY_K,
    ANOMALY_MIN_DETECTIONS,
    NEW_ACTIVITY_MIN_DETECTIONS,
    PTS_BASELINE_EXCEEDANCE,
    PTS_NEW_ACTIVITY,
    PTS_RECORD_FRP,
    PTS_LARGE_EXCEEDANCE,
    LARGE_EXCEEDANCE_RATIO,
    PTS_FACILITY_MATCH,
    PRIORITY_HIGH_MIN,
    PRIORITY_MEDIUM_MIN,
    SIM_SEED,
    SIM_N_DETECTIONS,
    SIM_FRP_MULTIPLIER,
    SIM_JITTER_M,
)
from processing.db import init_db, set_metadata

# Expected columns in each raw FIRMS CSV
EXPECTED_COLUMNS = [
    "latitude",
    "longitude",
    "bright_ti4",
    "scan",
    "track",
    "acq_date",
    "acq_time",
    "satellite",
    "instrument",
    "confidence",
    "version",
    "bright_ti5",
    "frp",
    "daynight",
    "type",
]


def load_raw_firms() -> pd.DataFrame:
    """
    Find, validate, and concatenate all raw FIRMS CSV chunks.
    Validates file count, column schema, and total row count.
    """
    if not RAW_FIRMS_DIR.exists() or not RAW_FIRMS_DIR.is_dir():
        print(f"Error: RAW_FIRMS_DIR does not exist at {RAW_FIRMS_DIR}. Stopping.")
        sys.exit(1)

    # 1. List and verify the 73 CSV files in deterministic sorted order
    firms_files = sorted(RAW_FIRMS_DIR.glob("*.csv"))
    if len(firms_files) != EXPECTED_FIRMS_FILES:
        print(
            f"Expected {EXPECTED_FIRMS_FILES} FIRMS files, found {len(firms_files)}. Stopping."
        )
        sys.exit(1)

    print(f"Found exactly {len(firms_files)} FIRMS chunk files in {RAW_FIRMS_DIR}.")

    # 2. Read each file, verify columns, and attach source_file name
    dataframes = []
    for filepath in firms_files:
        df_chunk = pd.read_csv(filepath)
        missing_cols = [c for c in EXPECTED_COLUMNS if c not in df_chunk.columns]
        if missing_cols:
            print(
                f"File {filepath.name} is missing expected columns: {missing_cols}. Stopping."
            )
            sys.exit(1)
        df_chunk["source_file"] = filepath.name
        dataframes.append(df_chunk)

    # 3. Concatenate and verify total detection count
    full_df = pd.concat(dataframes, ignore_index=True)
    if len(full_df) != EXPECTED_DETECTIONS:
        print(
            f"Expected {EXPECTED_DETECTIONS} detections, found {len(full_df)}. Stopping."
        )
        sys.exit(1)

    print(f"Concatenated {len(full_df)} total raw detections across all chunks.")
    return full_df


def normalise_detections(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise detection timestamps, compute week indices, and validate dates.
    - Zero-pads acq_time to 4 digits (e.g. 845 -> '0845')
    - Builds ISO 8601 UTC timestamp: YYYY-MM-DDTHH:MM:00Z
    - Calculates week_index = min((acq_date - 2025-07-01).days // 7, 51)
    - Verifies all dates are within [DATASET_START, DATASET_END]
    """
    print("Normalising timestamps and week indices...")

    # Validate dates are within dataset period
    min_date = df["acq_date"].min()
    max_date = df["acq_date"].max()
    if min_date < DATASET_START or max_date > DATASET_END:
        print(
            f"Detections fall outside dataset period [{DATASET_START}, {DATASET_END}]: "
            f"min={min_date}, max={max_date}. Stopping."
        )
        sys.exit(1)

    # Zero-pad acq_time to 4 digits as string
    df["acq_time"] = df["acq_time"].astype(str).str.zfill(4)

    # Build ISO 8601 UTC timestamp: YYYY-MM-DDTHH:MM:00Z
    hours = df["acq_time"].str.slice(0, 2)
    minutes = df["acq_time"].str.slice(2, 4)
    df["acq_datetime_utc"] = df["acq_date"] + "T" + hours + ":" + minutes + ":00Z"

    # Compute week_index: 0 to 51
    # Week 51 ends 2026-06-30 (8 days, covering days 357..364)
    start_date = datetime.date.fromisoformat(DATASET_START)
    dates = pd.to_datetime(df["acq_date"]).dt.date
    days_from_start = dates.apply(lambda d: (d - start_date).days)
    df["week_index"] = days_from_start.apply(lambda days: min(days // 7, 51))

    # Verification of week_index range
    if df["week_index"].min() < 0 or df["week_index"].max() > 51:
        print(
            f"Week index out of bounds [0, 51]: min={df['week_index'].min()}, "
            f"max={df['week_index'].max()}. Stopping."
        )
        sys.exit(1)

    # Confirm week 51 contains 2026-06-30 detections
    jun30_weeks = set(df.loc[df["acq_date"] == DATASET_END, "week_index"])
    if jun30_weeks != {51}:
        print(
            f"Expected {DATASET_END} detections to have week_index 51, got {jun30_weeks}. Stopping."
        )
        sys.exit(1)

    # Assign stable 1-indexed detection_id in load order
    df["detection_id"] = range(1, len(df) + 1)

    # site_id is initially NULL for all detections (assigned in Stage 2)
    df["site_id"] = None

    # Real detections have is_simulated = 0
    df["is_simulated"] = 0

    print("Normalisation and date verification successful.")
    return df


def save_to_database(df: pd.DataFrame) -> None:
    """
    Rebuilds the SQLite database from scratch and inserts all detections
    along with configuration metadata.
    """
    print(f"Initialising fresh SQLite database at {DB_PATH}...")
    conn = init_db(reset=True)

    # Prepare records for insertion
    records = []
    for _, row in df.iterrows():
        records.append(
            (
                int(row["detection_id"]),
                float(row["latitude"]),
                float(row["longitude"]),
                str(row["acq_date"]),
                str(row["acq_time"]),
                str(row["acq_datetime_utc"]),
                int(row["week_index"]),
                float(row["frp"]),
                float(row["bright_ti4"]) if pd.notna(row["bright_ti4"]) else None,
                float(row["bright_ti5"]) if pd.notna(row["bright_ti5"]) else None,
                float(row["scan"]) if pd.notna(row["scan"]) else None,
                float(row["track"]) if pd.notna(row["track"]) else None,
                str(row["confidence"]) if pd.notna(row["confidence"]) else None,
                str(row["satellite"]) if pd.notna(row["satellite"]) else None,
                str(row["instrument"]) if pd.notna(row["instrument"]) else None,
                str(row["version"]) if pd.notna(row["version"]) else None,
                str(row["daynight"]) if pd.notna(row["daynight"]) else None,
                int(row["type"]) if pd.notna(row["type"]) else None,
                str(row["source_file"]),
                None,  # site_id
                0,  # is_simulated
            )
        )

    print(f"Inserting {len(records)} detection records into database...")
    insert_sql = """
    INSERT INTO detections (
        detection_id, latitude, longitude, acq_date, acq_time,
        acq_datetime_utc, week_index, frp, bright_ti4, bright_ti5,
        scan, track, confidence, satellite, instrument, version,
        daynight, type, source_file, site_id, is_simulated
    ) VALUES (
        ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?
    );
    """
    conn.executemany(insert_sql, records)
    conn.commit()

    # Populate metadata key/values
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    meta_entries = {
        "dataset_start": DATASET_START,
        "dataset_end": DATASET_END,
        "status_as_of": DATASET_END,
        "n_weeks": str(N_WEEKS),
        "expected_detections": str(EXPECTED_DETECTIONS),
        "actual_detections": str(len(df)),
        "firms_files_loaded": str(EXPECTED_FIRMS_FILES),
        "stage_1_loaded_at_utc": now_iso,
        "cluster_eps_km": str(CLUSTER_EPS_KM),
        "cluster_min_samples": str(CLUSTER_MIN_SAMPLES),
        "projected_crs": str(PROJECTED_CRS),
        "match_radius_m": str(MATCH_RADIUS_M),
        "baseline_min_active_weeks": str(BASELINE_MIN_ACTIVE_WEEKS),
        "anomaly_k": str(ANOMALY_K),
        "anomaly_min_detections": str(ANOMALY_MIN_DETECTIONS),
        "new_activity_min_detections": str(NEW_ACTIVITY_MIN_DETECTIONS),
        "pts_baseline_exceedance": str(PTS_BASELINE_EXCEEDANCE),
        "pts_new_activity": str(PTS_NEW_ACTIVITY),
        "pts_record_frp": str(PTS_RECORD_FRP),
        "pts_large_exceedance": str(PTS_LARGE_EXCEEDANCE),
        "large_exceedance_ratio": str(LARGE_EXCEEDANCE_RATIO),
        "pts_facility_match": str(PTS_FACILITY_MATCH),
        "priority_high_min": str(PRIORITY_HIGH_MIN),
        "priority_medium_min": str(PRIORITY_MEDIUM_MIN),
        "sim_seed": str(SIM_SEED),
        "sim_n_detections": str(SIM_N_DETECTIONS),
        "sim_frp_multiplier": str(SIM_FRP_MULTIPLIER),
        "sim_jitter_m": str(SIM_JITTER_M),
        "raw_data_file_count": str(RAW_DATA_FILE_COUNT),
        "raw_data_total_bytes": str(RAW_DATA_TOTAL_BYTES),
        "raw_payload_file_count": str(RAW_PAYLOAD_FILE_COUNT),
        "raw_payload_total_bytes": str(RAW_PAYLOAD_TOTAL_BYTES),
    }

    for k, v in meta_entries.items():
        set_metadata(conn, k, v)

    conn.close()
    print("Database population completed successfully.")


def export_csv(df: pd.DataFrame) -> None:
    """
    Export the detections dataframe to output/exports/detections.csv.
    Maintains exact column ordering matching TECH_SPEC §4.
    """
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = EXPORT_DIR / "detections.csv"

    columns_order = [
        "detection_id",
        "latitude",
        "longitude",
        "acq_date",
        "acq_time",
        "acq_datetime_utc",
        "week_index",
        "frp",
        "bright_ti4",
        "bright_ti5",
        "scan",
        "track",
        "confidence",
        "satellite",
        "instrument",
        "version",
        "daynight",
        "type",
        "source_file",
        "site_id",
        "is_simulated",
    ]

    print(f"Exporting detections to {export_path}...")
    df[columns_order].to_csv(export_path, index=False)
    print(f"Export complete: {export_path} ({len(df)} data rows).")


def main() -> None:
    print("=" * 60)
    print("THERMOGRAPH Pipeline — Stage 1: Load FIRMS Detections")
    print("=" * 60)

    # 1. Load and validate raw CSV files
    df = load_raw_firms()

    # 2. Normalise dates, zero-pad acq_time, compute week_index
    df = normalise_detections(df)

    # 3. Store into SQLite database output/thermograph.db
    save_to_database(df)

    # 4. Export to output/exports/detections.csv
    export_csv(df)

    print("=" * 60)
    print(f"Stage 1 successfully completed. {len(df)} detections loaded.")
    print("=" * 60)


if __name__ == "__main__":
    main()
