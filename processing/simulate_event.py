"""
THERMOGRAPH — Stage 8: Simulated Demo Event (T9)
Generates a transparent, clearly labelled simulated thermal event for demonstration purposes.

Rules:
1. Automatically selects target site using:
   - site_class = 'PERSISTENT_INDUSTRIAL'
   - status = 'NORMAL'
   - highest active_weeks
   - if tied, highest detections
   (Algorithmically selects TS-0001 ArcelorMittal without hardcoding).
2. Generates exactly SIM_N_DETECTIONS (12) detections in week 52 (1–7 Jul 2026, night-time).
3. Located at centroid plus deterministic random jitter <= SIM_JITTER_M (200 m) using SIM_SEED (42).
4. Each FRP = baseline_max_frp * SIM_FRP_MULTIPLIER (1.5).
5. Saves to output/simulated/simulated_detections.csv.
6. Inserts into detections with is_simulated = 1.
7. Inserts into site_weekly for week 52 with period = 'simulated', is_simulated = 1.
8. Runs Stage 7 scoring on week 52; stores anomaly in anomalies with is_simulated = 1
   and every reason prefixed with '[SIMULATED] '.
9. Real site status (NORMAL) remains unchanged. Real baselines and monitoring data unaffected.
10. Refreshes output/exports/anomalies.csv with the labelled simulated row.

Specifications: PRD FR-27 through FR-30; TECH_SPEC §5.8; TASKS.md T9.
"""

import datetime
import json
import math
import random
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
    DB_PATH,
    NEW_ACTIVITY_MIN_DETECTIONS,
    SIM_CSV,
    SIM_FRP_MULTIPLIER,
    SIM_JITTER_M,
    SIM_N_DETECTIONS,
    SIM_SEED,
    SIM_WEEK,
)
from processing.db import get_connection, set_metadata
from processing.anomalies import format_display_date, generate_reasons_and_score


