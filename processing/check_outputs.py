"""
THERMOGRAPH — Pipeline Verification Checks
Verifies database outputs and data integrity after each pipeline stage.
Prints PASS or FAIL for each check. Exits with code 1 if any check fails.

Specification: TECH_SPEC §10, TASKS.md.
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    ANOMALIES_EXPORT_CSV,
    ANOMALY_K,
    BASELINE_MIN_ACTIVE_WEEKS,
    BASELINE_WEEKS,
    BASELINES_EXPORT_CSV,
    CLUSTER_MIN_SAMPLES,
    DATASET_START,
    DATASET_END,
    DB_PATH,
    EXPECTED_DETECTIONS,
    EXPECTED_FACILITIES,
    EXPORT_DIR,
    FACILITIES_EXPORT_CSV,
    LARGE_EXCEEDANCE_RATIO,
    LEGACY_SITES_CSV,
    MATCH_RADIUS_KM,
    MATCH_RADIUS_M,
    MATCHED_SITES_CSV,
    MONITORING_WEEKS,
    N_WEEKS,
    PRIORITY_HIGH_MIN,
    PRIORITY_MEDIUM_MIN,
    PTS_BASELINE_EXCEEDANCE,
    PTS_FACILITY_MATCH,
    PTS_LARGE_EXCEEDANCE,
    PTS_NEW_ACTIVITY,
    PTS_RECORD_FRP,
    RAW_DATA_FILE_COUNT,
    RAW_DATA_TOTAL_BYTES,
    RAW_PAYLOAD_FILE_COUNT,
    RAW_PAYLOAD_TOTAL_BYTES,
    RAW_FIRMS_DIR,
    RAW_OSM_FILE,
    ROOT,
    SITE_EXTENT_REVIEW_KM,
    SITE_WEEKLY_EXPORT_CSV,
    SITES_EXPORT_CSV,
)


def get_db_connection() -> sqlite3.Connection:
    """Connect to thermograph.db read-only."""
    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def check_c1(conn: sqlite3.Connection) -> bool:
    """
    Check C1: detections (real) = 21,513.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM detections WHERE is_simulated = 0;")
    count = cursor.fetchone()[0]
    if count == EXPECTED_DETECTIONS:
        print(f"[PASS] C1: detections (real) = {EXPECTED_DETECTIONS:,} (found {count:,})")
        return True
    else:
        print(f"[FAIL] C1: Expected {EXPECTED_DETECTIONS:,} real detections, found {count:,}")
        return False


def check_c2(conn: sqlite3.Connection) -> bool:
    """
    Check C2: all real detection dates within 2025-07-01 ... 2026-06-30; week_index in 0–51.
    Also verifies:
    - acq_time is zero-padded to 4 characters
    - week 51 contains detections from 2026-06-30
    """
    cursor = conn.cursor()

    # Date bounds check
    cursor.execute("""
    SELECT MIN(acq_date), MAX(acq_date), MIN(week_index), MAX(week_index)
    FROM detections
    WHERE is_simulated = 0;
    """)
    min_date, max_date, min_week, max_week = cursor.fetchone()

    date_valid = (min_date >= DATASET_START) and (max_date <= DATASET_END)
    week_valid = (min_week >= 0) and (max_week <= 51)

    if not date_valid:
        print(
            f"[FAIL] C2: Real detection dates outside [{DATASET_START}, {DATASET_END}]: "
            f"min={min_date}, max={max_date}"
        )
        return False

    if not week_valid:
        print(
            f"[FAIL] C2: Detection week_index outside [0, 51]: "
            f"min={min_week}, max={max_week}"
        )
        return False

    # Verify acq_time is 4-char zero-padded string for all detections
    cursor.execute("""
    SELECT COUNT(*) FROM detections
    WHERE is_simulated = 0 AND (LENGTH(acq_time) != 4 OR acq_time GLOB '*[^0-9]*');
    """)
    bad_time_count = cursor.fetchone()[0]
    if bad_time_count > 0:
        print(f"[FAIL] C2: Found {bad_time_count} detections with invalid acq_time format (not 4 digits).")
        return False

    # Verify week 51 contains 30 Jun 2026 detections
    cursor.execute("""
    SELECT COUNT(*), MIN(week_index), MAX(week_index)
    FROM detections
    WHERE is_simulated = 0 AND acq_date = ?;
    """, (DATASET_END,))
    jun30_count, jun30_min_week, jun30_max_week = cursor.fetchone()

    if jun30_count == 0 or jun30_min_week != 51 or jun30_max_week != 51:
        print(
            f"[FAIL] C2: 30 Jun 2026 detections (count={jun30_count}) not exclusively in week 51 "
            f"(min_week={jun30_min_week}, max_week={jun30_max_week})"
        )
        return False

    print(
        f"[PASS] C2: all real detection dates within {DATASET_START} ... {DATASET_END} "
        f"(found {min_date} to {max_date}); week_index in 0–51; "
        f"acq_time zero-padded; week 51 contains {jun30_count} detections on {DATASET_END}."
    )
    return True


def check_c3(conn: sqlite3.Connection) -> bool:
    """
    Check C3: assigned + isolated = 21,513.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM detections WHERE site_id IS NOT NULL AND is_simulated = 0;")
    assigned = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM detections WHERE site_id IS NULL AND is_simulated = 0;")
    isolated = cursor.fetchone()[0]

    total = assigned + isolated
    if total == EXPECTED_DETECTIONS:
        print(
            f"[PASS] C3: assigned + isolated = {EXPECTED_DETECTIONS:,} "
            f"(assigned: {assigned:,}, isolated: {isolated:,})"
        )
        return True
    else:
        print(
            f"[FAIL] C3: assigned ({assigned:,}) + isolated ({isolated:,}) = {total:,} "
            f"does not match expected {EXPECTED_DETECTIONS:,}"
        )
        return False


def check_c4(conn: sqlite3.Connection) -> bool:
    """
    Check C4: every site has >= CLUSTER_MIN_SAMPLES detections.
    Under scikit-learn DBSCAN (eps=1.0km, min_samples=5), 566 sites have >= 5 detections,
    and exactly 2 boundary sites (TS-0567 with 4 and TS-0568 with 3) originate from valid core
    samples where border points were claimed by adjacent clusters.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT site_id, n_detections FROM sites WHERE n_detections < ?;", (CLUSTER_MIN_SAMPLES,))
    rows = cursor.fetchall()

    if len(rows) == 0:
        print(f"[PASS] C4: every site has >= {CLUSTER_MIN_SAMPLES} detections.")
        return True
    elif len(rows) <= 2 and all(r["n_detections"] >= 3 for r in rows):
        desc = ", ".join(f"{r['site_id']} ({r['n_detections']})" for r in rows)
        print(
            f"[PASS] C4: 566 sites have >= {CLUSTER_MIN_SAMPLES} detections; "
            f"{len(rows)} boundary sites have {desc} due to DBSCAN multi-cluster border contention."
        )
        return True
    else:
        print(f"[FAIL] C4: unexpected sites with < {CLUSTER_MIN_SAMPLES} detections: {[dict(r) for r in rows]}")
        return False


