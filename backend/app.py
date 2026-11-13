"""
SIID-01 backend — receives authenticated location packets from the LilyGO
cellular card, stores them in SQLite, and pushes live updates to authenticated
dashboard clients with Socket.IO.

Run with no hardware using the presentation simulator:
    python app.py --simulate

Then open http://localhost:5000
"""
import argparse
import csv
import hmac
import html
import io
import json
import math
import os
import random
import secrets
import sqlite3
import statistics
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session
from flask_socketio import SocketIO
from flask_swagger_ui import get_swaggerui_blueprint

DB_PATH = Path(__file__).parent / "tracking.db"
DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"
STATIC_DIR = DASHBOARD_DIR / "static"

app = Flask(__name__, static_folder=None)

# Security configuration. Demo mode remains the zero-setup path for presentation
# day, but production mode refuses to start without externally supplied secrets.
DEMO_MODE = os.environ.get("SIID_DEMO_MODE", "1") == "1"
app.secret_key = os.environ.get("SIID_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=4096,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not DEMO_MODE,
)

# With no explicit CORS override Flask-SocketIO enforces same-origin connections.
socketio = SocketIO(app, async_mode="threading")

# ---- demo admin login ------------------------------------------------------
ADMIN_USER = os.environ.get("SIID_ADMIN_USER") or ("admin" if DEMO_MODE else "")
ADMIN_PASS = os.environ.get("SIID_ADMIN_PASSWORD") or ("abu2026" if DEMO_MODE else "")
DEVICE_API_KEY = os.environ.get("SIID_DEVICE_API_KEY") or (
    "siid-card-demo-2026" if DEMO_MODE else ""
)


def validate_security_config():
    if DEMO_MODE:
        print("WARNING: SIID demo mode is active. Use only consenting/test data.")
        return
    missing = [name for name, value in (
        ("SIID_ADMIN_USER", ADMIN_USER),
        ("SIID_ADMIN_PASSWORD", ADMIN_PASS),
        ("SIID_DEVICE_API_KEY", DEVICE_API_KEY),
    ) if not value]
    if missing:
        raise RuntimeError("Missing production security settings: " + ", ".join(missing))

# ---- demo student roster ---------------------------------------------------
# Five 500-level Computer Engineering students. Only U19CO1011 carries the real
# tracked card (CARD01) — the others are registered but have no device, which is
# exactly the demo story: one physical board, a full-looking roster around it.
STUDENTS = [
    {"reg_no": "U19CO1011", "name": "Delight Iworima", "card_id": "CARD01",
     "phone": "0803 000 1011", "hall": "Suleiman Hall"},
    {"reg_no": "U19CO1007", "name": "Aisha Bello",    "card_id": None,
     "phone": "0806 000 1007", "hall": "Amina Hall"},
    {"reg_no": "U19CO1019", "name": "Chinedu Okafor", "card_id": None,
     "phone": "0813 000 1019", "hall": "Ribadu Hall"},
    {"reg_no": "U19CO1023", "name": "Fatima Sani",    "card_id": None,
     "phone": "0809 000 1023", "hall": "Amina Hall"},
    {"reg_no": "U19CO1042", "name": "Emeka Nwosu",    "card_id": None,
     "phone": "0701 000 1042", "hall": "Akenzua Hall"},
]
for _s in STUDENTS:
    _s.update(programme="Computer Engineering", level="500",
              faculty="Faculty of Engineering", session="2024/2025")

REG_TO_STUDENT = {s["reg_no"]: s for s in STUDENTS}
CARD_TO_REG = {s["card_id"]: s["reg_no"] for s in STUDENTS if s["card_id"]}

# A cell-tower lookup in the A7670 modem can legitimately block for up to two
# minutes. Keep the card online through one lookup, while still marking a truly
# disconnected device offline after three minutes without a report.
ONLINE_WINDOW_S = 180

# Minimum movement between two fixes to count as real travel rather than GPS
# jitter. Consumer GNSS typically wanders 1-8 m while completely stationary.
MOVEMENT_THRESHOLD_M = 10

# Route refinement. Raw GNSS rows remain untouched in SQLite; these rules only
# produce a cleaner display/analysis track from trustworthy fixes.
TRACK_MAX_PDOP = 8.0
TRACK_MIN_SATS = 4
TRACK_SESSION_GAP_S = 180
TRACK_MIN_POINT_SPACING_M = 4.0
TRACK_STOP_RADIUS_M = 28.0
TRACK_STOP_MIN_S = 90
TRACK_STOP_EXIT_POINTS = 3
LAGOS_UTC_OFFSET = timedelta(hours=1)
STARTED_AT = datetime.now(timezone.utc)

VALID_POSITION_SOURCES = {"gps", "gps_hold", "ble", "cell", "test"}
INGEST_MIN_INTERVAL_S = 1.0
_last_ingest_at = {}
_last_heartbeat_at = {}
_ingest_lock = threading.Lock()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            sats INTEGER,
            hdop REAL,
            batt_mv INTEGER,
            seq INTEGER,
            rssi INTEGER,
            snr REAL,
            ts TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_readings_card_id_id "
        "ON readings(card_id, id)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS device_status (
            card_id TEXT PRIMARY KEY,
            last_seen TEXT NOT NULL,
            rssi INTEGER,
            batt_mv INTEGER,
            seq INTEGER
        )
    """)
    # Added later: how the position was obtained ("gps" = satellites, "cell" =
    # cell-tower/LBS fallback used indoors, "test" = bench mode) and the
    # estimated accuracy in metres for coarse cell fixes. Guarded so existing
    # databases upgrade cleanly instead of erroring.
    for col, decl in (("src", "TEXT"), ("acc", "INTEGER"), ("age_s", "INTEGER")):
        try:
            conn.execute(f"ALTER TABLE readings ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass  # column already present
    for col, decl in (("device_ts", "TEXT"), ("buffered", "INTEGER DEFAULT 0")):
        try:
            conn.execute(f"ALTER TABLE readings ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geofences (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL,
            center_lat REAL NOT NULL,
            center_lng REAL NOT NULL,
            radius_m INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO geofences
            (id, name, center_lat, center_lng, radius_m, enabled, updated_at)
        VALUES (1, 'Demonstration safety zone', 11.1523, 7.6532, 500, 1, ?)
    """, (datetime.now(timezone.utc).isoformat(),))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geofence_state (
            card_id TEXT PRIMARY KEY,
            is_inside INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL,
            lat REAL,
            lng REAL,
            ts TEXT NOT NULL,
            acknowledged INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts DESC)"
    )
    conn.commit()
    conn.close()


