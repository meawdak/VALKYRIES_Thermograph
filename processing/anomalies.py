"""
THERMOGRAPH — Stage 7: Anomaly Detection, Priority Scoring, and Explanations
Detects thermal deviations in monitoring weeks (weeks 39–51: 31 Mar 2026 to 30 Jun 2026).
Applies rule-based detection against historical baselines established in Stage 6:
  - BASELINE_EXCEEDANCE: established=1, detection_count >= 2, frp_sum > threshold
  - NEW_ACTIVITY: baseline_detections=0, detection_count >= 2

Calculates priority scores (prototype settings), generates plain-English explanations,
updates site status as of 30 June 2026, and exports anomalies.csv.

Specification: PRD FR-14, FR-15, FR-16; TECH_SPEC §5.7, §6, §7; TASKS.md T7.
"""

import datetime
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    ANOMALIES_EXPORT_CSV,
    ANOMALY_MIN_DETECTIONS,
    DATASET_END,
    DB_PATH,
    LARGE_EXCEEDANCE_RATIO,
    MONITORING_WEEKS,
    NEW_ACTIVITY_MIN_DETECTIONS,
    PRIORITY_HIGH_MIN,
    PRIORITY_MEDIUM_MIN,
    PTS_BASELINE_EXCEEDANCE,
    PTS_FACILITY_MATCH,
    PTS_LARGE_EXCEEDANCE,
    PTS_NEW_ACTIVITY,
    PTS_RECORD_FRP,
    SITES_EXPORT_CSV,
)
from processing.db import get_connection, set_metadata

ALLOWED_SITE_STATUSES = {
    "HIGH",
    "MEDIUM",
    "LOW",
    "NORMAL",
    "INSUFFICIENT_HISTORY",
    "NEW_SITE_NO_ANOMALY",
}


def format_display_date(d_str: str) -> str:
    """
    Format ISO YYYY-MM-DD to plain date like '31 Mar 2026' or '1 Jul 2025'.
    Omits leading zero on the day to match TECH_SPEC §6 specification.
    """
    dt = datetime.date.fromisoformat(d_str)
    return f"{dt.day} {dt.strftime('%b %Y')}"


def generate_reasons_and_score(
    anomaly_type: str,
    detection_count: int,
    frp_sum: float,
    frp_max: float,
    threshold: Optional[float],
    ratio: Optional[float],
    frp_sum_mean: Optional[float],
    frp_sum_std: Optional[float],
    baseline_max_frp: Optional[float],
    week_start: str,
    week_end: str,
    match_type: str,
    match_distance_m: Optional[float],
    display_name: Optional[str],
    industrial: Optional[str],
    landuse: Optional[str],
) -> Tuple[int, str, List[str]]:
    """
    Compute priority score, priority level, and plain-English reasons list
    according to TECH_SPEC §6 and §7.
    """
    score = 0
    reasons: List[str] = []
    fmt_start = format_display_date(week_start)
    fmt_end = format_display_date(week_end)

    if anomaly_type == "BASELINE_EXCEEDANCE":
        # 1. Base points for exceedance
        score += PTS_BASELINE_EXCEEDANCE

        # Primary trigger explanation
        thresh_val = threshold if threshold is not None else 0.0
        mean_val = frp_sum_mean if frp_sum_mean is not None else 0.0
        std_val = frp_sum_std if frp_sum_std is not None else 0.0
        reasons.append(
            f"Weekly heat output {frp_sum:.1f} MW ({fmt_start}–{fmt_end}) exceeded this site's normal upper limit of {thresh_val:.1f} MW "
            f"(baseline average {mean_val:.1f} MW + 3 × variation {std_val:.1f} MW, from 39 weeks, 1 Jul 2025–30 Mar 2026)."
        )

        # 2. Record FRP
        prev_max = baseline_max_frp if baseline_max_frp is not None else 0.0
        if frp_max > prev_max:
            score += PTS_RECORD_FRP
            reasons.append(
                f"Strongest single detection this week ({frp_max:.1f} MW) is higher than anything seen here in the baseline period (previous highest {prev_max:.1f} MW)."
            )

        # 3. Large exceedance ratio >= 2.0
        rat_val = ratio if ratio is not None else (frp_sum / thresh_val if thresh_val > 0 else 0.0)
        if rat_val >= LARGE_EXCEEDANCE_RATIO:
            score += PTS_LARGE_EXCEEDANCE
            reasons.append(
                f"Heat output was {rat_val:.1f}× the normal upper limit."
            )

    elif anomaly_type == "NEW_ACTIVITY":
        # 1. Base points for new activity
        score += PTS_NEW_ACTIVITY

        # Primary trigger explanation
        reasons.append(
            f"No detections at this location during the 39-week baseline period; {detection_count} detections in the week {fmt_start}–{fmt_end}."
        )

    else:
        raise ValueError(f"Unknown anomaly type: {anomaly_type}")

    # Facility matching reason and points (applies to both types)
    if match_type in ("inside", "nearby"):
        score += PTS_FACILITY_MATCH

    # Facility reason formatting
    tag_text = ""
    if industrial and str(industrial).strip():
        tag_text = f" (industrial={industrial})"
    elif landuse and str(landuse).strip():
        tag_text = f" (landuse={landuse})"

    facility_name = display_name if display_name else "industrial facility"

    if match_type == "inside":
        reasons.append(
            f"Located inside mapped industrial facility: {facility_name}{tag_text}."
        )
    elif match_type == "nearby":
        dist_m = int(round(match_distance_m if match_distance_m is not None else 0.0))
        reasons.append(
            f"Located {dist_m} m from mapped industrial facility: {facility_name}{tag_text}."
        )
    else:
        reasons.append(
            "No mapped OSM industrial facility within 1 km — source needs manual verification."
        )

    # Priority level mapping
    if score >= PRIORITY_HIGH_MIN:
        priority = "HIGH"
    elif score >= PRIORITY_MEDIUM_MIN:
        priority = "MEDIUM"
    else:
        priority = "LOW"

    return score, priority, reasons


