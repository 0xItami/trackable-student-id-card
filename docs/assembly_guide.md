# SIID-01 Assembly & Bring-up Guide (LilyGO T-A7670)

Almost everything is on the one board. There is barely any wiring — the ESP32,
4G LTE modem, SIM slot, GPS, and battery charging are all integrated. Do the
staged bring-up at the bottom so problems are easy to isolate.

---

## 1. What the board already has (so you DON'T wire it)

| On the LilyGO T-A7670 | Replaces |
|---|---|
| ESP32-WROVER | the separate MCU |
| A7670 4G LTE modem + SIM slot | the SIM800L / SIM868 module |
| **GNSS built into the A7670E modem** | the separate NEO-6M / L76K |
| Li-ion/LiPo charge circuit + JST connector | the TP4056 module |
| Power management for the modem's current bursts | the 1000µF capacitor |

So the old parts list (TP4056, SIM800L, NEO-6M, capacitor, extra wiring) is
**gone**. That's the whole point of this board.

---

## 2. Physical setup — the entire "assembly"

1. **SIM:** insert a **nano** data SIM (MTN/Airtel/Glo/9mobile, 4G-enabled) into
   the onboard slot.
2. **Battery:** plug a 3.7V LiPo into the onboard **JST** connector. Mind the
   polarity — check the + / − silk marks; a reversed cell can damage the board.
3. **Antennas — attach BOTH:**
   - the **LTE / main** antenna → the connector marked **MAIN** (or **LTE**)
   - the **GPS** antenna → the connector marked **GPS**
   Wrong antenna on wrong port = no signal, so match the labels.
4. **USB-C** to your laptop to flash and watch the serial monitor.

That's it. No breadboard, no solder for the electronics.

> **Confirm your board has GPS.** GNSS + the GPS antenna port are only on the
> **A7670E-with-GPS** version. If there is only one antenna connector, your board
> has no GPS — you'd need a board swap or an add-on GPS. Check before demo day.

---

## 3. Data flow (end to end)

```
GPS satellites        4G LTE network            your laptop
      |                     |                        |
      v                     v                        v
  modem GNSS --AT--> ESP32 (T-A7670E) --LTE HTTP--> ngrok tunnel --> Python backend
  (position)          A7670 modem       POST /api/ingest             |        |
                                                                  SQLite   WebSocket
                                                                             v
                                                                Leaflet dashboard (map)
```

---

## 4. Bridge the card to your laptop (one-time)

The card is on the public internet (via LTE); your backend runs on your laptop.
Connect them with a free tunnel:

For the presentation, `START_DEMO.cmd` in the project root performs steps 1–2
and opens the system-health screen automatically. The manual commands below are
kept so you can explain and troubleshoot the process.

1. `python app.py`  (in `backend/` — cellular mode is the default, no flags)
2. In a second terminal: `ngrok http 5000 --scheme http`
3. ngrok prints an HTTP forwarding address such as
   `http://your-name.ngrok-free.app -> http://localhost:5000`.
4. Put only that address's **host name** into `SERVER_HOST`, keep
   `SERVER_PORT` at `80`, and confirm firmware `DEVICE_API_KEY` matches the
   backend's `SIID_DEVICE_API_KEY`. Then flash.

Use the static HTTP development domain assigned by your ngrok account when
available so the address does not change between sessions.

---

## 5. Bring-up order (do NOT skip stages)

**Stage A — flash + modem boot.** Board settings: **"ESP32 Wrover Module"**.
Install **ArduinoHttpClient** + **TinyGSM (LilyGO's fork)**. Flash,
open Serial Monitor @ 115200. You should see "Modem: ..." print its info. If the
modem never answers, see troubleshooting below.

**Stage B — network (indoors OK).** With the SIM + LTE antenna on, the log should
reach **"LTE data connected."** If not: SIM not 4G-enabled, wrong APN, or no LTE
coverage. Sanity-check by browsing 4G with that SIM in a phone first.

**Stage C — full path, fake GPS (indoors).** Set `#define TEST_MODE 1`, set your
ngrok `SERVER_HOST`/`SERVER_PORT`, flash. Run `python app.py` + `ngrok http 5000 --scheme http`,
open `http://localhost:5000`. The marker should sit at the fake coordinate and
update every 5 s — this proves card → LTE → backend → map without needing GPS.

**Stage D — real GPS (outdoors).** Set `TEST_MODE 0`, flash. Go **outside with
clear sky** and the GPS antenna facing up. First fix can take 1–5 min (cold
start). "No GPS fix yet" becomes real coordinates; the marker jumps to your
position.

**Stage E — untethered + 200 m demo.** Unplug USB, run on the LiPo. Walk 200 m+
across campus — over LTE the map keeps updating regardless of distance. Screen-
record it for the report.

---

## 6. Troubleshooting the modem (most common issue)

If the Serial Monitor shows no modem reply:
- Confirm the **LiPo is plugged in** — the modem's transmit bursts need battery
  current even when USB is connected; some boards won't register on USB alone.
- The firmware already sets **POWERON (GPIO12) HIGH** and pulses **PWRKEY** — if
  it still fails, flip `MODEM_RESET_LEVEL` from `LOW` to `HIGH` in the firmware
  (board revisions differ) and re-flash.
- Give it time — LTE registration can take 30–60 s on first boot.

---

## 7. Physical fit for the enclosure

The board is bigger than a credit card, so this is a **lanyard/pocket badge**
(present that as the deliberate trade-off in the report). In the case:
- Keep **both antennas' tips unobstructed** — especially the GPS antenna facing
  the lid / sky. Don't sandwich them under the battery.
- Battery sits under the board on foam tape.
- Leave the USB-C port reachable at the case edge for charging.

See `hardware/enclosure.scad` — measure the actual board + battery and update
the parameters at the top before printing.