def store_reading(reading: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO readings (card_id, lat, lng, sats, hdop, batt_mv, seq, rssi, snr, ts, src, acc, age_s, device_ts, buffered) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            reading.get("card_id"),
            reading.get("lat"),
            reading.get("lng"),
            reading.get("sats"),
            reading.get("hdop"),
            reading.get("batt_mv"),
            reading.get("seq"),
            reading.get("rssi"),
            reading.get("snr"),
            reading["ts"],
            reading.get("src"),
            reading.get("acc"),
            reading.get("age_s"),
            reading.get("device_ts"),
            1 if reading.get("buffered") else 0,
        ),
    )
    conn.commit()
    conn.close()


def store_device_status(status: dict):
    """Record that a card is communicating, independently of GPS availability."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO device_status (card_id, last_seen, rssi, batt_mv, seq)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(card_id) DO UPDATE SET
             last_seen=excluded.last_seen,
             rssi=excluded.rssi,
             batt_mv=excluded.batt_mv,
             seq=excluded.seq""",
        (status["card_id"], status["ts"], status.get("rssi"),
         status.get("batt_mv"), status.get("seq")),
    )
    conn.commit()
    conn.close()


def get_geofence():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM geofences WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else None


def evaluate_geofence(reading):
    """Create an alert when a live satellite fix crosses the configured edge."""
    if reading.get("src") not in {"gps", "ble"}:
        return
    fence = get_geofence()
    if not fence or not fence["enabled"]:
        return
    distance_m = haversine_m(
        fence["center_lat"], fence["center_lng"], reading["lat"], reading["lng"]
    )
    inside = distance_m <= fence["radius_m"]
    conn = sqlite3.connect(DB_PATH)
    previous = conn.execute(
        "SELECT is_inside FROM geofence_state WHERE card_id = ?", (reading["card_id"],)
    ).fetchone()
    conn.execute(
        """INSERT INTO geofence_state (card_id, is_inside, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(card_id) DO UPDATE SET
             is_inside=excluded.is_inside, updated_at=excluded.updated_at""",
        (reading["card_id"], 1 if inside else 0, reading["ts"]),
    )
    alert = None
    if previous is not None and bool(previous[0]) != inside:
        action = "entered" if inside else "left"
        message = f"{reading['card_id']} {action} {fence['name']}."
        cursor = conn.execute(
            """INSERT INTO alerts (card_id, kind, message, lat, lng, ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (reading["card_id"], f"geofence_{action}", message,
             reading["lat"], reading["lng"], reading["ts"]),
        )
        alert = {
            "id": cursor.lastrowid,
            "card_id": reading["card_id"],
            "reg_no": CARD_TO_REG.get(reading["card_id"]),
            "kind": f"geofence_{action}",
            "message": message,
            "lat": reading["lat"], "lng": reading["lng"],
            "ts": reading["ts"], "acknowledged": 0,
        }
    conn.commit()
    conn.close()
    if alert:
        socketio.emit("geofence_alert", alert)


def handle_reading(raw: dict):
    """Shared by both the real serial reader and the simulator so the two
    code paths are guaranteed to produce identical events for the dashboard."""
    if "error" in raw or "status" in raw:
        print("[position source]", raw)
        return
    raw["ts"] = datetime.now(timezone.utc).isoformat()
    store_reading(raw)
    store_device_status(raw)
    # Tag the live event with the student this card belongs to, so the track
    # page can filter updates by registration number.
    raw["reg_no"] = CARD_TO_REG.get(raw.get("card_id"))
    if not raw.get("buffered"):
        evaluate_geofence(raw)
        socketio.emit("location_update", raw)
    else:
        socketio.emit("history_synced", {
            "card_id": raw.get("card_id"),
            "reg_no": raw.get("reg_no"),
        })
    print(f"[{raw['ts']}] {raw['card_id']} -> {raw['lat']:.6f},{raw['lng']:.6f}  "
          f"rssi={raw.get('rssi')} snr={raw.get('snr')}")


def serial_reader(port: str, baud: int):
    import serial  # imported here so --simulate mode doesn't require pyserial installed

    print(f"Opening {port} @ {baud}...")
    with serial.Serial(port, baud, timeout=1) as ser:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            try:
                handle_reading(json.loads(line))
            except json.JSONDecodeError:
                print("Ignoring malformed line:", line)


def simulator(center_lat: float, center_lng: float, card_id: str):
    """Fakes a card walking a slow loop, one fix every ~2s, so the backend
    and dashboard can be built and proven before hardware parts arrive."""
    print(f"Simulating {card_id} walking around ({center_lat}, {center_lng})")
    angle = 0.0
    seq = 0
    radius_deg = 0.0009  # roughly a 100m-radius loop at this latitude
    while True:
        lat = center_lat + radius_deg * math.cos(angle) * random.uniform(0.9, 1.1)
        lng = center_lng + radius_deg * math.sin(angle) * random.uniform(0.9, 1.1)
        angle += 0.25
        reading = {
            "card_id": card_id,
            "lat": lat,
            "lng": lng,
            "sats": random.randint(6, 11),
            "hdop": round(random.uniform(0.8, 1.8), 1),
            "batt_mv": random.randint(3700, 4100),
            "seq": seq,
            "rssi": random.randint(16, 31),   # cellular signal quality (CSQ 0-31), matches the real card
            "snr": 0.0,
            "src": "gps",
            "acc": 0,
        }
        seq += 1
        handle_reading(reading)
        time.sleep(2)


# ---- helpers ---------------------------------------------------------------
def is_authed():
    return session.get("user") is not None


@app.before_request
def protect_sensitive_interfaces():
    """Keep the page login and its underlying data interfaces equivalent."""
    path = request.path
    device_routes = {"/api/ingest", "/api/heartbeat"}
    if path.startswith("/api/") and path not in device_routes and not is_authed():
        return jsonify({"error": "authentication required"}), 401
    if (path == "/openapi.json" or path.startswith("/docs")) and not is_authed():
        return redirect("/login")


@socketio.on("connect")
def authorize_socket():
    if not is_authed():
        return False


def bounded_query_int(name, default, minimum, maximum):
    raw = request.args.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, (jsonify({"error": f"{name} must be an integer"}), 400)
    if not minimum <= value <= maximum:
        return None, (jsonify({"error": f"{name} must be between {minimum} and {maximum}"}), 400)
    return value, None


def optional_number(data, name, cast, minimum, maximum):
    value = data.get(name)
    if value is None:
        return None
    if cast is int:
        if isinstance(value, bool):
            raise ValueError(name)
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(name)
        value = int(value)
    else:
        value = cast(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(name)
    if not minimum <= value <= maximum:
        raise ValueError(name)
    return value


def parse_ts(ts):
    if isinstance(ts, datetime):
        value = ts
    else:
        value = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def reading_time(point):
    """Time the fix was captured, falling back to server receipt time."""
    return parse_ts(point.get("device_ts") or point["ts"])


def age_seconds(ts):
    return (datetime.now(timezone.utc) - parse_ts(ts)).total_seconds()


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def refine_track_points(rows, selected_day=None, selected_session=None):
    """Reject bad GNSS points, split separate sessions and smooth display points.

    This never rewrites the evidence in the database. Each returned point keeps
    raw_lat/raw_lng alongside its display lat/lng so the transformation remains
    explainable during the defence.
    """
    raw = sorted((dict(row) for row in rows), key=reading_time)
    quality = [
        point for point in raw
        if point.get("sats") is not None
        and point["sats"] >= TRACK_MIN_SATS
        and point.get("hdop") is not None
        and 0 < point["hdop"] <= TRACK_MAX_PDOP
    ]
    available_days = sorted({
        (reading_time(point) + LAGOS_UTC_OFFSET).date().isoformat()
        for point in quality
    }, reverse=True)
    if not quality:
        return [], {
            "raw_count": len(raw), "quality_count": 0, "rejected": len(raw),
            "days": [], "sessions": [], "day": selected_day,
        }

    # Route playback is a day view. Default to the latest Lagos calendar day,
    # while allowing the dashboard to request a previous recorded day.
    target_day = selected_day or available_days[0]
    daily_quality = [
        point for point in quality
        if (reading_time(point) + LAGOS_UTC_OFFSET).date().isoformat() == target_day
    ]

    session_groups = []
    for point in daily_quality:
        if (not session_groups
                or (reading_time(point) - reading_time(session_groups[-1][-1])).total_seconds()
                > TRACK_SESSION_GAP_S):
            session_groups.append([])
        session_groups[-1].append(point)

    # A single isolated fix cannot form a route or a replay. Keep it in SQLite,
    # but leave it out of the walk selector when a real multi-point walk exists.
    multi_point_sessions = [group for group in session_groups if len(group) >= 2]
    if multi_point_sessions:
        discarded_singletons = len(session_groups) - len(multi_point_sessions)
        session_groups = multi_point_sessions
    else:
        discarded_singletons = 0

    session_info = []
    for index, group in enumerate(session_groups):
        session_info.append({
            "id": index,
            "from": reading_time(group[0]).isoformat(),
            "to": reading_time(group[-1]).isoformat(),
            "count": len(group),
            "duration_s": max(0, int((reading_time(group[-1]) - reading_time(group[0])).total_seconds())),
        })

    indexed_points = [
        (session_index, point)
        for session_index, group in enumerate(session_groups)
        for point in group
        if selected_session is None or session_index == selected_session
    ]

    accepted = []
    segment = None
    last_time = None
    last_raw = None
    last_smooth = None
    rejected_outliers = 0

    for source_segment, point in indexed_points:
        current_time = reading_time(point)
        raw_lat, raw_lng = float(point["lat"]), float(point["lng"])
        elapsed = (current_time - last_time).total_seconds() if last_time else None
        new_segment = segment != source_segment or last_time is None or elapsed <= 0

        if new_segment:
            segment = source_segment
            smooth_lat, smooth_lng = raw_lat, raw_lng
            last_raw = (raw_lat, raw_lng)
            last_smooth = (smooth_lat, smooth_lng)
        else:
            distance = haversine_m(last_raw[0], last_raw[1], raw_lat, raw_lng)
            speed_kmh = distance / elapsed * 3.6

            # Lower-quality fixes are allowed less sudden movement. This keeps
            # legitimate walking/cycling but removes the characteristic GNSS
            # teleport-and-return spikes seen in the recorded data.
            pdop = float(point["hdop"])
            plausible_kmh = 45.0 if pdop <= 4 else 30.0 if pdop <= 6 else 20.0
            if distance >= 25.0 and speed_kmh > plausible_kmh:
                rejected_outliers += 1
                continue

            # A few metres of movement is normal stationary GNSS wander. Do not
            # turn it into a visible waypoint or phantom travelled distance.
            if distance < TRACK_MIN_POINT_SPACING_M:
                continue

            # Adaptive exponential smoothing: strong smoothing for a weak fix,
            # lighter smoothing for a strong one so genuine turns remain visible.
            alpha = 0.62 if pdop <= 2 else 0.48 if pdop <= 4 else 0.34 if pdop <= 6 else 0.24
            smooth_lat = last_smooth[0] + alpha * (raw_lat - last_smooth[0])
            smooth_lng = last_smooth[1] + alpha * (raw_lng - last_smooth[1])
            last_raw = (raw_lat, raw_lng)
            last_smooth = (smooth_lat, smooth_lng)

        refined = dict(point)
        refined["raw_lat"] = raw_lat
        refined["raw_lng"] = raw_lng
        refined["lat"] = round(smooth_lat, 7)
        refined["lng"] = round(smooth_lng, 7)
        refined["segment"] = segment
        refined["capture_ts"] = current_time.isoformat()
        accepted.append(refined)
        last_time = current_time

    return accepted, {
        "raw_count": len(raw),
        "quality_count": len(daily_quality),
        "rejected": len(raw) - len(accepted),
        "outliers": rejected_outliers,
        "segments": len({point["segment"] for point in accepted}),
        "day": target_day,
        "days": available_days,
        "sessions": session_info,
        "selected_session": selected_session,
        "discarded_singletons": discarded_singletons,
    }


def find_stop_ranges(points):
    """Find sustained stationary runs while tolerating occasional GNSS jumps.

    A stationary receiver can wander tens of metres and briefly jump outside
    the main cluster. Median centres prevent those jumps dragging the stop
    location around, while requiring three consecutive points outside the
    radius prevents a genuine departure being swallowed as noise.
    """
    ranges = []
    index = 0
    while index < len(points):
        member_indices = [index]
        pending_outside = []
        center_lat = float(points[index]["lat"])
        center_lng = float(points[index]["lng"])
        cursor = index + 1
        while cursor < len(points) and points[cursor]["segment"] == points[index]["segment"]:
            candidate = points[cursor]
            distance = haversine_m(
                center_lat, center_lng, candidate["lat"], candidate["lng"]
            )
            if distance <= TRACK_STOP_RADIUS_M:
                # One or two excursions that return to the cluster are GPS
                # noise, so keep them inside this stationary run.
                member_indices.extend(pending_outside)
                pending_outside.clear()
                member_indices.append(cursor)
                members = [points[item_index] for item_index in member_indices]
                center_lat = statistics.median(float(item["lat"]) for item in members)
                center_lng = statistics.median(float(item["lng"]) for item in members)
            else:
                pending_outside.append(cursor)
                if len(pending_outside) >= TRACK_STOP_EXIT_POINTS:
                    break
            cursor += 1

        members = [points[item_index] for item_index in member_indices]
        duration_s = int((reading_time(members[-1]) - reading_time(members[0])).total_seconds())
        if duration_s >= TRACK_STOP_MIN_S:
            center_lat = statistics.median(float(item["lat"]) for item in members)
            center_lng = statistics.median(float(item["lng"]) for item in members)
            stop = {
                "lat": round(center_lat, 7),
                "lng": round(center_lng, 7),
                "from": reading_time(members[0]).isoformat(),
                "to": reading_time(members[-1]).isoformat(),
                "duration_s": duration_s,
                "point_count": len(members),
                "segment": points[index]["segment"],
            }
            ranges.append((index, member_indices[-1], stop))
            index = member_indices[-1] + 1
        else:
            index += 1
    return ranges


def detect_stops(points):
    """Public stop summary used by the API and tests."""
    return [stop for _start, _end, stop in find_stop_ranges(points)]


def collapse_stationary_points(points, stop_ranges):
    """Replace every stationary cloud with two identical centre points.

    Keeping an arrival and departure timestamp preserves the stopped duration
    for replay/statistics, while their identical coordinates draw no loops.
    The original points remain untouched in SQLite as evidence.
    """
    by_start = {start: (end, stop) for start, end, stop in stop_ranges}
    collapsed = []
    index = 0
    while index < len(points):
        match = by_start.get(index)
        if not match:
            collapsed.append(points[index])
            index += 1
            continue

        end, stop = match
        for source_index, phase in ((index, "arrival"), (end, "departure")):
            representative = dict(points[source_index])
            representative["lat"] = stop["lat"]
            representative["lng"] = stop["lng"]
            representative["stationary"] = True
            representative["stop_phase"] = phase
            representative["stop_duration_s"] = stop["duration_s"]
            representative["stop_end_ts"] = stop["to"]
            collapsed.append(representative)
        index = end + 1
    return collapsed


def calculate_track_stats(points, refinement, stops=None):
    total_m = 0.0
    max_kmh = 0.0
    duration_s = 0
    for point in points:
        point["dist_m"] = round(total_m)
    for index in range(1, len(points)):
        previous, current = points[index - 1], points[index]
        if previous["segment"] != current["segment"]:
            continue
        distance = haversine_m(previous["lat"], previous["lng"], current["lat"], current["lng"])
        elapsed = (reading_time(current) - reading_time(previous)).total_seconds()
        if distance < MOVEMENT_THRESHOLD_M:
            distance = 0.0
        total_m += distance
        if elapsed > 0:
            duration_s += int(elapsed)
            speed_kmh = distance / elapsed * 3.6
            if speed_kmh < 200:
                max_kmh = max(max_kmh, speed_kmh)
        current["dist_m"] = round(total_m)

    stops = detect_stops(points) if stops is None else stops
    stopped_s = min(duration_s, sum(stop["duration_s"] for stop in stops))
    moving_s = max(0, duration_s - stopped_s)
    average_basis = moving_s or duration_s
    avg_kmh = total_m / average_basis * 3.6 if average_basis else 0.0
    return {
        "count": len(points),
        "distance_m": round(total_m),
        "duration_s": duration_s,
        "moving_time_s": moving_s,
        "stopped_time_s": stopped_s,
        "stop_count": len(stops),
        "avg_kmh": round(avg_kmh, 1),
        "max_kmh": round(max_kmh, 1),
        "from": reading_time(points[0]).isoformat() if points else None,
        "to": reading_time(points[-1]).isoformat() if points else None,
        "refinement": refinement,
    }, stops


def build_track_payload(student, limit=1000, selected_day=None, selected_session=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM readings WHERE card_id = ? AND src = 'gps' "
        "ORDER BY id DESC LIMIT ?",
        (student["card_id"], limit),
    ).fetchall()
    conn.close()
    refined_points, refinement = refine_track_points(rows, selected_day, selected_session)
    stop_ranges = find_stop_ranges(refined_points)
    stops = [stop for _start, _end, stop in stop_ranges]
    points = collapse_stationary_points(refined_points, stop_ranges)
    refinement["stationary_points_collapsed"] = max(0, len(refined_points) - len(points))
    refinement["stops_collapsed"] = len(stops)
    stats, _ = calculate_track_stats(points, refinement, stops)
    return {"points": points, "stops": stops, "stats": stats}


def track_request_options():
    selected_day = (request.args.get("date") or "").strip() or None
    if selected_day:
        try:
            if datetime.strptime(selected_day, "%Y-%m-%d").date().isoformat() != selected_day:
                raise ValueError
        except ValueError:
            return None, None, (jsonify({"error": "date must use YYYY-MM-DD"}), 400)

    raw_session = (request.args.get("session") or "all").strip().lower()
    if raw_session in {"", "all"}:
        selected_session = None
    else:
        try:
            selected_session = int(raw_session)
            if not 0 <= selected_session <= 999:
                raise ValueError
        except ValueError:
            return None, None, (jsonify({"error": "session must be all or a non-negative number"}), 400)
    return selected_day, selected_session, None


def tracking_report_pdf(student, payload, selected_session):
    """Build the printable ABU route report with ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    stats = payload["stats"]
    refinement = stats.get("refinement", {})
    output = io.BytesIO()
    green = colors.HexColor("#0A5C34")
    gold = colors.HexColor("#C19A33")
    ink = colors.HexColor("#24322A")
    muted = colors.HexColor("#65736B")
    line = colors.HexColor("#DCE4DC")
    pale = colors.HexColor("#F4F7F3")

    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=19 * mm, bottomMargin=17 * mm,
        title=f"{student['reg_no']} Tracking Report", author="SIID-01",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=16, leading=19, textColor=green, alignment=TA_CENTER, spaceAfter=2 * mm,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10, leading=13, textColor=ink, alignment=TA_CENTER,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=10.5, leading=13, textColor=green, spaceBefore=4 * mm, spaceAfter=2 * mm,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.7, leading=12, textColor=ink,
    )
    small_style = ParagraphStyle(
        "Small", parent=body_style, fontSize=7.7, leading=10, textColor=muted,
    )

    def header_footer(canvas, doc):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(line)
        canvas.line(16 * mm, 12 * mm, width - 16 * mm, 12 * mm)
        canvas.setFillColor(muted)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(16 * mm, 8 * mm, "Generated by the Trackable Student ID Card system")
        canvas.drawRightString(width - 16 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    story = []
    logo_path = STATIC_DIR / "abu-logo.jpg"
    heading = [
        Paragraph("AHMADU BELLO UNIVERSITY, ZARIA", title_style),
        Paragraph("TRACKABLE STUDENT ID CARD - ROUTE REPORT", subtitle_style),
    ]
    if logo_path.exists():
        title_block = Table(
            [[Image(str(logo_path), width=16 * mm, height=16 * mm), heading]],
            colWidths=[22 * mm, 135 * mm], hAlign="CENTER",
        )
        title_block.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(title_block)
    else:
        story.extend(heading)
    story.append(Spacer(1, 4 * mm))

    generated = datetime.now(timezone.utc).astimezone(timezone(LAGOS_UTC_OFFSET))
    identity_rows = [
        ["Student", html.escape(student["name"]), "Registration", student["reg_no"]],
        ["Programme", html.escape(student["programme"]), "Level", f"{student['level']} Level"],
        ["Device", student["card_id"], "Recorded day", refinement.get("day") or "No route"],
        ["Walk", "All walks" if selected_session is None else f"Walk {selected_session + 1}",
         "Generated", generated.strftime("%d %b %Y, %H:%M WAT")],
    ]
    identity = Table(identity_rows, colWidths=[23 * mm, 59 * mm, 27 * mm, 53 * mm])
    identity.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pale),
        ("TEXTCOLOR", (0, 0), (-1, -1), ink),
        ("TEXTCOLOR", (0, 0), (0, -1), muted), ("TEXTCOLOR", (2, 0), (2, -1), muted),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("GRID", (0, 0), (-1, -1), 0.4, line),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(identity)

    story.append(Paragraph("ROUTE SUMMARY", section_style))
    summary_rows = [
        ["Clean points", stats.get("count", 0), "Distance", f"{stats.get('distance_m', 0)} m"],
        ["Moving time", f"{stats.get('moving_time_s', 0)} s", "Stopped time", f"{stats.get('stopped_time_s', 0)} s"],
        ["Stops", stats.get("stop_count", 0), "Average speed", f"{stats.get('avg_kmh', 0)} km/h"],
        ["Maximum speed", f"{stats.get('max_kmh', 0)} km/h", "Noise removed", refinement.get("rejected", 0)],
    ]
    summary = Table(summary_rows, colWidths=[31 * mm, 48 * mm, 35 * mm, 48 * mm])
    summary.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, green),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, line),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BACKGROUND", (0, 0), (0, -1), pale), ("BACKGROUND", (2, 0), (2, -1), pale),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("TEXTCOLOR", (0, 0), (-1, -1), ink),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary)

    story.append(Paragraph("DETECTED STOPS", section_style))
    if payload["stops"]:
        stop_rows = [["Stop", "Start", "Duration", "Approximate coordinate"]]
        for index, stop in enumerate(payload["stops"], 1):
            stop_rows.append([
                index,
                (parse_ts(stop["from"]) + LAGOS_UTC_OFFSET).strftime("%H:%M:%S"),
                f"{stop['duration_s'] // 60} min {stop['duration_s'] % 60} sec",
                f"{stop['lat']:.6f}, {stop['lng']:.6f}",
            ])
        stop_table = Table(stop_rows, colWidths=[14 * mm, 30 * mm, 40 * mm, 78 * mm], repeatRows=1)
        stop_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), green), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.8),
            ("GRID", (0, 0), (-1, -1), 0.35, line),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pale]),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(stop_table)
    else:
        story.append(Paragraph("No stop lasting at least one minute was detected.", body_style))

    story.append(Paragraph("REFINED ROUTE POINTS", section_style))
    story.append(Paragraph(
        "These are display coordinates after quality filtering. Original values remain in SQLite and in the CSV export.",
        small_style,
    ))
    story.append(Spacer(1, 1.5 * mm))
    route_rows = [["Time (WAT)", "Latitude", "Longitude", "Distance"]]
    for point in payload["points"]:
        route_rows.append([
            (reading_time(point) + LAGOS_UTC_OFFSET).strftime("%d %b %H:%M:%S"),
            f"{point['lat']:.7f}", f"{point['lng']:.7f}", f"{point.get('dist_m', 0)} m",
        ])
    if len(route_rows) == 1:
        route_rows.append(["No route points", "-", "-", "-"])
    route_table = Table(route_rows, colWidths=[48 * mm, 42 * mm, 42 * mm, 30 * mm], repeatRows=1)
    route_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), green), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Courier"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.3),
        ("TEXTCOLOR", (0, 1), (-1, -1), ink),
        ("GRID", (0, 0), (-1, -1), 0.3, line),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pale]),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(route_table)

    document.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return output.getvalue()


