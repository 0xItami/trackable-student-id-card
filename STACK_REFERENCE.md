# SIID-01 — Stack & Design Reference

Full technical reference: every dependency with its pinned version, every route,
the data model, and the reasoning behind each design decision (backend, frontend
and CSS).

Written at engineering level — this is the companion to `HOW_TO_EXPLAIN_THIS.md`,
which is the plain-language version for presenting.

The current build includes six dashboard pages, a hand-written API description,
an offline service worker, launcher scripts and the LilyGO firmware.

---

## 1. Backend

### 1.1 Runtime & dependencies (pinned, from `backend/requirements.txt`)

| Package | Version | Role |
|---|---|---|
| **Python** | 3.13.5 | Runtime |
| **Flask** | 3.0.3 | WSGI web framework — routing, request/response, sessions |
| **Flask-SocketIO** | 5.3.6 | WebSocket layer for server-push |
| **flask-swagger-ui** | 5.32.9 | Serves Swagger UI locally (no CDN) |
| **pyserial** | 3.5 | Legacy USB-serial reader, retained from the LoRa design |
| **ReportLab** | 4.4.9 | Generates the branded multi-page tracking PDF |

Transitive (installed, worth knowing): `python-socketio 5.16.3`,
`python-engineio 4.13.3`, `simple-websocket 1.1.0`, `wsproto 1.3.2`,
`Werkzeug 3.1.8`, `Jinja2 3.1.6`, `itsdangerous 2.2.0`, `blinker 1.9.0`,
`bidict 0.23.1`, `h11 0.16.0`, `click 8.4.2`.

### 1.2 Architecture

Single-module Flask app (`backend/app.py`). Deliberately not layered into
packages — at this size, indirection would cost readability without buying
testability.

**Concurrency model:** `SocketIO(async_mode="threading")`. The device POSTs are
low-frequency (0.2 req/s), so a threaded WSGI server is sufficient; no ASGI/event
loop needed. The simulator and the legacy serial reader each run on a
`threading.Thread(daemon=True)`.

**The central design decision — one write path:**

```python
def handle_reading(raw: dict): ...   # timestamp -> persist -> enrich -> emit
```

Both the real device (`POST /api/ingest`) and the built-in simulator call this
same function. That guarantees the dashboard behaves identically whether data is
real or synthetic — which is what allowed the whole UI to be built and proven
before the hardware arrived. Any divergence between "demo mode" and "real mode"
would be a bug by construction.

### 1.3 Route table

**Pages** (session-guarded, return static HTML):

| Route | Notes |
|---|---|
| `GET /` | Redirects to `/dashboard` or `/login` by session state |
| `GET,POST /login` | Renders form; POST validates and sets session |
| `GET /logout` | `session.clear()` → redirect |
| `GET /dashboard` | Operations overview |
| `GET /students` | Roster + search |
| `GET /admin` | 302 → `/students` (back-compat after rename) |
| `GET /activity` | Event log + charts |
| `GET /health` | Pre-presentation readiness checks |
| `GET /live` | Resolves the active device, 302 → `/track/<reg>` |
| `GET /track/<reg_no>` | Live map; 302 → `/students` on unknown reg |
| `GET /readyz` | Minimal launcher readiness probe |
| `GET /sw.js` | Offline service worker at root scope |
| `GET /static/<path>` | Static assets |
| `GET /docs`, `GET /openapi.json` | Swagger UI + hand-written spec |