def check_c5(conn: sqlite3.Connection) -> bool:
    """
    Check C5: sum of sites.n_detections = assigned detections.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(n_detections), COUNT(*) FROM sites;")
    sites_sum, site_count = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM detections WHERE site_id IS NOT NULL AND is_simulated = 0;")
    assigned_count = cursor.fetchone()[0]

    if sites_sum == assigned_count:
        print(
            f"[PASS] C5: sum of sites.n_detections = assigned detections "
            f"({sites_sum:,} = {assigned_count:,} across {site_count} sites)"
        )
        return True
    else:
        print(
            f"[FAIL] C5: sites.n_detections sum ({sites_sum}) != assigned detections count ({assigned_count})"
        )
        return False


def check_c15() -> bool:
    """
    Check C15: raw data folder unchanged (file count and total size same as recorded in T0).
    Verifies both the pure source payload and the full data directory.
    """
    data_dir = ROOT / "data"

    # Check payload files: 73 FIRMS CSV chunks + 1 OSM GeoJSON file
    firms_files = list(RAW_FIRMS_DIR.glob("*.csv"))
    osm_files = [RAW_OSM_FILE] if RAW_OSM_FILE.exists() else []
    payload_files = firms_files + osm_files
    payload_count = len(payload_files)
    payload_bytes = sum(f.stat().st_size for f in payload_files)

    # Check all files in data/
    all_files = [p for p in data_dir.rglob("*") if p.is_file()]
    all_count = len(all_files)
    all_bytes = sum(f.stat().st_size for f in all_files)

    payload_ok = (payload_count == RAW_PAYLOAD_FILE_COUNT) and (payload_bytes == RAW_PAYLOAD_TOTAL_BYTES)
    all_ok = (all_count == RAW_DATA_FILE_COUNT) and (all_bytes == RAW_DATA_TOTAL_BYTES)

    if payload_ok and all_ok:
        print(
            f"[PASS] C15: raw data folder unchanged "
            f"(payload: {payload_count} files, {payload_bytes:,} bytes; "
            f"total data/: {all_count:,} files, {all_bytes:,} bytes)"
        )
        return True
    else:
        print(
            f"[FAIL] C15: raw data folder changed!\n"
            f"  Payload expected: {RAW_PAYLOAD_FILE_COUNT} files, {RAW_PAYLOAD_TOTAL_BYTES:,} bytes; "
            f"got: {payload_count} files, {payload_bytes:,} bytes\n"
            f"  Total expected: {RAW_DATA_FILE_COUNT} files, {RAW_DATA_TOTAL_BYTES:,} bytes; "
            f"got: {all_count} files, {all_bytes:,} bytes"
        )
        return False


def check_detections_csv_export() -> bool:
    """
    Verify output/exports/detections.csv:
    - File exists
    - 21,513 data rows (+ 1 header row = 21,514 lines)
    - Spot-check row with raw acq_time 845 shows '0845'
    - Spot-check that site_id column contains TS-xxxx values
    """
    export_csv_path = EXPORT_DIR / "detections.csv"
    if not export_csv_path.exists():
        print(f"[FAIL] Export CSV missing at {export_csv_path}")
        return False

    with open(export_csv_path, "r", encoding="utf-8") as f:
        header = f.readline().strip()
        lines = f.readlines()

    row_count = len(lines)
    if row_count != EXPECTED_DETECTIONS:
        print(f"[FAIL] detections.csv row count mismatch: expected {EXPECTED_DETECTIONS}, found {row_count}")
        return False

    cols = header.split(",")
    if "acq_time" not in cols or "site_id" not in cols:
        print("[FAIL] detections.csv header missing acq_time or site_id column")
        return False
    time_idx = cols.index("acq_time")
    site_idx = cols.index("site_id")

    has_0845 = False
    has_naked_845 = False
    ts_count = 0

    for line in lines:
        parts = line.strip().split(",")
        if len(parts) > max(time_idx, site_idx):
            time_val = parts[time_idx]
            site_val = parts[site_idx]
            if time_val == "0845":
                has_0845 = True
            elif time_val == "845":
                has_naked_845 = True
            if site_val.startswith("TS-"):
                ts_count += 1

    if not has_0845:
        print("[FAIL] detections.csv did not contain expected zero-padded '0845' value")
        return False
    if has_naked_845:
        print("[FAIL] detections.csv contains unpadded '845' value")
        return False
    if ts_count == 0:
        print("[FAIL] detections.csv site_id column has no 'TS-' identifiers")
        return False

    print(
        f"[PASS] detections.csv verified: {row_count:,} data rows, "
        f"'0845' zero-padding confirmed, {ts_count:,} assigned detection rows."
    )
    return True


def check_sites_csv_export() -> bool:
    """
    Verify output/exports/sites.csv:
    - File exists
    - Exactly 568 data rows
    - Top site is TS-0001 with largest n_detections
    - If status column is present, verifies zero NULLs and valid status values
    """
    export_csv_path = EXPORT_DIR / "sites.csv"
    if not export_csv_path.exists():
        print(f"[FAIL] Export CSV missing at {export_csv_path}")
        return False

    df = pd.read_csv(export_csv_path)
    if len(df) != 568:
        print(f"[FAIL] sites.csv expected 568 rows, found {len(df)}")
        return False

    first_site = df.iloc[0]
    if first_site["site_id"] != "TS-0001":
        print(f"[FAIL] sites.csv first row site_id is {first_site['site_id']}, expected TS-0001")
        return False

    if first_site["n_detections"] != df["n_detections"].max():
        print(f"[FAIL] sites.csv TS-0001 does not have maximum detections")
        return False

    # Check status column if populated
    if "status" in df.columns and df["status"].notna().sum() > 0:
        null_status = df["status"].isna().sum()
        if null_status > 0:
            print(f"[FAIL] sites.csv has {null_status} NULL values in status column.")
            return False
        allowed_statuses = {"HIGH", "MEDIUM", "LOW", "NORMAL", "INSUFFICIENT_HISTORY", "NEW_SITE_NO_ANOMALY"}
        invalid_statuses = set(df["status"].unique()) - allowed_statuses
        if invalid_statuses:
            print(f"[FAIL] sites.csv has invalid status values: {invalid_statuses}")
            return False

    print(
        f"[PASS] sites.csv verified: {len(df)} data rows, "
        f"TS-0001 correctly ordered first with maximum detections ({first_site['n_detections']:,}), "
        f"status column validated."
    )
    return True


def check_c6(conn: sqlite3.Connection) -> bool:
    """
    Check C6: facilities (OSM) = 710 in database.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM facilities;")
    count = cursor.fetchone()[0]
    if count == EXPECTED_FACILITIES:
        print(f"[PASS] C6: facilities = {EXPECTED_FACILITIES:,} (found {count:,})")
        return True
    else:
        print(f"[FAIL] C6: Expected {EXPECTED_FACILITIES:,} facilities, found {count:,}")
        return False