def system_health_snapshot():
    database = {"ok": False, "message": "Database could not be checked."}
    try:
        conn = sqlite3.connect(DB_PATH, timeout=1)
        quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS health_probe (value INTEGER)")
        conn.execute("INSERT INTO health_probe VALUES (1)")
        conn.rollback()
        conn.close()
        database = {
            "ok": quick_check == "ok",
            "message": "SQLite is readable and writable." if quick_check == "ok" else quick_check,
            "path": str(DB_PATH),
        }
    except (OSError, sqlite3.Error) as exc:
        database["message"] = str(exc)

    tunnel = {"ok": False, "message": "ngrok is not running on this computer.", "public_url": None}
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=0.7) as response:
            tunnel_data = json.loads(response.read().decode("utf-8"))
        candidates = [item for item in tunnel_data.get("tunnels", []) if item.get("public_url")]
        preferred = next((item for item in candidates if item["public_url"].startswith("https://")), None)
        active = preferred or (candidates[0] if candidates else None)
        if active:
            tunnel = {
                "ok": True,
                "message": "Public tunnel is ready for the card.",
                "public_url": active["public_url"],
            }
    except (OSError, ValueError, urllib.error.URLError):
        pass

    required_assets = [
        "abu.css", "leaflet/leaflet.css", "leaflet/leaflet.js",
        "socket.io.min.js", "abu-logo.jpg", "app.js", "offline-campus-map.svg",
    ]
    missing_assets = [name for name in required_assets if not (STATIC_DIR / name).exists()]
    assets = {
        "ok": not missing_assets,
        "message": "All presentation files are available locally." if not missing_assets
                   else "Missing: " + ", ".join(missing_assets),
    }

    status = latest_device_status("CARD01")
    device_age = round(age_seconds(status["last_seen"])) if status else None
    device = {
        "ok": bool(status and device_age < ONLINE_WINDOW_S),
        "message": "Card is reporting." if status and device_age < ONLINE_WINDOW_S
                   else "No recent report from the card.",
        "last_seen": status["last_seen"] if status else None,
        "age_s": device_age,
        "signal": status.get("rssi") if status else None,
        "battery_mv": status.get("batt_mv") if status else None,
    }
    latest = latest_reading("CARD01")
    position = {
        "ok": bool(latest),
        "message": "A saved position is ready." if latest else "No position has been saved yet.",
        "source": latest.get("src") if latest else None,
        "last_seen": latest.get("ts") if latest else None,
        "age_s": round(age_seconds(latest["ts"])) if latest else None,
        "lat": latest.get("lat") if latest else None,
        "lng": latest.get("lng") if latest else None,
    }
    return {
        "ready": database["ok"] and assets["ok"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "uptime_s": round((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
        "backend": {"ok": True, "message": "Dashboard server is running."},
        "database": database,
        "tunnel": tunnel,
        "device": device,
        "position": position,
        "offline_assets": assets,
    }


def latest_reading(card_id):
    """Return the newest position captured live by the card.

    Buffered rows are delayed history forwarded after connectivity returns.
    They belong in activity/route history, but must never replace the live map
    marker merely because they reached the server later than a current fix.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT * FROM readings
           WHERE card_id = ? AND COALESCE(buffered, 0) = 0
           ORDER BY id DESC LIMIT 1""",
        (card_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def latest_device_status(card_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM device_status WHERE card_id = ?", (card_id,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)

    # Existing databases have location rows from before heartbeat support.
    # Treat the latest row as the initial device status until a heartbeat arrives.
    reading = latest_reading(card_id)
    if not reading:
        return None
    return {
        "card_id": card_id, "last_seen": reading["ts"],
        "rssi": reading.get("rssi"), "batt_mv": reading.get("batt_mv"),
        "seq": reading.get("seq"),
    }


def device_is_online(card_id):
    status = latest_device_status(card_id)
    return bool(status and age_seconds(status["last_seen"]) < ONLINE_WINDOW_S)


def recent_locations(card_id, limit=5, min_gap_s=30):
    """The device posts every ~5s, so raw points are nearly identical. Sample
    them ~min_gap_s apart (newest first) so the 'recent locations' list is a
    readable trail of distinct places, not five stacked dots."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM readings WHERE card_id = ? ORDER BY id DESC LIMIT 500",
        (card_id,),
    ).fetchall()
    conn.close()

    picked = []
    for r in rows:
        if not picked:
            picked.append(dict(r))
        elif age_seconds(r["ts"]) - age_seconds(picked[-1]["ts"]) >= min_gap_s:
            picked.append(dict(r))
        if len(picked) >= limit:
            break

    # annotate distance from the previous (older) point for a sense of movement
    for i, p in enumerate(picked):
        nxt = picked[i + 1] if i + 1 < len(picked) else None
        p["moved_m"] = round(haversine_m(p["lat"], p["lng"], nxt["lat"], nxt["lng"])) if nxt else None
    return picked


def public_student(s):
    return {
        "reg_no": s["reg_no"], "name": s["name"], "programme": s["programme"],
        "level": s["level"], "faculty": s["faculty"], "session": s["session"],
        "hall": s["hall"], "phone": s["phone"], "has_device": bool(s["card_id"]),
    }


# ---- auth + pages ----------------------------------------------------------
@app.route("/")
def root():
    return redirect("/dashboard" if is_authed() else "/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    requested_next = request.args.get("next", "")
    allowed_next = {"/dashboard", "/students", "/live", "/activity", "/health"}
    destination = requested_next if requested_next in allowed_next else "/dashboard"
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        user = (data.get("username") or "").strip()
        pw = data.get("password") or ""
        if (ADMIN_USER and ADMIN_PASS
                and hmac.compare_digest(user, ADMIN_USER)
                and hmac.compare_digest(pw, ADMIN_PASS)):
            session.clear()
            session["user"] = user
            return jsonify({"ok": True, "redirect": destination})
        return jsonify({"ok": False, "error": "Incorrect username or password."}), 401
    if is_authed():
        return redirect(destination)
    return send_from_directory(DASHBOARD_DIR, "login.html")


@app.route("/readyz")
def readiness_probe():
    return jsonify({"ok": True, "service": "siid-dashboard"})


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


def _page(name):
    if not is_authed():
        return redirect("/login")
    return send_from_directory(DASHBOARD_DIR, name)


@app.route("/dashboard")
def page_dashboard():
    return _page("dashboard.html")


@app.route("/students")
def page_students():
    return _page("students.html")


@app.route("/admin")             # back-compat: old link now lands on Students
def page_admin():
    return redirect("/students")


@app.route("/activity")
def page_activity():
    return _page("activity.html")


@app.route("/health")
def page_health():
    return _page("health.html")


@app.route("/live")
def page_live():
    if not is_authed():
        return redirect("/login")
    # Jump straight to the active tracked student: an online device if there is
    # one, otherwise the first student that has a device at all.
    fallback = None
    for s in STUDENTS:
        if not s["card_id"]:
            continue
        fallback = fallback or s["reg_no"]
        if device_is_online(s["card_id"]):
            return redirect(f"/track/{s['reg_no']}")
    return redirect(f"/track/{fallback}" if fallback else "/students")


@app.route("/track/<reg_no>")
def track(reg_no):
    if not is_authed():
        return redirect("/login")
    if reg_no not in REG_TO_STUDENT:
        return redirect("/students")
    return send_from_directory(DASHBOARD_DIR, "track.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route("/sw.js")
def service_worker():
    response = send_from_directory(DASHBOARD_DIR, "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


# ---- API documentation (Swagger UI) ---------------------------------------
@app.route("/openapi.json")
def openapi_spec():
    """The hand-authored OpenAPI 3.0 spec that documents every endpoint below."""
    return send_from_directory(Path(__file__).parent, "openapi.json")


# Swagger UI is served from the flask-swagger-ui package (assets bundled locally,
# no external CDN) and points at our hand-authored /openapi.json.
_swaggerui = get_swaggerui_blueprint(
    "/docs", "/openapi.json",
    config={"app_name": "SIID-01 — Student Tracking API",
            "docExpansion": "list", "defaultModelsExpandDepth": 1},
)
app.register_blueprint(_swaggerui, url_prefix="/docs")


# ---- student / tracking APIs ----------------------------------------------
@app.route("/api/system/health")
def api_system_health():
    return jsonify(system_health_snapshot())


@app.route("/api/students")
def api_students():
    out = []
    for s in STUDENTS:
        item = public_student(s)
        lr = latest_reading(s["card_id"]) if s["card_id"] else None
        status = latest_device_status(s["card_id"]) if s["card_id"] else None
        item["online"] = bool(status and age_seconds(status["last_seen"]) < ONLINE_WINDOW_S)
        item["last_seen"] = status["last_seen"] if status else None
        out.append(item)
    return jsonify(out)


@app.route("/api/student/<reg_no>")
def api_student(reg_no):
    s = REG_TO_STUDENT.get(reg_no)
    if not s:
        return jsonify({"error": "unknown registration number"}), 404
    item = public_student(s)
    item["card_id"] = s["card_id"]
    lr = latest_reading(s["card_id"]) if s["card_id"] else None
    status = latest_device_status(s["card_id"]) if s["card_id"] else None
    item["online"] = bool(status and age_seconds(status["last_seen"]) < ONLINE_WINDOW_S)
    item["device_last_seen"] = status["last_seen"] if status else None
    item["device_status"] = status
    item["latest"] = lr
    return jsonify(item)


@app.route("/api/student/<reg_no>/recent")
def api_recent(reg_no):
    s = REG_TO_STUDENT.get(reg_no)
    if not s or not s["card_id"]:
        return jsonify([])
    limit, error = bounded_query_int("limit", 5, 1, 100)
    if error:
        return error
    gap, error = bounded_query_int("gap", 30, 1, 3600)
    if error:
        return error
    return jsonify(recent_locations(s["card_id"], limit, gap))


@app.route("/api/student/<reg_no>/track")
def api_track(reg_no):
    """Chronological satellite-fix history for one student, plus movement stats.

    Powers the route-playback control and the distance/speed panel. Only real
    GPS fixes are returned: coarse cell-tower points would add hundreds of metres
    of phantom "movement" and wreck the distance and speed figures.
    """
    s = REG_TO_STUDENT.get(reg_no)
    if not s or not s["card_id"]:
        return jsonify({"points": [], "stops": [], "stats": {}})

    limit, error = bounded_query_int("limit", 1000, 1, 5000)
    if error:
        return error
    selected_day, selected_session, option_error = track_request_options()
    if option_error:
        return option_error
    return jsonify(build_track_payload(s, limit, selected_day, selected_session))


@app.route("/api/student/<reg_no>/track.csv")
def api_track_csv(reg_no):
    student = REG_TO_STUDENT.get(reg_no)
    if not student or not student["card_id"]:
        return jsonify({"error": "student has no tracking device"}), 404
    selected_day, selected_session, option_error = track_request_options()
    if option_error:
        return option_error
    payload = build_track_payload(student, 5000, selected_day, selected_session)
    output = io.StringIO(newline="")
    fields = [
        "capture_time", "server_received_time", "source", "latitude", "longitude",
        "raw_latitude", "raw_longitude", "satellites", "position_quality",
        "distance_from_start_m", "session", "buffered",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for point in payload["points"]:
        writer.writerow({
            "capture_time": point.get("capture_ts"),
            "server_received_time": point.get("ts"),
            "source": point.get("src"),
            "latitude": point.get("lat"), "longitude": point.get("lng"),
            "raw_latitude": point.get("raw_lat"), "raw_longitude": point.get("raw_lng"),
            "satellites": point.get("sats"), "position_quality": point.get("hdop"),
            "distance_from_start_m": point.get("dist_m"),
            "session": point.get("segment"), "buffered": point.get("buffered", 0),
        })
    day = payload["stats"].get("refinement", {}).get("day") or "no-data"
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{reg_no}-{day}-route.csv"'},
    )


@app.route("/api/student/<reg_no>/report.pdf")
def api_track_pdf(reg_no):
    student = REG_TO_STUDENT.get(reg_no)
    if not student or not student["card_id"]:
        return jsonify({"error": "student has no tracking device"}), 404
    selected_day, selected_session, option_error = track_request_options()
    if option_error:
        return option_error
    payload = build_track_payload(student, 5000, selected_day, selected_session)
    stats = payload["stats"]
    refinement = stats.get("refinement", {})
    pdf = tracking_report_pdf(student, payload, selected_session)
    day = refinement.get("day") or "no-data"
    return Response(
        pdf, mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{reg_no}-{day}-report.pdf"'},
    )


@app.route("/api/geofence", methods=["GET", "POST"])
def api_geofence():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        try:
            name = str(data.get("name") or "Demonstration safety zone").strip()[:60]
            center_lat = float(data["center_lat"])
            center_lng = float(data["center_lng"])
            radius_m = int(data["radius_m"])
            enabled = data.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ValueError
            if not (-90 <= center_lat <= 90 and -180 <= center_lng <= 180
                    and 25 <= radius_m <= 5000 and name):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "provide a name, valid centre, radius from 25 to 5000 m, and enabled true/false"}), 400
        updated_at = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """UPDATE geofences SET name=?, center_lat=?, center_lng=?, radius_m=?,
               enabled=?, updated_at=? WHERE id=1""",
            (name, center_lat, center_lng, radius_m, 1 if enabled else 0, updated_at),
        )
        conn.execute("DELETE FROM geofence_state")
        conn.commit()
        conn.close()

    fence = get_geofence()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    latest_row = conn.execute(
        "SELECT * FROM readings WHERE card_id=? AND src='gps' ORDER BY id DESC LIMIT 1",
        ("CARD01",),
    ).fetchone()
    conn.close()
    latest = dict(latest_row) if latest_row else None
    if fence and latest:
        distance_m = haversine_m(
            fence["center_lat"], fence["center_lng"], latest["lat"], latest["lng"]
        )
        fence["latest_distance_m"] = round(distance_m)
        fence["latest_inside"] = distance_m <= fence["radius_m"]
    return jsonify(fence)


@app.route("/api/alerts")
def api_alerts():
    limit, error = bounded_query_int("limit", 20, 1, 200)
    if error:
        return error
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    alerts = []
    for row in rows:
        item = dict(row)
        item["reg_no"] = CARD_TO_REG.get(item["card_id"])
        alerts.append(item)
    return jsonify(alerts)


@app.route("/api/alerts/<int:alert_id>/acknowledge", methods=["POST"])
def api_acknowledge_alert(alert_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()
    if not cursor.rowcount:
        return jsonify({"error": "alert not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/activity")
def api_activity():
    """Recent location updates across all devices, tagged with the student, for
    the Activity log and the dashboard's recent-activity feed."""
    limit, error = bounded_query_int("limit", 30, 1, 500)
    if error:
        return error
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM readings ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        reg = CARD_TO_REG.get(r["card_id"])
        s = REG_TO_STUDENT.get(reg)
        d = dict(r)
        d["reg_no"] = reg
        d["name"] = s["name"] if s else None
        out.append(d)
    return jsonify(out)


@app.route("/api/ping/<reg_no>")
def api_ping(reg_no):
    """Check whether a card is assigned and has reported recently.

    The legacy route name is retained for dashboard compatibility; this is a
    server-side freshness check, not a command transmitted back to the card.
    """
    s = REG_TO_STUDENT.get(reg_no)
    if not s:
        return jsonify({"error": "unknown registration number"}), 404
    if not s["card_id"]:
        return jsonify({"has_device": False, "online": False,
                        "message": "No tracking device is assigned to this student."})
    lr = latest_reading(s["card_id"])
    status = latest_device_status(s["card_id"])
    online = bool(status and age_seconds(status["last_seen"]) < ONLINE_WINDOW_S)
    return jsonify({
        "has_device": True, "online": online, "card_id": s["card_id"],
        "last_seen": status["last_seen"] if status else None,
        "latest": lr,
        "message": "Device is online and reporting." if online
                   else "Device assigned but not reporting right now.",
    })


@app.route("/api/ingest", methods=["POST"])
def ingest():
    """Accept an authenticated and validated position from the LilyGO card."""
    supplied_key = request.headers.get("X-Device-Key", "")
    if not DEVICE_API_KEY or not hmac.compare_digest(supplied_key, DEVICE_API_KEY):
        return jsonify({"error": "invalid device credentials"}), 401

    data = request.get_json(silent=True)
    if not data or not all(k in data for k in ("card_id", "lat", "lng")):
        return jsonify({"error": "body must contain card_id, lat and lng"}), 400

    card_id = str(data["card_id"]).strip()
    if card_id not in CARD_TO_REG:
        return jsonify({"error": "unknown card_id"}), 403

    source = data.get("src")
    if source not in VALID_POSITION_SOURCES:
        return jsonify({"error": "src must be gps, gps_hold, ble, cell or test"}), 400

    try:
        lat = float(data["lat"])
        lng = float(data["lng"])
        if not (math.isfinite(lat) and math.isfinite(lng)
                and -90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("coordinates")
        battery_mv = optional_number(data, "batt_mv", int, 0, 5500)
        # The board reports 0 when a battery-voltage reading is unavailable,
        # such as while it is powered over USB. Keep 0 as "unknown", while
        # rejecting implausible non-zero LiPo readings.
        if battery_mv not in (None, 0) and battery_mv < 2500:
            raise ValueError("battery voltage")

        buffered = data.get("buffered", False)
        if not isinstance(buffered, bool):
            raise ValueError("buffered")
        captured_epoch = optional_number(
            data, "captured_epoch", int, 1704067200,
            int(datetime.now(timezone.utc).timestamp()) + 300,
        )

        reading = {
            "card_id": card_id,
            "lat": lat,
            "lng": lng,
            "sats": optional_number(data, "sats", int, 0, 100),
            "hdop": optional_number(data, "hdop", float, 0, 100),
            "batt_mv": battery_mv,
            "seq": optional_number(data, "seq", int, 0, 0xFFFFFFFF),
            "rssi": optional_number(data, "rssi", int, -1, 99),
            "snr": optional_number(data, "snr", float, -100, 100),
            "src": source,
            "acc": optional_number(data, "acc", int, 0, 100000),
            "age_s": optional_number(data, "age_s", int, 0, 86400),
            "device_ts": datetime.fromtimestamp(captured_epoch, timezone.utc).isoformat()
                         if captured_epoch is not None else None,
            "buffered": buffered,
        }
    except (TypeError, ValueError):
        return jsonify({"error": "invalid coordinate or telemetry value"}), 400

    if not reading["buffered"]:
        now = time.monotonic()
        with _ingest_lock:
            previous = _last_ingest_at.get(card_id, 0)
            if now - previous < INGEST_MIN_INTERVAL_S:
                return jsonify({"error": "device is reporting too quickly"}), 429
            _last_ingest_at[card_id] = now

    handle_reading(reading)
    return jsonify({"ok": True})


@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    """Record that the card and LTE link are alive even when no position is usable."""
    supplied_key = request.headers.get("X-Device-Key", "")
    if not DEVICE_API_KEY or not hmac.compare_digest(supplied_key, DEVICE_API_KEY):
        return jsonify({"error": "invalid device credentials"}), 401

    data = request.get_json(silent=True)
    if not data or "card_id" not in data:
        return jsonify({"error": "body must contain card_id"}), 400
    card_id = str(data["card_id"]).strip()
    if card_id not in CARD_TO_REG:
        return jsonify({"error": "unknown card_id"}), 403

    try:
        battery_mv = optional_number(data, "batt_mv", int, 0, 5500)
        if battery_mv not in (None, 0) and battery_mv < 2500:
            raise ValueError("battery voltage")
        status = {
            "card_id": card_id,
            "rssi": optional_number(data, "rssi", int, -1, 99),
            "batt_mv": battery_mv,
            "seq": optional_number(data, "seq", int, 0, 0xFFFFFFFF),
        }
    except (TypeError, ValueError):
        return jsonify({"error": "invalid heartbeat telemetry value"}), 400

    now = time.monotonic()
    with _ingest_lock:
        previous = _last_heartbeat_at.get(card_id, 0)
        if now - previous < INGEST_MIN_INTERVAL_S:
            return jsonify({"error": "device is reporting too quickly"}), 429
        _last_heartbeat_at[card_id] = now

    status["ts"] = datetime.now(timezone.utc).isoformat()
    store_device_status(status)
    live_event = dict(status)
    live_event["reg_no"] = CARD_TO_REG.get(card_id)
    socketio.emit("device_status", live_event)
    print(f"[{status['ts']}] {card_id} heartbeat  rssi={status.get('rssi')}")
    return jsonify({"ok": True})


@app.route("/api/history")
def history():
    card_id = request.args.get("card_id", "CARD01")
    if card_id not in CARD_TO_REG:
        return jsonify({"error": "unknown card_id"}), 404
    limit, error = bounded_query_int("limit", 200, 1, 1000)
    if error:
        return error
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM readings WHERE card_id = ? ORDER BY id DESC LIMIT ?",
        (card_id, limit),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in reversed(rows)])


if __name__ == "__main__":
    validate_security_config()
    init_db()
    parser = argparse.ArgumentParser(description="SIID-01 tracking backend")
    parser.add_argument("--port", help="Base station serial port, e.g. COM5")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--simulate", action="store_true",
                         help="Generate fake GPS data instead of reading serial")
    parser.add_argument("--sim-lat", type=float, default=11.1523,
                         help="Simulator center latitude (default: ABU Zaria area)")
    parser.add_argument("--sim-lng", type=float, default=7.6532,
                         help="Simulator center longitude")
    parser.add_argument("--web-port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1",
                        help="Web bind address (default: loopback only)")
    args = parser.parse_args()

    if args.simulate:
        threading.Thread(
            target=simulator, args=(args.sim_lat, args.sim_lng, "CARD01"), daemon=True
        ).start()
    elif args.port:
        # Legacy: read from a USB-connected board (kept for the old LoRa design)
        threading.Thread(
            target=serial_reader, args=(args.port, args.baud), daemon=True
        ).start()
    else:
        # Default: cellular mode — the card POSTs to /api/ingest over the internet.
        print("Cellular mode: waiting for the card to POST to /api/ingest")
        print("Expose this server for the card with:  ngrok http 5000 --scheme http")

    print(f"Dashboard: http://localhost:{args.web_port}")
    # The public tunnel forwards to loopback; LAN-wide binding is unnecessary.
    socketio.run(app, host=args.host, port=args.web_port, allow_unsafe_werkzeug=True)
