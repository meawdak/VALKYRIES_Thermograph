"""
THERMOGRAPH — Stage 5: Weekly History Generation (T5)
Generates complete 52-week activity time-series for every candidate thermal site.
Aggregates detection count, total FRP, maximum FRP, and night detections per site
and week. Weeks with no detections are populated with zero values. Populates the
SQLite 'site_weekly' table, updates active week counts in 'sites', records metadata,
exports output/exports/site_weekly.csv, and runs validation checks.

Specifications implemented: TECH_SPEC §5.5, PRD FR-15, TASKS.md T5.
"""

import datetime
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    BASELINE_WEEKS,
    DATASET_END,
    DATASET_START,
    DB_PATH,
    MONITORING_WEEKS,
    N_WEEKS,
    SITE_WEEKLY_EXPORT_CSV,
    SITES_EXPORT_CSV,
)
from processing.db import get_connection, set_metadata


def build_week_calendar() -> List[Dict[str, Any]]:
    """
    Construct calendar boundaries and periods for all 52 weeks (0 to 51):
    - Week 0 starts on DATASET_START (2025-07-01).
    - Weeks 0-50 span 7 days (start to start + 6 days).
    - Week 51 ends on DATASET_END (2026-06-30, 8 days).
    - Weeks 0-38: period = 'baseline'.
    - Weeks 39-51: period = 'monitoring'.
    """
    start_date = datetime.date.fromisoformat(DATASET_START)
    end_date = datetime.date.fromisoformat(DATASET_END)

    calendar: List[Dict[str, Any]] = []
    for w in range(N_WEEKS):
        w_start = start_date + datetime.timedelta(days=w * 7)
        if w == N_WEEKS - 1:
            w_end = end_date
        else:
            w_end = w_start + datetime.timedelta(days=6)

        period = "baseline" if w in BASELINE_WEEKS else "monitoring"

        calendar.append(
            {
                "week_index": w,
                "week_start": str(w_start),
                "week_end": str(w_end),
                "period": period,
            }
        )
    return calendar


def generate_weekly_history(conn: sqlite3.Connection) -> Tuple[List[Dict[str, Any]], pd.DataFrame]:
    """
    Query detection aggregations and generate full 52-week records for every site.
    Ensures missing site-weeks are explicitly populated with zeros.
    """
    cursor = conn.cursor()

    # 1. Fetch all distinct sites
    cursor.execute("SELECT site_id, n_detections FROM sites ORDER BY site_id ASC;")
    sites = cursor.fetchall()
    site_ids = [r["site_id"] for r in sites]
    site_detections_map = {r["site_id"]: r["n_detections"] for r in sites}
    total_sites = len(site_ids)

    print(f"Loaded {total_sites:,} sites from database.")
    if total_sites == 0:
        print("[FAIL] No sites found in database. Run Stage 2 first. Stopping.")
        sys.exit(1)

    # 2. Build week calendar
    calendar = build_week_calendar()
    cal_map = {c["week_index"]: c for c in calendar}

    # 3. Query active aggregations from detections table
    query = """
    SELECT
        site_id,
        week_index,
        COUNT(*) AS detection_count,
        ROUND(SUM(frp), 2) AS frp_sum,
        ROUND(MAX(frp), 2) AS frp_max,
        SUM(CASE WHEN daynight = 'N' THEN 1 ELSE 0 END) AS night_count
    FROM detections
    WHERE site_id IS NOT NULL AND is_simulated = 0
    GROUP BY site_id, week_index;
    """
    cursor.execute(query)
    active_rows = cursor.fetchall()

    # Map active aggregates by (site_id, week_index)
    agg_map = {}
    for r in active_rows:
        agg_map[(r["site_id"], r["week_index"])] = {
            "detection_count": int(r["detection_count"]),
            "frp_sum": float(r["frp_sum"]),
            "frp_max": float(r["frp_max"]),
            "night_count": int(r["night_count"]),
        }

    print(f"Aggregated {len(agg_map):,} active site-week observations from real detections.")

    # 4. Generate Cartesian product of sites × 52 weeks
    weekly_records: List[Dict[str, Any]] = []

    for sid in site_ids:
        for w in range(N_WEEKS):
            c_info = cal_map[w]
            agg = agg_map.get((sid, w))

            if agg is not None:
                det_count = agg["detection_count"]
                frp_sum = agg["frp_sum"]
                frp_max = agg["frp_max"]
                night_count = agg["night_count"]
            else:
                det_count = 0
                frp_sum = 0.0
                frp_max = 0.0
                night_count = 0

            weekly_records.append(
                {
                    "site_id": sid,
                    "week_index": w,
                    "week_start": c_info["week_start"],
                    "week_end": c_info["week_end"],
                    "period": c_info["period"],
                    "detection_count": det_count,
                    "frp_sum": frp_sum,
                    "frp_max": frp_max,
                    "night_count": night_count,
                    "is_simulated": 0,
                }
            )

    expected_total_rows = total_sites * N_WEEKS
    if len(weekly_records) != expected_total_rows:
        print(
            f"[FAIL] Expected {expected_total_rows:,} weekly records, generated {len(weekly_records):,}. Stopping."
        )
        sys.exit(1)

    print(f"Generated {len(weekly_records):,} total site-weekly rows ({total_sites} sites × {N_WEEKS} weeks).")
    df_weekly = pd.DataFrame(weekly_records)
    return weekly_records, df_weekly