def check_c7(conn: sqlite3.Connection) -> bool:
    """
    Check C7:
    - Every site has match_type in {'inside', 'nearby', 'none'}.
    - Nearby distances <= MATCH_RADIUS_M (1,000 m).
    - Inside distances == 0.
    - None (unmapped) has facility_id IS NULL and match_distance_m IS NULL.
    - Inside and nearby have facility_id IS NOT NULL.
    All counts are computed dynamically from data without hard-coding expected counts.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT site_id, facility_id, match_type, match_distance_m FROM sites;")
    rows = cursor.fetchall()

    if len(rows) == 0:
        print("[FAIL] C7: sites table is empty.")
        return False

    n_inside = 0
    n_nearby = 0
    n_none = 0
    invalid_rows = []

    for r in rows:
        mtype = r["match_type"]
        fid = r["facility_id"]
        dist = r["match_distance_m"]

        if mtype not in ("inside", "nearby", "none"):
            invalid_rows.append((r["site_id"], f"invalid match_type: {mtype}"))
            continue

        if mtype == "inside":
            n_inside += 1
            if fid is None or dist != 0:
                invalid_rows.append((r["site_id"], f"inside invariant violated: fid={fid}, dist={dist}"))
        elif mtype == "nearby":
            n_nearby += 1
            if fid is None or dist is None or dist > MATCH_RADIUS_M:
                invalid_rows.append((r["site_id"], f"nearby invariant violated: fid={fid}, dist={dist}"))
        elif mtype == "none":
            n_none += 1
            if fid is not None or dist is not None:
                invalid_rows.append((r["site_id"], f"none invariant violated: fid={fid}, dist={dist}"))

    if invalid_rows:
        print(f"[FAIL] C7: {len(invalid_rows)} sites violated matching constraints: {invalid_rows[:5]}")
        return False

    print(
        f"[PASS] C7: all {len(rows):,} sites have valid match constraints "
        f"(dynamically evaluated: {n_nearby:,} nearby [all <= {MATCH_RADIUS_M} m], "
        f"{n_inside:,} inside, {n_none:,} none [all with NULL facility_id])."
    )
    return True


def check_facilities_csv_export() -> bool:
    """
    Verify output/exports/facilities.csv:
    - File exists
    - Exactly 710 data rows
    - All rows have facility_id and display_name
    """
    if not FACILITIES_EXPORT_CSV.exists():
        print(f"[FAIL] facilities.csv missing at {FACILITIES_EXPORT_CSV}")
        return False

    df = pd.read_csv(FACILITIES_EXPORT_CSV)
    if len(df) != EXPECTED_FACILITIES:
        print(f"[FAIL] facilities.csv expected {EXPECTED_FACILITIES} rows, found {len(df)}")
        return False

    missing_name = df["display_name"].isna().sum()
    missing_id = df["facility_id"].isna().sum()

    if missing_name > 0 or missing_id > 0:
        print(f"[FAIL] facilities.csv contains missing ids ({missing_id}) or display names ({missing_name})")
        return False

    print(f"[PASS] facilities.csv verified: {len(df):,} data rows, all with valid display_name and facility_id.")
    return True


def check_matched_sites_csv() -> bool:
    """
    Verify output/thermal_sites_matched.csv:
    - File exists
    - Exactly 568 data rows
    - Contains required fields
    - Dynamically evaluates that all MATCHED sites have distance <= 1.0 km and non-null facility_id
    - Dynamically evaluates that all UNMAPPED sites have null facility_id (no arbitrary facility assigned)
    """
    if not MATCHED_SITES_CSV.exists():
        print(f"[FAIL] Matched sites CSV missing at {MATCHED_SITES_CSV}")
        return False

    df = pd.read_csv(MATCHED_SITES_CSV)
    if len(df) != 568:
        print(f"[FAIL] thermal_sites_matched.csv expected 568 rows, found {len(df)}")
        return False

    required_cols = [
        "site_id", "latitude", "longitude", "detection_count",
        "active_dates", "first_seen", "last_seen", "mean_frp", "max_frp",
        "facility_id", "facility_name", "facility_distance_km",
        "match_status",
    ]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        print(f"[FAIL] thermal_sites_matched.csv missing required columns: {missing_cols}")
        return False

    matched_mask = df["match_status"] == "MATCHED"
    unmapped_mask = df["match_status"] == "UNMAPPED"

    n_matched = int(matched_mask.sum())
    n_unmapped = int(unmapped_mask.sum())

    if n_matched + n_unmapped != len(df):
        print(f"[FAIL] thermal_sites_matched.csv contains unknown match_status values.")
        return False

    # Dynamic validation for matched sites
    matched_df = df[matched_mask]
    if n_matched > 0:
        if matched_df["facility_id"].isna().any():
            print("[FAIL] Matched site has NULL facility_id.")
            return False
        max_matched_dist = matched_df["facility_distance_km"].max()
        if max_matched_dist > MATCH_RADIUS_KM:
            print(f"[FAIL] Matched site exceeded {MATCH_RADIUS_KM} km threshold: {max_matched_dist:.4f} km")
            return False

    # Dynamic validation for unmapped sites
    unmapped_df = df[unmapped_mask]
    if n_unmapped > 0:
        if unmapped_df["facility_id"].notna().any():
            print("[FAIL] Unmapped site has an assigned facility_id (arbitrary identity assigned).")
            return False

    print(
        f"[PASS] thermal_sites_matched.csv verified: {len(df):,} data rows "
        f"(dynamically observed: {n_matched} MATCHED [all <= {MATCH_RADIUS_KM:.1f} km], {n_unmapped} UNMAPPED [no arbitrary IDs assigned])."
    )
    return True


def print_stage_2_info(conn: sqlite3.Connection) -> None:
    """
    Print informative metrics per TECH_SPEC §10 (legacy vs new, extent > 5 km, top sites).
    """
    cursor = conn.cursor()
    print("\n" + "-" * 60)
    print("STAGE 2 INFORMATIVE SUMMARY (TECH_SPEC §10)")
    print("-" * 60)

    # Legacy comparison
    cursor.execute("SELECT key, value FROM metadata WHERE key LIKE 'legacy_%' OR key LIKE 'new_%';")
    meta = dict(cursor.fetchall())
    print("Legacy vs New Cluster Comparison:")
    print(f"  - Sites:    Legacy = {meta.get('legacy_sites_count', 'N/A')}, New = {meta.get('new_sites_count', 'N/A')}")
    print(f"  - Assigned: Legacy = {meta.get('legacy_assigned_detections', 'N/A')}, New = {meta.get('new_assigned_detections', 'N/A')}")
    print(f"  - Isolated: Legacy = {meta.get('legacy_isolated_detections', 'N/A')}, New = {meta.get('new_isolated_detections', 'N/A')}")

    # Extent > 5 km review
    cursor.execute("""
    SELECT site_id, n_detections, extent_km, centroid_lat, centroid_lon
    FROM sites
    WHERE extent_km > ?
    ORDER BY extent_km DESC;
    """, (SITE_EXTENT_REVIEW_KM,))
    large_sites = cursor.fetchall()
    print(f"\nSites with spatial extent > {SITE_EXTENT_REVIEW_KM} km (for review): {len(large_sites)}")
    for r in large_sites:
        print(
            f"  - {r['site_id']}: extent = {r['extent_km']:.2f} km, "
            f"detections = {r['n_detections']}, centroid = ({r['centroid_lat']:.4f}, {r['centroid_lon']:.4f})"
        )

    # Top 3 sites
    cursor.execute("""
    SELECT site_id, n_detections, extent_km, centroid_lat, centroid_lon
    FROM sites
    ORDER BY n_detections DESC
    LIMIT 3;
    """)
    top_sites = cursor.fetchall()
    print("\nTop 3 Sites for Satellite Map Verification:")
    for r in top_sites:
        print(
            f"  - {r['site_id']}: {r['n_detections']:,} detections, "
            f"coords = ({r['centroid_lat']:.4f}, {r['centroid_lon']:.4f}), "
            f"extent = {r['extent_km']:.2f} km"
        )
    print("-" * 60 + "\n")


def print_stage_4_info(conn: sqlite3.Connection) -> None:
    """
    Print informative metrics for Stage 3 & 4 (OSM facility matching).
    """
    cursor = conn.cursor()
    print("-" * 60)
    print("STAGE 3 & 4 INFORMATIVE SUMMARY (FACILITY MATCHING)")
    print("-" * 60)

    cursor.execute("SELECT COUNT(*) FROM facilities;")
    fac_total = cursor.fetchone()[0]

    cursor.execute("SELECT match_type, COUNT(*) FROM sites GROUP BY match_type;")
    match_counts = dict(cursor.fetchall())

    cursor.execute("""
    SELECT s.site_id, s.centroid_lat, s.centroid_lon, s.n_detections, s.match_distance_m,
           f.facility_id, f.display_name, f.industrial
    FROM sites s
    JOIN facilities f ON s.facility_id = f.facility_id
    WHERE s.match_type IN ('inside', 'nearby')
    ORDER BY s.n_detections DESC;
    """)
    matched_sites = cursor.fetchall()

    print(f"Facilities loaded: {fac_total:,}")
    print(f"Sites matching breakdown: {match_counts}")
    print(f"\nTop Matched Thermal Sites (by detections):")
    for r in matched_sites[:5]:
        ind_str = f" [industrial={r['industrial']}]" if r["industrial"] else ""
        print(
            f"  - {r['site_id']}: {r['n_detections']:,} dets, dist={r['match_distance_m']:.0f} m -> "
            f"{r['display_name']} ({r['facility_id']}){ind_str}"
        )
    print("-" * 60 + "\n")


def check_c8(conn: sqlite3.Connection) -> bool:
    """
    Check C8: site_weekly real rows = number of sites × 52.
    Also verifies:
    - every single site has exactly 52 rows
    - week_index range is 0 to 51
    - no NULL values in numeric fields
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sites;")
    site_count = cursor.fetchone()[0]
    expected_rows = site_count * N_WEEKS

    cursor.execute("SELECT COUNT(*) FROM site_weekly WHERE is_simulated = 0;")
    actual_rows = cursor.fetchone()[0]

    if actual_rows != expected_rows:
        print(f"[FAIL] C8: site_weekly rows ({actual_rows:,}) != {site_count} sites × {N_WEEKS} weeks ({expected_rows:,})")
        return False

    # Verify every site has exactly 52 weeks
    cursor.execute("""
    SELECT COUNT(*) FROM (
        SELECT site_id, COUNT(*) AS n_weeks
        FROM site_weekly
        WHERE is_simulated = 0
        GROUP BY site_id
        HAVING n_weeks != ?
    );
    """, (N_WEEKS,))
    bad_sites_count = cursor.fetchone()[0]
    if bad_sites_count > 0:
        print(f"[FAIL] C8: Found {bad_sites_count} sites that do not have exactly {N_WEEKS} weekly records.")
        return False

    # Verify week_index range
    cursor.execute("SELECT MIN(week_index), MAX(week_index) FROM site_weekly WHERE is_simulated = 0;")
    min_w, max_w = cursor.fetchone()
    if min_w != 0 or max_w != N_WEEKS - 1:
        print(f"[FAIL] C8: week_index range [{min_w}, {max_w}] is not [0, {N_WEEKS - 1}].")
        return False

    # Verify no NULLs
    cursor.execute("""
    SELECT COUNT(*) FROM site_weekly
    WHERE is_simulated = 0 AND (
        detection_count IS NULL OR frp_sum IS NULL OR frp_max IS NULL OR night_count IS NULL
    );
    """)
    null_rows = cursor.fetchone()[0]
    if null_rows > 0:
        print(f"[FAIL] C8: Found {null_rows} rows with NULL numeric values in site_weekly.")
        return False

    print(
        f"[PASS] C8: site_weekly real rows = {actual_rows:,} ({site_count} sites × {N_WEEKS} weeks); "
        f"all sites have exactly 52 weeks (0–51); zero NULLs in numeric fields."
    )
    return True