def select_simulation_target(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Select the demonstration target site algorithmically:
      1. site_class = 'PERSISTENT_INDUSTRIAL'
      2. status = 'NORMAL'
      3. highest active_weeks
      4. if tied, highest n_detections
      5. if tied, higher centroid latitude
    """
    cursor = conn.cursor()
    query = """
    SELECT
        s.site_id,
        s.centroid_lat,
        s.centroid_lon,
        s.n_detections,
        s.site_class,
        s.status,
        s.match_type,
        s.match_distance_m,
        s.facility_id,
        b.active_weeks,
        b.baseline_max_frp,
        b.threshold,
        b.frp_sum_mean,
        b.frp_sum_std,
        b.established,
        b.baseline_detections,
        f.display_name,
        f.industrial,
        f.landuse
    FROM sites s
    JOIN baselines b ON s.site_id = b.site_id
    LEFT JOIN facilities f ON s.facility_id = f.facility_id
    WHERE s.site_class = 'PERSISTENT_INDUSTRIAL'
      AND s.status = 'NORMAL'
    ORDER BY b.active_weeks DESC, s.n_detections DESC, s.centroid_lat DESC
    LIMIT 1;
    """
    cursor.execute(query)
    row = cursor.fetchone()

    if not row:
        print("[FAIL] No PERSISTENT_INDUSTRIAL site with status NORMAL found for simulation. Stopping.")
        sys.exit(1)

    target = dict(row)
    print(f"Selected simulation target: {target['site_id']} ({target['display_name']})")
    print(
        f"  Criteria: class={target['site_class']}, status={target['status']}, "
        f"active_weeks={target['active_weeks']}, detections={target['n_detections']:,}, "
        f"baseline_max_frp={target['baseline_max_frp']} MW, threshold={target['threshold']} MW"
    )
    return target


def generate_simulated_detections(
    target: Dict[str, Any], conn: sqlite3.Connection
) -> List[Dict[str, Any]]:
    """
    Generate exactly SIM_N_DETECTIONS deterministic night detections in week 52
    (1–7 Jul 2026) within SIM_JITTER_M of the target centroid.
    """
    rng = random.Random(SIM_SEED)
    c_lat = float(target["centroid_lat"])
    c_lon = float(target["centroid_lon"])

    # Determine next detection_id (preserving real detections)
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(detection_id), 0) FROM detections WHERE is_simulated = 0;")
    max_real_id = cursor.fetchone()[0]

    # FRP for each detection = baseline_max_frp * SIM_FRP_MULTIPLIER
    base_max = float(target["baseline_max_frp"])
    sim_frp = round(base_max * SIM_FRP_MULTIPLIER, 2)

    # Spread 12 detections across week 52 (1 Jul to 7 Jul 2026, night passes)
    # Using deterministic schedule in July 2026
    sim_schedule = [
        ("2026-07-01", "2045"),
        ("2026-07-01", "2215"),
        ("2026-07-02", "2115"),
        ("2026-07-02", "2230"),
        ("2026-07-03", "2050"),
        ("2026-07-03", "2220"),
        ("2026-07-04", "2130"),
        ("2026-07-04", "2245"),
        ("2026-07-05", "2110"),
        ("2026-07-05", "2210"),
        ("2026-07-06", "2105"),
        ("2026-07-07", "2120"),
    ]

    detections = []
    for i in range(SIM_N_DETECTIONS):
        date_str, time_str = sim_schedule[i % len(sim_schedule)]

        # Deterministic spatial offset within SIM_JITTER_M metres
        dist_m = rng.uniform(25.0, float(SIM_JITTER_M))
        angle_rad = rng.uniform(0.0, 2.0 * math.pi)
        dx_m = dist_m * math.cos(angle_rad)
        dy_m = dist_m * math.sin(angle_rad)

        # Convert metres to coordinate degrees
        dlat = dy_m / 111320.0
        dlon = dx_m / (111320.0 * math.cos(math.radians(c_lat)))
        sim_lat = round(c_lat + dlat, 5)
        sim_lon = round(c_lon + dlon, 5)

        det_record = {
            "detection_id": max_real_id + i + 1,
            "latitude": sim_lat,
            "longitude": sim_lon,
            "acq_date": date_str,
            "acq_time": time_str,
            "acq_datetime_utc": f"{date_str}T{time_str[:2]}:{time_str[2:]}:00Z",
            "week_index": SIM_WEEK,
            "frp": sim_frp,
            "bright_ti4": 365.2,
            "bright_ti5": 293.4,
            "scan": 0.38,
            "track": 0.36,
            "confidence": "nominal",
            "satellite": "N",
            "instrument": "VIIRS",
            "version": "2",
            "daynight": "N",
            "type": 2,
            "source_file": "simulated",
            "site_id": target["site_id"],
            "is_simulated": 1,
        }
        detections.append(det_record)

    return detections


def run_simulation() -> None:
    """
    Main execution of Stage 8 Simulated Demo Event:
    1. Select demonstration target algorithmically.
    2. Generate deterministic simulated detections.
    3. Save to output/simulated/simulated_detections.csv.
    4. Insert into detections, site_weekly, anomalies.
    5. Refresh output/exports/anomalies.csv with the labelled simulated row.
    6. Ensure real baselines, counts, and statuses remain completely untouched.
    """
    print("=" * 60)
    print("THERMOGRAPH Pipeline — Stage 8: Simulated Demo Event (T9)")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}. Run earlier stages first. Stopping.")
        sys.exit(1)

    conn = get_connection(DB_PATH)

    # 1. Select target site
    target = select_simulation_target(conn)
    sid = target["site_id"]

    # 2. Generate simulated detections
    sim_detections = generate_simulated_detections(target, conn)
    sim_frp = sim_detections[0]["frp"]
    sim_frp_sum = round(sum(d["frp"] for d in sim_detections), 4)
    sim_frp_max = max(d["frp"] for d in sim_detections)

    print(f"Generated {len(sim_detections)} simulated detections for {sid}:")
    print(f"  FRP per detection: {sim_frp} MW (baseline_max_frp {target['baseline_max_frp']} × {SIM_FRP_MULTIPLIER})")
    print(f"  Total weekly FRP:  {sim_frp_sum} MW (across {len(sim_detections)} night detections)")

    # 3. Export to output/simulated/simulated_detections.csv
    SIM_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_sim = pd.DataFrame(sim_detections)
    df_sim.to_csv(SIM_CSV, index=False)
    print(f"Exported simulated detections to {SIM_CSV} ({len(df_sim)} rows).")

    # 4. Clean previous simulated rows for idempotency
    conn.execute("DELETE FROM detections WHERE is_simulated = 1;")
    conn.execute("DELETE FROM site_weekly WHERE is_simulated = 1;")
    conn.execute("DELETE FROM anomalies WHERE is_simulated = 1;")

    # 5. Insert simulated detections into SQLite detections table
    insert_det_sql = """
    INSERT INTO detections (
        detection_id, latitude, longitude, acq_date, acq_time, acq_datetime_utc,
        week_index, frp, bright_ti4, bright_ti5, scan, track, confidence,
        satellite, instrument, version, daynight, type, source_file, site_id, is_simulated
    ) VALUES (
        :detection_id, :latitude, :longitude, :acq_date, :acq_time, :acq_datetime_utc,
        :week_index, :frp, :bright_ti4, :bright_ti5, :scan, :track, :confidence,
        :satellite, :instrument, :version, :daynight, :type, :source_file, :site_id, :is_simulated
    );
    """
    conn.executemany(insert_det_sql, sim_detections)

    # 6. Insert simulated weekly history record into site_weekly
    week_start = "2026-07-01"
    week_end = "2026-07-07"
    site_weekly_record = {
        "site_id": sid,
        "week_index": SIM_WEEK,
        "week_start": week_start,
        "week_end": week_end,
        "period": "simulated",
        "detection_count": len(sim_detections),
        "frp_sum": sim_frp_sum,
        "frp_max": sim_frp_max,
        "night_count": len(sim_detections),
        "is_simulated": 1,
    }
    insert_weekly_sql = """
    INSERT INTO site_weekly (
        site_id, week_index, week_start, week_end, period,
        detection_count, frp_sum, frp_max, night_count, is_simulated
    ) VALUES (
        :site_id, :week_index, :week_start, :week_end, :period,
        :detection_count, :frp_sum, :frp_max, :night_count, :is_simulated
    );
    """
    conn.execute(insert_weekly_sql, site_weekly_record)

    # 7. Evaluate simulated week using the exact same Stage 7 anomaly detection rules
    thresh = float(target["threshold"])
    det_count = len(sim_detections)
    est = target["established"]
    baseline_dets = target["baseline_detections"]

    anomaly_type = None
    ratio = None
    store_threshold = None

    # Stage 7 Rule 1: BASELINE_EXCEEDANCE
    # established = 1, detection_count >= 2, frp_sum > threshold
    if est == 1 and det_count >= ANOMALY_MIN_DETECTIONS and sim_frp_sum > thresh:
        anomaly_type = "BASELINE_EXCEEDANCE"
        store_threshold = round(thresh, 4)
        ratio = round(sim_frp_sum / thresh, 4)
    # Stage 7 Rule 2: NEW_ACTIVITY
    # baseline_detections = 0, detection_count >= 2
    elif baseline_dets == 0 and det_count >= NEW_ACTIVITY_MIN_DETECTIONS:
        anomaly_type = "NEW_ACTIVITY"
        store_threshold = None
        ratio = None

    # Fail clearly if the simulated event does not satisfy the anomaly condition
    if anomaly_type is None:
        print(
            f"[FAIL] Simulated week 52 did not satisfy Stage 7 anomaly conditions! "
            f"(established={est}, detections={det_count}, frp_sum={sim_frp_sum:.1f} MW, threshold={thresh:.1f} MW). Stopping."
        )
        sys.exit(1)

    raw_score, raw_priority, raw_reasons = generate_reasons_and_score(
        anomaly_type=anomaly_type,
        detection_count=det_count,
        frp_sum=sim_frp_sum,
        frp_max=sim_frp_max,
        threshold=store_threshold,
        ratio=ratio,
        frp_sum_mean=float(target["frp_sum_mean"]),
        frp_sum_std=float(target["frp_sum_std"]),
        baseline_max_frp=float(target["baseline_max_frp"]),
        week_start=week_start,
        week_end=week_end,
        match_type=target["match_type"],
        match_distance_m=target["match_distance_m"],
        display_name=target["display_name"],
        industrial=target["industrial"],
        landuse=target["landuse"],
    )

    # Prefix EVERY reason with [SIMULATED] per scientific rules
    simulated_reasons = [f"[SIMULATED] {r}" for r in raw_reasons]

    anomaly_record = {
        "site_id": sid,
        "week_index": SIM_WEEK,
        "week_start": week_start,
        "week_end": week_end,
        "anomaly_type": anomaly_type,
        "detection_count": det_count,
        "frp_sum": sim_frp_sum,
        "frp_max": sim_frp_max,
        "threshold": store_threshold,
        "ratio": ratio,
        "score": raw_score,
        "priority": raw_priority,
        "reasons": json.dumps(simulated_reasons),
        "is_simulated": 1,
    }
    insert_anom_sql = """
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
    conn.execute(insert_anom_sql, anomaly_record)
    conn.commit()

    # 8. Update metadata table
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    set_metadata(conn, "simulated_target_site_id", sid)
    set_metadata(conn, "simulated_detections_count", str(len(sim_detections)))
    set_metadata(conn, "stage_8_simulation_at_utc", now_iso)

    # 9. Refresh output/exports/anomalies.csv to include the labelled simulated row
    df_all_anomalies = pd.read_sql_query(
        "SELECT * FROM anomalies ORDER BY is_simulated ASC, anomaly_id ASC;",
        conn,
    )
    df_all_anomalies.to_csv(ANOMALIES_EXPORT_CSV, index=False)
    print(f"Refreshed {ANOMALIES_EXPORT_CSV} ({len(df_all_anomalies)} rows: 160 real + 1 simulated).")

    conn.close()

    # 10. Summary report
    print("\n" + "=" * 60)
    print("STAGE 8 SIMULATION SUMMARY")
    print("=" * 60)
    print(f"Target site selected:       {sid} ({target['display_name']})")
    print(f"Site class:                 {target['site_class']}")
    print(f"Real site status preserved: {target['status']} (NORMAL)")
    print(f"Simulation week:            Week {SIM_WEEK} ({week_start} to {week_end})")
    print(f"Simulated detections:       {len(sim_detections)}")
    print(f"Simulated FRP per det:      {sim_frp} MW")
    print(f"Simulated anomaly score:    {raw_score} (Priority: {raw_priority})")
    print("Simulated Reasons:")
    for r in simulated_reasons:
        print(f"  • {r}")
    print("=" * 60)
    print("Stage 8 successfully completed.")
    print("=" * 60)


if __name__ == "__main__":
    run_simulation()