def compute_anomalies(conn: sqlite3.Connection) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Evaluate monitoring weeks (39–51) for all sites to identify anomalies
    and calculate status as of 30 June 2026 for all 568 thermal sites.
    """
    cursor = conn.cursor()

    min_mon_week = min(MONITORING_WEEKS)
    max_mon_week = max(MONITORING_WEEKS)

    # Query monitoring weekly data joined with baseline statistics, site metadata, and facility tags
    query = """
    SELECT
        w.site_id,
        w.week_index,
        w.week_start,
        w.week_end,
        w.detection_count,
        w.frp_sum,
        w.frp_max,
        b.n_weeks,
        b.active_weeks,
        b.baseline_detections,
        b.frp_sum_mean,
        b.frp_sum_std,
        b.threshold,
        b.baseline_max_frp,
        b.established,
        s.match_type,
        s.match_distance_m,
        s.facility_id,
        s.site_class,
        f.display_name,
        f.industrial,
        f.landuse
    FROM site_weekly w
    JOIN baselines b ON w.site_id = b.site_id
    JOIN sites s ON w.site_id = s.site_id
    LEFT JOIN facilities f ON s.facility_id = f.facility_id
    WHERE w.week_index >= ? AND w.week_index <= ?
      AND w.is_simulated = 0
    ORDER BY w.week_index ASC, w.site_id ASC;
    """
    cursor.execute(query, (min_mon_week, max_mon_week))
    monitoring_rows = cursor.fetchall()

    anomaly_records: List[Dict[str, Any]] = []
    # Track anomalies per site for site status evaluation: list of (score, frp_sum, priority)
    site_anomalies_map: Dict[str, List[Tuple[int, float, str]]] = {}

    for r in monitoring_rows:
        sid = r["site_id"]
        w_idx = r["week_index"]
        w_start = r["week_start"]
        w_end = r["week_end"]
        det_count = r["detection_count"]
        frp_sum = float(r["frp_sum"])
        frp_max = float(r["frp_max"])
        established = r["established"]
        baseline_dets = r["baseline_detections"]
        threshold = r["threshold"]

        anomaly_type: Optional[str] = None
        ratio: Optional[float] = None
        store_threshold: Optional[float] = None

        # Rule 1: BASELINE_EXCEEDANCE
        # established = 1, detection_count >= 2, frp_sum > threshold
        if established == 1 and det_count >= ANOMALY_MIN_DETECTIONS and frp_sum > threshold:
            anomaly_type = "BASELINE_EXCEEDANCE"
            store_threshold = round(threshold, 4)
            ratio = round(frp_sum / threshold, 4)

        # Rule 2: NEW_ACTIVITY
        # baseline_detections = 0, detection_count >= 2
        elif baseline_dets == 0 and det_count >= NEW_ACTIVITY_MIN_DETECTIONS:
            anomaly_type = "NEW_ACTIVITY"
            store_threshold = None
            ratio = None

        if anomaly_type is not None:
            score, priority, reasons = generate_reasons_and_score(
                anomaly_type=anomaly_type,
                detection_count=det_count,
                frp_sum=frp_sum,
                frp_max=frp_max,
                threshold=threshold,
                ratio=ratio,
                frp_sum_mean=r["frp_sum_mean"],
                frp_sum_std=r["frp_sum_std"],
                baseline_max_frp=r["baseline_max_frp"],
                week_start=w_start,
                week_end=w_end,
                match_type=r["match_type"],
                match_distance_m=r["match_distance_m"],
                display_name=r["display_name"],
                industrial=r["industrial"],
                landuse=r["landuse"],
            )

            record = {
                "site_id": sid,
                "week_index": w_idx,
                "week_start": w_start,
                "week_end": w_end,
                "anomaly_type": anomaly_type,
                "detection_count": det_count,
                "frp_sum": round(frp_sum, 4),
                "frp_max": round(frp_max, 2),
                "threshold": store_threshold,
                "ratio": ratio,
                "score": score,
                "priority": priority,
                "reasons": json.dumps(reasons),
                "is_simulated": 0,
            }
            anomaly_records.append(record)

            if sid not in site_anomalies_map:
                site_anomalies_map[sid] = []
            site_anomalies_map[sid].append((score, frp_sum, priority))

    # Evaluate site status as of 30 June 2026 across all sites in the sites table
    cursor.execute("""
    SELECT s.site_id, b.established, b.baseline_detections
    FROM sites s
    JOIN baselines b ON s.site_id = b.site_id
    ORDER BY s.site_id ASC;
    """)
    all_sites = cursor.fetchall()
    site_status_map: Dict[str, str] = {}

    for s in all_sites:
        sid = s["site_id"]
        est = s["established"]
        b_dets = s["baseline_detections"]

        if sid in site_anomalies_map and len(site_anomalies_map[sid]) > 0:
            # Sort anomalies by score DESC, then frp_sum DESC to pick highest-scoring anomaly
            # (ties broken by highest frp_sum)
            sorted_anoms = sorted(site_anomalies_map[sid], key=lambda x: (x[0], x[1]), reverse=True)
            top_priority = sorted_anoms[0][2]
            site_status_map[sid] = top_priority
        else:
            # No anomalies detected in monitoring period
            if est == 1:
                site_status_map[sid] = "NORMAL"
            elif b_dets == 0:
                site_status_map[sid] = "NEW_SITE_NO_ANOMALY"
            else:
                site_status_map[sid] = "INSUFFICIENT_HISTORY"

    return anomaly_records, site_status_map


def validate_anomalies_and_statuses(
    anomaly_records: List[Dict[str, Any]],
    site_status_map: Dict[str, str],
    conn: sqlite3.Connection,
) -> bool:
    """
    Run comprehensive internal validation checks before finalizing Stage 7.
    """
    print("-" * 60)
    print("Running Stage 7 internal validation checks...")
    print("-" * 60)
    checks_passed = True
    cursor = conn.cursor()

    # 1. Total anomalies count and breakdown
    n_total = len(anomaly_records)
    be_records = [r for r in anomaly_records if r["anomaly_type"] == "BASELINE_EXCEEDANCE"]
    na_records = [r for r in anomaly_records if r["anomaly_type"] == "NEW_ACTIVITY"]

    print(f"Total anomaly records generated: {n_total:,}")
    print(f"  • BASELINE_EXCEEDANCE: {len(be_records):,}")
    print(f"  • NEW_ACTIVITY:        {len(na_records):,}")

    if len(be_records) != 14:
        print(f"[FAIL] Expected exactly 14 BASELINE_EXCEEDANCE records, found {len(be_records)}.")
        checks_passed = False
    else:
        print("[PASS] Exactly 14 BASELINE_EXCEEDANCE records verified.")

    if len(na_records) != 146:
        print(f"[FAIL] Expected exactly 146 NEW_ACTIVITY records, found {len(na_records)}.")
        checks_passed = False
    else:
        print("[PASS] Exactly 146 NEW_ACTIVITY records verified.")

    # 2. Distinct anomalous sites
    distinct_be_sites = set(r["site_id"] for r in be_records)
    distinct_na_sites = set(r["site_id"] for r in na_records)
    all_anom_sites = set(r["site_id"] for r in anomaly_records)

    print(f"Distinct anomalous sites: {len(all_anom_sites):,} (exceedance: {len(distinct_be_sites)}, new: {len(distinct_na_sites)})")
    if len(distinct_be_sites) != 10:
        print(f"[FAIL] Expected 10 distinct sites with BASELINE_EXCEEDANCE, found {len(distinct_be_sites)}.")
        checks_passed = False
    else:
        print("[PASS] Exactly 10 distinct sites with BASELINE_EXCEEDANCE.")

    if len(distinct_na_sites) != 113:
        print(f"[FAIL] Expected 113 distinct sites with NEW_ACTIVITY, found {len(distinct_na_sites)}.")
        checks_passed = False
    else:
        print("[PASS] Exactly 113 distinct sites with NEW_ACTIVITY.")

    # 3. Validate scoring and priority invariants for each record
    cursor.execute("SELECT site_id, baseline_max_frp, threshold, established, baseline_detections FROM baselines;")
    baselines_dict = {r["site_id"]: dict(r) for r in cursor.fetchall()}
    cursor.execute("SELECT site_id, match_type FROM sites;")
    sites_dict = {r["site_id"]: dict(r) for r in cursor.fetchall()}

    scoring_errors = []
    for r in anomaly_records:
        sid = r["site_id"]
        b_info = baselines_dict.get(sid, {})
        s_info = sites_dict.get(sid, {})

        # Recompute score
        if r["anomaly_type"] == "BASELINE_EXCEEDANCE":
            exp_score = PTS_BASELINE_EXCEEDANCE
            if r["frp_max"] > b_info.get("baseline_max_frp", 0.0):
                exp_score += PTS_RECORD_FRP
            if r["ratio"] is not None and r["ratio"] >= LARGE_EXCEEDANCE_RATIO:
                exp_score += PTS_LARGE_EXCEEDANCE
            if s_info.get("match_type") in ("inside", "nearby"):
                exp_score += PTS_FACILITY_MATCH
        elif r["anomaly_type"] == "NEW_ACTIVITY":
            exp_score = PTS_NEW_ACTIVITY
            if s_info.get("match_type") in ("inside", "nearby"):
                exp_score += PTS_FACILITY_MATCH
        else:
            scoring_errors.append(f"{sid}: unknown type {r['anomaly_type']}")
            continue

        if r["score"] != exp_score:
            scoring_errors.append(f"{sid} wk {r['week_index']}: score={r['score']} != {exp_score}")

        exp_prio = "HIGH" if exp_score >= PRIORITY_HIGH_MIN else ("MEDIUM" if exp_score >= PRIORITY_MEDIUM_MIN else "LOW")
        if r["priority"] != exp_prio:
            scoring_errors.append(f"{sid} wk {r['week_index']}: prio={r['priority']} != {exp_prio}")

        # Check reasons
        try:
            parsed_reasons = json.loads(r["reasons"])
            if not isinstance(parsed_reasons, list) or len(parsed_reasons) < 1:
                scoring_errors.append(f"{sid} wk {r['week_index']}: invalid reasons list")
            if any(not isinstance(s, str) or len(s.strip()) == 0 for s in parsed_reasons):
                scoring_errors.append(f"{sid} wk {r['week_index']}: empty or non-string reason")
        except Exception as e:
            scoring_errors.append(f"{sid} wk {r['week_index']}: json decode error: {e}")

    if scoring_errors:
        print(f"[FAIL] Scoring/priority/reason errors found: {scoring_errors[:5]}")
        checks_passed = False
    else:
        print("[PASS] All 160 anomaly records have verified scores, priorities, and JSON reasons.")

    # 4. Check site status coverage and invariants
    cursor.execute("SELECT COUNT(*) FROM sites;")
    total_sites = cursor.fetchone()[0]
    if len(site_status_map) != total_sites:
        print(f"[FAIL] Status map contains {len(site_status_map)} sites, expected {total_sites}.")
        checks_passed = False
    else:
        print(f"[PASS] All {total_sites} sites have assigned statuses.")

    invalid_statuses = [s for s in site_status_map.values() if s not in ALLOWED_SITE_STATUSES]
    if invalid_statuses:
        print(f"[FAIL] Found invalid statuses: {set(invalid_statuses)}")
        checks_passed = False
    else:
        print("[PASS] All site statuses belong to the allowed specification set.")

    # 5. Check persistent industrial sites status (at least one must be NORMAL)
    cursor.execute("""
    SELECT s.site_id, f.display_name, s.status
    FROM sites s
    LEFT JOIN facilities f ON s.facility_id = f.facility_id
    WHERE s.site_class = 'PERSISTENT_INDUSTRIAL';
    """)
    pi_sites = cursor.fetchall()
    pi_statuses = [site_status_map.get(r["site_id"]) for r in pi_sites]
    n_normal_pi = sum(1 for st in pi_statuses if st == "NORMAL")

    print(f"PERSISTENT_INDUSTRIAL sites ({len(pi_sites)} total) status breakdown:")
    for r in pi_sites:
        st = site_status_map.get(r["site_id"])
        print(f"  • {r['site_id']}: status={st} ({r['display_name']})")

    if n_normal_pi >= 1:
        print(f"[PASS] Found {n_normal_pi} PERSISTENT_INDUSTRIAL site(s) with status NORMAL (satisfies demo requirement).")
    else:
        print("[FAIL] No PERSISTENT_INDUSTRIAL sites have status NORMAL.")
        checks_passed = False

    print("-" * 60)
    return checks_passed


def run_anomalies() -> pd.DataFrame:
    """
    Main execution of Stage 7 Anomaly Detection:
    1. Connects to SQLite thermograph.db.
    2. Identifies anomalies in monitoring weeks 39–51.
    3. Populates SQLite anomalies table (idempotent / rerun-safe).
    4. Updates status in sites table.
    5. Updates metadata table.
    6. Exports output/exports/anomalies.csv and refreshes output/exports/sites.csv.
    7. Runs comprehensive validation checks.
    """
    print("=" * 60)
    print("THERMOGRAPH Pipeline — Stage 7: Anomaly Detection (T7)")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}. Run earlier stages first. Stopping.")
        sys.exit(1)

    conn = get_connection(DB_PATH)

    # 1. Compute anomalies and site statuses
    anomaly_records, site_status_map = compute_anomalies(conn)

    # 2. Populate SQLite anomalies table (safe to rerun)
    print("Populating SQLite 'anomalies' table...")
    conn.execute("DELETE FROM anomalies WHERE is_simulated = 0;")

    insert_sql = """
    INSERT INTO anomalies (
        site_id, week_index, week_start, week_end, anomaly_type,
        detection_count, frp_sum, frp_max, threshold, ratio,
        score, priority, reasons, is_simulated
    ) VALUES (
        :site_id, :week_index, :week_start, :week_end, :anomaly_type,
        :detection_count, :frp_sum, :frp_max, :threshold, :ratio,
        :score, :priority, :reasons, :is_simulated
    );
    """
    conn.executemany(insert_sql, anomaly_records)

    # 3. Update status in sites table
    print("Updating 'status' in SQLite 'sites' table...")
    status_updates = [(status, sid) for sid, status in site_status_map.items()]
    conn.executemany(
        "UPDATE sites SET status = ? WHERE site_id = ?;",
        status_updates,
    )
    conn.commit()

    # 4. Update metadata table
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n_be = sum(1 for r in anomaly_records if r["anomaly_type"] == "BASELINE_EXCEEDANCE")
    n_na = sum(1 for r in anomaly_records if r["anomaly_type"] == "NEW_ACTIVITY")

    set_metadata(conn, "anomalies_count", str(len(anomaly_records)))
    set_metadata(conn, "anomalies_baseline_exceedance_count", str(n_be))
    set_metadata(conn, "anomalies_new_activity_count", str(n_na))
    set_metadata(conn, "stage_7_anomalies_at_utc", now_iso)

    # 5. Export CSV files
    ANOMALIES_EXPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_anomalies = pd.read_sql_query(
        "SELECT * FROM anomalies WHERE is_simulated = 0 ORDER BY anomaly_id ASC;",
        conn,
    )
    df_anomalies.to_csv(ANOMALIES_EXPORT_CSV, index=False)
    print(f"Exported anomalies to {ANOMALIES_EXPORT_CSV} ({len(df_anomalies):,} rows).")

    # Refresh sites.csv export with populated status
    sites_updated_df = pd.read_sql_query(
        "SELECT * FROM sites ORDER BY n_detections DESC, centroid_lat DESC;",
        conn,
    )
    sites_updated_df.to_csv(SITES_EXPORT_CSV, index=False)
    print(f"Refreshed {SITES_EXPORT_CSV} with updated status ({len(sites_updated_df):,} rows).")

    # 6. Run validation checks
    valid = validate_anomalies_and_statuses(anomaly_records, site_status_map, conn)
    conn.close()

    if not valid:
        print("\n[FAIL] Stage 7 anomaly validation checks failed!")
        sys.exit(1)

    # 7. Print summary metrics
    status_counts = pd.Series(list(site_status_map.values())).value_counts().to_dict()
    priority_counts = df_anomalies["priority"].value_counts().to_dict()
    type_counts = df_anomalies["anomaly_type"].value_counts().to_dict()

    print("\n" + "=" * 60)
    print("STAGE 7 ANOMALY DETECTION SUMMARY")
    print("=" * 60)
    print(f"Monitoring weeks evaluated:     {len(MONITORING_WEEKS)} (weeks 39–51, 31 Mar–30 Jun 2026)")
    print(f"Total anomaly records:          {len(df_anomalies):,}")
    print("\nAnomalies by Type:")
    for a_type, count in type_counts.items():
        print(f"  • {a_type:<24}: {count:>4} records")

    print("\nAnomalies by Priority:")
    for prio, count in priority_counts.items():
        print(f"  • {prio:<24}: {count:>4} records")

    print(f"\nSite Status as of {DATASET_END} (568 sites):")
    for st in ["HIGH", "MEDIUM", "LOW", "NORMAL", "INSUFFICIENT_HISTORY", "NEW_SITE_NO_ANOMALY"]:
        count = status_counts.get(st, 0)
        pct = count / len(site_status_map) * 100
        print(f"  • {st:<24}: {count:>4} sites ({pct:>5.1f}%)")

    # Representative anomaly records
    print("\n" + "-" * 60)
    print("Representative Anomaly Records (with reasons):")
    print("-" * 60)
    sample_be = df_anomalies[df_anomalies["anomaly_type"] == "BASELINE_EXCEEDANCE"].head(2)
    sample_na = df_anomalies[df_anomalies["anomaly_type"] == "NEW_ACTIVITY"].head(2)
    sample_df = pd.concat([sample_be, sample_na])

    for _, row in sample_df.iterrows():
        reasons_list = json.loads(row["reasons"])
        print(f"\nSite {row['site_id']} | Week {row['week_index']} ({row['week_start']} to {row['week_end']}):")
        print(f"  Type: {row['anomaly_type']} | Score: {row['score']} | Priority: {row['priority']}")
        print(f"  Detections: {row['detection_count']} | FRP Sum: {row['frp_sum']} MW | FRP Max: {row['frp_max']} MW")
        if row["threshold"] is not None:
            print(f"  Threshold: {row['threshold']} MW | Ratio: {row['ratio']}x")
        print("  Reasons:")
        for r_txt in reasons_list:
            print(f"    - {r_txt}")

    print("=" * 60)
    print("Stage 7 successfully completed.")
    print("=" * 60)

    return df_anomalies


if __name__ == "__main__":
    run_anomalies()
