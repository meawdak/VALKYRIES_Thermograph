"""
THERMOGRAPH — Stage 2: Spatial Clustering of Detections into Thermal Sites
Clusters real FIRMS detections into candidate thermal sites using DBSCAN
with Haversine distance metric. Assigns persistent site IDs (TS-0001, etc.)
ordered by detection count descending. Populates the sites table, updates
detections with site_id, records legacy comparison metadata, and exports
sites.csv and updated detections.csv.

Specifications implemented: TECH_SPEC §5.2, PRD FR-05 through FR-10.
"""

import datetime
import sqlite3
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    CLUSTER_EPS_KM,
    CLUSTER_MIN_SAMPLES,
    DB_PATH,
    EARTH_RADIUS_KM,
    EXPECTED_DETECTIONS,
    EXPORT_DIR,
    LEGACY_SITES_CSV,
    SITE_EXTENT_REVIEW_KM,
)
from processing.db import get_connection, set_metadata


def haversine_distance_km(lat1: float, lon1: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """
    Compute great-circle (Haversine) distances in kilometres from a single point
    (lat1, lon1) in degrees to arrays of points (lats, lons) in degrees.
    """
    phi1 = np.radians(lat1)
    phi2 = np.radians(lats)
    dphi = phi2 - phi1
    dlambda = np.radians(lons - lon1)

    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    c = 2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))
    return EARTH_RADIUS_KM * c