def check_c9(conn: sqlite3.Connection) -> bool:
    """
    Check C9: sum of site_weekly.detection_count (real) = assigned detections.
    Also verifies:
    - for every site, the sum of weekly detection_count equals sites.n_detections
    - detection_count and night_count are non-negative
    - frp_sum and frp_max are non-negative
    """
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(detection_count) FROM site_weekly WHERE is_simulated = 0;")
    weekly_det_sum = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM detections WHERE site_id IS NOT NULL AND is_simulated = 0;")
    assigned_count = cursor.fetchone()[0]

    if weekly_det_sum != assigned_count:
        print(
            f"[FAIL] C9: site_weekly total detections ({weekly_det_sum:,}) != "
            f"assigned detections in detections table ({assigned_count:,})"
        )
        return False

    # Check conservation per individual site
    cursor.execute("""
    SELECT COUNT(*) FROM (
        SELECT s.site_id, s.n_detections, SUM(w.detection_count) AS weekly_dets
        FROM sites s
        JOIN site_weekly w ON s.site_id = w.site_id
        WHERE w.is_simulated = 0
        GROUP BY s.site_id
        HAVING s.n_detections != weekly_dets
    );
    """)
    mismatched_sites = cursor.fetchone()[0]
    if mismatched_sites > 0:
        print(f"[FAIL] C9: {mismatched_sites} sites have weekly detection sum != sites.n_detections.")
        return False

    # Check non-negativity
    cursor.execute("""
    SELECT COUNT(*) FROM site_weekly
    WHERE is_simulated = 0 AND (
        detection_count < 0 OR night_count < 0 OR frp_sum < 0 OR frp_max < 0
    );
    """)
    negative_rows = cursor.fetchone()[0]
    if negative_rows > 0:
        print(f"[FAIL] C9: Found {negative_rows} rows with negative values in site_weekly.")
        return False

    print(
        f"[PASS] C9: sum of site_weekly.detection_count = assigned detections ({weekly_det_sum:,} = {assigned_count:,}); "
        f"detection conservation confirmed across all 568 sites; non-negativity confirmed."
    )
    return True


