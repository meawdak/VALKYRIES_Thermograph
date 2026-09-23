"""
THERMOGRAPH — Stage 6: Historical Baseline & Site Classification (T6)
Computes per-site baseline statistics over the 39-week baseline period
(1 July 2025 to 30 March 2026, weeks 0–38). Calculates mean weekly FRP,
population standard deviation (ddof=0), upper anomaly threshold (mean + 3 * std),
determines established baseline status (active weeks >= 10), and assigns
rule-based site classes in the sites table.

Specifications implemented: TECH_SPEC §5.6, PRD FR-16, TASKS.md T6.
"""

import datetime
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    ANOMALY_K,
    BASELINE_MIN_ACTIVE_WEEKS,
    BASELINE_WEEKS,
    BASELINES_EXPORT_CSV,
    DB_PATH,
    SITES_EXPORT_CSV,
)
from processing.db import get_connection, set_metadata

ALLOWED_SITE_CLASSES = {
    "PERSISTENT_INDUSTRIAL",
    "PERSISTENT_UNMAPPED",
    "EPISODIC_NEAR_FACILITY",
    "EPISODIC_OTHER",
}


def compute_site_baselines(
    conn: sqlite3.Connection,
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]], pd.DataFrame]:
    """
    Compute baseline metrics for all sites using ONLY baseline weeks (0–38).
    Returns baseline records, site_class update tuples, and a pandas DataFrame.
    """
    cursor = conn.cursor()

    # 1. Fetch site metadata: site_id, match_type
    cursor.execute("SELECT site_id, match_type, n_detections FROM sites ORDER BY site_id ASC;")
    sites = cursor.fetchall()
    total_sites = len(sites)

    if total_sites == 0:
        print("[FAIL] No sites found in database. Run earlier stages first. Stopping.")
        sys.exit(1)

    site_match_type = {r["site_id"]: r["match_type"] for r in sites}
    site_ids = [r["site_id"] for r in sites]

    # 2. Fetch weekly history for baseline weeks ONLY (weeks 0 to 38)
    baseline_weeks_list = list(BASELINE_WEEKS)
    max_baseline_week = max(baseline_weeks_list)
    min_baseline_week = min(baseline_weeks_list)
    n_expected_weeks = len(baseline_weeks_list)

    query = f"""
    SELECT
        site_id, week_index, detection_count, frp_sum, frp_max
    FROM site_weekly
    WHERE week_index >= {min_baseline_week} AND week_index <= {max_baseline_week} AND is_simulated = 0
    ORDER BY site_id, week_index;
    """
    df_baseline_weekly = pd.read_sql_query(query, conn)

    print(
        f"Loaded {len(df_baseline_weekly):,} weekly records for {total_sites} sites "
        f"across baseline weeks [{min_baseline_week}..{max_baseline_week}] ({n_expected_weeks} weeks)."
    )

    # 3. Calculate metrics per site
    baseline_records: List[Dict[str, Any]] = []
    site_class_updates: List[Tuple[str, str]] = []

    grouped = df_baseline_weekly.groupby("site_id")

    for sid in site_ids:
        if sid not in grouped.groups:
            print(f"[FAIL] Missing baseline weekly records for site {sid}. Stopping.")
            sys.exit(1)

        grp = grouped.get_group(sid)
        n_weeks = len(grp)

        if n_weeks != n_expected_weeks:
            print(f"[FAIL] Site {sid} has {n_weeks} baseline weeks, expected {n_expected_weeks}. Stopping.")
            sys.exit(1)

        active_weeks = int((grp["detection_count"] > 0).sum())
        baseline_dets = int(grp["detection_count"].sum())

        # FRP calculations across all 39 weeks (zeros included)
        frp_sums = grp["frp_sum"].to_numpy(dtype=float)
        mean_val = float(np.mean(frp_sums))
        std_val = float(np.std(frp_sums, ddof=0))  # Population standard deviation
        threshold = float(mean_val + ANOMALY_K * std_val)

        # Baseline max FRP: highest single-detection FRP in baseline period (0 if none)
        if baseline_dets > 0:
            baseline_max_frp = float(grp["frp_max"].max())
        else:
            baseline_max_frp = 0.0

        # Established status: active in >= 10 of 39 baseline weeks
        established = 1 if active_weeks >= BASELINE_MIN_ACTIVE_WEEKS else 0

        # Rule-based site classification (PRD FR-16)
        mtype = site_match_type.get(sid, "none")
        has_facility_match = mtype in ("inside", "nearby")

        if established == 1:
            site_class = "PERSISTENT_INDUSTRIAL" if has_facility_match else "PERSISTENT_UNMAPPED"
        else:
            site_class = "EPISODIC_NEAR_FACILITY" if has_facility_match else "EPISODIC_OTHER"

        baseline_records.append(
            {
                "site_id": sid,
                "n_weeks": n_weeks,
                "active_weeks": active_weeks,
                "baseline_detections": baseline_dets,
                "frp_sum_mean": round(mean_val, 4),
                "frp_sum_std": round(std_val, 4),
                "threshold": round(threshold, 4),
                "baseline_max_frp": round(baseline_max_frp, 2),
                "established": established,
            }
        )
        site_class_updates.append((site_class, sid))

    df_baselines = pd.DataFrame(baseline_records)
    return baseline_records, site_class_updates, df_baselines