**API:**

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/ingest` | Authenticated position report from the card |
| `POST` | `/api/heartbeat` | Authenticated online report when no position is usable |
| `GET` | `/api/students` | Roster, each tagged `has_device` / `online` |
| `GET` | `/api/student/<reg>` | One student + latest reading |
| `GET` | `/api/student/<reg>/recent?limit&gap` | Time-sampled trail |
| `GET` | `/api/student/<reg>/track?limit&date&session` | Refined route, walks, stops and stats |
| `GET` | `/api/student/<reg>/track.csv` | Download refined and original coordinates |
| `GET` | `/api/student/<reg>/report.pdf` | Download printable route report |
| `GET, POST` | `/api/geofence` | Read or configure the safety zone |
| `GET` | `/api/alerts` | Recent boundary crossings |
| `POST` | `/api/alerts/<id>/acknowledge` | Mark an alert reviewed |
| `GET` | `/api/system/health` | Server/database/tunnel/card/offline readiness |
| `GET` | `/api/ping/<reg>` | Device assigned? reporting? |
| `GET` | `/api/activity?limit` | Cross-device event feed |
| `GET` | `/api/history?card_id&limit` | Raw rows for map replay |

### 1.4 Data model

SQLite (`tracking.db`), five small tables:

```sql
readings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
  sats INTEGER, hdop REAL, batt_mv INTEGER, seq INTEGER,
  rssi INTEGER, snr REAL, ts TEXT NOT NULL,
  src TEXT, acc INTEGER, age_s INTEGER,
  device_ts TEXT, buffered INTEGER DEFAULT 0
)

device_status(
  card_id TEXT PRIMARY KEY, last_seen TEXT NOT NULL,
  rssi INTEGER, batt_mv INTEGER, seq INTEGER
)