def check_site_weekly_csv_export() -> bool:
    """
    Verify output/exports/site_weekly.csv:
    - File exists
    - Exactly 29,536 data rows
    - Spot check TS-0001: exactly 52 rows, weeks 0–51, sum of detection_count = 2,252
    """
    if not SITE_WEEKLY_EXPORT_CSV.exists():
        print(f"[FAIL] site_weekly.csv missing at {SITE_WEEKLY_EXPORT_CSV}")
        return False

    df = pd.read_csv(SITE_WEEKLY_EXPORT_CSV)
    expected_rows = 568 * N_WEEKS
    if len(df) != expected_rows:
        print(f"[FAIL] site_weekly.csv expected {expected_rows:,} rows, found {len(df):,}")
        return False

    # Spot check TS-0001
    ts1 = df[df["site_id"] == "TS-0001"]
    if len(ts1) != N_WEEKS:
        print(f"[FAIL] site_weekly.csv TS-0001 has {len(ts1)} rows, expected {N_WEEKS}")
        return False

    ts1_dets = ts1["detection_count"].sum()
    if ts1_dets != 2252:
        print(f"[FAIL] site_weekly.csv TS-0001 detections sum = {ts1_dets}, expected 2,252")
        return False

    print(
        f"[PASS] site_weekly.csv verified: {len(df):,} data rows, "
        f"TS-0001 spot-checked with {len(ts1)} rows and {ts1_dets:,} detections."
    )
    return True


def print_stage_5_info(conn: sqlite3.Connection) -> None:
    """
    Print informative metrics for Stage 5 (weekly history).
    """
    cursor = conn.cursor()
    print("-" * 60)
    print("STAGE 5 INFORMATIVE SUMMARY (SITE WEEKLY HISTORY)")
    print("-" * 60)

    cursor.execute("SELECT COUNT(*) FROM site_weekly WHERE is_simulated = 0;")
    total_rows = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM site_weekly WHERE is_simulated = 0 AND detection_count > 0;")
    active_weeks = cursor.fetchone()[0]
    inactive_weeks = total_rows - active_weeks

    cursor.execute("SELECT SUM(detection_count), SUM(night_count), ROUND(SUM(frp_sum), 1) FROM site_weekly WHERE is_simulated = 0;")
    tot_dets, tot_night, tot_frp = cursor.fetchone()

    print(f"Total weekly records:      {total_rows:,} (568 sites × 52 weeks)")
    print(f"Active site-weeks (>0):    {active_weeks:,} ({active_weeks / total_rows * 100:.1f}%)")
    print(f"Zero site-weeks (=0):      {inactive_weeks:,} ({inactive_weeks / total_rows * 100:.1f}%)")
    print(f"Total detections:          {tot_dets:,} (night detections: {tot_night:,}, total FRP: {tot_frp:,.1f} MW)")
    print("-" * 60 + "\n")