def validate_baselines(
    df_baselines: pd.DataFrame,
    site_class_updates: List[Tuple[str, str]],
    conn: sqlite3.Connection,
) -> bool:
    """
    Execute all Stage 6 validation checks:
    - exactly 568 baseline rows
    - exactly 568 classified sites
    - no NULL baseline statistics
    - threshold >= frp_sum_mean for every site
    - established is only 0 or 1
    - site_class belongs to the four allowed classes
    - baseline_detections equals sum of detection_count from weeks 0–38
    - active_weeks equals number of baseline weeks where detection_count > 0
    - no monitoring weeks (39–51) are used in baseline calculations
    """
    print("\n" + "-" * 60)
    print("RUNNING STAGE 6 BASELINE VALIDATION CHECKS")
    print("-" * 60)

    checks_passed = True

    # 1. Row counts
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sites;")
    total_sites = cursor.fetchone()[0]

    if len(df_baselines) == total_sites:
        print(f"[PASS] Exactly {len(df_baselines)} baseline rows for {total_sites} sites.")
    else:
        print(f"[FAIL] Baseline rows count {len(df_baselines)} != {total_sites}.")
        checks_passed = False

    if len(site_class_updates) == total_sites:
        print(f"[PASS] Exactly {len(site_class_updates)} sites classified.")
    else:
        print(f"[FAIL] Classified sites count {len(site_class_updates)} != {total_sites}.")
        checks_passed = False

    # 2. No NULL values
    numeric_cols = [
        "n_weeks", "active_weeks", "baseline_detections",
        "frp_sum_mean", "frp_sum_std", "threshold",
        "baseline_max_frp", "established",
    ]
    null_counts = df_baselines[numeric_cols].isna().sum()
    if null_counts.sum() == 0:
        print("[PASS] Zero NULL values in baseline statistics.")
    else:
        print(f"[FAIL] Found NULL values in baseline statistics: {null_counts.to_dict()}")
        checks_passed = False

    # 3. Threshold >= Mean
    threshold_valid = (df_baselines["threshold"] >= df_baselines["frp_sum_mean"]).all()
    if threshold_valid:
        print("[PASS] threshold >= frp_sum_mean for all sites.")
    else:
        bad_thresh = df_baselines[df_baselines["threshold"] < df_baselines["frp_sum_mean"]]
        print(f"[FAIL] threshold < frp_sum_mean for {len(bad_thresh)} sites.")
        checks_passed = False

    # 4. Established values strictly in {0, 1}
    est_values = set(df_baselines["established"].unique())
    if est_values.issubset({0, 1}):
        n_est = int((df_baselines["established"] == 1).sum())
        n_non_est = int((df_baselines["established"] == 0).sum())
        print(f"[PASS] established is strictly 0 or 1 (established: {n_est:,}, not established: {n_non_est:,}).")
    else:
        print(f"[FAIL] Invalid established values: {est_values}")
        checks_passed = False

    # 5. Site classes belong to the four allowed classes
    classes_assigned = set(sc[0] for sc in site_class_updates)
    if classes_assigned.issubset(ALLOWED_SITE_CLASSES):
        print(f"[PASS] All site classes belong to allowed set: {sorted(list(classes_assigned))}.")
    else:
        invalid_classes = classes_assigned - ALLOWED_SITE_CLASSES
        print(f"[FAIL] Invalid site classes detected: {invalid_classes}")
        checks_passed = False

    # 6. Conservation with site_weekly weeks 0–38
    cursor.execute("""
    SELECT
        w.site_id,
        SUM(w.detection_count) AS weekly_dets,
        SUM(CASE WHEN w.detection_count > 0 THEN 1 ELSE 0 END) AS weekly_active
    FROM site_weekly w
    WHERE w.week_index < 39 AND w.is_simulated = 0
    GROUP BY w.site_id;
    """)
    weekly_sums = {r["site_id"]: (r["weekly_dets"], r["weekly_active"]) for r in cursor.fetchall()}

    det_mismatches = []
    active_mismatches = []
    for _, r in df_baselines.iterrows():
        sid = r["site_id"]
        exp_dets, exp_active = weekly_sums.get(sid, (0, 0))
        if r["baseline_detections"] != exp_dets:
            det_mismatches.append((sid, exp_dets, r["baseline_detections"]))
        if r["active_weeks"] != exp_active:
            active_mismatches.append((sid, exp_active, r["active_weeks"]))

    if len(det_mismatches) == 0:
        print("[PASS] baseline_detections matches sum of detection_count from weeks 0–38 for all sites.")
    else:
        print(f"[FAIL] baseline_detections mismatch for {len(det_mismatches)} sites: {det_mismatches[:5]}")
        checks_passed = False

    if len(active_mismatches) == 0:
        print("[PASS] active_weeks matches number of baseline weeks with detection_count > 0 for all sites.")
    else:
        print(f"[FAIL] active_weeks mismatch for {len(active_mismatches)} sites: {active_mismatches[:5]}")
        checks_passed = False

    # 7. Verify no monitoring weeks (39–51) were included in baseline statistics
    if (df_baselines["n_weeks"] == len(BASELINE_WEEKS)).all():
        print(f"[PASS] Exactly {len(BASELINE_WEEKS)} weeks used; no monitoring weeks (39–51) included.")
    else:
        print(f"[FAIL] Inconsistent n_weeks in baselines table.")
        checks_passed = False

    print("-" * 60)
    return checks_passed


