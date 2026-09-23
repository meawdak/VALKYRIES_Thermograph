"""
THERMOGRAPH — Stage 4: Spatial Matching of Thermal Sites to OSM Facilities
Associates candidate thermal sites with nearby OpenStreetMap (OSM) industrial
facilities using great-circle (Haversine) distance and a 1.0 km radius threshold.
Generates output/thermal_sites_matched.csv, updates the SQLite 'sites' table,
refreshes output/exports/sites.csv, and logs spatial matching metrics.

Scientific principle:
Spatial matching provides contextual proximity only. Proximity to an industrial
facility does not prove causation; it establishes geographical context for
subsequent baseline and anomaly analysis.

Specifications implemented: TECH_SPEC §5.4, PRD FR-11 through FR-14.
"""

import datetime
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    DB_PATH,
    EARTH_RADIUS_KM,
    EXPECTED_FACILITIES,
    LEGACY_SITES_CSV,
    MATCH_RADIUS_KM,
    MATCHED_SITES_CSV,
    RAW_OSM_FILE,
    SITES_EXPORT_CSV,
)
from processing.db import get_connection, set_metadata
from processing.load_facilities import load_and_parse_geojson, run_load_facilities


def haversine_vectorized_km(
    site_lats: np.ndarray,
    site_lons: np.ndarray,
    fac_lats: np.ndarray,
    fac_lons: np.ndarray,
) -> np.ndarray:
    """
    Compute pairwise Haversine distances in kilometres between N sites and M facilities.
    Returns an (N, M) matrix of great-circle distances.
    """
    phi1 = np.radians(site_lats)[:, np.newaxis]  # shape (N, 1)
    phi2 = np.radians(fac_lats)[np.newaxis, :]  # shape (1, M)
    dphi = phi2 - phi1
    dlambda = np.radians(fac_lons)[np.newaxis, :] - np.radians(site_lons)[:, np.newaxis]

    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    c = 2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))
    return EARTH_RADIUS_KM * c


def load_candidate_sites() -> pd.DataFrame:
    """
    Load candidate thermal sites.
    Prefers output/thermal_sites.csv (568 sites with original fields).
    Falls back to SQLite sites table if needed.
    """
    if LEGACY_SITES_CSV.exists():
        df = pd.read_csv(LEGACY_SITES_CSV)
        print(f"Loaded {len(df):,} candidate thermal sites from {LEGACY_SITES_CSV.name}.")
        return df

    if DB_PATH.exists():
        conn = get_connection(DB_PATH)
        df = pd.read_sql_query(
            """
            SELECT
                site_id, centroid_lat AS latitude, centroid_lon AS longitude,
                n_detections AS detection_count, active_weeks_total AS active_dates,
                first_seen, last_seen, mean_frp, max_frp
            FROM sites
            ORDER BY site_id ASC;
            """,
            conn,
        )
        conn.close()
        print(f"Loaded {len(df):,} candidate thermal sites from database.")
        return df

    print(f"[FAIL] Neither {LEGACY_SITES_CSV} nor {DB_PATH} found. Run earlier stages first. Stopping.")
    sys.exit(1)