def run_clustering() -> None:
    """
    Main function executing Stage 2 clustering:
    1. Read real detections from SQLite.
    2. Cluster with DBSCAN (haversine, ball_tree).
    3. Order clusters by detection count descending (ties: higher centroid lat first).
    4. Compute site attributes: centroid, extent_km, active_weeks, night/static fractions, etc.
    5. Populate sites table in SQLite and update detections.site_id.
    6. Record comparison metadata and export CSV files.
    """
    print("=" * 60)
    print("THERMOGRAPH Pipeline — Stage 2: Cluster Sites")
    print("=" * 60)

    # 1. Connect to SQLite database
    if not DB_PATH.exists():
        print(f"Error: Database file not found at {DB_PATH}. Run Stage 1 first. Stopping.")
        sys.exit(1)

    conn = get_connection(DB_PATH)

    # 2. Fetch all real detections ordered deterministically by detection_id
    query = """
    SELECT
        detection_id, latitude, longitude, acq_date, acq_time,
        acq_datetime_utc, week_index, frp, bright_ti4, bright_ti5,
        scan, track, confidence, satellite, instrument, version,
        daynight, type, source_file, is_simulated
    FROM detections
    WHERE is_simulated = 0
    ORDER BY detection_id ASC;
    """
    detections_df = pd.read_sql_query(query, conn)
    total_detections = len(detections_df)
    print(f"Loaded {total_detections:,} real detections from database.")

    if total_detections != EXPECTED_DETECTIONS:
        print(f"Expected {EXPECTED_DETECTIONS:,} detections, found {total_detections:,}. Stopping.")
        conn.close()
        sys.exit(1)

    # 3. Convert coordinates to radians for Haversine DBSCAN
    coords_deg = detections_df[["latitude", "longitude"]].to_numpy()
    coords_rad = np.radians(coords_deg)

    # 4. Configure and run DBSCAN
    # eps in radians = radius_in_km / earth_radius_in_km
    eps_rad = CLUSTER_EPS_KM / EARTH_RADIUS_KM
    print(
        f"Running DBSCAN: eps={CLUSTER_EPS_KM} km ({eps_rad:.8f} rad), "
        f"min_samples={CLUSTER_MIN_SAMPLES}, metric=haversine, algorithm=ball_tree..."
    )

    dbscan = DBSCAN(
        eps=eps_rad,
        min_samples=CLUSTER_MIN_SAMPLES,
        metric="haversine",
        algorithm="ball_tree",
    )
    cluster_labels = dbscan.fit_predict(coords_rad)
    detections_df["raw_cluster_id"] = cluster_labels

    # 5. Separate clustered detections from isolated (noise) detections
    clustered_mask = detections_df["raw_cluster_id"] != -1
    clustered_df = detections_df[clustered_mask].copy()
    noise_df = detections_df[~clustered_mask].copy()

    n_assigned = len(clustered_df)
    n_isolated = len(noise_df)
    raw_cluster_count = clustered_df["raw_cluster_id"].nunique()

    print(f"Clustering complete:")
    print(f"  - Total detections:     {total_detections:,}")
    print(f"  - Assigned detections:  {n_assigned:,}")
    print(f"  - Isolated detections:  {n_isolated:,}")
    print(f"  - Candidate sites:      {raw_cluster_count:,}")

    # Consistency check: assigned + isolated must equal total
    if n_assigned + n_isolated != total_detections:
        print(
            f"Error: Assigned ({n_assigned}) + Isolated ({n_isolated}) != Total ({total_detections}). Stopping."
        )
        conn.close()
        sys.exit(1)

    # 6. Group clusters to calculate preliminary counts and centroids for ordering
    cluster_summary = (
        clustered_df.groupby("raw_cluster_id")
        .agg(
            n_detections=("detection_id", "count"),
            centroid_lat=("latitude", "mean"),
            centroid_lon=("longitude", "mean"),
        )
        .reset_index()
    )

    # Order clusters by detection count descending; break ties with higher centroid latitude
    cluster_summary = cluster_summary.sort_values(
        by=["n_detections", "centroid_lat"],
        ascending=[False, False],
    ).reset_index(drop=True)

    # Assign persistent site IDs: TS-0001, TS-0002, ...
    cluster_summary["site_id"] = [f"TS-{i + 1:04d}" for i in range(len(cluster_summary))]

    # Map raw_cluster_id to persistent site_id
    raw_to_site_id = dict(zip(cluster_summary["raw_cluster_id"], cluster_summary["site_id"]))
    clustered_df["site_id"] = clustered_df["raw_cluster_id"].map(raw_to_site_id)
    detections_df["site_id"] = detections_df["raw_cluster_id"].map(raw_to_site_id)

    # 7. Compute full site-level metrics
    print("Computing site statistics and spatial extents...")
    site_records = []
    large_extent_sites = []

    for _, site_row in cluster_summary.iterrows():
        sid = site_row["site_id"]
        c_lat = float(site_row["centroid_lat"])
        c_lon = float(site_row["centroid_lon"])
        n_dets = int(site_row["n_detections"])

        # Member detections for this site
        members = clustered_df[clustered_df["site_id"] == sid]

        # Calculate spatial extent: max distance from centroid to any member * 2
        member_lats = members["latitude"].to_numpy()
        member_lons = members["longitude"].to_numpy()
        distances_to_centroid = haversine_distance_km(c_lat, c_lon, member_lats, member_lons)
        extent_km = float(2.0 * np.max(distances_to_centroid))

        if extent_km > SITE_EXTENT_REVIEW_KM:
            large_extent_sites.append((sid, n_dets, extent_km, c_lat, c_lon))

        # Temporal metrics
        first_seen = str(members["acq_date"].min())
        last_seen = str(members["acq_date"].max())
        active_weeks_total = int(members["week_index"].nunique())

        # Proportions and FRP stats
        night_fraction = float((members["daynight"] == "N").mean())
        static_type_fraction = float((members["type"] == 2).mean())
        mean_frp = float(members["frp"].mean())
        max_frp = float(members["frp"].max())

        site_records.append(
            {
                "site_id": sid,
                "centroid_lat": c_lat,
                "centroid_lon": c_lon,
                "extent_km": extent_km,
                "n_detections": n_dets,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "active_weeks_total": active_weeks_total,
                "night_fraction": night_fraction,
                "static_type_fraction": static_type_fraction,
                "mean_frp": mean_frp,
                "max_frp": max_frp,
                "facility_id": None,
                "match_type": None,
                "match_distance_m": None,
                "site_class": None,
                "status": None,
            }
        )

    sites_df = pd.DataFrame(site_records)

    # 8. Update SQLite database
    print(f"Storing {len(sites_df)} sites into SQLite 'sites' table...")
    # Clear existing rows in sites table before inserting
    conn.execute("DELETE FROM sites;")

    insert_sites_sql = """
    INSERT INTO sites (
        site_id, centroid_lat, centroid_lon, extent_km, n_detections,
        first_seen, last_seen, active_weeks_total, night_fraction,
        static_type_fraction, mean_frp, max_frp, facility_id,
        match_type, match_distance_m, site_class, status
    ) VALUES (
        :site_id, :centroid_lat, :centroid_lon, :extent_km, :n_detections,
        :first_seen, :last_seen, :active_weeks_total, :night_fraction,
        :static_type_fraction, :mean_frp, :max_frp, :facility_id,
        :match_type, :match_distance_m, :site_class, :status
    );
    """
    conn.executemany(insert_sites_sql, site_records)

    # Update site_id in detections table
    print("Updating detections table with assigned site_id...")
    # Reset all site_ids to NULL first
    conn.execute("UPDATE detections SET site_id = NULL WHERE is_simulated = 0;")

    # Batch update detections with assigned site_id
    update_tuples = [
        (str(row["site_id"]), int(row["detection_id"]))
        for _, row in detections_df.iterrows()
        if pd.notna(row["site_id"])
    ]
    conn.executemany(
        "UPDATE detections SET site_id = ? WHERE detection_id = ?;",
        update_tuples,
    )
    conn.commit()

    # 9. Legacy comparison and metadata recording
    legacy_count = 568
    legacy_assigned = 10539
    legacy_isolated = 10974

    if LEGACY_SITES_CSV.exists():
        legacy_df = pd.read_csv(LEGACY_SITES_CSV)
        legacy_count = len(legacy_df)
        legacy_assigned = int(legacy_df["detection_count"].sum())
        legacy_isolated = EXPECTED_DETECTIONS - legacy_assigned

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata_entries = {
        "legacy_sites_count": str(legacy_count),
        "legacy_assigned_detections": str(legacy_assigned),
        "legacy_isolated_detections": str(legacy_isolated),
        "new_sites_count": str(len(sites_df)),
        "new_assigned_detections": str(n_assigned),
        "new_isolated_detections": str(n_isolated),
        "stage_2_clustered_at_utc": now_iso,
    }

    for k, v in metadata_entries.items():
        set_metadata(conn, k, v)

    conn.close()

    # 10. Export sites.csv
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    sites_export_path = EXPORT_DIR / "sites.csv"
    sites_df.to_csv(sites_export_path, index=False)
    print(f"Exported sites to {sites_export_path} ({len(sites_df)} rows).")

    # 11. Re-export detections.csv with populated site_id
    detections_export_path = EXPORT_DIR / "detections.csv"
    detections_columns = [
        "detection_id", "latitude", "longitude", "acq_date", "acq_time",
        "acq_datetime_utc", "week_index", "frp", "bright_ti4", "bright_ti5",
        "scan", "track", "confidence", "satellite", "instrument", "version",
        "daynight", "type", "source_file", "site_id", "is_simulated",
    ]
    detections_df[detections_columns].to_csv(detections_export_path, index=False)
    print(f"Updated detections export: {detections_export_path} ({len(detections_df)} rows).")

    # 12. Print summary report
    print("\n" + "=" * 60)
    print("STAGE 2 CLUSTERING SUMMARY")
    print("=" * 60)
    print(f"Sites generated:            {len(sites_df)} (legacy: {legacy_count})")
    print(f"Assigned detections:        {n_assigned:,} (legacy: {legacy_assigned:,})")
    print(f"Isolated detections:        {n_isolated:,} (legacy: {legacy_isolated:,})")

    match_legacy = (
        len(sites_df) == legacy_count
        and n_assigned == legacy_assigned
        and n_isolated == legacy_isolated
    )
    if match_legacy:
        print(">> EXACT MATCH with legacy clustering results (568 / 10,539 / 10,974).")
    else:
        print(">> NOTICE: Clustering counts differ from legacy counts.")

    print(f"\nSites with spatial extent > {SITE_EXTENT_REVIEW_KM} km (for review): {len(large_extent_sites)}")
    for sid, n_dets, extent_km, lat, lon in large_extent_sites:
        print(f"  - {sid}: extent = {extent_km:.2f} km, detections = {n_dets}, centroid = ({lat:.4f}, {lon:.4f})")

    print(f"\nTop 5 Sites by Detection Count:")
    for _, r in sites_df.head(5).iterrows():
        print(
            f"  - {r['site_id']}: {r['n_detections']:,} detections, "
            f"centroid = ({r['centroid_lat']:.4f}, {r['centroid_lon']:.4f}), "
            f"extent = {r['extent_km']:.2f} km, active_weeks = {r['active_weeks_total']}"
        )

    print("=" * 60)
    print("Stage 2 successfully completed.")
    print("=" * 60)


if __name__ == "__main__":
    run_clustering()
