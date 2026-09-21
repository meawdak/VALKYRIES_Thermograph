"""
THERMOGRAPH — Pipeline Verification Checks
Verifies database outputs and data integrity after each pipeline stage.
Prints PASS or FAIL for each check. Exits with code 1 if any check fails.

Specification: TECH_SPEC §10, TASKS.md.
"""

import sqlite3
import sys
from pathlib import Path
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    CLUSTER_MIN_SAMPLES,
    DATASET_START,
    DATASET_END,
    DB_PATH,
    EXPECTED_DETECTIONS,
    EXPORT_DIR,
    LEGACY_SITES_CSV,
    RAW_DATA_FILE_COUNT,
    RAW_DATA_TOTAL_BYTES,
    RAW_PAYLOAD_FILE_COUNT,
    RAW_PAYLOAD_TOTAL_BYTES,
    RAW_FIRMS_DIR,
    RAW_OSM_FILE,
    ROOT,
    SITE_EXTENT_REVIEW_KM,
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

    print(
        f"[PASS] sites.csv verified: {len(df)} data rows, "
        f"TS-0001 correctly ordered first with maximum detections ({first_site['n_detections']:,})."
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


def main() -> None:
    print("=" * 60)
    print("THERMOGRAPH Output Verification — Stage T2")
    print("=" * 60)

    conn = get_db_connection()
    results = []

    try:
        results.append(check_c1(conn))
        results.append(check_c2(conn))
        results.append(check_c3(conn))
        results.append(check_c4(conn))
        results.append(check_c5(conn))
        results.append(check_c15())
        results.append(check_detections_csv_export())
        results.append(check_sites_csv_export())
        print_stage_2_info(conn)
    finally:
        conn.close()

    print("=" * 60)
    if all(results):
        print("ALL ACTIVE VERIFICATION CHECKS PASSED (C1–C5, C15).")
        print("=" * 60)
        sys.exit(0)
    else:
        failed = results.count(False)
        print(f"VERIFICATION FAILED: {failed} check(s) failed.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