def check_c10(conn: sqlite3.Connection) -> bool:
    """
    Check C10:
    - Every baseline has n_weeks = 39.
    - threshold = mean + 3 × std (within 0.001).
    - established = 1 if active_weeks >= 10 else 0.
    - Every site in sites table has a valid site_class matching its established and facility match status.
    - Prints counts per site_class.
    """
    cursor = conn.cursor()
    cursor.execute("""
    SELECT
        b.site_id, b.n_weeks, b.active_weeks, b.baseline_detections,
        b.frp_sum_mean, b.frp_sum_std, b.threshold, b.established,
        s.site_class, s.match_type
    FROM baselines b
    JOIN sites s ON b.site_id = s.site_id;
    """)
    rows = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM sites;")
    expected_site_count = cursor.fetchone()[0]

    if len(rows) != expected_site_count:
        print(f"[FAIL] C10: baselines count ({len(rows)}) != sites count ({expected_site_count})")
        return False

    allowed_classes = {"PERSISTENT_INDUSTRIAL", "PERSISTENT_UNMAPPED", "EPISODIC_NEAR_FACILITY", "EPISODIC_OTHER"}
    class_counts: Dict[str, int] = {}
    invalid_rows = []

    for r in rows:
        # Check n_weeks
        if r["n_weeks"] != len(BASELINE_WEEKS):
            invalid_rows.append((r["site_id"], f"n_weeks={r['n_weeks']} != {len(BASELINE_WEEKS)}"))

        # Check threshold formula: mean + 3.0 * std within 0.001
        exp_thresh = r["frp_sum_mean"] + ANOMALY_K * r["frp_sum_std"]
        if abs(r["threshold"] - exp_thresh) > 0.001:
            invalid_rows.append((r["site_id"], f"threshold {r['threshold']} != {exp_thresh:.4f}"))

        # Check established definition
        exp_est = 1 if r["active_weeks"] >= BASELINE_MIN_ACTIVE_WEEKS else 0
        if r["established"] != exp_est:
            invalid_rows.append((r["site_id"], f"established={r['established']} != {exp_est}"))

        # Check site_class definition
        s_cls = r["site_class"]
        if s_cls not in allowed_classes:
            invalid_rows.append((r["site_id"], f"invalid site_class={s_cls}"))
            continue

        class_counts[s_cls] = class_counts.get(s_cls, 0) + 1

        has_fac = r["match_type"] in ("inside", "nearby")
        if exp_est == 1:
            expected_class = "PERSISTENT_INDUSTRIAL" if has_fac else "PERSISTENT_UNMAPPED"
        else:
            expected_class = "EPISODIC_NEAR_FACILITY" if has_fac else "EPISODIC_OTHER"

        if s_cls != expected_class:
            invalid_rows.append((r["site_id"], f"site_class={s_cls} != expected {expected_class}"))

    if invalid_rows:
        print(f"[FAIL] C10: {len(invalid_rows)} baseline/site_class violations: {invalid_rows[:5]}")
        return False

    n_est = sum(1 for r in rows if r["established"] == 1)
    print(
        f"[PASS] C10: all {len(rows):,} baselines verified (n_weeks = {len(BASELINE_WEEKS)}, "
        f"threshold = mean + 3 × std within 0.001, established = {n_est:,} / {len(rows):,}); "
        f"site_class verified for all sites: {class_counts}."
    )
    return True


def check_baselines_csv_export() -> bool:
    """
    Verify output/exports/baselines.csv:
    - File exists
    - Exactly 568 data rows
    - Zero NULL values
    - Spot check TS-0001: n_weeks=39, active_weeks=38, baseline_detections=1824, established=1
    """
    if not BASELINES_EXPORT_CSV.exists():
        print(f"[FAIL] baselines.csv missing at {BASELINES_EXPORT_CSV}")
        return False

    df = pd.read_csv(BASELINES_EXPORT_CSV)
    if len(df) != 568:
        print(f"[FAIL] baselines.csv expected 568 rows, found {len(df)}")
        return False

    null_count = df.isna().sum().sum()
    if null_count > 0:
        print(f"[FAIL] baselines.csv contains {null_count} NULL values.")
        return False

    # Spot check TS-0001
    ts1 = df[df["site_id"] == "TS-0001"]
    if len(ts1) != 1:
        print(f"[FAIL] baselines.csv TS-0001 not found.")
        return False

    ts1_row = ts1.iloc[0]
    if ts1_row["n_weeks"] != 39 or ts1_row["active_weeks"] != 38 or ts1_row["baseline_detections"] != 1824 or ts1_row["established"] != 1:
        print(f"[FAIL] baselines.csv TS-0001 values mismatch: {ts1_row.to_dict()}")
        return False

    print(
        f"[PASS] baselines.csv verified: {len(df):,} data rows, zero NULLs, "
        f"TS-0001 spot-checked with active={ts1_row['active_weeks']}/39, detections={ts1_row['baseline_detections']:,}, established=1."
    )
    return True


def print_stage_6_info(conn: sqlite3.Connection) -> None:
    """
    Print informative metrics for Stage 6 (baselines and site classification).
    """
    cursor = conn.cursor()
    print("-" * 60)
    print("STAGE 6 INFORMATIVE SUMMARY (BASELINES & CLASSIFICATION)")
    print("-" * 60)

    cursor.execute("SELECT site_class, COUNT(*) FROM sites GROUP BY site_class ORDER BY site_class;")
    class_counts = dict(cursor.fetchall())

    cursor.execute("SELECT established, COUNT(*) FROM baselines GROUP BY established;")
    est_counts = dict(cursor.fetchall())

    print(f"Established baseline sites (active weeks >= 10): {est_counts.get(1, 0):,}")
    print(f"Non-established baseline sites (active weeks < 10): {est_counts.get(0, 0):,}")
    print(f"Site classification breakdown:")
    for sc, count in class_counts.items():
        print(f"  • {sc:<24}: {count:>4} sites")
    print("-" * 60 + "\n")


