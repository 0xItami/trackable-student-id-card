# SIID-01 Demonstration Checklist

Use this as the final operating checklist. Do not replace measured values with
estimates; write the real results into the table below.

## 1. One-time preparation

1. In `firmware/card/card.ino`, verify the SIM APN and current ngrok
   `SERVER_HOST`. Keep `SERVER_PORT` at `80` for the tested demo transport.
2. Confirm the firmware `DEVICE_API_KEY` and backend demo key match. The supplied
   presentation value is `siid-card-demo-2026`.
3. Flash the updated firmware. This is required because the backend now rejects
   unauthenticated card reports.
4. Attach the LTE antenna to MAIN/LTE and GPS antenna to GPS before powering the modem.
5. Fully charge the battery or power bank.

## 2. Start the system

Double-click this file in the project root:

```powershell
C:\Projects\bt_scan\START_DEMO.cmd
```

It starts both the backend and ngrok, then opens the readiness screen. Sign in
with the controlled-demo account `admin` / `abu2026`. Do not continue until the
server, database and offline-file checks are green. The card and tunnel checks
must also be green for the live part; a saved replay remains available if they are not.

The backend prints a warning when demo mode is active. That is intentional: use
only your own/consenting test location and the fictional roster.

## 3. Real-card checks

- Serial Monitor shows the modem identity.
- SIM status is ready.
- LTE registers and data connects.
- GNSS is enabled.
- A real GPS fix appears outdoors.
- Every POST receives HTTP `200`.
- Dashboard changes to online after the next successful report (normally 5–15 s).
- `U19CO1011` opens the correct map.
- Activity receives new readings.
- Route playback contains the outdoor walk.
- Route arrows point in the walking direction and one-minute stops appear as purple markers.
- Select the correct recorded day/walk and click **Save offline replay**.
- CSV and PDF route downloads both open successfully.
- Set a small safety zone around the current position and verify its circle appears.
- Briefly stop ngrok, collect at least one point, restart it, and confirm the
  firmware prints `Forwarding saved packet` (store-and-forward test).
- Unplug/reconnect test restores a recent good GPS hold.

If POST returns `401`, the firmware was not reflashed or its device key differs
from the backend. `403` means the card ID is not registered. `429` means reports
are arriving faster than once per second.

## 4. Measurements for the report

| Test | Result | Evidence file/photo |
|---|---:|---|
| Cold-start time to first GPS fix | ___ min ___ s | ___ |
| Satellites at first accepted fix | ___ | ___ |
| Best fix-quality value | ___ | ___ |
| 100 m test: updates received | ___ / ___ | ___ |
| 200 m test: updates received | ___ / ___ | ___ |
| 500 m test, if attempted | ___ / ___ | ___ |
| Typical card-to-dashboard delay | ___ s | ___ |
| Battery runtime at 5 s reporting | ___ h ___ min | ___ |
| Measured finished enclosure | ___ × ___ × ___ mm | ___ |

For update delay, compare the serial POST time with the dashboard arrival time
for at least ten readings and report the average.

## 5. Presentation sequence

1. Explain the problem and show the physical badge.
2. Open System Health and show that the six checks explain exactly what is ready.
3. Show Dashboard health and telemetry—there is intentionally no map on Home.
4. Open Students, search `U19CO1011`, then click **Track student**.
5. Explain that “checking device status” reads the most recent server report; it
   is not a command sent back to the card.
6. Show the satellite marker, location source, age, battery and cellular signal.
7. Demonstrate day/walk selection, route arrows, stops, playback, distance and speed.
8. Show the safety-zone circle and download the PDF report.
9. Open Activity and explain GPS, last-GPS and cell-source readings in plain language.
10. Open `/docs`; the browser session authorizes read APIs. For POST `/api/ingest`,
   press **Authorize** and enter the demo device key before using **Try it out**.
11. State the physical-size, indoor-GPS, plaintext-demo-link and one-device limitations.

## 6. Fallbacks

- Primary: real card and live GPS/LTE.
- First fallback: use the **saved offline replay** on the live-map page; its local
  ABU reference map works even when internet map tiles fail.
- Second fallback: stop the normal backend and run
  `.\venv\Scripts\python.exe app.py --simulate`; clearly call it simulation.
- Keep screenshots of the real map, serial log and Activity page available offline.

After the presentation, double-click `STOP_DEMO.cmd`.