def load_facilities_data() -> pd.DataFrame:
    """
    Load OSM facilities. Ensures facilities are parsed from GeoJSON
    or read from SQLite if already populated.
    """
    if DB_PATH.exists():
        conn = get_connection(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM facilities;")
        fac_count = cursor.fetchone()[0]
        if fac_count == EXPECTED_FACILITIES:
            df = pd.read_sql_query(
                """
                SELECT
                    facility_id, name, industrial, landuse, osm_type,
                    centroid_lat, centroid_lon, display_name
                FROM facilities
                ORDER BY facility_id ASC;
                """,
                conn,
            )
            conn.close()
            print(f"Loaded {len(df):,} OSM facilities from SQLite 'facilities' table.")
            return df
        conn.close()

    # Otherwise load and populate directly
    print("Facilities table not yet loaded in database. Running Stage 3 loader...")
    records = run_load_facilities()
    return pd.DataFrame(records)


def run_facility_matching() -> pd.DataFrame:
    """
    Main execution of Stage 4 facility matching:
    1. Loads candidate thermal sites and OSM facilities.
    2. Computes pairwise Haversine distances.
    3. Finds nearest facility for each site and applies the 1.0 km radius threshold.
    4. Generates output/thermal_sites_matched.csv.
    5. Updates SQLite 'sites' table and output/exports/sites.csv.
    6. Logs statistics and validation summary.
    """
    print("=" * 60)
    print("THERMOGRAPH Pipeline — Stage 4: Match Sites to OSM Facilities")
    print("=" * 60)

    # 1. Load inputs
    sites_df = load_candidate_sites()
    fac_df = load_facilities_data()

    total_sites = len(sites_df)
    total_facs = len(fac_df)

    if total_sites == 0 or total_facs == 0:
        print("[FAIL] Empty sites or facilities dataset. Stopping.")
        sys.exit(1)

    # 2. Extract coordinates
    site_lats = sites_df["latitude"].to_numpy(dtype=float)
    site_lons = sites_df["longitude"].to_numpy(dtype=float)
    fac_lats = fac_df["centroid_lat"].to_numpy(dtype=float)
    fac_lons = fac_df["centroid_lon"].to_numpy(dtype=float)

    # 3. Vectorized Haversine distance computation
    print(
        f"Computing geodesic distances ({total_sites} sites × {total_facs} facilities = "
        f"{total_sites * total_facs:,} comparisons) with Haversine formula..."
    )
    dist_matrix = haversine_vectorized_km(site_lats, site_lons, fac_lats, fac_lons)

    # 4. Find nearest facility for each site
    nearest_indices = np.argmin(dist_matrix, axis=1)
    nearest_distances = dist_matrix[np.arange(total_sites), nearest_indices]

    matched_rows: List[Dict[str, Any]] = []
    matched_distances: List[float] = []
    db_update_tuples: List[Tuple[Any, ...]] = []

    matched_count = 0
    unmapped_count = 0

    for i in range(total_sites):
        site = sites_df.iloc[i]
        nearest_idx = nearest_indices[i]
        nearest_dist_km = float(nearest_distances[i])
        nearest_fac = fac_df.iloc[nearest_idx]

        is_matched = nearest_dist_km <= MATCH_RADIUS_KM

        # Base site information preserved
        base_record = {
            "site_id": site["site_id"],
            "latitude": float(site["latitude"]),
            "longitude": float(site["longitude"]),
            "detection_count": int(site["detection_count"]),
            "active_dates": int(site["active_dates"]),
            "first_seen": str(site["first_seen"]),
            "last_seen": str(site["last_seen"]),
            "mean_frp": float(site["mean_frp"]),
            "max_frp": float(site["max_frp"]),
        }

        if is_matched:
            matched_count += 1
            matched_distances.append(nearest_dist_km)
            match_status = "MATCHED"

            # Facility information associated
            fac_id = str(nearest_fac["facility_id"])
            fac_name = nearest_fac["name"] if pd.notna(nearest_fac["name"]) else None
            fac_type = nearest_fac["osm_type"] if pd.notna(nearest_fac.get("osm_type")) else None
            fac_ind = nearest_fac["industrial"] if pd.notna(nearest_fac["industrial"]) else None
            fac_land = nearest_fac["landuse"] if pd.notna(nearest_fac["landuse"]) else None
            fac_lat = float(nearest_fac["centroid_lat"])
            fac_lon = float(nearest_fac["centroid_lon"])
            fac_dist_km = round(nearest_dist_km, 4)
            match_dist_m = round(nearest_dist_km * 1000.0)

            record = {
                **base_record,
                "facility_id": fac_id,
                "facility_name": fac_name,
                "facility_type": fac_type,
                "facility_industrial": fac_ind,
                "facility_landuse": fac_land,
                "facility_latitude": fac_lat,
                "facility_longitude": fac_lon,
                "facility_distance_km": fac_dist_km,
                "nearest_facility_distance_km": round(nearest_dist_km, 4),
                "match_status": match_status,
            }

            # Database updates (match_type = 'nearby', match_distance_m in whole metres)
            db_update_tuples.append(
                (fac_id, "nearby", float(match_dist_m), str(site["site_id"]))
            )

        else:
            unmapped_count += 1
            match_status = "UNMAPPED"

            # No facility identity assigned to unmapped sites
            record = {
                **base_record,
                "facility_id": None,
                "facility_name": None,
                "facility_type": None,
                "facility_industrial": None,
                "facility_landuse": None,
                "facility_latitude": None,
                "facility_longitude": None,
                "facility_distance_km": None,
                "nearest_facility_distance_km": round(nearest_dist_km, 4),
                "match_status": match_status,
            }

            # Database updates for unmapped sites (match_type = 'none', NULL facility/distance)
            db_update_tuples.append(
                (None, "none", None, str(site["site_id"]))
            )

        matched_rows.append(record)

    matched_df = pd.DataFrame(matched_rows)

    # 5. Export output/thermal_sites_matched.csv
    MATCHED_SITES_CSV.parent.mkdir(parents=True, exist_ok=True)
    matched_df.to_csv(MATCHED_SITES_CSV, index=False)
    print(f"\nGenerated primary matched output: {MATCHED_SITES_CSV} ({len(matched_df)} rows).")

    # 6. Update SQLite 'sites' table and refresh exports/sites.csv
    if DB_PATH.exists():
        conn = get_connection(DB_PATH)
        print("Synchronizing facility matching results into SQLite 'sites' table...")

        # If sites table uses TS-0001 IDs and sites_df used SITE_00000, map them by coordinates
        cursor = conn.cursor()
        cursor.execute("SELECT site_id, centroid_lat, centroid_lon FROM sites ORDER BY site_id ASC;")
        db_sites = cursor.fetchall()

        if len(db_sites) > 0:
            db_site_ids = [r["site_id"] for r in db_sites]
            # Check if IDs match directly
            first_db_id = db_site_ids[0]
            if first_db_id.startswith("TS-"):
                # Match by nearest centroid coordinate to map legacy IDs to TS- IDs
                db_lats = np.array([r["centroid_lat"] for r in db_sites])
                db_lons = np.array([r["centroid_lon"] for r in db_sites])

                ts_update_tuples = []
                for _, m_row in matched_df.iterrows():
                    s_lat = m_row["latitude"]
                    s_lon = m_row["longitude"]
                    # Find corresponding TS- site
                    coord_dists = np.hypot(db_lats - s_lat, db_lons - s_lon)
                    ts_idx = int(np.argmin(coord_dists))
                    ts_id = db_site_ids[ts_idx]

                    if m_row["match_status"] == "MATCHED":
                        dist_m = round(float(m_row["facility_distance_km"]) * 1000.0)
                        ts_update_tuples.append(
                            (m_row["facility_id"], "nearby", float(dist_m), ts_id)
                        )
                    else:
                        ts_update_tuples.append(
                            (None, "none", None, ts_id)
                        )

                conn.executemany(
                    """
                    UPDATE sites
                    SET facility_id = ?, match_type = ?, match_distance_m = ?
                    WHERE site_id = ?;
                    """,
                    ts_update_tuples,
                )
            else:
                conn.executemany(
                    """
                    UPDATE sites
                    SET facility_id = ?, match_type = ?, match_distance_m = ?
                    WHERE site_id = ?;
                    """,
                    db_update_tuples,
                )

            conn.commit()

            # Record metadata
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            set_metadata(conn, "matched_sites_count", str(matched_count))
            set_metadata(conn, "unmapped_sites_count", str(unmapped_count))
            set_metadata(conn, "stage_4_matched_at_utc", now_iso)

            # Re-export sites.csv
            sites_updated_df = pd.read_sql_query("SELECT * FROM sites ORDER BY n_detections DESC, centroid_lat DESC;", conn)
            SITES_EXPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
            sites_updated_df.to_csv(SITES_EXPORT_CSV, index=False)
            print(f"Refreshed {SITES_EXPORT_CSV} ({len(sites_updated_df)} rows).")

        conn.close()

    # 7. Print validation metrics
    print("\n" + "=" * 60)
    print("STAGE 4 FACILITY MATCHING RESULTS & VALIDATION")
    print("=" * 60)
    print(f"Total thermal sites processed:          {total_sites:,}")
    print(f"Total OSM industrial facilities:        {total_facs:,}")
    print(f"Matching threshold applied:             {MATCH_RADIUS_KM:.1f} km (1,000 m)")
    print(f"Number of matched sites:                {matched_count:,} ({matched_count / total_sites * 100:.2f}%)")
    print(f"Number of unmapped sites:               {unmapped_count:,} ({unmapped_count / total_sites * 100:.2f}%)")

    if matched_distances:
        min_dist = min(matched_distances)
        max_dist = max(matched_distances)
        avg_dist = sum(matched_distances) / len(matched_distances)
        print(f"Minimum matching distance:              {min_dist:.4f} km ({min_dist * 1000.0:.1f} m)")
        print(f"Maximum matching distance:              {max_dist:.4f} km ({max_dist * 1000.0:.1f} m)")
        print(f"Average matching distance:              {avg_dist:.4f} km ({avg_dist * 1000.0:.1f} m)")
        assert max_dist <= MATCH_RADIUS_KM, "Error: matched distance exceeded 1.0 km threshold!"
        print(f">> Verification: ALL {matched_count} matched sites have distance <= {MATCH_RADIUS_KM:.1f} km.")
    else:
        print("No sites matched within threshold.")

    # 8. Example matched records
    print("\n" + "-" * 60)
    print("Example Matched Records:")
    print("-" * 60)
    matched_samples = matched_df[matched_df["match_status"] == "MATCHED"].head(5)
    for _, r in matched_samples.iterrows():
        fac_name = r["facility_name"] if pd.notna(r["facility_name"]) else "Unnamed"
        ind_tag = f", ind={r['facility_industrial']}" if pd.notna(r["facility_industrial"]) else ""
        print(
            f"  • {r['site_id']}: coords=({r['latitude']:.4f}, {r['longitude']:.4f}), "
            f"dets={r['detection_count']}, dist={r['facility_distance_km']:.4f} km "
            f"({r['facility_distance_km'] * 1000.0:.0f} m) -> {r['facility_id']} ('{fac_name}'{ind_tag})"
        )

    # 9. Example unmapped records
    print("\n" + "-" * 60)
    print("Example Unmapped Records (preserving coordinates, nearest dist for inspection):")
    print("-" * 60)
    unmapped_samples = matched_df[matched_df["match_status"] == "UNMAPPED"].head(5)
    for _, r in unmapped_samples.iterrows():
        print(
            f"  • {r['site_id']}: coords=({r['latitude']:.4f}, {r['longitude']:.4f}), "
            f"dets={r['detection_count']}, status={r['match_status']}, "
            f"nearest_facility_dist={r['nearest_facility_distance_km']:.2f} km"
        )
    print("=" * 60)

    return matched_df


if __name__ == "__main__":
    run_facility_matching()