def run_baselines() -> pd.DataFrame:
    """
    Main execution of Stage 6 Historical Baseline:
    1. Connects to SQLite thermograph.db.
    2. Computes baseline metrics over weeks 0–38.
    3. Populates SQLite baselines table (idempotent / rerun-safe).
    4. Updates site_class in sites table.
    5. Updates metadata table.
    6. Exports output/exports/baselines.csv and refreshes output/exports/sites.csv.
    7. Runs comprehensive validation checks.
    """
    print("=" * 60)
    print("THERMOGRAPH Pipeline — Stage 6: Historical Baseline (T6)")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}. Run earlier stages first. Stopping.")
        sys.exit(1)

    conn = get_connection(DB_PATH)

    # 1. Compute baselines and classifications
    records, site_class_updates, df_baselines = compute_site_baselines(conn)

    # 2. Populate SQLite baselines table (safe to rerun)
    print("Populating SQLite 'baselines' table...")
    conn.execute("DELETE FROM baselines;")

    insert_sql = """
    INSERT INTO baselines (
        site_id, n_weeks, active_weeks, baseline_detections,
        frp_sum_mean, frp_sum_std, threshold, baseline_max_frp, established
    ) VALUES (
        :site_id, :n_weeks, :active_weeks, :baseline_detections,
        :frp_sum_mean, :frp_sum_std, :threshold, :baseline_max_frp, :established
    );
    """
    conn.executemany(insert_sql, records)

    # 3. Update site_class in sites table
    print("Updating 'site_class' in SQLite 'sites' table...")
    conn.executemany(
        "UPDATE sites SET site_class = ? WHERE site_id = ?;",
        site_class_updates,
    )
    conn.commit()

    # 4. Update metadata table
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n_established = int((df_baselines["established"] == 1).sum())
    set_metadata(conn, "baselines_count", str(len(records)))
    set_metadata(conn, "established_sites_count", str(n_established))
    set_metadata(conn, "stage_6_baselines_at_utc", now_iso)

    # 5. Export CSV files
    BASELINES_EXPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_baselines.to_csv(BASELINES_EXPORT_CSV, index=False)
    print(f"Exported baselines to {BASELINES_EXPORT_CSV} ({len(df_baselines):,} rows).")

    # Refresh sites.csv export with populated site_class
    sites_updated_df = pd.read_sql_query(
        "SELECT * FROM sites ORDER BY n_detections DESC, centroid_lat DESC;",
        conn,
    )
    sites_updated_df.to_csv(SITES_EXPORT_CSV, index=False)
    print(f"Refreshed {SITES_EXPORT_CSV} with updated site_class ({len(sites_updated_df):,} rows).")

    # 6. Run validation checks
    valid = validate_baselines(df_baselines, site_class_updates, conn)
    conn.close()

    if not valid:
        print("\n[FAIL] Stage 6 baseline validation checks failed!")
        sys.exit(1)

    # 7. Print summary metrics
    class_series = pd.Series([sc[0] for sc in site_class_updates])
    class_counts = class_series.value_counts().to_dict()

    print("\n" + "=" * 60)
    print("STAGE 6 BASELINE & CLASSIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total baseline rows:            {len(df_baselines):,}")
    print(f"Baseline weeks evaluated:       {len(BASELINE_WEEKS)} (weeks 0–38)")
    print(f"Established sites (weeks >= 10):{n_established:,} ({n_established / len(df_baselines) * 100:.1f}%)")
    print(f"Non-established sites:          {len(df_baselines) - n_established:,} ({(len(df_baselines) - n_established) / len(df_baselines) * 100:.1f}%)")
    print("\nSite Class Distribution:")
    for s_class in sorted(ALLOWED_SITE_CLASSES):
        count = class_counts.get(s_class, 0)
        pct = count / len(df_baselines) * 100
        print(f"  • {s_class:<24}: {count:>4} sites ({pct:>5.1f}%)")

    # Representative records
    print("\n" + "-" * 60)
    print("Representative Baseline Records:")
    print("-" * 60)
    rep_sites = ["TS-0001", "TS-0002", "TS-0004", "TS-0035", "TS-0568"]
    for sid in rep_sites:
        row = df_baselines[df_baselines["site_id"] == sid].iloc[0]
        s_cls = [sc[0] for sc in site_class_updates if sc[1] == sid][0]
        print(
            f"  • {sid}: class={s_cls:<22} active={row['active_weeks']:>2}/39, "
            f"dets={row['baseline_detections']:>4}, mean={row['frp_sum_mean']:>7.2f} MW, "
            f"std={row['frp_sum_std']:>7.2f} MW, thresh={row['threshold']:>8.2f} MW, "
            f"est={row['established']}"
        )
    print("=" * 60)
    print("Stage 6 successfully completed.")
    print("=" * 60)

    return df_baselines


if __name__ == "__main__":
    run_baselines()
