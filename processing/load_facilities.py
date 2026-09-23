"""
THERMOGRAPH — Stage 3: Load OSM Industrial Facilities
Loads OpenStreetMap industrial facilities from the Gujarat GeoJSON file
into SQLite table 'facilities', validates geometries with Shapely,
constructs plain-English display names, records metadata, and exports
facilities.csv for tabular inspection.

Specifications implemented: TECH_SPEC §5.3, PRD FR-11.
"""

import datetime
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
import pandas as pd
from shapely.geometry import shape

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.config import (
    DB_PATH,
    EXPECTED_FACILITIES,
    FACILITIES_EXPORT_CSV,
    RAW_OSM_FILE,
)
from processing.db import get_connection, set_metadata


def build_display_name(
    facility_id: str,
    name: str | None,
    industrial: str | None,
    landuse: str | None,
) -> str:
    """
    Construct human-readable display name for an OSM industrial facility per TECH_SPEC §5.3:
    - If name is present, use name.
    - Else if industrial tag is present, 'Unnamed <industrial> site (OSM <id>)'.
    - Else if landuse tag is present, 'Unnamed <landuse> site (OSM <id>)'.
    - Else 'Unnamed industrial site (OSM <id>)'.
    """
    if name and str(name).strip():
        return str(name).strip()
    if industrial and str(industrial).strip():
        return f"Unnamed {str(industrial).strip()} site (OSM {facility_id})"
    if landuse and str(landuse).strip():
        return f"Unnamed {str(landuse).strip()} site (OSM {facility_id})"
    return f"Unnamed industrial site (OSM {facility_id})"


def load_and_parse_geojson(
    geojson_path: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, int], int]:
    """
    Read the OSM GeoJSON file, validate feature counts, validate geometries
    using Shapely, and extract standardized facility records.
    """
    if not geojson_path.exists():
        print(f"[FAIL] Raw OSM file not found at {geojson_path}. Stopping.")
        sys.exit(1)

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    total_features = len(features)
    print(f"Loaded {total_features:,} features from {geojson_path.name}.")

    if total_features != EXPECTED_FACILITIES:
        print(
            f"[FAIL] Expected {EXPECTED_FACILITIES:,} facilities, found {total_features:,}. Stopping."
        )
        sys.exit(1)

    records: List[Dict[str, Any]] = []
    geom_type_counts: Dict[str, int] = {}
    fixed_geometry_count = 0

    for feat in features:
        props = feat.get("properties", {})
        geom_dict = feat.get("geometry", {})

        # Facility ID: prefer @id, fallback to feature top-level id
        facility_id = props.get("@id") or feat.get("id")
        if not facility_id:
            print("[FAIL] Encountered feature with no identifiable OSM ID. Stopping.")
            sys.exit(1)

        facility_id = str(facility_id).strip()

        # Geometry validation with Shapely
        geom_obj = shape(geom_dict)
        if not geom_obj.is_valid:
            geom_obj = geom_obj.buffer(0)
            fixed_geometry_count += 1

        geom_type = geom_obj.geom_type
        geom_type_counts[geom_type] = geom_type_counts.get(geom_type, 0) + 1

        # Centroid coordinates
        centroid = geom_obj.centroid
        centroid_lat = float(centroid.y)
        centroid_lon = float(centroid.x)

        # OSM Properties
        name = props.get("name")
        name = str(name).strip() if name is not None else None
        industrial = props.get("industrial")
        industrial = str(industrial).strip() if industrial is not None else None
        landuse = props.get("landuse")
        landuse = str(landuse).strip() if landuse is not None else None
        osm_type = props.get("type")
        osm_type = str(osm_type).strip() if osm_type is not None else None
        wikidata = props.get("wikidata")
        wikidata = str(wikidata).strip() if wikidata is not None else None

        display_name = build_display_name(facility_id, name, industrial, landuse)
        geojson_text = json.dumps(geom_dict)

        records.append(
            {
                "facility_id": facility_id,
                "name": name,
                "industrial": industrial,
                "landuse": landuse,
                "osm_type": osm_type,
                "wikidata": wikidata,
                "geometry_type": geom_type,
                "centroid_lat": centroid_lat,
                "centroid_lon": centroid_lon,
                "geojson": geojson_text,
                "display_name": display_name,
            }
        )

    return records, geom_type_counts, fixed_geometry_count


def run_load_facilities() -> List[Dict[str, Any]]:
    """
    Main pipeline stage 3 execution:
    1. Parse and validate GeoJSON.
    2. Insert records into SQLite facilities table.
    3. Update metadata table.
    4. Export facilities.csv.
    """
    print("=" * 60)
    print("THERMOGRAPH Pipeline — Stage 3: Load OSM Facilities")
    print("=" * 60)

    # 1. Parse and validate
    records, geom_counts, fixed_count = load_and_parse_geojson(RAW_OSM_FILE)

    # 2. Database connection
    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}. Run earlier stages first. Stopping.")
        sys.exit(1)

    conn = get_connection(DB_PATH)

    # Clear and repopulate facilities table
    print(f"Populating 'facilities' table with {len(records)} records...")
    conn.execute("DELETE FROM facilities;")

    insert_sql = """
    INSERT INTO facilities (
        facility_id, name, industrial, landuse, osm_type,
        wikidata, geometry_type, centroid_lat, centroid_lon,
        geojson, display_name
    ) VALUES (
        :facility_id, :name, :industrial, :landuse, :osm_type,
        :wikidata, :geometry_type, :centroid_lat, :centroid_lon,
        :geojson, :display_name
    );
    """
    conn.executemany(insert_sql, records)
    conn.commit()

    # 3. Update metadata
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    set_metadata(conn, "facilities_count", str(len(records)))
    set_metadata(conn, "stage_3_loaded_at_utc", now_iso)

    conn.close()

    # 4. Export CSV
    FACILITIES_EXPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    # Drop raw geojson column from CSV export for clean tabular inspection
    export_df = df[
        [
            "facility_id",
            "name",
            "industrial",
            "landuse",
            "osm_type",
            "wikidata",
            "geometry_type",
            "centroid_lat",
            "centroid_lon",
            "display_name",
        ]
    ]
    export_df.to_csv(FACILITIES_EXPORT_CSV, index=False)
    print(f"Exported facilities to {FACILITIES_EXPORT_CSV} ({len(export_df)} rows).")

    # 5. Print summary report
    named_count = sum(1 for r in records if r["name"] is not None)
    print("\n" + "=" * 60)
    print("STAGE 3 OSM FACILITIES SUMMARY")
    print("=" * 60)
    print(f"Total facilities loaded:    {len(records):,}")
    print(f"Named facilities:           {named_count:,} ({named_count / len(records) * 100:.1f}%)")
    print(f"Geometries needing repair:  {fixed_count}")
    print("Geometry types:")
    for gtype, count in sorted(geom_counts.items()):
        print(f"  - {gtype}: {count:,} ({count / len(records) * 100:.1f}%)")
    print("=" * 60)
    print("Stage 3 successfully completed.")
    print("=" * 60)

    return records


if __name__ == "__main__":
    run_load_facilities()
