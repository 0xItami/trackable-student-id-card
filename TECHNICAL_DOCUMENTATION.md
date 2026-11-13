# SIID-01 — Trackable Student ID Card
## Full Technical Documentation

**Project:** A card-shaped lanyard/pocket badge prototype that reports its live GPS location to a
branded web dashboard, demonstrable across 200 m and beyond.
**Author:** Final-year project, Department of Computer Engineering, Ahmadu Bello
University, Zaria.
**Status:** Working end-to-end (hardware + firmware + backend + dashboard + API docs).

> This document is written to be **read** (to understand how and why the system
> works) and **presented** (each section can be explained to a panel). Terms in
> *italics* on first use are defined in the [Glossary](#15-glossary).

---

## Table of contents
1. [What the project does](#1-what-the-project-does)
2. [The requirements and how each is met](#2-the-requirements-and-how-each-is-met)
3. [System architecture](#3-system-architecture)
4. [Underlying concepts (the theory)](#4-underlying-concepts-the-theory)
5. [Design decisions & why the alternatives were rejected](#5-design-decisions--why-the-alternatives-were-rejected)
6. [Hardware](#6-hardware)
7. [Firmware (the card)](#7-firmware-the-card)
8. [Backend (server)](#8-backend-server)
9. [Frontend (dashboard)](#9-frontend-dashboard)
10. [The API and its documentation](#10-the-api-and-its-documentation)
11. [Setup & running](#11-setup--running)
12. [Demo-day runbook](#12-demo-day-runbook)
13. [Limitations & honest trade-offs](#13-limitations--honest-trade-offs)
14. [Troubleshooting](#14-troubleshooting)
15. [Glossary](#15-glossary)
16. [Project file structure](#16-project-file-structure)

---

## 1. What the project does

The card is a small battery-powered device carried by a student. Every few
seconds it:

1. works out **where it is** using satellites (GPS),
2. sends that position **over the mobile phone network** (4G) to a server, and
3. the server pushes it to a **live map** in a web browser, so an authorised
   staff member watches the student move in real time.

The demo tells a small story: five Computer Engineering students are *registered*
in the system, but only **one** — registration number **U19CO1011** — carries the
physical card, because we built one board. An administrator signs in, searches for
that student, "pings" the device, and opens a live tracking page.

---

## 2. The requirements and how each is met

| Requirement | How it is satisfied |
|---|---|
| Trackable student ID card | GPS position reported live to a dashboard |
| Portable ID form | Flat lanyard/pocket badge; the development board prevents ISO wallet-card dimensions (see §13) |
| Works across 200 m | Uses the **cellular network**, so range is effectively unlimited — 200 m is trivial |
| Full functionality demonstrable | End-to-end live demo: card → network → map, plus a simulator fallback |
| Real map, not a toy | OpenStreetMap tiles via Leaflet.js, centred on the ABU Zaria campus |

---

## 3. System architecture

The system is four cooperating parts. Data flows in one direction for position
(card → dashboard) and the dashboard makes read requests back to the server.

```
   SATELLITES (GPS)                MOBILE NETWORK (4G LTE)             ADMIN LAPTOP
        │                                  │                               │
        ▼                                  ▼                               ▼
 ┌──────────────┐   AT+CGNSSINFO     ┌───────────┐   HTTP POST     ┌──────────────────┐
 │ GNSS receiver│ ─────────────────► │  ESP32    │ ──────────────► │  Python backend  │
 │ inside the   │   (position)       │  asks the │  /api/ingest    │  Flask-SocketIO  │
 │ A7670E modem │                    │  modem    │  (JSON, over    │                  │
 └──────────────┘                    │           │   the internet) │  ┌────────────┐  │
                                                 └───────────┘      │  │  SQLite DB │  │
                                                                    │  └────────────┘  │
                                                                    │        │         │
                                                                    │  WebSocket push  │
                                                                    │  (location_update)│
                                                                    └────────┬─────────┘
                                                                             ▼
                                                                   ┌────────────────────┐
                                                                   │  Web dashboard     │
                                                                   │  Leaflet live map  │
                                                                   │  (browser)         │
                                                                   └────────────────────┘
```

**One-sentence summary for the panel:** *"The card finds itself with GPS, phones
home over 4G to a Python server, and the server pushes each position to a live map
over a WebSocket."*

Because the card is on the public internet but the laptop server is on a private
network, a **tunnel** (ngrok) gives the card a public address that forwards to the
laptop — see §4.6.

---

## 3a. Technology stack — what, and why that choice

Every layer, the technology used, and the reason it was chosen over the obvious
alternatives. This is the table to have in front of you in a defence.

| Layer | Technology | Why this, not something else |
|---|---|---|
| **Board** | LilyGO T-A7670E (ESP32-WROVER + A7670E LTE Cat-1 + GNSS + charger) | One PCB replaces MCU + modem + GPS + charger + capacitor. Fewest parts, least wiring, lowest risk. |
| **Positioning** | GNSS → GPS-hold → cell tower (hybrid) | No single method works everywhere. Satellites die indoors; cell works indoors but is coarse. Tiering gives coverage *and* honesty about accuracy. |
| **Link to server** | 4G LTE (Cat-1), band B3 | Range stops being a design variable — the network carries the data any distance, so the 200 m spec is trivially met. LoRa would have needed a second device. |
| **Firmware language** | Arduino C++ (ESP32 core 3.3.11) | Mature libraries for this exact board; far faster to build than ESP-IDF, and the vendor's own examples are Arduino. |
| **Modem driver** | TinyGSM (**LilyGO fork**) | Mainline TinyGSM has no `A7670` support and will not compile. The fork adds it. |
| **HTTP on device** | ArduinoHttpClient over `TinyGsmClient` | Plain HTTP, no TLS — a Cat-1 modem doing TLS is a common failure point, and the tunnel lets us avoid it. |
| **Persistence on device** | ESP32 NVS (`Preferences`) | The last good GPS fix survives a power cycle. RAM updates every fix; flash is checkpointed at most every five minutes to reduce wear. |
| **Backend framework** | Python + Flask | Small, readable, easy to defend line by line. FastAPI was considered — it would not have made the demo do anything new. |
| **Live updates** | Flask-SocketIO (WebSocket) | The map must update *by itself*. Polling wastes requests and adds lag. |
| **Database** | SQLite | Zero-configuration, single file, survives restarts. A server database would add setup with no benefit at this scale. |
| **Public address** | ngrok HTTP tunnel (`--scheme http`) | The card is on the public internet; the laptop is not. Free-tier ngrok refuses TCP endpoints, and `--scheme http` avoids the HTTPS redirect so the modem needs no TLS. |
| **Map** | Leaflet.js + Esri World Imagery | Free, no API key, no billing card. OpenStreetMap street data is sparse outside campus, so satellite imagery is the default layer. Google Maps requires a billing account. |
| **Frontend** | Plain HTML/CSS/JS, no framework | Nothing here needs React. No build step means the whole UI is readable source, which matters for a report appendix. |
| **Charts** | Hand-written SVG | No charting library to explain or bundle. The palette was run through a colourblind-safety validator rather than eyeballed. |
| **API documentation** | Hand-authored OpenAPI 3.0 + Swagger UI | Written by hand so every endpoint can be explained intrinsically; served locally so it works offline. |
| **Enclosure** | OpenSCAD (parametric) | The model is *code*, so dimensions are edited as numbers rather than redrawn — and the file itself documents the measurements. |

**The through-line:** at every layer the choice was the one with the fewest moving
parts that still met the requirement, and each rejected alternative was rejected
for a specific, stateable reason — not on taste.

## 4. Underlying concepts (the theory)

This section explains the ideas the project rests on, so they can be defended.

### 4.1 GPS / GNSS — how the card knows where it is
*GPS* (Global Positioning System) is a constellation of ~30 satellites orbiting
Earth, each continuously broadcasting the exact time and its own orbital position.
A GPS receiver listens to several satellites at once. Because radio travels at the
speed of light, the tiny difference in arrival time from each satellite tells the
receiver how far away that satellite is. With distances to **at least four**
satellites, the receiver solves for its own 3-D position — this is
**trilateration**.

**Where the receiver is on this board:** the GNSS receiver is **built into the
A7670E modem itself** — there is no separate GPS chip. The ESP32 therefore does not
parse raw satellite data at all; it powers the receiver with `AT+CGNSSPWR=1` and
then simply *asks* the modem for the current position with `AT+CGNSSINFO`. The modem
does the satellite work internally and replies with a comma-separated line.
*(This was verified on the actual hardware — see §7.3.)*

Key practical points (all worth mentioning in a defence):
- **What the modem returns:** `+CGNSSINFO:` followed by fix mode (2 = 2-D, 3 = 3-D),
  satellites used, latitude/longitude, altitude, speed and dilution-of-precision
  values. Before a fix is acquired the fields are **empty commas**
  (`+CGNSSINFO: ,,,,,,,,`) — a useful, unambiguous "powered but not locked" signal.
- **Time to first fix (TTFF) / cold start:** on first power-up in a new location
  the receiver has no idea which satellites are overhead, so the first fix can take
  **1–5 minutes**. After that, fixes are near-instant. *This is why we test and
  demo outdoors and power the card on early.*
- **Clear sky needed:** GPS signals are weak and blocked by roofs and walls, so a
  fix requires a view of the sky. Indoors you get empty commas, not a wrong position.
- **Dilution of precision (PDOP/HDOP):** a number describing fix quality from
  satellite geometry — **lower is better** (≈1 is excellent). We report the PDOP
  field from `+CGNSSINFO` on the telemetry panel.
- **Coordinate format:** depending on modem firmware revision the latitude/longitude
  can arrive as decimal degrees *or* as NMEA `ddmm.mmmm`. The firmware normalises
  anything outside the legal range, so the map is correct on either revision.

### 4.1a Hybrid positioning — staying trackable indoors
GPS alone fails the moment a student walks into a lecture hall. The card therefore
uses a **three-tier positioning hierarchy** and degrades gracefully, reporting
*which* method produced each fix so the reading is never misleading:

| Tier | Method | How it works | Accuracy | Works indoors? |
|---|---|---|---|---|
| 1 | **GNSS** | Satellites, via `AT+CGNSSINFO` | 2–5 m | ✗ |
| 2 | **BLE anchor** | ESP32 scans for a known Bluetooth beacon at a surveyed position | 5–20 m (room level) | ✓ (near an anchor) |
| 3 | **Cell tower (LBS)** | Network reports serving-cell position, via `AT+CLBS` | ~100 m – 1 km | ✓ (anywhere with signal) |

The card tries them in order and sends the first that succeeds, tagging the packet
with `src` (`gps` / `ble` / `cell`) and `acc` (accuracy in metres). The dashboard
displays the method and draws an **uncertainty circle** for coarse fixes, so a
±550 m cell fix is never presented as if it were a 3 m GPS fix.

**Why BLE needs anchors.** Bluetooth gives *proximity to a known point*, not
absolute position — so an anchor (any BLE beacon, or a laptop/phone advertising)
must be placed at a surveyed location and listed in `BLE_ANCHORS[]` in the
firmware. This is exactly how indoor positioning works in airports and malls.
Signal strength (RSSI) is converted to a rough distance with the log-distance
path-loss model, `d = 10^((txPower − RSSI) / (10n))`.

**Verified indoors** on 2026-07-25 with no satellite lock:
`No GNSS/BLE — trying cell-tower location... OK 11.149096,7.659633 ~550m`,
posted successfully and plotted on the dashboard.

### 4.2 Cellular data (4G LTE) — how the card reaches the internet
The card contains an **A7670 LTE Cat-1 modem** and a SIM card, exactly like a
phone. To send data it must:
- **register on the network** — find a cell tower and attach, and
- **open a data (PDP) context** using the network's *APN* (Access Point Name),
  which is the setting that tells the modem which gateway to the internet to use
  (e.g. MTN's APN is `web.gprs.mtnnigeria.net`).

Once attached, the card can make ordinary internet requests. **LTE bands:** the
A7670E supports band **B3 (1800 MHz)**, the main 4G band used by MTN, Airtel and
9mobile in Nigeria, so it connects in urban Zaria. **CSQ** (0–31) is the modem's
signal-strength number shown on the dashboard.

**Why this makes range a non-issue:** the two devices never talk to each other
directly. The card talks to a cell tower; the dashboard talks to the internet.
The distance between them is irrelevant — 5 m or 5 km behaves the same. That is the
core reason this design beats a direct radio link for the 200 m requirement.

### 4.3 The client–server model and HTTP
The **card is a client**; the **Python program is a server**. The card sends an
*HTTP POST* request — a small, structured internet message — to a fixed address
(`/api/ingest`) with the position encoded as **JSON** (a plain-text data format,
e.g. `{"lat":11.15,"lng":7.65}`). The server replies `{"ok":true}`. This is the
same request/response pattern every website uses.

### 4.4 The database (persistence)
The server saves every reading into **SQLite**, a small self-contained database
stored in one file (`tracking.db`). This means history survives restarts, the map
trail can be redrawn on page load, and the "recent locations" and "activity" views
have data to read. Each row is one position report (see the `readings` table in §8).

### 4.5 WebSockets — live updates without refreshing
A normal web page only receives data when it asks (a request). To make the map
update *by itself* the moment a new position arrives, we use a **WebSocket** — a
connection that stays open so the server can **push** messages to the browser at
any time. We use the **Socket.IO** library for this. When a reading arrives, the
server emits a `location_update` event and every open dashboard receives it
instantly.

*Why not just poll every second?* Polling wastes requests and adds lag; a WebSocket
delivers updates the instant they happen and scales to many viewers cleanly.

### 4.6 Tunnelling (ngrok) — connecting a public device to a private laptop
The card, on the mobile network, is on the **public internet**. The laptop running
the server is behind a router on a **private network** with no public address, so
the card cannot reach it directly. **ngrok** solves this: it opens a public address
and forwards anything sent there to the laptop's `localhost:5000`. We put that public
address into the firmware, and the card's POSTs arrive at the laptop. (In production
you would instead deploy the server to a cloud host with its own public address.)

**Why an HTTP tunnel and not a TCP one.** The obvious choice is `ngrok tcp 5000`,
which gives a raw `tcp://host:port`. On ngrok's **free** plan that is refused
(`ERR_NGROK_8013` — TCP endpoints require a payment method on file). HTTP tunnels
are free, so we use one:

```
ngrok http 5000 --scheme http
```

The `--scheme http` flag matters. By default an ngrok HTTP endpoint answers plain
HTTP with a **307 redirect to HTTPS**, and following that would force the modem to
perform a TLS handshake — extra complexity and a common source of failure on a
Cat-1 modem. Binding the endpoint to HTTP only serves the request directly on
**port 80**, so the card sends ordinary unencrypted HTTP.

Two further practical points:
- The free plan includes **one static domain**, so the address stays the same
  between sessions and the card never needs re-flashing (verified: the same
  `*.ngrok-free.dev` host was issued across separate agent runs).
- Free accounts may inject an HTML "browser warning" interstitial. The firmware
  sends the header `ngrok-skip-browser-warning: true` so the request passes
  straight through to the backend.

> **Security note for the report:** plain HTTP means the location payload is
> unencrypted in transit. That is acceptable for a controlled demo, but a
> production deployment should use HTTPS/TLS (the A7670E does support SSL) — list
> this in Chapter 6 recommendations.

---

## 5. Design decisions & why the alternatives were rejected

The project deliberately evaluated several approaches before choosing cellular +
GPS on an integrated board. Being able to justify this is worth marks.

| Approach | Range to 200 m | Verdict |
|---|---|---|
| **Passive RFID** | A few centimetres | Rejected — nowhere near 200 m |
| **Classic Bluetooth / BLE** | Tens of metres (BLE Long-Range needs line-of-sight + low-level coding) | Rejected — unreliable at 200 m, hard to build in time |
| **LoRa + base station** | Kilometres | Considered — works, but needs a *second* device (a base station) and a matched radio pair: more parts, more wiring, more to fail |
| **GPS + separate GSM module** (SIM868 / SIM800L) | Unlimited (network) | Considered — one device, but two loose modules and a fussy power circuit (a big capacitor to survive transmit current spikes) |
| **GPS + integrated 4G board (LilyGO T-A7670E)** ✅ chosen | Unlimited (network) | **Chosen** — the MCU, 4G modem, SIM slot, GPS and battery charging are all on **one board**. Fewest parts, least wiring, lowest risk before a deadline |

The evolution of the design (LoRa → discrete cellular → integrated board) is itself
part of the engineering story: each step **reduced part count and coupling** while
keeping the same software, because the server only ever cares about the JSON the
card posts — not how the card produced it.

---

## 6. Hardware

### 6.1 The board: LilyGO T-A7670E
A single PCB that integrates everything the card needs:

| On the board | Replaces (from earlier discrete designs) |
|---|---|
| ESP32-WROVER microcontroller | a separate MCU |
| A7670E 4G LTE Cat-1 modem + nano-SIM slot | a separate SIM800L/SIM868 module |
| **GNSS receiver inside the A7670E modem** | a separate NEO-6M / L76K GPS module |
| Li-ion/LiPo charge circuit + JST battery connector | a separate TP4056 charger |
| On-board power handling for the modem's current bursts | an external 1000 µF capacitor |

> **Variant note:** GPS requires the **A7670E-with-GPS** variant, which has a
> *second* antenna connector marked **GPS**. Our board is that variant. On this
> board the GNSS receiver is **inside the modem** — it is queried over AT commands,
> not read as NMEA from a separate chip on a UART (§7.3).

### 6.2 The rest of the bill of materials
| Part | Purpose |
|---|---|
| LilyGO T-A7670E board | The entire card electronics |
| LTE + GPS antennas | Cellular + satellite reception (ship with the board) |
| Nano data SIM (4G-enabled: MTN/Airtel/Glo/9mobile) | Mobile data for the card |
| 3.7 V LiPo battery, 1000 mAh+, JST connector | Power; charges on-board over USB-C |
| 3D-printed case (or hard ID-card holder) | Housing (`hardware/enclosure.scad`) |

### 6.3 Physical setup (the entire "wiring")
There is essentially no wiring — the electronics are integrated:
1. Insert the nano SIM into the on-board slot.
2. Plug the LiPo into the on-board JST connector (mind polarity).
3. Screw the **LTE antenna** onto the **MAIN** connector and the **GPS antenna**
   onto the **GPS** connector (matching the labels matters).
4. Connect USB-C to the laptop to flash the firmware.

### 6.4 Board pin map used by the firmware (from LilyGO's board definition)
| Function | ESP32 GPIO |
|---|---|
| Modem UART TX / RX | 26 / 27 |
| Modem PWRKEY / POWERON / RESET | 4 / 12 / 5 |
| Battery voltage sense (ADC) | 35 |

GPS needs **no GPIO** on this board — it lives inside the modem and is reached over
the same UART (26/27) using AT commands.

---

## 7. Firmware (the card)

File: [`firmware/card/card.ino`](firmware/card/card.ino). Written in the Arduino
framework for the ESP32.

### 7.1 Libraries
- **TinyGSM (LilyGO's fork — <https://github.com/lewisxhe/TinyGSM-fork>)** — drives
  the A7670 modem (network attach, data connection, HTTP). **Must be the fork:**
  mainline TinyGSM supports `A7672X`/`SIM7600` but has **no `TINY_GSM_MODEM_A7670`**,
  so the sketch fails to compile with "Please define GSM modem model". Install it
  via *Sketch → Include Library → Add .ZIP Library*, not the Library Manager.
- **ArduinoHttpClient** — builds the HTTP POST request over the modem's data link.
- *(TinyGPSPlus is **not** needed — the modem parses GNSS internally, so there is no
  NMEA stream for the ESP32 to decode.)*

### 7.2 What the firmware does, step by step
1. **Power the modem on.** LTE modems need a specific boot sequence: set the board
   power pin (`POWERON`, GPIO12) high, pulse the reset line, then pulse **PWRKEY**
   (GPIO4) low→high→low for over a second. This is the single most common
   bring-up gotcha and is handled in `powerOnModem()`. The A7670E then needs about
   **10 s** before it answers AT commands.
2. **Open one serial port:** UART1 to the modem (pins 26/27) at 115200 baud —
   everything, including GPS, goes over this one link.
3. **Power up the GNSS receiver** with `modem.enableGPS()` (`AT+CGNSSPWR=1`, which
   replies `+CGNSSPWR: READY!`).
4. **Attach to the network** and open a data connection using the SIM's **APN**.
5. **Loop forever:** every `POST_INTERVAL_MS` (5 s) ask the modem for its position
   with `modem.getGPS(...)` (`AT+CGNSSINFO`) and **HTTP POST** it as JSON
   to the server. Also read battery voltage and cellular signal (CSQ) to include.

### 7.3 How the GPS source was verified on the real hardware
The board's documentation and LilyGO's own example sketch (`ExternalGPS_A7670G_Only`)
suggested an **external L76K GPS chip** on ESP32 UART pins 22/21. On this board that
produced **zero bytes**. Rather than guess, a dedicated diagnostic sketch
([`firmware/gps_probe/gps_probe.ino`](firmware/gps_probe/gps_probe.ino)) was written
to test all three possibilities on the actual hardware:

| Test | Result |
|---|---|
| External GPS UART, RX 22 / TX 21 | **0 bytes** |
| External GPS UART, pins swapped (RX 21 / TX 22) | 1 byte (electrical noise) |
| Modem built-in GNSS, `AT+CGNSSPWR=1` | **`OK` + `+CGNSSPWR: READY!`** ✅ |

`AT+CGNSSPWR?` also returned `+CGNSSPWR: 0,0,1` (GNSS supported) and
`AT+CGNSSMODE?` returned `3` (multi-constellation). **Conclusion: this board has no
separate GPS chip — GNSS is inside the A7670E modem**, so the firmware queries it
over AT commands. This is a good example of verifying a datasheet assumption against
the physical device instead of trusting the documentation.

### 7.4 The packet the card sends
```json
{ "card_id":"CARD01", "lat":11.152300, "lng":7.653200,
  "sats":8, "hdop":1.1, "batt_mv":4020, "seq":128, "rssi":24, "snr":0 }
```

### 7.5 The two values you must set before flashing
Near the top of `card.ino`:
- **`APN`** — your SIM's access point name (default is MTN's, confirmed working).
- **`SERVER_HOST` / `SERVER_PORT`** — the public address ngrok prints.

### 7.6 `TEST_MODE` — proving the pipeline indoors
GPS needs open sky, which you don't have at a desk. Setting `#define TEST_MODE 1`
makes the card send a **fixed fake coordinate** every cycle, so you can prove the
whole chain (card → 4G → server → map) indoors before the GNSS can see satellites.
Set it back to `0` for the real outdoor demo.

### 7.7 Arduino IDE settings
Board: **"ESP32 Wrover Module"**. Install `ArduinoHttpClient` from the Library
Manager and **TinyGSM from LilyGO's fork** (§7.1), set the SIM APN and ngrok address,
select the COM port, and upload. Serial monitor baud is **115200**.

### 7.8 Verified bring-up log (what a healthy boot looks like)
```
Starting modem (allow ~10s to boot)...
Modem: Manufacturer: INCORPORATED Model: A7670E-FASE Revision: A7670M7_V1.11.1 IMEI: ...
Enabling built-in GNSS...
GNSS powered on (READY).
SIM status: 1  (1=READY, ...)
Waiting for LTE network...
Network registered. Operator: 62130          <- MCC 621 / MNC 30 = MTN Nigeria
Connecting data...
LTE data connected.
Setup done. Acquiring GNSS fix + sending positions...
No GNSS fix yet (needs clear sky — test outdoors). raw: ,,,,,,,,
```
The final line is the expected **indoor** state: the GNSS receiver is powered and
answering, but has no satellite lock. Outdoors those empty commas fill with data.

---

## 8. Backend (server)

File: [`backend/app.py`](backend/app.py). A **Flask** web server with
**Flask-SocketIO** for live push. Runs on the demo laptop.

### 8.1 The data model
**`readings` table (SQLite)** — one row per position report:
`id, card_id, lat, lng, sats, hdop, batt_mv, seq, rssi, snr, ts`.

**Student roster (in code)** — five 500-level Computer Engineering students.
Only `U19CO1011` (Delight Iworima) is mapped to a real card (`CARD01`); the others are
registered with no device. Edit the `STUDENTS` list to change names/reg numbers.

| Reg number | Name | Device |
|---|---|---|
| U19CO1011 | Delight Iworima | CARD01 (trackable) |
| U19CO1007 | Aisha Bello | — |
| U19CO1019 | Chinedu Okafor | — |
| U19CO1023 | Fatima Sani | — |
| U19CO1042 | Emeka Nwosu | — |

### 8.2 The single shared write path
Both the real card and the built-in simulator call one function,
**`handle_reading()`**, which: adds a server timestamp, stores the row, tags it with
the student it belongs to, and **emits** the `location_update` WebSocket event. This
guarantees the dashboard behaves identically whether the data is real or simulated —
a deliberate design choice so the software could be built and proven before hardware
arrived.

### 8.3 Endpoints (full reference)
**Pages (require sign-in):**
`/login`, `/logout`, `/dashboard`, `/students`, `/track/<reg>`, `/live` (jumps to
the active tracked student), `/activity`, `/docs` (API docs).

**APIs:**
| Method & path | Purpose |
|---|---|
| `POST /api/ingest` | An authenticated card reports a validated position (the only write endpoint) |
| `GET /api/students` | The roster, each tagged online/offline |
| `GET /api/student/<reg>` | One student + their latest reading |
| `GET /api/student/<reg>/recent?limit&gap` | Recent locations, sampled ~`gap` s apart |
| `GET /api/student/<reg>/track?limit` | GPS-only route playback plus distance and speed statistics |
| `GET /api/ping/<reg>` | Check whether a device is assigned and has reported recently |
| `GET /api/activity?limit` | Recent updates across all devices (activity feed) |
| `GET /api/history?card_id&limit` | Raw history to redraw the map trail |

### 8.4 The "recent locations" sampling (and the interval choice)
The device posts every ~5 s, so five *raw* recent points would be almost identical
dots. `recent_locations()` walks the history newest-first and keeps a point only if
it is at least **`gap` seconds** (default **30 s**) older than the last kept point.
**Why 30 s:** five points 30 s apart span ~2½ minutes of movement — frequent enough
to show a real trail, spaced enough that the points are visibly distinct. The value
is a query parameter, so it is trivially tunable.

### 8.5 Authentication
Sign-in uses a Flask **session** (a signed cookie). The demo accepts
`admin` / `abu2026`. Page routes, student/location APIs, Swagger and Socket.IO all
require that session. Device reports use a separate `X-Device-Key` header and reject
unknown card identifiers. *(The supplied credentials are still demonstration values;
see §13.)*

---

## 9. Frontend (dashboard)

Static HTML/CSS/JavaScript served by the backend. Shared design system in
[`dashboard/static/abu.css`](dashboard/static/abu.css).

### 9.1 Pages
| Page | What it shows |
|---|---|
| **Login** | ABU-branded split screen; staff sign-in |
| **Dashboard** | Overview: KPI tiles, active-device telemetry, health indicators, charts and recent activity (no map) |
| **Students** | The roster; search by reg number; "Track student" checks device status then opens the map |
| **Live Map** (track) | Full campus map, live marker + trail, telemetry panel, top-5 recent locations |
| **Activity** | A live event log of every location update received |

### 9.2 The visual design system
- **Brand:** Ahmadu Bello University green (`#0a5c34`) and gold (`#c19a33`) on
  clean white; a subtle northern-Nigeria 8-point-star geometric motif.
- **Type:** the **IBM Plex** family — Plex Sans (interface), Plex Mono (machine
  data like registration numbers and coordinates), Plex Serif (the university
  wordmark). The three roles encode meaning: institution / interface / data.
- **Surfaces:** frosted-glass ("glassmorphism") chrome — sidebar, top bars, cards —
  over the patterned background; **no gradients**; a persistent left sidebar for
  navigation (Dashboard / Students / Live Map / Activity / API Docs).

### 9.3 The live map
Uses **Leaflet.js** with Esri satellite imagery by default and OpenStreetMap as an
alternate layer. A `location_update` from the
WebSocket moves the marker, extends the trail polyline, and refreshes the telemetry
and recent-locations panels. On load, `/api/history` redraws the existing trail.

---

## 10. The API and its documentation

The API is documented with a hand-authored **OpenAPI 3.0** specification
([`backend/openapi.json`](backend/openapi.json)) and rendered as interactive
**Swagger UI** at **`/docs`** (served locally by `flask-swagger-ui`, no external
CDN, so it works offline).

At `/docs` every endpoint expands to show its description, parameters, request and
response schemas, and worked examples. The **"Try it out"** button executes a real
request against the running server. Browser read requests use the signed-in session;
`POST /api/ingest` additionally requires the demonstration `X-Device-Key` entered
through Swagger's **Authorize** control.

**Presentation value:** the OpenAPI file is written by hand (not auto-generated), so
each endpoint can be explained intrinsically, and the interactive docs let the panel
watch the API work live.

---

## 11. Setup & running

### 11.1 Backend + dashboard (no hardware needed — simulator)
```
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app.py --simulate
```
Open <http://localhost:5000>, sign in (`admin` / `abu2026`), search `U19CO1011`,
and track. The simulator stands in for the card, walking a loop around campus.

### 11.2 Backend for the real card
```
venv\Scripts\python app.py            # cellular mode (default, no flags)
```
In a second terminal, expose it to the card over the internet:
```
ngrok http 5000 --scheme http
```
Copy the `host` and `port` ngrok prints into `firmware/card/card.ino`
(`SERVER_HOST` / `SERVER_PORT`).

### 11.3 Flash the card
Arduino IDE → board **"ESP32 Wrover Module"** → install **ArduinoHttpClient**
(Library Manager) plus **TinyGSM from LilyGO's fork** (see §7.1 — the mainline
version will not compile) → set `APN` and the ngrok address → upload.

### 11.4 Assemble
Insert SIM, plug in the LiPo, attach both antennas (LTE→MAIN, GPS→GPS), close the
case with both antennas facing out. (See `docs/assembly_guide.md`.)

---

## 12. Demo-day runbook

**Before the panel arrives**
1. Start the backend: `venv\Scripts\python app.py`.
2. Start the tunnel: `ngrok http 5000 --scheme http`; confirm the firmware has that address.
3. Power the card **early** and take it outside — the first GPS fix can take
   minutes. Confirm the serial monitor reaches "LTE data connected" then real
   coordinates.
4. Have `--simulate` mode ready as a fallback if the network misbehaves indoors.

**In front of the panel**
1. Open the dashboard, sign in.
2. Show the **Dashboard** overview: KPIs, active telemetry, health indicators and charts.
3. Go to **Students**, search `U19CO1011`, click **Track student** — narrate the
   device-status check.
4. On the **Live Map**, show the marker moving, the telemetry, and the recent-
   locations trail. Walk the card 200 m away to prove range.
5. Open **API Docs** (`/docs`): use **Authorize** to enter the demo device key,
   expand `POST /api/ingest`, hit **Try it out**, and show the posted point appear
   on the map.

**The one-line pitch:** *"A student ID that finds itself with GPS and reports its
position over 4G to a live, access-controlled dashboard — with a documented API
behind it."*

---

## 13. Limitations & honest trade-offs

Stating these plainly is stronger than hiding them.

- **Physical size:** a real ISO ID card is about 85.6 × 54 × 0.76 mm. The current
  enclosure calculates to roughly **110.4 × 75.1 × 8.4 mm** before printer
  tolerances because the development board alone is about 106 mm long. The result
  is a lanyard/pocket badge, not a wallet card. A custom PCB is the miniaturisation path.
- **Indoor GPS:** GPS needs a clear sky; it will not fix reliably indoors. Always
  demo outdoors and power on early.
- **Network dependency:** tracking requires mobile coverage and a data-enabled SIM
  at the location. Urban Zaria has LTE B3 coverage; confirm by browsing on a phone
  first.
- **Demo security:** the presentation mode uses replaceable demonstration credentials
  and a device key. Production mode requires environment-supplied secrets. The modem
  link remains plain HTTP for demo reliability, so use only consenting/test data;
  production requires certificate-validated TLS and individual staff accounts.
- **Battery life:** continuous GPS + 4G is power-hungry; run time depends on battery
  capacity. A larger cell or a slower report interval extends it.
- **One device:** the demo has five registered students but one physical card, so
  only `U19CO1011` shows live data.

---

## 14. Troubleshooting

| Symptom | Likely cause & fix |
|---|---|
| Serial monitor shows no modem reply | Keep the LiPo plugged in (the modem needs battery current); the firmware already sets POWERON high and pulses PWRKEY — if it still fails, flip `MODEM_RESET_LEVEL` and re-flash |
| "No network" / won't attach | SIM not 4G-enabled, wrong APN, or weak signal; test the SIM in a phone first |
| "No GPS fix yet" | Needs open sky; first fix can take 1–5 min; keep the GPS antenna facing up and unblocked |
| Dashboard shows nothing | Backend not running, or the firmware's ngrok address is stale (ngrok addresses change unless you reserve one) |
| Points appear but don't move | You are stationary, or `TEST_MODE` is still `1` (fixed fake coordinate) |
| `/docs` blank | Re-run `pip install -r requirements.txt` (installs `flask-swagger-ui`) |

---

## 15. Glossary

- **GPS / GNSS** — satellite positioning system the card uses to find itself.
- **NMEA** — the text format a GPS chip outputs its results in.
- **HDOP** — a fix-quality measure from satellite geometry; lower is better.
- **TTFF / cold start** — time for the first GPS fix after power-on (minutes).
- **LTE Cat-1** — the class of 4G the A7670 modem uses.
- **APN** — the SIM setting that opens the path from the modem to the internet.
- **CSQ** — cellular signal-strength value, 0–31.
- **HTTP POST** — an internet request that sends data to a server.
- **JSON** — a plain-text data format used for the position packets.
- **WebSocket / Socket.IO** — a persistent connection letting the server push live
  updates to the browser.
- **SQLite** — a small single-file database storing every reading.
- **Flask** — the Python web framework running the server.
- **ngrok / tunnel** — gives the laptop server a public internet address the card
  can reach.
- **OpenAPI / Swagger** — a standard for describing an API and a UI for exploring it.
- **ESP32** — the microcontroller (the "brain") on the board.

---

## 16. Project file structure

```
bt_scan/
├── TECHNICAL_DOCUMENTATION.md      ← this document
├── README.md                       ← quick start
├── firmware/
│   ├── card/card.ino               ← card firmware (ESP32 + A7670E + built-in GNSS)
│   └── gps_probe/gps_probe.ino     ← diagnostic: proves which GPS source the board has
├── backend/
│   ├── app.py                      ← Flask server + Socket.IO + APIs
│   ├── openapi.json                ← hand-authored API specification
│   ├── requirements.txt            ← Python dependencies
│   └── tracking.db                 ← SQLite database (created on first run)
├── dashboard/
│   ├── login.html                  ← staff sign-in
│   ├── dashboard.html              ← overview
│   ├── students.html               ← roster + search + track
│   ├── track.html                  ← live map + telemetry + recent locations
│   ├── activity.html               ← live event log
│   ├── health.html                 ← live readiness checks
│   ├── sw.js                       ← offline cache rules
│   └── static/                     ← ABU CSS, local libraries and offline map
├── hardware/
│   └── enclosure.scad              ← parametric 3D-printable case
└── docs/
    ├── project_plan.html           ← architecture, BOM, schedule (visual)
    ├── assembly_guide.md           ← wiring, setup, bring-up
    ├── build_visual_guide.html     ← component/coupling/product visuals
    └── report_outline.md           ← report skeleton
```

---

## 17. Final reliability and analysis additions

### 17.1 Route selection and stop detection

The server groups satellite readings by Lagos calendar day. A gap longer than
three minutes starts another **walk session**, preventing a false straight line
between separate outings. A **stop** is detected when accepted points stay within
an 18 m area for at least 60 seconds. The response therefore separates total,
moving and stopped time and allows the user to select a date and walk.

### 17.2 Direction and marker movement

The line is still calculated from evidence-preserving refined GPS points. The
browser adds spaced arrows from the bearing between neighbouring points. New live
positions animate over 900 ms with eased interpolation, so the marker moves
naturally between five-second reports. Users who request reduced motion receive
an immediate update instead.

### 17.3 Safety zone

One configurable circular zone is stored in SQLite. For each live GPS or BLE
anchor reading, the server calculates distance from the centre and compares the
new inside/outside state with the previous one. A changed state creates a stored
alert and a live Socket.IO event. Cell-tower and GPS-hold reports never trigger
the boundary because they are not precise enough.

### 17.4 Offline presentation

The service worker stores the dashboard's local CSS, JavaScript, logo, map engine
and map tiles that have already been viewed. API responses are not silently
cached. The presenter explicitly stores one labelled route snapshot in browser
local storage. A bundled simplified ABU SVG provides a map background if online
tiles fail.

### 17.5 Store-and-forward on the card

The ESP32 has a 20-packet circular queue in NVS flash. Temporary HTTP/network
failures add a position JSON packet to the queue. Once LTE returns, three saved
packets are sent per cycle before the current point. Each includes its original
UTC capture time and `buffered: true`. SQLite stores capture and server-arrival
times separately, and route playback sorts by capture time.

### 17.6 Reports, health and startup

The route page downloads CSV evidence or a branded multi-page PDF generated with
ReportLab. `/health` checks Flask, SQLite, ngrok, the card's last report,
the last saved position and local presentation assets. `START_DEMO.cmd` starts
the server/tunnel and opens that readiness flow; `STOP_DEMO.cmd` stops only the
processes recorded by the launcher.

---

*End of technical documentation. For the quick-start, see `README.md`; for the
build visuals, open `docs/build_visual_guide.html`; for the interactive API, run the
backend and visit `/docs`.*
