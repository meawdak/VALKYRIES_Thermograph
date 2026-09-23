"""
THERMOGRAPH — Flask API Test Suite (Task T10)
Verifies all API endpoints against the SQLite database per TECH_SPEC §8 and TASKS.md T10:
  - GET /api/dashboard
  - GET /api/facilities
  - GET /api/anomalies
  - GET /api/risk
  - GET /api/sites
  - GET /api/sites/<site_id>
  - GET /api/detections/isolated
  - Error handling (404 for unknown sites, 503 for missing database)
"""

import json
import unittest
from pathlib import Path
import sys

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.app import create_app
from processing.config import (
    DB_PATH,
    EXPECTED_DETECTIONS,
    EXPECTED_FACILITIES,
)


class ThermographApiTestCase(unittest.TestCase):
    """Test suite for THERMOGRAPH Flask REST API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Create test client pointing to the processed database."""
        cls.app = create_app({"TESTING": True, "DB_PATH": DB_PATH})
        cls.client = cls.app.test_client()

    def test_root_index(self):
        """GET / returns 200 and serves the dashboard HTML."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn("THERMOGRAPH", content)
        self.assertIn("weekly-chart", content)
        res.close()

    def test_static_assets(self):
        """Verify static CSS, JS, and vendor assets are served locally without CDN."""
        asset_paths = [
            "/static/style.css",
            "/static/app.js",
            "/static/vendor/leaflet/leaflet.css",
            "/static/vendor/leaflet/leaflet.js",
            "/static/vendor/chartjs/chart.umd.min.js",
        ]
        for path in asset_paths:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Failed to serve {path}")
            data = res.get_data()
            self.assertGreater(len(data), 0, f"Empty content in {path}")
            res.close()

    # -------------------------------------------------------------------------
    # Test 1: GET /api/dashboard
    # -------------------------------------------------------------------------
    def test_get_dashboard(self):
        """GET /api/dashboard returns expected structure and verified counts."""
        res = self.client.get("/api/dashboard")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        # Check top-level keys
        self.assertIn("dataset_start", data)
        self.assertIn("dataset_end", data)
        self.assertIn("status_as_of", data)
        self.assertIn("baseline_period", data)
        self.assertIn("monitoring_period", data)
        self.assertIn("counts", data)
        self.assertIn("parameters", data)
        self.assertIn("simulated_included", data)
        self.assertFalse(data["simulated_included"])

        # Check date periods
        self.assertEqual(data["dataset_start"], "2025-07-01")
        self.assertEqual(data["dataset_end"], "2026-06-30")
        self.assertEqual(data["baseline_period"], ["2025-07-01", "2026-03-30"])
        self.assertEqual(data["monitoring_period"], ["2026-03-31", "2026-06-30"])

        # Check counts match check_outputs.py
        counts = data["counts"]
        self.assertEqual(counts["detections"], EXPECTED_DETECTIONS)
        self.assertEqual(counts["sites"], 568)
        self.assertEqual(counts["isolated_detections"], 10974)
        self.assertEqual(counts["facilities"], EXPECTED_FACILITIES)
        self.assertEqual(counts["sites_matched"], 13)
        self.assertEqual(counts["sites_unmapped"], 555)

        # Sites by class
        by_class = counts["sites_by_class"]
        self.assertEqual(by_class["PERSISTENT_INDUSTRIAL"], 4)
        self.assertEqual(by_class["PERSISTENT_UNMAPPED"], 36)
        self.assertEqual(by_class["EPISODIC_NEAR_FACILITY"], 9)
        self.assertEqual(by_class["EPISODIC_OTHER"], 519)

        # Sites by status
        by_status = counts["sites_by_status"]
        self.assertEqual(by_status["HIGH"], 10)
        self.assertEqual(by_status["MEDIUM"], 0)
        self.assertEqual(by_status["LOW"], 113)
        self.assertEqual(by_status["NORMAL"], 30)
        self.assertEqual(by_status["INSUFFICIENT_HISTORY"], 415)
        self.assertEqual(by_status["NEW_SITE_NO_ANOMALY"], 0)

        self.assertEqual(counts["anomalous_sites"], 123)
        self.assertEqual(counts["sites_normal"], 30)

        # Parameters dictionary from metadata table
        params = data["parameters"]
        self.assertIsInstance(params, dict)
        self.assertIn("cluster_eps_km", params)
        self.assertIn("anomaly_k", params)

    def test_get_dashboard_with_simulation(self):
        """GET /api/dashboard?include_simulated=1 includes simulated observations."""
        res = self.client.get("/api/dashboard?include_simulated=1")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertTrue(data["simulated_included"])
        counts = data["counts"]
        # Total detections includes 6 simulated detections (21,513 + 6 = 21,519)
        self.assertEqual(counts["detections"], EXPECTED_DETECTIONS + 6)
        # Anomalous sites count includes the simulated event site TS-0001 (123 + 1 = 124)
        self.assertEqual(counts["anomalous_sites"], 124)
        # Real status distribution in sites table remains unchanged
        self.assertEqual(counts["sites_by_status"]["NORMAL"], 30)

    # -------------------------------------------------------------------------
    # Test 2: GET /api/facilities
    # -------------------------------------------------------------------------
    def test_get_facilities(self):
        """GET /api/facilities returns GeoJSON FeatureCollection of 710 facilities."""
        res = self.client.get("/api/facilities")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertEqual(data.get("type"), "FeatureCollection")
        features = data.get("features", [])
        self.assertEqual(len(features), EXPECTED_FACILITIES)

        # Inspect first feature properties and geometry
        feat = features[0]
        self.assertEqual(feat["type"], "Feature")
        self.assertIn("geometry", feat)
        self.assertIn("type", feat["geometry"])
        self.assertIn("coordinates", feat["geometry"])

        props = feat["properties"]
        self.assertIn("facility_id", props)
        self.assertIn("display_name", props)
        self.assertIn("industrial", props)
        self.assertIn("landuse", props)
        self.assertTrue(len(props["display_name"]) > 0)

    # -------------------------------------------------------------------------
    # Test 3: GET /api/anomalies
    # -------------------------------------------------------------------------
    def test_get_anomalies_default(self):
        """GET /api/anomalies returns 160 real anomalies sorted newest first."""
        res = self.client.get("/api/anomalies")
        self.assertEqual(res.status_code, 200)
        anomalies = res.get_json()

        self.assertEqual(len(anomalies), 160)

        # Check sorting by week_index descending
        week_indices = [a["week_index"] for a in anomalies]
        self.assertEqual(week_indices, sorted(week_indices, reverse=True))

        # Check structure of each anomaly row
        first = anomalies[0]
        expected_fields = [
            "anomaly_id", "site_id", "week_index", "week_start", "week_end",
            "anomaly_type", "detection_count", "frp_sum", "frp_max",
            "score", "priority", "reasons", "is_simulated", "lat", "lon"
        ]
        for field in expected_fields:
            self.assertIn(field, first)

        self.assertIsInstance(first["reasons"], list)
        self.assertFalse(first["is_simulated"])

        # Spot-check TS-0035 week 40
        spot = [a for a in anomalies if a["site_id"] == "TS-0035" and a["week_index"] == 40]
        self.assertEqual(len(spot), 1)
        self.assertEqual(spot[0]["score"], 7)
        self.assertEqual(spot[0]["priority"], "HIGH")

    def test_get_anomalies_filtered_by_site(self):
        """GET /api/anomalies?site_id=TS-0035 filters by site; invalid site returns empty list."""
        # Valid site with anomalies
        res = self.client.get("/api/anomalies?site_id=TS-0035")
        self.assertEqual(res.status_code, 200)
        anoms = res.get_json()
        self.assertTrue(len(anoms) > 0)
        for a in anoms:
            self.assertEqual(a["site_id"], "TS-0035")

        # Unknown / inactive site returns empty list
        res_empty = self.client.get("/api/anomalies?site_id=NONEXISTENT_SITE")
        self.assertEqual(res_empty.status_code, 200)
        self.assertEqual(res_empty.get_json(), [])

    def test_get_anomalies_with_simulation(self):
        """GET /api/anomalies?include_simulated=1 returns 161 anomalies with 1 simulated."""
        res = self.client.get("/api/anomalies?include_simulated=1")
        self.assertEqual(res.status_code, 200)
        anomalies = res.get_json()

        self.assertEqual(len(anomalies), 161)
        sim_rows = [a for a in anomalies if a["is_simulated"]]
        self.assertEqual(len(sim_rows), 1)

        sim_anom = sim_rows[0]
        self.assertEqual(sim_anom["site_id"], "TS-0001")
        self.assertEqual(sim_anom["week_index"], 52)
        self.assertTrue(all(r.startswith("[SIMULATED]") for r in sim_anom["reasons"]))

    # -------------------------------------------------------------------------
    # Test 4: GET /api/risk
    # -------------------------------------------------------------------------
    def test_get_risk_default(self):
        """GET /api/risk returns 123 unique anomalous sites ranked by score descending."""
        res = self.client.get("/api/risk")
        self.assertEqual(res.status_code, 200)
        risk_list = res.get_json()

        # 123 distinct real anomalous sites
        self.assertEqual(len(risk_list), 123)

        # Unique sites check
        site_ids = [item["site_id"] for item in risk_list]
        self.assertEqual(len(site_ids), len(set(site_ids)))

        # Consecutive ranks 1..123
        ranks = [item["rank"] for item in risk_list]
        self.assertEqual(ranks, list(range(1, 124)))

        # Score ordering check: score must be monotonically non-increasing
        scores = [item["score"] for item in risk_list]
        self.assertEqual(scores, sorted(scores, reverse=True))

        # Check first item schema
        top = risk_list[0]
        expected_keys = [
            "rank", "site_id", "lat", "lon", "priority", "score",
            "anomaly_type", "week_start", "facility_display_name", "top_reason",
            "is_simulated"
        ]
        for k in expected_keys:
            self.assertIn(k, top)

        self.assertEqual(top["rank"], 1)
        self.assertTrue(len(top["top_reason"]) > 0)
        self.assertFalse(top["is_simulated"])

    def test_get_risk_with_simulation(self):
        """GET /api/risk?include_simulated=1 has 1 extra simulated row (124 total)."""
        res = self.client.get("/api/risk?include_simulated=1")
        self.assertEqual(res.status_code, 200)
        risk_list = res.get_json()

        # Exactly 1 extra simulated row
        self.assertEqual(len(risk_list), 124)

        # Exactly 1 row has is_simulated = True
        sim_rows = [item for item in risk_list if item["is_simulated"]]
        self.assertEqual(len(sim_rows), 1)

        sim_item = sim_rows[0]
        self.assertEqual(sim_item["site_id"], "TS-0001")
        self.assertTrue(sim_item["top_reason"].startswith("[SIMULATED]"))

    # -------------------------------------------------------------------------
    # Test 5: GET /api/sites and GET /api/sites/<site_id>
    # -------------------------------------------------------------------------
    def test_get_sites_registry(self):
        """GET /api/sites returns all 568 sites with required fields."""
        res = self.client.get("/api/sites")
        self.assertEqual(res.status_code, 200)
        sites = res.get_json()

        self.assertEqual(len(sites), 568)
        first = sites[0]
        self.assertEqual(first["site_id"], "TS-0001")
        self.assertIn("lat", first)
        self.assertIn("lon", first)
        self.assertIn("site_class", first)
        self.assertIn("status", first)
        self.assertIn("n_detections", first)
        self.assertIn("facility_display_name", first)
        self.assertIn("match_type", first)

    def test_get_site_detail_ts0001(self):
        """GET /api/sites/TS-0001 returns complete detail with 52 weekly records."""
        res = self.client.get("/api/sites/TS-0001")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertIn("site", data)
        self.assertIn("facility", data)
        self.assertIn("baseline", data)
        self.assertIn("weekly", data)
        self.assertIn("anomalies", data)

        self.assertEqual(data["site"]["site_id"], "TS-0001")
        self.assertIsNotNone(data["facility"])
        self.assertEqual(data["facility"]["facility_id"], "way/104647203")
        self.assertEqual(data["facility"]["osm_url"], "https://www.openstreetmap.org/way/104647203")

        # Baseline details
        self.assertEqual(data["baseline"]["established"], 1)
        self.assertEqual(data["baseline"]["n_weeks"], 39)

        # Weekly history: exactly 52 weeks (0–51)
        weekly = data["weekly"]
        self.assertEqual(len(weekly), 52)
        self.assertEqual(weekly[0]["week_index"], 0)
        self.assertEqual(weekly[51]["week_index"], 51)

    def test_get_site_detail_ts0001_with_simulation(self):
        """GET /api/sites/TS-0001?include_simulated=1 includes week 52 simulated row."""
        res = self.client.get("/api/sites/TS-0001?include_simulated=1")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        weekly = data["weekly"]
        self.assertEqual(len(weekly), 53)
        self.assertEqual(weekly[52]["week_index"], 52)
        self.assertTrue(weekly[52]["is_simulated"])

        anoms = data["anomalies"]
        self.assertTrue(any(a["is_simulated"] for a in anoms))

    def test_get_site_detail_not_found(self):
        """GET /api/sites/<unknown> returns 404 with error message."""
        res = self.client.get("/api/sites/TS-9999")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data.get("error"), "site not found")

    # -------------------------------------------------------------------------
    # Test 6: GET /api/detections/isolated
    # -------------------------------------------------------------------------
    def test_get_isolated_detections(self):
        """GET /api/detections/isolated returns 10,974 coordinate pairs."""
        res = self.client.get("/api/detections/isolated")
        self.assertEqual(res.status_code, 200)
        coords = res.get_json()

        self.assertEqual(len(coords), 10974)
        first = coords[0]
        self.assertIsInstance(first, list)
        self.assertEqual(len(first), 2)
        self.assertIsInstance(first[0], float)
        self.assertIsInstance(first[1], float)

    # -------------------------------------------------------------------------
    # Test 7: Error handling for missing database
    # -------------------------------------------------------------------------
    def test_missing_database_graceful_error(self):
        """Missing database returns HTTP 503 Service Unavailable."""
        missing_db_path = ROOT / "output" / "nonexistent_thermograph.db"
        bad_app = create_app({"TESTING": True, "DB_PATH": missing_db_path})
        bad_client = bad_app.test_client()

        res = bad_client.get("/api/dashboard")
        self.assertEqual(res.status_code, 503)
        data = res.get_json()
        self.assertEqual(data.get("error"), "database_not_found")
        self.assertIn("message", data)


if __name__ == "__main__":
    unittest.main()