geofences(id, name, center_lat, center_lng, radius_m, enabled, updated_at)
geofence_state(card_id, is_inside, updated_at)
alerts(id, card_id, kind, message, lat, lng, ts, acknowledged)
```

**Migration approach:** `init_db()` issues guarded `ALTER TABLE … ADD COLUMN`
inside `try/except sqlite3.OperationalError`. Idempotent, no migration framework,
and existing databases upgrade in place. Appropriate at this scale; a real product
would use Alembic.

**The roster is in code, not the database** (`STUDENTS` list + two derived dicts,
`REG_TO_STUDENT` and `CARD_TO_REG`). Five fixed records with no CRUD requirement —
putting them in SQLite would add a table, seed logic and admin screens for zero
functional gain. `CARD_TO_REG` is the reverse index used to attribute an incoming
`card_id` to a student on the hot path.

### 1.5 Domain logic worth defending

**`recent_locations(card_id, limit, min_gap_s=30)`** — the device reports every
5 s, so consecutive rows are near-identical. This walks newest-first and keeps a
point only if it is ≥ `gap` seconds older than the last kept one, producing a
readable trail rather than five stacked dots.

**`MOVEMENT_THRESHOLD_M = 10`** — consumer GNSS wanders 1–8 m while completely
stationary. Distance is only accumulated for steps above this, otherwise a
motionless card reports phantom kilometres and the max-speed statistic becomes
noise. The frontend uses the same constant, deliberately kept in sync.

**Route refinement** — the playback API leaves every raw database row intact but
only displays trustworthy fixes (at least four satellites and PDOP no greater
than 8). It breaks the line after a three-minute reporting gap, rejects
quality-adjusted impossible-speed jumps, ignores sub-4 m jitter and applies an
adaptive low-pass filter. The browser then uses two passes of Chaikin corner
cutting to round the line without falsely snapping it onto a road.

**Day, walk and stop analysis** — Lagos calendar days are listed explicitly. A
three-minute data gap starts another walk, so separate outings are never joined
by a false straight line. A stop is a group of points remaining within an 18 m
area for at least one minute. Moving and stopped time are then reported separately.

**Safety-zone alerts** — only a fresh GPS or configured BLE-anchor reading may
change the inside/outside state. Cell-tower and held positions are deliberately
excluded because their uncertainty could create a false boundary crossing.

**`ONLINE_WINDOW_S = 180`** — a device is "online" if it reported within 180 s.
This accommodates the modem's slow cell-tower lookup, which can take up to two
minutes, without calling a powered and communicating card offline mid-request.
(6 × the 5 s report interval, tolerating a couple of missed posts).

**Speed sanity gates** — route points are rejected at a quality-adjusted limit
of 20–45 km/h when the jump is at least 25 m. A final 200 km/h cap remains on
the displayed maximum-speed statistic as defence in depth.

### 1.6 Auth

Flask signed-cookie session (`itsdangerous`) guards pages, read APIs, Swagger and
Socket.IO. The device uses a separate `X-Device-Key`; unknown card IDs and invalid
telemetry are rejected, request size and query limits are bounded, and ingest is
rate-limited. Demo mode retains one shared staff account for presentation. Production
mode requires environment-supplied secrets and should add hashed individual accounts,
TLS, CSRF protection and a persistent multi-process rate limiter.

### 1.7 API documentation

`backend/openapi.json` is a **hand-authored OpenAPI 3.0.3 document** — schemas,
`$ref` components, parameter definitions, and multiple worked examples per
response. Rendered by `flask-swagger-ui` from bundled assets (works offline; no
CDN dependency and no SRI concerns). Hand-writing it over auto-generation was
deliberate: the point is to be able to explain each endpoint, not to emit a spec.

### 1.8 Ingress path

The device is on the public internet via 4G; the laptop is not. An **ngrok HTTP
tunnel** bridges them:

```
ngrok http 5000 --scheme http
```

- ngrok's **free tier refuses TCP endpoints** (`ERR_NGROK_8013` — requires a card
  on file), so the obvious `ngrok tcp` is unavailable.
- Default HTTP endpoints answer plain HTTP with a **307 → HTTPS**, which would
  force TLS onto a Cat-1 modem — a common failure point. `--scheme http` binds
  HTTP only, so the device sends unencrypted HTTP on port 80.
- The account's **free static domain** means the firmware's server address is
  stable across sessions (no re-flash per demo).
- The firmware sends `ngrok-skip-browser-warning: true` to bypass the free-tier
  interstitial.

**Security note:** plain HTTP means location data is unencrypted in transit —
acceptable for a controlled demo, listed as a production recommendation.

---

## 2. Frontend

### 2.1 Libraries (only three, all pinned)

| Library | Version | Delivery | Why |
|---|---|---|---|
| **Leaflet** | 1.9.4 | Local files in `dashboard/static` | Map rendering. No API key or billing account |
| **Socket.IO client** | 4.8.3 | Local file in `dashboard/static` | Must match the server's Socket.IO protocol |
| **IBM Plex** (Sans/Mono/Serif) | — | Google Fonts with system fallback | Typeface; the interface remains readable offline |

Everything else is hand-written: **no framework, no build step, no bundler, no
package.json.** Six plain HTML pages. Justification: there
is no shared client state beyond "latest reading", no routing requirement beyond
server-rendered page loads, and no component reuse that plain functions don't
cover. A React/Vite toolchain would add a build artefact between the source and
the running page — bad for a report appendix, where the deliverable should be
readable source.

The functional JavaScript libraries are stored locally, so a CDN outage cannot
stop the map engine or live connection from starting.

### 2.2 Map tiles

| Layer | Source | Why |
|---|---|---|
| **Satellite** (default) | Esri World Imagery | Global coverage. OpenStreetMap street data is sparse outside ABU campus, so OSM rendered near-blank at the test location |
| Roads/labels overlay | Esri World Transportation + World Boundaries and Places | Road names over imagery |
| Street map (alternate) | OpenStreetMap | Good detail on campus |

**`maxNativeZoom: 18, maxZoom: 22`** — verified empirically that Esri has no
imagery beyond z18 over Zaria (z19 returns byte-identical 2,521-byte "Map data not
yet available" placeholders). Capping native zoom makes Leaflet upscale real z18
tiles instead of showing placeholders, so zoom keeps working past 18.

Google Maps was rejected: the JavaScript and Geolocation APIs both require a
billing account with a card on file.

### 2.3 Offline presentation protection

`dashboard/sw.js` caches the page shell, Leaflet, Socket.IO, the logo and map
tiles already viewed. Location API responses are not silently cached. Instead,
the tracking page explicitly stores a labelled route snapshot in browser
`localStorage`; **Save offline replay** lets the presenter refresh that copy.
If internet tiles are unavailable, a bundled simplified ABU reference SVG is
placed below the route, preserving the demonstration without pretending it is
a full street map.

### 2.4 Real-time transport

Socket.IO over WebSocket. The server emits `location_update` on every reading;
pages subscribe and patch the DOM. Polling was rejected — it wastes requests and
adds latency proportional to the poll interval. Socket.IO (rather than a raw
`WebSocket`) buys automatic reconnection and transport fallback for free.

---

## 3. CSS & design system

`dashboard/static/abu.css` — 259 lines, hand-written, no Tailwind/Bootstrap.

### 3.1 Token architecture

Everything is CSS custom properties on `:root`: brand colours, surfaces, ink,
status colours, three font stacks, radii, shadows, and a focus ring. Components
reference tokens only — never raw hex — so light/dark and any future rebrand are
single-point changes.

Dark mode is declared under **both** `@media (prefers-color-scheme: dark)` and
`:root[data-theme="dark"]`, so an explicit toggle beats the OS setting in both
directions.

### 3.2 Type system — three faces, three jobs

| Role | Face | Used for |
|---|---|---|
| Institution | IBM Plex **Serif** | University wordmark |
| Interface | IBM Plex **Sans** | All UI text |
| Machine data | IBM Plex **Mono** | Reg numbers, coordinates, telemetry, timestamps |

The split is semantic, not decorative: monospace signals "this is machine output",
and `font-variant-numeric: tabular-nums` keeps digits from jittering as live values
update.

### 3.3 Visual direction

- **Flat, no gradients** (an explicit requirement) — flat ABU green `#0a5c34` and
  gold `#c19a33`.