def validate_weekly_history(df_weekly: pd.DataFrame, conn: sqlite3.Connection) -> bool:
    """
    Execute all Stage 5 validation checks:
    - exactly 568 distinct site IDs
    - exactly 52 weeks per site
    - exactly 29,536 rows total (568 × 52)
    - week_index range is 0–51
    - no NULL values in the calculated numeric fields
    - detection_count and night_count are non-negative
    - frp_sum and frp_max are non-negative
    - for every site, the sum of weekly detection_count equals that site's assigned detection count
    """
    print("\n" + "-" * 60)
    print("RUNNING STAGE 5 VALIDATION CHECKS")
    print("-" * 60)

    checks_passed = True

    # 1. Total row count
    total_rows = len(df_weekly)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sites;")
    site_count = cursor.fetchone()[0]
    expected_rows = site_count * N_WEEKS

    if total_rows == expected_rows:
        print(f"[PASS] Total rows: {total_rows:,} == {site_count} sites × {N_WEEKS} weeks.")
    else:
        print(f"[FAIL] Total rows {total_rows:,} != expected {expected_rows:,}.")
        checks_passed = False

    # 2. Distinct site IDs
    distinct_sites = df_weekly["site_id"].nunique()
    if distinct_sites == site_count:
        print(f"[PASS] Distinct site IDs: {distinct_sites} == {site_count}.")
    else:
        print(f"[FAIL] Distinct site IDs {distinct_sites} != expected {site_count}.")
        checks_passed = False

    # 3. Exactly 52 weeks per site
    weeks_per_site = df_weekly.groupby("site_id")["week_index"].count()
    if (weeks_per_site == N_WEEKS).all():
        print(f"[PASS] Exactly {N_WEEKS} weeks for every single site.")
    else:
        bad_sites = weeks_per_site[weeks_per_site != N_WEEKS]
        print(f"[FAIL] Sites with != {N_WEEKS} weeks: {len(bad_sites)} sites.")
        checks_passed = False

    # 4. week_index range 0–51
    min_w = df_weekly["week_index"].min()
    max_w = df_weekly["week_index"].max()
    if min_w == 0 and max_w == N_WEEKS - 1:
        print(f"[PASS] week_index range: {min_w} to {max_w}.")
    else:
        print(f"[FAIL] Invalid week_index range: {min_w} to {max_w}.")
        checks_passed = False

    # 5. No NULL values in calculated numeric fields
    numeric_cols = ["detection_count", "frp_sum", "frp_max", "night_count", "is_simulated"]
    null_counts = df_weekly[numeric_cols].isna().sum()
    if null_counts.sum() == 0:
        print("[PASS] Zero NULL values in calculated numeric fields.")
    else:
        print(f"[FAIL] Found NULL values in numeric fields: {null_counts.to_dict()}")
        checks_passed = False

    # 6. Non-negativity constraints
    if (df_weekly["detection_count"] >= 0).all() and (df_weekly["night_count"] >= 0).all():
        print("[PASS] detection_count and night_count are non-negative.")
    else:
        print("[FAIL] Found negative detection_count or night_count.")
        checks_passed = False

    if (df_weekly["frp_sum"] >= 0.0).all() and (df_weekly["frp_max"] >= 0.0).all():
        print("[PASS] frp_sum and frp_max are non-negative.")
    else:
        print("[FAIL] Found negative frp_sum or frp_max.")
        checks_passed = False

    # 7. Detection count conservation per site
    cursor.execute("SELECT site_id, n_detections FROM sites;")
    expected_site_dets = dict(cursor.fetchall())
    site_weekly_sum = df_weekly.groupby("site_id")["detection_count"].sum().to_dict()

    mismatches = []
    for sid, exp_dets in expected_site_dets.items():
        act_dets = site_weekly_sum.get(sid, 0)
        if act_dets != exp_dets:
            mismatches.append((sid, exp_dets, act_dets))

    if len(mismatches) == 0:
        total_assigned = sum(expected_site_dets.values())
        print(
            f"[PASS] Detection count conservation: weekly sums match sites.n_detections "
            f"for all {len(expected_site_dets)} sites (total: {total_assigned:,} detections)."
        )
    else:
        print(f"[FAIL] Detection count mismatch for {len(mismatches)} sites: {mismatches[:5]}")
        checks_passed = False

    print("-" * 60)
    return checks_passed


