import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import app as backend


VALID_READING = {
    "card_id": "CARD01",
    "lat": 11.1523,
    "lng": 7.6532,
    "sats": 8,
    "hdop": 1.4,
    "batt_mv": 4010,
    "seq": 1,
    "rssi": 24,
    "snr": 0,
    "src": "gps",
    "acc": 0,
    "age_s": 0,
}


class BackendSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        backend.DB_PATH = Path(self.temp_dir.name) / "tracking.db"
        backend.init_db()
        backend.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        backend._last_ingest_at.clear()
        backend._last_heartbeat_at.clear()
        self.client = backend.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self):
        response = self.client.post(
            "/login", json={"username": backend.ADMIN_USER, "password": backend.ADMIN_PASS}
        )
        self.assertEqual(response.status_code, 200)

    def ingest(self, payload=None, key=None):
        return self.client.post(
            "/api/ingest",
            json=payload or VALID_READING,
            headers={"X-Device-Key": key if key is not None else backend.DEVICE_API_KEY},
        )

    def test_sensitive_api_requires_login(self):
        response = self.client.get("/api/students")
        self.assertEqual(response.status_code, 401)

    def test_login_preserves_dashboard_api_access(self):
        self.login()
        response = self.client.get("/api/students")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()), 5)

    def test_docs_and_openapi_require_login(self):
        self.assertEqual(self.client.get("/openapi.json").status_code, 302)
        self.assertEqual(self.client.get("/docs/").status_code, 302)
        self.login()
        spec = self.client.get("/openapi.json")
        docs = self.client.get("/docs/")
        try:
            self.assertEqual(spec.status_code, 200)
            self.assertEqual(docs.status_code, 200)
        finally:
            spec.close()
            docs.close()

    def test_student_detail_returns_the_assigned_card(self):
        self.login()
        student = self.client.get("/api/student/U19CO1011").get_json()
        self.assertEqual(student["card_id"], "CARD01")

    def test_socket_requires_authenticated_session(self):
        anonymous = backend.socketio.test_client(backend.app, flask_test_client=self.client)
        self.assertFalse(anonymous.is_connected())
        self.login()
        authenticated = backend.socketio.test_client(backend.app, flask_test_client=self.client)
        self.assertTrue(authenticated.is_connected())
        self.assertEqual(self.ingest().status_code, 200)
        events = authenticated.get_received()
        self.assertIn("location_update", [event["name"] for event in events])
        authenticated.disconnect()

    def test_ingest_rejects_missing_device_key(self):
        response = self.ingest(key="")
        self.assertEqual(response.status_code, 401)

    def test_ingest_rejects_unknown_card_before_storage(self):
        payload = dict(VALID_READING, card_id="<img src=x onerror=alert(1)>")
        response = self.ingest(payload)
        self.assertEqual(response.status_code, 403)
        conn = sqlite3.connect(backend.DB_PATH)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 0)
        finally:
            conn.close()

    def test_ingest_rejects_invalid_source_and_coordinates(self):
        self.assertEqual(self.ingest(dict(VALID_READING, src="<script>bad</script>")).status_code, 400)
        self.assertEqual(self.ingest(dict(VALID_READING, lat=191)).status_code, 400)
        self.assertEqual(self.ingest(dict(VALID_READING, sats=4.5)).status_code, 400)

    def test_valid_card_report_is_stored(self):
        response = self.ingest()
        self.assertEqual(response.status_code, 200)
        conn = sqlite3.connect(backend.DB_PATH)
        try:
            card_id, source = conn.execute(
                "SELECT card_id, src FROM readings ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual((card_id, source), ("CARD01", "gps"))

    def test_zero_battery_voltage_means_reading_unavailable(self):
        response = self.ingest(dict(VALID_READING, batt_mv=0, seq=9001))
        self.assertEqual(response.status_code, 200)

    def test_implausible_nonzero_battery_voltage_is_rejected(self):
        response = self.ingest(dict(VALID_READING, batt_mv=1200, seq=9002))
        self.assertEqual(response.status_code, 400)

    def test_ingest_rate_limit_and_query_limit(self):
        self.assertEqual(self.ingest().status_code, 200)
        self.assertEqual(self.ingest().status_code, 429)
        self.login()
        self.assertEqual(self.client.get("/api/history?limit=-1").status_code, 400)

    def test_buffered_fix_keeps_capture_time_and_bypasses_live_rate_limit(self):
        self.assertEqual(self.ingest().status_code, 200)
        captured = int((datetime.now(timezone.utc) - timedelta(minutes=3)).timestamp())
        buffered = dict(VALID_READING, seq=2, buffered=True, captured_epoch=captured)
        self.assertEqual(self.ingest(buffered).status_code, 200)
        conn = sqlite3.connect(backend.DB_PATH)
        try:
            device_ts, is_buffered = conn.execute(
                "SELECT device_ts, buffered FROM readings ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(is_buffered, 1)
        self.assertAlmostEqual(backend.parse_ts(device_ts).timestamp(), captured, delta=1)

        # Delayed history must remain stored without replacing the position
        # shown as live merely because it arrived after the current packet.
        self.login()
        latest = self.client.get("/api/student/U19CO1011").get_json()["latest"]
        self.assertEqual(latest["seq"], VALID_READING["seq"])
        self.assertEqual(latest["buffered"], 0)

    def test_stop_detection_collapses_stationary_jitter_to_one_beacon(self):
        start = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)
        points = []
        for index in range(8):
            points.append({
                "lat": 11.1523 + ((index % 3) - 1) * 0.00005,
                "lng": 7.6532 + ((index % 2) * 0.00004),
                "segment": 0,
                "ts": (start + timedelta(seconds=index * 20)).isoformat(),
            })
        ranges = backend.find_stop_ranges(points)
        stops = [item[2] for item in ranges]
        collapsed = backend.collapse_stationary_points(points, ranges)
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["duration_s"], 140)
        self.assertEqual(len(collapsed), 2)
        self.assertEqual(collapsed[0]["lat"], collapsed[1]["lat"])
        self.assertEqual(collapsed[0]["lng"], collapsed[1]["lng"])
        self.assertEqual(collapsed[0]["stop_phase"], "arrival")
        self.assertEqual(collapsed[1]["stop_phase"], "departure")

    def test_geofence_crossing_creates_alert(self):
        self.assertEqual(self.ingest().status_code, 200)
        backend._last_ingest_at.clear()
        outside = dict(VALID_READING, lat=11.18, seq=3)
        self.assertEqual(self.ingest(outside).status_code, 200)
        self.login()
        alerts = self.client.get("/api/alerts").get_json()
        self.assertEqual(alerts[0]["kind"], "geofence_left")

    def test_route_exports_are_downloadable(self):
        self.assertEqual(self.ingest().status_code, 200)
        self.login()
        csv_response = self.client.get("/api/student/U19CO1011/track.csv")
        pdf_response = self.client.get("/api/student/U19CO1011/report.pdf")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response.content_type)
        self.assertIn(b"capture_time", csv_response.data)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertTrue(pdf_response.data.startswith(b"%PDF-1.4"))

    def test_health_endpoint_reports_core_services(self):
        self.login()
        response = self.client.get("/api/system/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["backend"]["ok"])
        self.assertTrue(data["database"]["ok"])


if __name__ == "__main__":
    unittest.main()