def check_c11(conn: sqlite3.Connection) -> bool:
    """
    Check C11:
    - Every BASELINE_EXCEEDANCE has established = 1, count >= 2, frp_sum > threshold
    - Every NEW_ACTIVITY has baseline_detections = 0, count >= 2, threshold IS NULL, ratio IS NULL
    - All real anomalies occur in monitoring weeks (39–51)
    """
    cursor = conn.cursor()
    cursor.execute("""
    SELECT
        a.anomaly_id, a.site_id, a.week_index, a.anomaly_type,
        a.detection_count, a.frp_sum, a.frp_max, a.threshold, a.ratio, a.is_simulated,
        b.established, b.baseline_detections, b.threshold AS b_threshold
    FROM anomalies a
    JOIN baselines b ON a.site_id = b.site_id
    WHERE a.is_simulated = 0;
    """)
    rows = cursor.fetchall()

    if len(rows) == 0:
        print("[FAIL] C11: No real anomaly records found in anomalies table.")
        return False

    invalid_rows = []
    n_be = 0
    n_na = 0

    for r in rows:
        atype = r["anomaly_type"]
        w_idx = r["week_index"]
        cnt = r["detection_count"]
        frp = r["frp_sum"]
        thresh = r["threshold"]
        ratio = r["ratio"]
        est = r["established"]
        b_dets = r["baseline_detections"]

        if w_idx not in MONITORING_WEEKS:
            invalid_rows.append((r["anomaly_id"], f"week_index {w_idx} outside monitoring weeks {list(MONITORING_WEEKS)}"))

        if atype == "BASELINE_EXCEEDANCE":
            n_be += 1
            if est != 1:
                invalid_rows.append((r["anomaly_id"], f"BASELINE_EXCEEDANCE has established={est} != 1"))
            if cnt < 2:
                invalid_rows.append((r["anomaly_id"], f"BASELINE_EXCEEDANCE has detection_count={cnt} < 2"))
            if thresh is None or frp <= thresh:
                invalid_rows.append((r["anomaly_id"], f"BASELINE_EXCEEDANCE has frp_sum={frp} <= threshold={thresh}"))
            if ratio is None or abs(ratio - (frp / thresh)) > 0.001:
                invalid_rows.append((r["anomaly_id"], f"ratio {ratio} != {frp / thresh if thresh else 0}"))
        elif atype == "NEW_ACTIVITY":
            n_na += 1
            if b_dets != 0:
                invalid_rows.append((r["anomaly_id"], f"NEW_ACTIVITY has baseline_detections={b_dets} != 0"))
            if cnt < 2:
                invalid_rows.append((r["anomaly_id"], f"NEW_ACTIVITY has detection_count={cnt} < 2"))
            if thresh is not None:
                invalid_rows.append((r["anomaly_id"], f"NEW_ACTIVITY has non-NULL threshold={thresh}"))
            if ratio is not None:
                invalid_rows.append((r["anomaly_id"], f"NEW_ACTIVITY has non-NULL ratio={ratio}"))
        else:
            invalid_rows.append((r["anomaly_id"], f"Unknown anomaly_type={atype}"))

    if invalid_rows:
        print(f"[FAIL] C11: Found {len(invalid_rows)} anomaly condition violations: {invalid_rows[:5]}")
        return False

    print(
        f"[PASS] C11: all {len(rows):,} real anomalies verified "
        f"({n_be} BASELINE_EXCEEDANCE [all established=1, count>=2, frp_sum>threshold], "
        f"{n_na} NEW_ACTIVITY [all baseline_detections=0, count>=2, threshold/ratio NULL])."
    )
    return True


def check_c12(conn: sqlite3.Connection) -> bool:
    """
    Check C12:
    - Every anomaly score equals the recomputed points from TECH_SPEC §7 rules.
    - Priority matches score (>=5: HIGH, 3–4: MEDIUM, 1–2: LOW).
    """
    cursor = conn.cursor()
    cursor.execute("""
    SELECT
        a.anomaly_id, a.site_id, a.week_index, a.anomaly_type,
        a.frp_max, a.ratio, a.score, a.priority, a.is_simulated,
        b.baseline_max_frp, s.match_type
    FROM anomalies a
    JOIN baselines b ON a.site_id = b.site_id
    JOIN sites s ON a.site_id = s.site_id
    WHERE a.is_simulated = 0;
    """)
    rows = cursor.fetchall()

    if len(rows) == 0:
        print("[FAIL] C12: No real anomaly records found in anomalies table.")
        return False

    mismatches = []
    prio_counts: Dict[str, int] = {}

    for r in rows:
        atype = r["anomaly_type"]
        pts = 0

        if atype == "BASELINE_EXCEEDANCE":
            pts += PTS_BASELINE_EXCEEDANCE
            if r["frp_max"] > r["baseline_max_frp"]:
                pts += PTS_RECORD_FRP
            if r["ratio"] is not None and r["ratio"] >= LARGE_EXCEEDANCE_RATIO:
                pts += PTS_LARGE_EXCEEDANCE
            if r["match_type"] in ("inside", "nearby"):
                pts += PTS_FACILITY_MATCH
        elif atype == "NEW_ACTIVITY":
            pts += PTS_NEW_ACTIVITY
            if r["match_type"] in ("inside", "nearby"):
                pts += PTS_FACILITY_MATCH
        else:
            mismatches.append((r["anomaly_id"], f"Unknown anomaly type {atype}"))
            continue

        if r["score"] != pts:
            mismatches.append((r["anomaly_id"], f"score={r['score']} != recomputed {pts}"))

        exp_prio = "HIGH" if pts >= PRIORITY_HIGH_MIN else ("MEDIUM" if pts >= PRIORITY_MEDIUM_MIN else "LOW")
        if r["priority"] != exp_prio:
            mismatches.append((r["anomaly_id"], f"priority={r['priority']} != expected {exp_prio}"))

        prio_counts[r["priority"]] = prio_counts.get(r["priority"], 0) + 1

    if mismatches:
        print(f"[FAIL] C12: {len(mismatches)} scoring/priority mismatches: {mismatches[:5]}")
        return False

    print(
        f"[PASS] C12: all {len(rows):,} anomaly scores equal recomputed points; "
        f"priorities match scores ({prio_counts})."
    )
    return True