def run_site_history() -> pd.DataFrame:
    """
    Main execution of Stage 5 Site History:
    1. Connects to SQLite thermograph.db.
    2. Generates weekly records for all sites and weeks.
    3. Populates site_weekly table.
    4. Updates active_weeks_total in sites table.
    5. Updates metadata table.
    6. Exports output/exports/site_weekly.csv.
    7. Runs comprehensive validation checks.
    """
    print("=" * 60)
    print("THERMOGRAPH Pipeline — Stage 5: Site History / Weekly Aggregation")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}. Run earlier stages first. Stopping.")
        sys.exit(1)

    conn = get_connection(DB_PATH)

    # 1. Generate weekly records
    records, df_weekly = generate_weekly_history(conn)

    # 2. Populate SQLite site_weekly table (idempotent / rerun-safe)
    print("Storing records in SQLite 'site_weekly' table...")
    conn.execute("DELETE FROM site_weekly WHERE is_simulated = 0;")

    insert_sql = """
    INSERT INTO site_weekly (
        site_id, week_index, week_start, week_end, period,
        detection_count, frp_sum, frp_max, night_count, is_simulated
    ) VALUES (
        :site_id, :week_index, :week_start, :week_end, :period,
        :detection_count, :frp_sum, :frp_max, :night_count, :is_simulated
    );
    """
    conn.executemany(insert_sql, records)

    # 3. Synchronize active_weeks_total in sites table
    print("Synchronizing active_weeks_total in 'sites' table...")
    active_weeks_by_site = (
        df_weekly[df_weekly["detection_count"] > 0]
        .groupby("site_id")["week_index"]
        .count()
        .to_dict()
    )

    cursor = conn.cursor()
    cursor.execute("SELECT site_id FROM sites;")
    all_site_ids = [r[0] for r in cursor.fetchall()]

    update_tuples = [
        (active_weeks_by_site.get(sid, 0), sid)
        for sid in all_site_ids
    ]
    conn.executemany(
        "UPDATE sites SET active_weeks_total = ? WHERE site_id = ?;",
        update_tuples,
    )
    conn.commit()

    # 4. Record metadata
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    set_metadata(conn, "site_weekly_rows", str(len(records)))
    set_metadata(conn, "stage_5_history_at_utc", now_iso)

    # 5. Export site_weekly.csv
    SITE_WEEKLY_EXPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_weekly.to_csv(SITE_WEEKLY_EXPORT_CSV, index=False)
    print(f"Exported weekly history to {SITE_WEEKLY_EXPORT_CSV} ({len(df_weekly):,} rows).")

    # Refresh sites.csv export with synchronized active_weeks_total
    sites_updated_df = pd.read_sql_query(
        "SELECT * FROM sites ORDER BY n_detections DESC, centroid_lat DESC;",
        conn,
    )
    sites_updated_df.to_csv(SITES_EXPORT_CSV, index=False)
    print(f"Refreshed {SITES_EXPORT_CSV} ({len(sites_updated_df):,} rows).")

    # 6. Run validation checks
    valid = validate_weekly_history(df_weekly, conn)
    conn.close()

    if not valid:
        print("\n[FAIL] Stage 5 validation checks failed!")
        sys.exit(1)

    # 7. Print summary metrics
    total_assigned = int(df_weekly["detection_count"].sum())
    active_site_weeks = int((df_weekly["detection_count"] > 0).sum())
    inactive_site_weeks = len(df_weekly) - active_site_weeks

    print("\n" + "=" * 60)
    print("STAGE 5 SITE HISTORY SUMMARY")
    print("=" * 60)
    print(f"Total sites:                    {len(all_site_ids):,}")
    print(f"Weeks per site:                 {N_WEEKS}")
    print(f"Total site_weekly rows:         {len(df_weekly):,}")
    print(f"Active site-weeks (>0 dets):    {active_site_weeks:,} ({active_site_weeks / len(df_weekly) * 100:.1f}%)")
    print(f"Zero site-weeks (0 dets):       {inactive_site_weeks:,} ({inactive_site_weeks / len(df_weekly) * 100:.1f}%)")
    print(f"Total detections preserved:     {total_assigned:,}")
    print("=" * 60)
    print("Stage 5 successfully completed.")
    print("=" * 60)

    return df_weekly


if __name__ == "__main__":
    run_site_history()