- **Glassmorphism** on chrome only (sidebar, top bars, KPI tiles):
  `backdrop-filter: blur(18px) saturate(1.3)` over a faint 8-point-star SVG
  background — a northern-Nigerian geometric motif, encoded as a data-URI so it
  costs no request. Glass needs texture beneath it or the blur is invisible.
- **Layout:** CSS Grid for the app shell (`250px` sidebar + fluid main) and card
  grids; Flexbox within components. No float, no positioning hacks.
- **`prefers-reduced-motion`** disables all animation.

### 3.4 Chart palette — validated, not eyeballed

Charts are hand-written SVG (no charting library). The categorical palette was run
through a colourblind-safety validator rather than chosen by taste:

| Slot | Light | Dark | Meaning |
|---|---|---|---|
| 1 | `#4a86c8` | `#4f8dcf` | GPS satellites |
| 2 | `#eb6834` | `#d95926` | Cell tower |
| 3 | `#1baf7a` | `#199e70` | Last GPS fix |
| 4 | `#9aa69d` | `#7d8a81` | Bench test (neutral) |

Checks passed **all-pairs** in both modes: lightness band, chroma floor, CVD
separation (worst ΔE 9.2 light / 9.4 dark, ≥ 8 target), normal-vision floor
(19.4 / 17.3, ≥ 15 floor), contrast vs surface.

Two findings worth noting:
1. The original slot-4 yellow **failed** beside orange (normal-vision ΔE 13.7,
   below the 15 floor). Fixed by dropping yellow — "bench test" is not a real
   positioning method, so it takes a neutral gray rather than competing for a hue.
2. Blue was softened from `#2a78d6` → `#4a86c8` on feedback that it was too loud,
   then **re-validated** rather than assumed still safe.

Because one light-mode slot sits under 3:1 contrast on white, every stacked
segment also carries a **direct % label plus a legend count** — colour never
carries meaning alone.

