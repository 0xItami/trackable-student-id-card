# SIID-01 — Trackable Student ID Card

Final year project (Computer Engineering, ABU Zaria). Full rationale, BOM,
and schedule: open `docs/project_plan.html`. Report skeleton: `docs/report_outline.md`.
For the final live test and presentation sequence, use `DEMO_CHECKLIST.md`.

**Design: one all-in-one board.** The tracker is a GPS-enabled **LilyGO
T-A7670-series** board — ESP32 +
4G LTE modem + SIM slot + GPS + battery charging on a single PCB. It reads its
own GPS and sends its position to the backend over 4G. No base station, no LoRa,
no separate GPS/charger/capacitor — range is effectively unlimited.

## What's in the card
- **GPS-enabled LilyGO T-A7670-series** board (ESP32 + A7670 LTE modem with **built-in GNSS**
  + battery charger — verified: GPS is inside the modem, not a separate chip)
- 3.7V LiPo battery (onboard JST connector)
- nano data SIM (MTN/Airtel/Glo/9mobile, 4G-enabled)
- LTE + GPS antennas (come with the board)

## Layout
- `firmware/card/` — flash to the T-A7670; setup is in the file header
- `hardware/enclosure.scad` — parametric 3D-printable case (open in OpenSCAD)
- `docs/assembly_guide.md` — physical setup, tunnel, and staged bring-up
- `backend/` — Python (Flask-SocketIO) that receives the card's position and
  serves the dashboard
- `dashboard/` — the live-map web page

## The dashboard (ABU Zaria branded)

Six main pages, served by the backend:
- **/login** — staff sign-in (the default controlled-demo account is documented below)
- **/dashboard** — system status, telemetry summaries and recent activity
- **/students** — roster of 5 Computer Engineering students; search by reg number,
  then "Track student" pings the device and opens the live map
- **/track/<reg>** — live map + telemetry, selectable recorded walks, route
  playback, direction arrows, detected stops, speed/distance, safety zone,
  CSV/PDF downloads and an offline replay
- **/activity** — recent readings and source/quality charts
- **/health** — one-screen readiness check for the server, database, ngrok,
  card, latest position and offline presentation files
- **/docs** — interactive API documentation (Swagger UI, rendered from the
  hand-authored `backend/openapi.json`); "Try it out" works against the live
  backend

Demo story: all 5 students are registered, but only **U19CO1011 (Delight Iworima)**
carries the real card (`CARD01`) — the others show "No device". Edit the roster
in `backend/app.py` (the `STUDENTS` list) to use real names/reg numbers.

## Running the backend

For the real presentation, double-click **`START_DEMO.cmd`** in this folder. It
starts the Flask server and ngrok in hidden background windows, waits for the
server, and opens the readiness/login screen. Use **`STOP_DEMO.cmd`** afterwards
to stop only the processes started by that launcher.

No hardware yet? Prove the whole software stack now:
```
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app.py --simulate
```
Open http://localhost:5000, sign in, search `U19CO1011`, and track — the marker
walks a loop with live telemetry, driven by the simulator standing in for the card.

Run the focused backend/security regression suite with:

```powershell
cd backend
.\venv\Scripts\python.exe -m unittest -v test_app.py
```

For the real card (cellular mode is the default):
```
venv\Scripts\python app.py
```
Then expose it to the card over the internet:
```
ngrok http 5000 --scheme http
```
Put the `host` and `port` ngrok prints into `firmware/card/card.ino`. Full
steps are in `docs/assembly_guide.md`.

The presentation build starts in explicit demo-security mode by default. Its
login is `admin` / `abu2026`, and the firmware sends the matching demonstration
device key. Use only consenting or synthetic student data. For a non-demo run,
set `SIID_DEMO_MODE=0` and provide `SIID_ADMIN_USER`, `SIID_ADMIN_PASSWORD`,
`SIID_DEVICE_API_KEY`, and `SIID_SECRET_KEY` as environment variables.

## Flashing the firmware
1. Arduino IDE → Boards Manager → install "esp32" (Espressif Systems)
2. Library Manager → install `ArduinoHttpClient` (Arduino)
2b. **TinyGSM must be LilyGO's fork** — <https://github.com/lewisxhe/TinyGSM-fork>
   (download ZIP → Sketch → Include Library → Add .ZIP Library). The mainline
   TinyGSM in Library Manager has **no A7670 support** and will not compile.
3. Open `firmware/card/card.ino`. Set your SIM's `APN` and your ngrok
   `SERVER_HOST`/`SERVER_PORT` near the top. Confirm `DEVICE_API_KEY` matches
   the backend's `SIID_DEVICE_API_KEY` (the supplied demo values already match).
4. Select board **"ESP32 Wrover Module"**, pick the COM port, upload.
5. Physical setup (SIM, battery, antennas) is in `docs/assembly_guide.md`.

The firmware keeps up to 20 unsent position packets in ESP32 flash. After a
temporary LTE/tunnel failure it forwards up to three per cycle, preserving the
time each point was captured. This is the store-and-forward behaviour visible
as `buffered` data in CSV exports.

## Known limits to flag in the report
- Live satellite GPS needs sky view. Indoors the card clearly falls back to its
  recent saved GPS position and then a coarse cell-tower estimate.
- GPS requires the **A7670E-with-GPS** variant — confirm your
  board has a second antenna connector labeled GPS
- This is a 4G LTE modem — the SIM must be 4G-enabled and there must be LTE
  coverage at the demo spot (urban Zaria has MTN/Airtel B3 1800MHz)
- The current enclosure calculates to roughly **110.4 × 75.1 × 8.4 mm** before
  printer tolerances. It is a lanyard/pocket badge, not a wallet-sized ISO card;
  present the custom-PCB miniaturisation path as future work.
