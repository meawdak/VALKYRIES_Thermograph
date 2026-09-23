"""
THERMOGRAPH — Flask REST API Backend (Task T10)
Serves processed satellite thermal anomaly results from SQLite read-only.
Conforms to TECH_SPEC §8 and PRD §7.8.

Run with:
    python app/app.py
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from flask import Flask, Response, g, jsonify, request, send_from_directory

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from processing.config import (
    DB_PATH,
    DATASET_START,
    DATASET_END,
)


def get_db(target_db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Open a read-only connection to the SQLite database for the current request.
    Uses SQLite URI read-only mode (?mode=ro) to guarantee no database modifications.
    """
    if "db" not in g:
        db_file = Path(target_db_path or DB_PATH)
        if not db_file.exists():
            raise FileNotFoundError(f"Database file not found at: {db_file}")

        # Connect with read-only URI mode and enable foreign keys
        conn = sqlite3.connect(f"file:{db_file.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def parse_include_simulated() -> bool:
    """
    Parse the include_simulated query parameter from request args.
    Returns True only if set to '1', 'true', 'yes', or 'on' (case-insensitive).
    Defaults to False (0).
    """
    val = request.args.get("include_simulated", "0").strip().lower()
    return val in ("1", "true", "yes", "on")


def create_app(test_config: Optional[Dict[str, Any]] = None) -> Flask:
    """
    Application factory for the THERMOGRAPH Flask API backend.
    """
    static_dir = ROOT / "app" / "static"
    app = Flask(__name__, static_folder=str(static_dir))

    # Configure application defaults
    app.config["DB_PATH"] = DB_PATH
    if test_config:
        app.config.update(test_config)

    @app.teardown_appcontext
    def close_db(exception: Optional[BaseException] = None) -> None:
        """Close the SQLite database connection at the end of each request."""
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def add_cors_and_cache_headers(response: Response) -> Response:
        """Add standard CORS headers for local frontend integration."""
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
        return response

    @app.errorhandler(FileNotFoundError)
    def handle_db_missing(e: FileNotFoundError) -> Any:
        """Return 503 if the database has not been generated yet."""
        return jsonify({
            "error": "database_not_found",
            "message": "Database not found or unavailable. Please run pipeline first: python processing/run_pipeline.py",
            "details": str(e)
        }), 503

    @app.errorhandler(sqlite3.DatabaseError)
    def handle_db_error(e: sqlite3.DatabaseError) -> Any:
        """Return 500 on database access or schema error."""
        return jsonify({
            "error": "database_error",
            "message": f"Database error encountered: {str(e)}"
        }), 500

    # -------------------------------------------------------------------------
    # Route: GET /
    # -------------------------------------------------------------------------
    @app.route("/", methods=["GET"])
    def index() -> Any:
        """
        Serve index.html if present; otherwise return an API summary.
        """
        index_file = static_dir / "index.html"
        if index_file.exists():
            return send_from_directory(str(static_dir), "index.html")
        return jsonify({
            "name": "THERMOGRAPH API",
            "description": "Satellite Thermal Anomaly Monitoring System (Gujarat)",
            "status": "operational",
            "endpoints": [
                "/api/dashboard",
                "/api/facilities",
                "/api/anomalies",
                "/api/risk",
                "/api/sites",
                "/api/sites/<site_id>",
                "/api/detections/isolated",
            ],
            "dataset_period": f"{DATASET_START} to {DATASET_END}",
        })

    # -------------------------------------------------------------------------
    # Route: GET /api/dashboard
    # -------------------------------------------------------------------------
    @app.route("/api/dashboard", methods=["GET"])
    def get_dashboard() -> Any:
        """
        Summary counts and metadata for dashboard header and stats panel.
        Conforms strictly to TECH_SPEC §8.
        """
        db = get_db(app.config.get("DB_PATH"))
        cursor = db.cursor()
        include_sim = parse_include_simulated()

        # 1. Fetch metadata key-values
        cursor.execute("SELECT key, value FROM metadata;")
        meta_dict = {row["key"]: row["value"] for row in cursor.fetchall()}

        dataset_start = meta_dict.get("dataset_start", DATASET_START)
        dataset_end = meta_dict.get("dataset_end", DATASET_END)
        status_as_of = meta_dict.get("status_as_of", DATASET_END)

        # 2. Baseline and monitoring period dates from site_weekly
        cursor.execute("""
        SELECT MIN(week_start), MAX(week_end)
        FROM site_weekly
        WHERE period = 'baseline' AND is_simulated = 0;
        """)
        b_row = cursor.fetchone()
        baseline_period = [b_row[0], b_row[1]] if b_row and b_row[0] else ["2025-07-01", "2026-03-30"]

        cursor.execute("""
        SELECT MIN(week_start), MAX(week_end)
        FROM site_weekly
        WHERE period = 'monitoring' AND is_simulated = 0;
        """)
        m_row = cursor.fetchone()
        monitoring_period = [m_row[0], m_row[1]] if m_row and m_row[0] else ["2026-03-31", "2026-06-30"]

        # 3. Detection counts (conditionally include simulated detections)
        if include_sim:
            cursor.execute("SELECT COUNT(*) FROM detections;")
        else:
            cursor.execute("SELECT COUNT(*) FROM detections WHERE is_simulated = 0;")
        total_detections = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM detections WHERE site_id IS NULL AND is_simulated = 0;")
        isolated_detections = cursor.fetchone()[0]

        # 4. Sites count and matched breakdown
        cursor.execute("SELECT COUNT(*) FROM sites;")
        total_sites = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sites WHERE match_type IN ('inside', 'nearby');")
        sites_matched = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sites WHERE match_type = 'none';")
        sites_unmapped = cursor.fetchone()[0]

        # 5. Facilities count
        cursor.execute("SELECT COUNT(*) FROM facilities;")
        total_facilities = cursor.fetchone()[0]

        # 6. Sites breakdown by class
        cursor.execute("SELECT site_class, COUNT(*) FROM sites GROUP BY site_class;")
        class_counts = {
            "PERSISTENT_INDUSTRIAL": 0,
            "PERSISTENT_UNMAPPED": 0,
            "EPISODIC_NEAR_FACILITY": 0,
            "EPISODIC_OTHER": 0,
        }
        for r in cursor.fetchall():
            if r[0] in class_counts:
                class_counts[r[0]] = r[1]

        # 7. Sites breakdown by status (real status is preserved per TECH_SPEC §5.8)
        cursor.execute("SELECT status, COUNT(*) FROM sites GROUP BY status;")
        status_counts = {
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "NORMAL": 0,
            "INSUFFICIENT_HISTORY": 0,
            "NEW_SITE_NO_ANOMALY": 0,
        }
        for r in cursor.fetchall():
            if r[0] in status_counts:
                status_counts[r[0]] = r[1]

        # 8. Distinct anomalous sites count
        sim_filter = 1 if include_sim else 0
        cursor.execute("""
        SELECT COUNT(DISTINCT site_id)
        FROM anomalies
        WHERE (? = 1 OR is_simulated = 0);
        """, (sim_filter,))
        anomalous_sites_count = cursor.fetchone()[0]

        response_data = {
            "dataset_start": dataset_start,
            "dataset_end": dataset_end,
            "status_as_of": status_as_of,
            "baseline_period": baseline_period,
            "monitoring_period": monitoring_period,
            "counts": {
                "detections": total_detections,
                "sites": total_sites,
                "isolated_detections": isolated_detections,
                "facilities": total_facilities,
                "sites_matched": sites_matched,
                "sites_unmapped": sites_unmapped,
                "sites_by_class": class_counts,
                "sites_by_status": status_counts,
                "anomalous_sites": anomalous_sites_count,
                "sites_normal": status_counts["NORMAL"],
            },
            "parameters": meta_dict,
            "simulated_included": include_sim,
        }
        return jsonify(response_data)

    # -------------------------------------------------------------------------
    # Route: GET /api/facilities
    # -------------------------------------------------------------------------
    @app.route("/api/facilities", methods=["GET"])
    def get_facilities() -> Any:
        """
        Return all 710 OSM facilities as a GeoJSON FeatureCollection.
        Conforms strictly to TECH_SPEC §8.
        """
        db = get_db(app.config.get("DB_PATH"))
        cursor = db.cursor()

        cursor.execute("""
        SELECT facility_id, display_name, industrial, landuse, geojson
        FROM facilities
        ORDER BY facility_id ASC;
        """)
        rows = cursor.fetchall()

        features = []
        for r in rows:
            try:
                geom = json.loads(r["geojson"])
            except Exception:
                geom = None

            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "facility_id": r["facility_id"],
                    "display_name": r["display_name"],
                    "industrial": r["industrial"],
                    "landuse": r["landuse"],
                },
            })

        return jsonify({
            "type": "FeatureCollection",
            "features": features,
        })

    # -------------------------------------------------------------------------
    # Route: GET /api/anomalies
    # -------------------------------------------------------------------------
    @app.route("/api/anomalies", methods=["GET"])
    def get_anomalies() -> Any:
        """
        Return all anomaly rows, newest week first.
        Supports optional ?site_id= filter and ?include_simulated=1.
        Conforms strictly to TECH_SPEC §8.
        """
        db = get_db(app.config.get("DB_PATH"))
        cursor = db.cursor()
        include_sim = parse_include_simulated()
        site_id = request.args.get("site_id", None)
        if site_id is not None:
            site_id = site_id.strip()

        sql = """
        SELECT a.anomaly_id, a.site_id, a.week_index, a.week_start, a.week_end,
               a.anomaly_type, a.detection_count, a.frp_sum, a.frp_max,
               a.threshold, a.ratio, a.score, a.priority, a.reasons, a.is_simulated,
               s.centroid_lat AS lat, s.centroid_lon AS lon, s.site_class, s.status,
               f.facility_id, f.display_name AS facility_display_name
        FROM anomalies a
        JOIN sites s ON a.site_id = s.site_id
        LEFT JOIN facilities f ON s.facility_id = f.facility_id
        WHERE (? = 1 OR a.is_simulated = 0)
        """
        params: List[Any] = [1 if include_sim else 0]

        if site_id:
            sql += " AND a.site_id = ?"
            params.append(site_id)

        sql += " ORDER BY a.week_index DESC, a.score DESC, a.frp_sum DESC;"

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        results = []
        for r in rows:
            try:
                reasons_list = json.loads(r["reasons"]) if r["reasons"] else []
            except Exception:
                reasons_list = [r["reasons"]] if r["reasons"] else []

            results.append({
                "anomaly_id": r["anomaly_id"],
                "site_id": r["site_id"],
                "week_index": r["week_index"],
                "week_start": r["week_start"],
                "week_end": r["week_end"],
                "anomaly_type": r["anomaly_type"],
                "detection_count": r["detection_count"],
                "frp_sum": r["frp_sum"],
                "frp_max": r["frp_max"],
                "threshold": r["threshold"],
                "ratio": r["ratio"],
                "score": r["score"],
                "priority": r["priority"],
                "reasons": reasons_list,
                "is_simulated": bool(r["is_simulated"]),
                "lat": r["lat"],
                "lon": r["lon"],
                "site_class": r["site_class"],
                "status": r["status"],
                "facility_id": r["facility_id"],
                "facility_display_name": r["facility_display_name"],
            })

        return jsonify(results)

    # -------------------------------------------------------------------------
    # Route: GET /api/risk
    # -------------------------------------------------------------------------
    @app.route("/api/risk", methods=["GET"])
    def get_risk() -> Any:
        """
        Return one row per anomalous site (its top-scoring anomaly),
        sorted by score descending, then frp_sum descending.
        Conforms strictly to TECH_SPEC §8.
        """
        db = get_db(app.config.get("DB_PATH"))
        cursor = db.cursor()
        include_sim = parse_include_simulated()

        # Query all candidate anomalies sorted by score DESC, then frp_sum DESC, then week DESC
        cursor.execute("""
        SELECT a.anomaly_id, a.site_id, a.week_index, a.week_start, a.week_end,
               a.anomaly_type, a.score, a.priority, a.frp_sum, a.frp_max,
               a.reasons, a.is_simulated,
               s.centroid_lat AS lat, s.centroid_lon AS lon, s.site_class, s.status,
               f.facility_id, f.display_name AS facility_display_name
        FROM anomalies a
        JOIN sites s ON a.site_id = s.site_id
        LEFT JOIN facilities f ON s.facility_id = f.facility_id
        WHERE (? = 1 OR a.is_simulated = 0)
        ORDER BY a.score DESC, a.frp_sum DESC, a.week_index DESC;
        """, (1 if include_sim else 0,))

        rows = cursor.fetchall()

        # Keep the top-scoring anomaly per unique site
        seen_sites = set()
        risk_list = []
        rank = 1

        for r in rows:
            sid = r["site_id"]
            if sid in seen_sites:
                continue
            seen_sites.add(sid)

            try:
                reasons_list = json.loads(r["reasons"]) if r["reasons"] else []
            except Exception:
                reasons_list = [r["reasons"]] if r["reasons"] else []

            top_reason = reasons_list[0] if reasons_list else ""

            risk_list.append({
                "rank": rank,
                "site_id": sid,
                "lat": r["lat"],
                "lon": r["lon"],
                "priority": r["priority"],
                "score": r["score"],
                "anomaly_type": r["anomaly_type"],
                "week_start": r["week_start"],
                "facility_display_name": r["facility_display_name"],
                "top_reason": top_reason,
                "is_simulated": bool(r["is_simulated"]),
                "status": r["status"],
                "site_class": r["site_class"],
            })
            rank += 1

        return jsonify(risk_list)

    # -------------------------------------------------------------------------
    # Route: GET /api/sites
    # -------------------------------------------------------------------------
    @app.route("/api/sites", methods=["GET"])
    def get_sites() -> Any:
        """
        Return the site registry list with coordinates, class, status, and facility match info.
        Conforms strictly to TECH_SPEC §8.
        """
        db = get_db(app.config.get("DB_PATH"))
        cursor = db.cursor()

        cursor.execute("""
        SELECT s.site_id, s.centroid_lat AS lat, s.centroid_lon AS lon,
               s.site_class, s.status, s.n_detections,
               s.extent_km, s.active_weeks_total, s.mean_frp, s.max_frp,
               s.first_seen, s.last_seen,
               s.match_type, s.match_distance_m,
               f.facility_id, f.display_name AS facility_display_name
        FROM sites s
        LEFT JOIN facilities f ON s.facility_id = f.facility_id
        ORDER BY s.site_id ASC;
        """)
        rows = cursor.fetchall()

        sites = []
        for r in rows:
            sites.append({
                "site_id": r["site_id"],
                "lat": r["lat"],
                "lon": r["lon"],
                "site_class": r["site_class"],
                "status": r["status"],
                "n_detections": r["n_detections"],
                "facility_display_name": r["facility_display_name"],
                "match_type": r["match_type"],
                "match_distance_m": r["match_distance_m"],
                "extent_km": r["extent_km"],
                "active_weeks_total": r["active_weeks_total"],
                "mean_frp": r["mean_frp"],
                "max_frp": r["max_frp"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
            })

        return jsonify(sites)

    # -------------------------------------------------------------------------
    # Route: GET /api/sites/<site_id>
    # -------------------------------------------------------------------------
    @app.route("/api/sites/<site_id>", methods=["GET"])
    def get_site_detail(site_id: str) -> Any:
        """
        Return complete details for a single site, including facility details,
        baseline statistics, weekly FRP history, and anomalies.
        Returns 404 {"error": "site not found"} if the site ID does not exist.
        Conforms strictly to TECH_SPEC §8.
        """
        db = get_db(app.config.get("DB_PATH"))
        cursor = db.cursor()
        include_sim = parse_include_simulated()
        clean_site_id = site_id.strip()

        # 1. Fetch site row
        cursor.execute("SELECT * FROM sites WHERE site_id = ?;", (clean_site_id,))
        site_row = cursor.fetchone()
        if not site_row:
            return jsonify({"error": "site not found"}), 404

        site_data = dict(site_row)

        # 2. Fetch matched facility row (if any)
        facility_data = None
        if site_data.get("facility_id"):
            cursor.execute("""
            SELECT facility_id, display_name, industrial, landuse
            FROM facilities
            WHERE facility_id = ?;
            """, (site_data["facility_id"],))
            fac_row = cursor.fetchone()
            if fac_row:
                fid = fac_row["facility_id"]
                osm_url = f"https://www.openstreetmap.org/{fid}"
                facility_data = {
                    "facility_id": fid,
                    "display_name": fac_row["display_name"],
                    "industrial": fac_row["industrial"],
                    "landuse": fac_row["landuse"],
                    "distance_m": site_data.get("match_distance_m", 0.0),
                    "osm_url": osm_url,
                }

        # 3. Fetch baseline row
        cursor.execute("SELECT * FROM baselines WHERE site_id = ?;", (clean_site_id,))
        base_row = cursor.fetchone()
        baseline_data = dict(base_row) if base_row else None

        # 4. Fetch weekly activity records
        cursor.execute("""
        SELECT week_index, week_start, week_end, period, detection_count, frp_sum, frp_max, night_count, is_simulated
        FROM site_weekly
        WHERE site_id = ? AND (? = 1 OR is_simulated = 0)
        ORDER BY week_index ASC;
        """, (clean_site_id, 1 if include_sim else 0))
        weekly_rows = cursor.fetchall()
        weekly_data = []
        for wr in weekly_rows:
            weekly_data.append({
                "week_index": wr["week_index"],
                "week_start": wr["week_start"],
                "week_end": wr["week_end"],
                "period": wr["period"],
                "detection_count": wr["detection_count"],
                "frp_sum": wr["frp_sum"],
                "frp_max": wr["frp_max"],
                "night_count": wr["night_count"],
                "is_simulated": bool(wr["is_simulated"]),
            })

        # 5. Fetch anomalies for this site
        cursor.execute("""
        SELECT anomaly_id, week_index, week_start, week_end, anomaly_type,
               detection_count, frp_sum, frp_max, threshold, ratio, score, priority, reasons, is_simulated
        FROM anomalies
        WHERE site_id = ? AND (? = 1 OR is_simulated = 0)
        ORDER BY week_index DESC;
        """, (clean_site_id, 1 if include_sim else 0))
        anom_rows = cursor.fetchall()
        anomalies_data = []
        for ar in anom_rows:
            try:
                r_list = json.loads(ar["reasons"]) if ar["reasons"] else []
            except Exception:
                r_list = [ar["reasons"]] if ar["reasons"] else []

            anomalies_data.append({
                "anomaly_id": ar["anomaly_id"],
                "week_index": ar["week_index"],
                "week_start": ar["week_start"],
                "week_end": ar["week_end"],
                "anomaly_type": ar["anomaly_type"],
                "detection_count": ar["detection_count"],
                "frp_sum": ar["frp_sum"],
                "frp_max": ar["frp_max"],
                "threshold": ar["threshold"],
                "ratio": ar["ratio"],
                "score": ar["score"],
                "priority": ar["priority"],
                "reasons": r_list,
                "is_simulated": bool(ar["is_simulated"]),
            })

        return jsonify({
            "site": site_data,
            "facility": facility_data,
            "baseline": baseline_data,
            "weekly": weekly_data,
            "anomalies": anomalies_data,
        })

    # -------------------------------------------------------------------------
    # Route: GET /api/detections/isolated
    # -------------------------------------------------------------------------
    @app.route("/api/detections/isolated", methods=["GET"])
    def get_isolated_detections() -> Any:
        """
        Return compact [[lat, lon], ...] coordinate pairs for isolated real detections.
        Used by the dashboard toggle layer.
        Conforms strictly to TECH_SPEC §8.
        """
        db = get_db(app.config.get("DB_PATH"))
        cursor = db.cursor()

        cursor.execute("""
        SELECT latitude, longitude
        FROM detections
        WHERE site_id IS NULL AND is_simulated = 0
        ORDER BY detection_id ASC;
        """)
        rows = cursor.fetchall()
        coords = [[r["latitude"], r["longitude"]] for r in rows]
        return jsonify(coords)

    return app


# Module-level application instance
app = create_app()


if __name__ == "__main__":
    import os
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting THERMOGRAPH API server on {host}:{port} from database: {DB_PATH}")
    print("Accessible endpoints:")
    print(f"  • http://{host}:{port}/api/dashboard")
    print(f"  • http://{host}:{port}/api/facilities")
    print(f"  • http://{host}:{port}/api/anomalies")
    print(f"  • http://{host}:{port}/api/risk")
    print(f"  • http://{host}:{port}/api/sites")
    print(f"  • http://{host}:{port}/api/sites/TS-0001")
    print(f"  • http://{host}:{port}/api/detections/isolated")
    app.run(host=host, port=port, debug=False)