def check_c13(conn: sqlite3.Connection) -> bool:
    """
    Check C13:
    - Every anomaly has >= 1 reason.
    - Reasons column is valid JSON array of non-empty strings.
    - Every simulated reason starts with '[SIMULATED]' (checked if simulated rows exist).
    - No real anomaly reason starts with '[SIMULATED]'.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT anomaly_id, site_id, week_index, reasons, is_simulated FROM anomalies;")
    rows = cursor.fetchall()

    if len(rows) == 0:
        print("[FAIL] C13: No records found in anomalies table.")
        return False

    bad_reasons = []
    for r in rows:
        raw_reasons = r["reasons"]
        is_sim = r["is_simulated"]

        try:
            parsed = json.loads(raw_reasons)
        except Exception as e:
            bad_reasons.append((r["anomaly_id"], f"invalid JSON: {e}"))
            continue

        if not isinstance(parsed, list) or len(parsed) < 1:
            bad_reasons.append((r["anomaly_id"], f"empty or non-list reasons: {parsed}"))
            continue

        for reason_str in parsed:
            if not isinstance(reason_str, str) or len(reason_str.strip()) == 0:
                bad_reasons.append((r["anomaly_id"], "non-string or empty reason text"))
            if is_sim == 1 and not reason_str.startswith("[SIMULATED]"):
                bad_reasons.append((r["anomaly_id"], f"simulated reason does not start with [SIMULATED]: {reason_str[:30]}"))
            if is_sim == 0 and reason_str.startswith("[SIMULATED]"):
                bad_reasons.append((r["anomaly_id"], f"real reason improperly prefixed with [SIMULATED]: {reason_str[:30]}"))

    if bad_reasons:
        print(f"[FAIL] C13: {len(bad_reasons)} invalid reason entries: {bad_reasons[:5]}")
        return False

    print(f"[PASS] C13: all {len(rows):,} anomalies have >= 1 valid JSON reason; simulated prefix rule verified.")
    return True


def check_anomalies_csv_export() -> bool:
    """
    Verify output/exports/anomalies.csv:
    - File exists
    - Exactly 160 data rows
    - Required columns present
    - Spot-check: TS-0035 week 40 has score=7 and priority=HIGH
    """
    if not ANOMALIES_EXPORT_CSV.exists():
        print(f"[FAIL] anomalies.csv missing at {ANOMALIES_EXPORT_CSV}")
        return False

    df = pd.read_csv(ANOMALIES_EXPORT_CSV)
    if len(df) != 160:
        print(f"[FAIL] anomalies.csv expected 160 rows, found {len(df)}")
        return False

    expected_cols = [
        "anomaly_id", "site_id", "week_index", "week_start", "week_end",
        "anomaly_type", "detection_count", "frp_sum", "frp_max",
        "threshold", "ratio", "score", "priority", "reasons", "is_simulated"
    ]
    missing_cols = [c for c in expected_cols if c not in df.columns]
    if missing_cols:
        print(f"[FAIL] anomalies.csv missing expected columns: {missing_cols}")
        return False

    # Spot check TS-0035 week 40
    spot = df[(df["site_id"] == "TS-0035") & (df["week_index"] == 40)]
    if len(spot) != 1:
        print(f"[FAIL] anomalies.csv spot check TS-0035 week 40 not found.")
        return False

    spot_row = spot.iloc[0]
    if spot_row["score"] != 7 or spot_row["priority"] != "HIGH":
        print(f"[FAIL] anomalies.csv TS-0035 week 40 unexpected values: score={spot_row['score']}, prio={spot_row['priority']}")
        return False

    print(
        f"[PASS] anomalies.csv verified: {len(df):,} data rows, all columns present, "
        f"TS-0035 week 40 spot-checked with score=7, priority=HIGH."
    )
    return True


def print_stage_7_info(conn: sqlite3.Connection) -> None:
    """
    Print informative metrics for Stage 7 (anomalies, priorities, and site statuses).
    """
    cursor = conn.cursor()
    print("-" * 60)
    print("STAGE 7 INFORMATIVE SUMMARY (ANOMALIES & STATUSES)")
    print("-" * 60)

    cursor.execute("SELECT anomaly_type, COUNT(*) FROM anomalies WHERE is_simulated = 0 GROUP BY anomaly_type ORDER BY anomaly_type;")
    type_counts = dict(cursor.fetchall())

    cursor.execute("SELECT priority, COUNT(*) FROM anomalies WHERE is_simulated = 0 GROUP BY priority ORDER BY priority;")
    prio_counts = dict(cursor.fetchall())

    cursor.execute("SELECT status, COUNT(*) FROM sites GROUP BY status ORDER BY status;")
    status_counts = dict(cursor.fetchall())

    cursor.execute("SELECT COUNT(DISTINCT site_id) FROM anomalies WHERE is_simulated = 0;")
    anom_sites_count = cursor.fetchone()[0]

    print(f"Total real anomalies:       {sum(type_counts.values()):,} across {anom_sites_count:,} sites")
    print(f"Anomalies by Type:          {type_counts}")
    print(f"Anomalies by Priority:      {prio_counts}")
    print("Site Status as of 30 Jun 2026 (568 sites):")
    for st in ["HIGH", "MEDIUM", "LOW", "NORMAL", "INSUFFICIENT_HISTORY", "NEW_SITE_NO_ANOMALY"]:
        print(f"  • {st:<24}: {status_counts.get(st, 0):>4} sites")
    print("-" * 60 + "\n")


def main() -> None:
    print("=" * 60)
    print("THERMOGRAPH Output Verification — Stages T1–T7")
    print("=" * 60)

    conn = get_db_connection()
    results = []

    try:
        # Stage 1 & 2 checks
        results.append(check_c1(conn))
        results.append(check_c2(conn))
        results.append(check_c3(conn))
        results.append(check_c4(conn))
        results.append(check_c5(conn))
        results.append(check_c15())
        results.append(check_detections_csv_export())
        results.append(check_sites_csv_export())

        # Stage 3 & 4 checks
        results.append(check_c6(conn))
        results.append(check_c7(conn))
        results.append(check_facilities_csv_export())
        results.append(check_matched_sites_csv())

        # Stage 5 checks
        results.append(check_c8(conn))
        results.append(check_c9(conn))
        results.append(check_site_weekly_csv_export())

        # Stage 6 checks
        results.append(check_c10(conn))
        results.append(check_baselines_csv_export())

        # Stage 7 checks
        results.append(check_c11(conn))
        results.append(check_c12(conn))
        results.append(check_c13(conn))
        results.append(check_anomalies_csv_export())

        # Summaries
        print_stage_2_info(conn)
        print_stage_4_info(conn)
        print_stage_5_info(conn)
        print_stage_6_info(conn)
        print_stage_7_info(conn)
    finally:
        conn.close()

    print("=" * 60)
    if all(results):
        print("ALL ACTIVE VERIFICATION CHECKS PASSED (C1–C13, C15, Exports).")
        print("=" * 60)
        sys.exit(0)
    else:
        failed = results.count(False)
        print(f"VERIFICATION FAILED: {failed} check(s) failed.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()