### 3.5 Chart engine

`dashboard/static/viz.js` (111 LOC) — extracted after the second page needed
charts, so the dashboard and activity pages share one renderer rather than
drifting. Provides `drawSeries()` (area + 2 px line, hairline gridlines, y ticks,
crosshair + tooltip), `drawSourceBar()`, `SRC` (the fixed source→colour map, never
cycled) and `timeAgo()`.

Outlier handling is explicit: fix-quality values above 25 are excluded from the
plot because a single 100+ reading flattens the useful 1–5 range — and the caption
**discloses the exclusion** rather than hiding it.

---

## 4. Firmware

| Dependency | Version | Note |
|---|---|---|
| **ESP32 Arduino core** | 3.3.11 | Board: `esp32:esp32:esp32wrover` |
| **TinyGSM** | 1.0.0 — **LilyGO fork** | Mainline has no `TINY_GSM_MODEM_A7670`; will not compile |
| **ArduinoHttpClient** | 0.6.1 | HTTP over `TinyGsmClient` |
| **TinyGPSPlus** | 1.1.0 | Installed but **unused** — the modem parses GNSS itself |

Verified flash footprint after store-and-forward: **332,720 bytes (25%)** of
1.31 MB and **23,884 bytes (7%)** of RAM with BLE compiled out;
1,126,400 bytes (86%) with `USE_BLE_ANCHORS 1`.

**Positioning tiers** (first success wins, each tagged in the payload):
`gps` (live satellites) → `ble` (optional, off by default) → `gps_hold` (last good
fix, ≤ 15 min) → `cell` (network location).

**GPS-hold quality gate:** a fix is only stored as "last known" if PDOP ≤ 8 **and**
≥ 4 satellites. Without it the receiver keeps reporting a "fix" while quality
collapses on the way indoors, so the held position ended up being the *worst* fix
of the session. Persisted to **NVS** (`Preferences`) with the fix's UTC timestamp,
so it survives a power cycle; age is recomputed from the network clock.

**Store-and-forward:** the ESP32 uses a second `Preferences` namespace as a
20-packet circular queue. A temporary network/server failure stores the JSON and
its original UTC capture time in flash. On later cycles the card forwards up to
three old packets before the current report and marks them `buffered: true`.
The server stores server-receipt time separately and orders playback by capture
time, so an outage does not draw a late point in the wrong part of the route.

---

## 5. Decision log — one line each

| Decision | Alternative rejected | Reason |
|---|---|---|
| Cellular (4G) link | LoRa + base station | Removes range as a variable; one device instead of two |
| Integrated LilyGO board | Discrete ESP32 + modem + GPS + charger | Fewest parts; eliminates the modem-brownout capacitor entirely |
| Flask | FastAPI | Nothing here is async-bound; would not change what the demo does |
| SQLite | Postgres/MySQL | Single writer, single file, zero configuration |
| Threading async mode | eventlet/gevent | 0.2 req/s; no benefit from an event loop |
| Roster in code | Database table | Five fixed records, no CRUD requirement |
| No frontend framework | React/Vue | No shared client state or routing need; readable source matters for the appendix |
| Hand-written SVG charts | Chart.js/D3 | Four small charts; avoids a dependency and gives exact control over the validated palette |
| Hand-authored OpenAPI | Auto-generated | The goal is explaining each endpoint, not emitting a spec |
| ngrok HTTP + `--scheme http` | ngrok TCP / HTTPS | TCP needs a payment method; HTTPS would force TLS onto the modem |
| Esri satellite tiles | Google Maps | No API key, no billing account, global coverage |
| Plain HTTP to the device | TLS on-device | Cat-1 TLS is a known failure point; documented as a production gap |
| 20-packet flash queue | Drop readings during outages | Preserves a short walk across brief LTE/ngrok interruptions |
