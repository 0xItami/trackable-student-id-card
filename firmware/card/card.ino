// ============================================================================
// SIID-01 CARD FIRMWARE — LilyGO T-A7670E (ESP32 + 4G LTE + built-in GNSS)
//
// ONE board does everything: ESP32, 4G LTE modem, SIM slot, GNSS (GPS) and
// USB-C power support. This firmware reads the position from the A7670E's OWN
// built-in GNSS receiver (AT+CGNSSPWR / AT+CGNSSINFO), opens an LTE data
// connection, and HTTP-POSTs the position to the backend.
// (The A7670E covers LTE band B3/1800MHz — the main Nigerian 4G band.)
//
// NOTE ON GPS SOURCE: this board has NO separate L76K GPS chip on a UART.
// Verified on the actual hardware with firmware/gps_probe: the external GPS
// UART produced 0 bytes, while AT+CGNSSPWR=1 returned "+CGNSSPWR: READY!".
// So GPS comes from the modem itself, via TinyGSM's enableGPS()/getGPS().
//
// Arduino IDE setup:
//   - Board: "ESP32 Wrover Module"
//   - Libraries: ArduinoHttpClient (Arduino), and
//     *** TinyGSM must be LilyGO's FORK: github.com/lewisxhe/TinyGSM-fork ***
//     Mainline TinyGSM has NO A7670 support and will not compile.
//     (TinyGPSPlus is NOT needed — the modem parses GNSS for us.)
//
// Hardware setup (that's ALL the "wiring"):
//   1. Insert a nano data SIM (4G-enabled, with an active data bundle)
//   2. Screw the FULL-BAND LTE antenna onto the MAIN port, and the GPS
//      ceramic-patch antenna onto the GPS port
//   3. Power over USB-C from a computer while flashing or from a power bank
//      during the demonstration. No battery is fitted to this prototype.
// ============================================================================

#define TINY_GSM_MODEM_A7670
#define TINY_GSM_RX_BUFFER 1024

// ---- optional BLE indoor tier ----------------------------------------------
// 0 = off (default): GPS -> last-GPS-hold -> cell tower. Smaller, faster, and
//     enough for the demo, since GPS-hold covers "walked in from outside".
// 1 = on: also scans for known BLE anchors for room-level indoor accuracy.
//     Requires configuring BLE_ANCHORS[] below with a real beacon + coordinates.
#define USE_BLE_ANCHORS 0

#include <TinyGsmClient.h>
#include <Preferences.h>
#if USE_BLE_ANCHORS
  #include <BLEDevice.h>
  #include <BLEScan.h>
  #include <BLEAdvertisedDevice.h>
#endif

// ---- identity --------------------------------------------------------------
#define CARD_ID "CARD01"

// ---- bench-test mode -------------------------------------------------------
// 1 = POST a fixed FAKE coordinate even without a GNSS fix, so the LTE +
// backend + dashboard path can be proven indoors. 0 = real GPS for the demo.
#define TEST_MODE 0
#define TEST_LAT  11.152300
#define TEST_LNG  7.653200

// ---- mobile network — SET THIS FOR YOUR SIM --------------------------------
// MTN:     web.gprs.mtnnigeria.net      (confirmed working: operator 621-30)
// Airtel:  internet.ng.airtel.com
// Glo:     gloflat
// 9mobile: 9mobile
const char APN[]       = "internet.ng.airtel.com";
const char GPRS_USER[] = "";
const char GPRS_PASS[] = "";

// ---- backend location ------------------------------------------------------
// Run the backend on the laptop, then in a second terminal:
//     ngrok http 5000
//
// This A7670 modem firmware cannot negotiate ngrok's current TLS ciphers
// (HTTPACTION 715: handshake failed), so ngrok exposes the device endpoint as
// HTTP and forwards it locally to Flask. The API key still authenticates posts.
//
// The domain below is this ngrok account's FREE STATIC domain — it does not
// change between sessions, so the card does not need re-flashing each time.
const char SERVER_HOST[] = "frill-relay-nacho.ngrok-free.dev";
const int  SERVER_PORT   = 80;
const char RESOURCE[]    = "/api/ingest";
const char HEARTBEAT_RESOURCE[] = "/api/heartbeat";
// Demo credential shared with backend/app.py. Replace this value and set the
// backend SIID_DEVICE_API_KEY environment variable before any non-demo use.
const char DEVICE_API_KEY[] = "siid-card-demo-2026";

#define POST_INTERVAL_MS 5000

#if USE_BLE_ANCHORS
// ---- BLE indoor anchors ----------------------------------------------------
// Satellites cannot reach inside a building, and cell-tower location is very
// coarse (~100 m - 1 km). So the card also scans for known Bluetooth LE
// "anchors" placed at known coordinates. Seeing one means the card is within a
// few metres of that anchor — room-level indoor positioning.
//
// An anchor can be ANY BLE device that advertises: a laptop/phone running a BLE
// beacon app, a cheap iBeacon tag, or a spare ESP32 advertising a name.
// Identify it by advertised NAME or by MAC address (either is matched below).
// Add one row per building/room you want to cover.
struct BleAnchor {
  const char *id;      // advertised name OR MAC, e.g. "SIID-ANCHOR-1" / "aa:bb:cc:dd:ee:ff"
  double      lat;
  double      lng;
  const char *label;   // human-readable place name (for your own reference)
};

BleAnchor BLE_ANCHORS[] = {
  // EDIT: set these to your real anchor device + its true coordinates.
  { "SIID-ANCHOR-1", 11.152300, 7.653200, "Computer Engineering Dept" },
};
const int BLE_ANCHOR_COUNT = sizeof(BLE_ANCHORS) / sizeof(BLE_ANCHORS[0]);

#define BLE_SCAN_SECONDS 2      // how long each scan lasts
#define BLE_RSSI_MIN    -95     // ignore anchors weaker than this (too far away)
#define BLE_RETRY_MS     10000  // how often to scan while there is no GNSS fix

BLEScan  *bleScan   = nullptr;
uint32_t  lastBleTry = 0;

// Rough distance from signal strength: d = 10^((txPower - rssi) / (10 * n))
// txPower ~= RSSI at 1 m, n = path-loss exponent (~2 free space, ~2.5-3 indoors).
int estimateMetresFromRssi(int rssi) {
  const float txPower = -59.0f, n = 2.5f;
  float d = pow(10.0f, (txPower - (float)rssi) / (10.0f * n));
  if (d < 1) d = 1;
  if (d > 100) d = 100;
  return (int)d;
}

// Scan for any configured anchor. Returns its index, or -1 if none seen.
int scanForBleAnchor(int *rssiOut) {
  if (!bleScan) return -1;
  BLEScanResults *results = bleScan->start(BLE_SCAN_SECONDS, false);
  int best = -1, bestRssi = -999;

  for (int i = 0; i < results->getCount(); i++) {
    BLEAdvertisedDevice d = results->getDevice(i);
    int rssi = d.getRSSI();
    if (rssi < BLE_RSSI_MIN) continue;

    String name = d.haveName() ? String(d.getName().c_str()) : String("");
    String mac  = String(d.getAddress().toString().c_str());
    name.toLowerCase();
    mac.toLowerCase();

    for (int a = 0; a < BLE_ANCHOR_COUNT; a++) {
      String want = String(BLE_ANCHORS[a].id);
      want.toLowerCase();
      if ((name.length() && name == want) || mac == want) {
        if (rssi > bestRssi) { bestRssi = rssi; best = a; }
      }
    }
  }
  bleScan->clearResults();
  if (best >= 0 && rssiOut) *rssiOut = bestRssi;
  return best;
}
#endif  // USE_BLE_ANCHORS

// ---- LilyGO T-A7670 pin map (from LilyGO's board definition) ----------------
#define MODEM_TX_PIN     26   // ESP32 -> modem RX
#define MODEM_RX_PIN     27   // ESP32 <- modem TX
#define MODEM_PWRKEY_PIN 4
#define MODEM_POWERON_PIN 12  // must be HIGH to power the modem (esp. on battery)
#define MODEM_RESET_PIN  5
#define MODEM_RESET_LEVEL HIGH
#define MODEM_BAUD       115200
#define BOARD_BAT_ADC_PIN 35

HardwareSerial SerialAT(1);

TinyGsm modem(SerialAT);

uint32_t seq = 0;
uint32_t lastPost = 0;

// Cell-tower lookups can block for up to two minutes. Repeating that operation
// every loop made a powered card appear offline. Refresh the network estimate
// occasionally and reuse the last successful result between refreshes.
#define CELL_REFRESH_MS 300000UL        // refresh a good cell estimate every 5 min
#define CELL_FAILURE_RETRY_MS 30000UL   // retry a failed lookup after 30 seconds
#define CELL_CACHE_MAX_AGE_MS 900000UL  // never reuse it for more than 15 min
uint32_t lastCellTry = 0;
bool     lastCellTrySucceeded = false;
bool     haveCellCache = false;
double   cellLat = 0, cellLng = 0;
int      cellAccuracyM = 0;
uint32_t cellFixMs = 0;

// ---- GPS hold ---------------------------------------------------------------
// When the card goes indoors it loses satellite lock, but the last real GPS fix
// is still far more accurate than a ~km cell-tower estimate. So remember it and
// keep reporting it (clearly labelled, with its age) for up to GPS_HOLD_MS.
// This is what commercial trackers do, and it means walking in from outside
// leaves the map showing a metre-accurate position instead of jumping away.
#define GPS_HOLD_MS 900000UL          // 15 minutes
// Only remember a fix that is actually trustworthy. As the card loses sky view
// the receiver keeps reporting a "fix" while quality collapses (PDOP climbing
// into the tens), so without this gate the held position ends up being the WORST
// fix of the session rather than the last good one — which is what made the held
// location drift/distort over time.
#define GPS_HOLD_MAX_PDOP 8.0         // PDOP above this is too unreliable to hold
#define GPS_HOLD_MIN_SATS 4           // need at least 4 satellites for a 3-D fix
#define GPS_HOLD_SAVE_MS 300000UL      // persist at most once every 5 minutes

bool     haveGpsHold = false;
double   holdLat = 0, holdLng = 0, holdPdop = 0;
int      holdSats = 0;
uint32_t holdMs = 0;            // millis() when stored — valid within this boot only
long long holdEpoch = 0;        // UTC seconds of the fix — survives reboots
uint32_t lastHoldSaveMs = 0;

// The hold is written to NVS (flash) so it survives a power cycle. Without this,
// unplugging the card to swap to a power bank wipes the last known position and
// the card falls back to a ~km cell estimate until it re-locks satellites.
Preferences prefs;
Preferences queuePrefs;

// ---- store-and-forward queue ----------------------------------------------
// If LTE or the laptop tunnel disappears briefly, retain the newest 20 reports
// in ESP32 flash and forward them after the connection returns. Each report also
// carries its original capture time, so replay order remains truthful.
#define QUEUE_CAPACITY 20
#define QUEUE_FLUSH_PER_CYCLE 3
long long cachedClockEpoch = 0;
uint32_t cachedClockMs = 0;

// UTC calendar -> epoch seconds (Howard Hinnant's days-from-civil algorithm).
long long toEpoch(int y, int mo, int d, int h, int mi, int s) {
  y -= mo <= 2;
  long long era = (y >= 0 ? y : y - 399) / 400;
  unsigned  yoe = (unsigned)(y - era * 400);
  unsigned  doy = (153 * (mo + (mo > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  unsigned  doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  long long days = era * 146097LL + (long long)doe - 719468LL;
  return days * 86400LL + h * 3600LL + mi * 60LL + s;
}

// Current UTC epoch from the LTE network clock (AT+CCLK). Returns 0 if unknown.
long long networkEpoch() {
  int y = 0, mo = 0, d = 0, h = 0, mi = 0, s = 0;
  float tz = 0;
  if (!modem.getNetworkTime(&y, &mo, &d, &h, &mi, &s, &tz)) return 0;
  if (y < 2020) return 0;                       // clearly not set yet
  // The modem reports local time plus a timezone offset in quarter-hours.
  return toEpoch(y, mo, d, h, mi, s) - (long long)(tz * 900.0f);
}

long long bestEffortEpoch() {
  if (cachedClockEpoch > 0 && millis() - cachedClockMs < 300000UL) {
    return cachedClockEpoch + (long long)((millis() - cachedClockMs) / 1000UL);
  }
  long long value = networkEpoch();
  if (value > 0) {
    cachedClockEpoch = value;
    cachedClockMs = millis();
  }
  return value;
}

void saveHold() {
  prefs.begin("siid", false);
  prefs.putDouble("lat", holdLat);
  prefs.putDouble("lng", holdLng);
  prefs.putInt("sats", holdSats);
  prefs.putDouble("pdop", holdPdop);
  prefs.putLong64("epoch", holdEpoch);
  prefs.end();
}

void loadHold() {
  prefs.begin("siid", true);
  long long e = prefs.getLong64("epoch", 0);
  double savedLat = prefs.getDouble("lat", 0);
  double savedLng = prefs.getDouble("lng", 0);
  int savedSats = prefs.getInt("sats", 0);
  double savedPdop = prefs.getDouble("pdop", 0);
  bool valid = e > 0
               && savedLat >= -90.0 && savedLat <= 90.0
               && savedLng >= -180.0 && savedLng <= 180.0
               && (savedLat != 0 || savedLng != 0)
               && savedSats >= GPS_HOLD_MIN_SATS
               && savedPdop > 0 && savedPdop <= GPS_HOLD_MAX_PDOP;
  if (valid) {
    holdLat  = savedLat;
    holdLng  = savedLng;
    holdSats = savedSats;
    holdPdop = savedPdop;
    holdEpoch = e;
    haveGpsHold = true;
  }
  prefs.end();
  if (haveGpsHold) {
    Serial.printf("Restored last GPS fix from flash: %.6f,%.6f (sats=%d pdop=%.1f)\n",
                  holdLat, holdLng, holdSats, holdPdop);
  }
}

uint16_t readBatteryMillivolts() {
  // The tested prototype has no fitted battery and is powered through USB-C.
  // Returning zero tells the backend that battery telemetry is unavailable.
  // Reading the unused ADC pin would allow electrical noise to create a false
  // battery voltage and could cause a valid location report to be rejected.
  return 0;
}

// The A76xx CGNSSINFO field can be decimal degrees OR NMEA ddmm.mmmm depending
// on firmware revision. Anything out of legal range must be ddmm.mmmm, so
// convert it. This keeps the map correct on either revision.
double normaliseCoord(double v, double limit) {
  if (fabs(v) <= limit) return v;              // already decimal degrees
  double sign = (v < 0) ? -1.0 : 1.0;
  v = fabs(v);
  double deg = floor(v / 100.0);
  double min = v - (deg * 100.0);
  return sign * (deg + min / 60.0);
}

void powerOnModem() {
  pinMode(MODEM_POWERON_PIN, OUTPUT);
  digitalWrite(MODEM_POWERON_PIN, HIGH);

  pinMode(MODEM_RESET_PIN, OUTPUT);
  digitalWrite(MODEM_RESET_PIN, !MODEM_RESET_LEVEL); delay(100);
  digitalWrite(MODEM_RESET_PIN,  MODEM_RESET_LEVEL);  delay(2600);
  digitalWrite(MODEM_RESET_PIN, !MODEM_RESET_LEVEL);

  pinMode(MODEM_PWRKEY_PIN, OUTPUT);
  digitalWrite(MODEM_PWRKEY_PIN, LOW);  delay(100);
  digitalWrite(MODEM_PWRKEY_PIN, HIGH); delay(1000);
  digitalWrite(MODEM_PWRKEY_PIN, LOW);
}

void connectNetwork() {
  int sim = modem.getSimStatus();
  Serial.printf("SIM status: %d  (1=READY, 0=absent/error, 2=PIN locked, 3=PUK)\n", sim);
  Serial.printf("Signal (CSQ): %d  (0-31 = real signal, 99 = none -> check antenna)\n",
                modem.getSignalQuality());

  Serial.println("Waiting for LTE network...");
  if (!modem.waitForNetwork(60000L)) {
    Serial.println("  no network — check SIM, antenna, 4G coverage");
    delay(3000);
    return;
  }
  Serial.print("Network registered. Operator: ");
  Serial.println(modem.getOperator());
  Serial.println("Connecting data...");
  if (!modem.gprsConnect(APN, GPRS_USER, GPRS_PASS)) {
    Serial.println("  data connect failed — check the APN for your SIM");
    delay(3000);
    return;
  }
  Serial.println("LTE data connected.");
}

int postJson(const char *resource, const char *body) {
  // Use the A7670 modem's built-in HTTP engine. This generates a standards-
  // compliant request and avoids the module's obsolete TLS handshake path.
  String url = String("http://") + SERVER_HOST + resource;
  if (!modem.https_begin()) {
    Serial.println("  HTTPS initialization failed");
    return -1;
  }

  modem.https_set_timeout(20, 10, 20);
  bool configured = modem.https_set_url(url, TINYGSM_SSL_AUTO, true)
                 && modem.https_set_ssl_index(0)
                 && modem.https_set_content_type("application/json")
                 && modem.https_add_header("X-Device-Key", DEVICE_API_KEY);
  if (!configured) {
    Serial.println("  HTTPS configuration failed");
    modem.https_end();
    return -1;
  }

  int status = modem.https_post(body, strlen(body));
  modem.https_end();
  return status;
}

bool postSucceeded(int status) {
  return status >= 200 && status < 300;
}

bool temporaryPostFailure(int status) {
  return status <= 0 || status == 408 || status == 429 || status >= 500;
}

String queueKey(int index) {
  return String("p") + String(index);
}

int queuedPacketCount() {
  queuePrefs.begin("siidqueue", true);
  int count = queuePrefs.getUChar("count", 0);
  queuePrefs.end();
  return count;
}

void enqueuePacket(const char *body) {
  queuePrefs.begin("siidqueue", false);
  int head = queuePrefs.getUChar("head", 0);
  int count = queuePrefs.getUChar("count", 0);
  if (count >= QUEUE_CAPACITY) {
    queuePrefs.remove(queueKey(head).c_str());
    head = (head + 1) % QUEUE_CAPACITY;
    count--;
  }
  int tail = (head + count) % QUEUE_CAPACITY;
  queuePrefs.putString(queueKey(tail).c_str(), body);
  queuePrefs.putUChar("head", head);
  queuePrefs.putUChar("count", count + 1);
  queuePrefs.end();
  Serial.printf("  saved for later (%d packet(s) queued)\n", count + 1);
}

bool peekQueuedPacket(String &packet) {
  queuePrefs.begin("siidqueue", true);
  int head = queuePrefs.getUChar("head", 0);
  int count = queuePrefs.getUChar("count", 0);
  packet = count > 0 ? queuePrefs.getString(queueKey(head).c_str(), "") : "";
  queuePrefs.end();
  return count > 0 && packet.length() > 0;
}

void removeQueuedPacket() {
  queuePrefs.begin("siidqueue", false);
  int head = queuePrefs.getUChar("head", 0);
  int count = queuePrefs.getUChar("count", 0);
  if (count > 0) {
    queuePrefs.remove(queueKey(head).c_str());
    head = (head + 1) % QUEUE_CAPACITY;
    count--;
    queuePrefs.putUChar("head", head);
    queuePrefs.putUChar("count", count);
  }
  queuePrefs.end();
}

String markPacketBuffered(String packet) {
  int closingBrace = packet.lastIndexOf('}');
  if (closingBrace >= 0) packet = packet.substring(0, closingBrace) + ",\"buffered\":true}";
  return packet;
}

void flushQueuedPackets() {
  if (!modem.isGprsConnected()) return;
  for (int sent = 0; sent < QUEUE_FLUSH_PER_CYCLE; sent++) {
    String packet;
    if (!peekQueuedPacket(packet)) return;
    String bufferedPacket = markPacketBuffered(packet);
    Serial.printf("Forwarding saved packet (%d waiting)...\n", queuedPacketCount());
    int status = postJson(RESOURCE, bufferedPacket.c_str());
    Serial.printf("  saved packet response: %d\n", status);
    if (!postSucceeded(status)) return;
    removeQueuedPacket();
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  powerOnModem();
  SerialAT.begin(MODEM_BAUD, SERIAL_8N1, MODEM_RX_PIN, MODEM_TX_PIN);

  loadHold();   // restore last known GPS position from flash (survives power cycles)

  Serial.println("Starting modem (allow ~10s to boot)...");
  delay(10000);                       // A7670E needs this long before it answers
  if (!modem.init()) {
    Serial.println("modem.init() failed — retrying restart()");
    modem.restart();
  }
  Serial.print("Modem: ");
  Serial.println(modem.getModemInfo());

#if USE_BLE_ANCHORS
  // Start BLE in scan-only mode for indoor anchor detection.
  BLEDevice::init("SIID-CARD");
  bleScan = BLEDevice::getScan();
  bleScan->setActiveScan(true);
  bleScan->setInterval(100);
  bleScan->setWindow(99);
  Serial.printf("BLE scanner ready (%d anchor(s) configured).\n", BLE_ANCHOR_COUNT);
#endif

  // Power up the modem's built-in GNSS receiver.
  Serial.println("Enabling built-in GNSS...");
  if (modem.enableGPS()) {
    Serial.println("GNSS powered on (READY).");
  } else {
    Serial.println("GNSS enable failed — will keep retrying in the loop.");
  }

  connectNetwork();
  Serial.printf("Setup done. Acquiring GNSS fix + sending positions... (%d saved packet(s))\n",
                queuedPacketCount());
}

void loop() {
  if (!modem.isGprsConnected()) connectNetwork();

  if (millis() - lastPost < POST_INTERVAL_MS) return;
  lastPost = millis();

  // Forward a few older reports first, then send the current position below.
  // Limiting each cycle prevents a large queue from delaying the live update.
  flushQueuedPackets();

  double lat = TEST_LAT, lng = TEST_LNG, hdopVal = 0.0;
  int sats = 0;
  const char *src = "test";     // gps | gps_hold | ble | cell | test
  int accuracyM = 0;            // estimated accuracy in metres
  int ageS = 0;                 // age of the fix in seconds (0 = live)
  long long capturedEpoch = 0;  // when this position was measured

  if (!TEST_MODE) {
    bool located = false;
    uint8_t fixMode = 0;
    float flat = 0, flon = 0, fspeed = 0, falt = 0, faccuracy = 0;
    int vsat = 0, usat = 0;
    int gy = 0, gmo = 0, gd = 0, gh = 0, gmi = 0, gs = 0;   // UTC of the fix

    if (modem.getGPS(&fixMode, &flat, &flon, &fspeed, &falt, &vsat, &usat, &faccuracy,
                     &gy, &gmo, &gd, &gh, &gmi, &gs)) {
      // --- best case: real satellite fix (a few metres, needs sky) ---
      lat     = normaliseCoord(flat, 90.0);
      lng     = normaliseCoord(flon, 180.0);
      sats    = vsat;                 // usat is not populated by the A76xx driver
      hdopVal = faccuracy;            // PDOP from +CGNSSINFO
      // Only remember GOOD fixes for the indoor hold. A degraded fix (high PDOP,
      // few satellites) is also not sent as live GPS: it is allowed to fall
      // through to the last trusted GPS point or the cell-tower estimate.
      bool goodEnough = (hdopVal > 0 && hdopVal <= GPS_HOLD_MAX_PDOP)
                        && (sats >= GPS_HOLD_MIN_SATS);
      if (goodEnough) {
        src = "gps";
        located = true;
        haveGpsHold = true;
        holdLat = lat; holdLng = lng; holdSats = sats; holdPdop = hdopVal;
        holdMs = millis();
        // GPS gives us true UTC, so the fix's age stays correct across reboots.
        holdEpoch = (gy > 2020) ? toEpoch(gy, gmo, gd, gh, gmi, gs) : bestEffortEpoch();
        capturedEpoch = holdEpoch;
        if (holdEpoch > 0) {
          cachedClockEpoch = holdEpoch;
          cachedClockMs = millis();
        }
        // Keep the freshest fix in RAM every cycle, but spare flash by writing
        // the reboot-surviving copy no more than once every five minutes.
        if (lastHoldSaveMs == 0 || millis() - lastHoldSaveMs >= GPS_HOLD_SAVE_MS) {
          saveHold();
          lastHoldSaveMs = millis();
        }
      }
      Serial.printf("GNSS fix: mode=%u sats=%d pdop=%.1f %s\n",
                    fixMode, vsat, faccuracy,
                    goodEnough ? "(accepted + held)" : "(rejected: poor quality)");
    }

    if (!located) {
      // ---- no satellite fix (almost certainly indoors) -> degrade gracefully ----
#if USE_BLE_ANCHORS
      // TIER 2: a known BLE anchor nearby gives room-level accuracy indoors.
      if (millis() - lastBleTry >= BLE_RETRY_MS) {
        lastBleTry = millis();
        int rssi = 0;
        int a = scanForBleAnchor(&rssi);
        if (a >= 0) {
          lat       = BLE_ANCHORS[a].lat;
          lng       = BLE_ANCHORS[a].lng;
          accuracyM = estimateMetresFromRssi(rssi);
          src       = "ble";
          located   = true;
          Serial.printf("BLE anchor '%s' (%s) rssi=%d -> ~%dm\n",
                        BLE_ANCHORS[a].label, BLE_ANCHORS[a].id, rssi, accuracyM);
        }
      }
#endif  // USE_BLE_ANCHORS

      // TIER 3: the last real GPS fix, if it is still recent. Metre-accurate and
      // therefore much better than a kilometre-scale cell estimate — this is what
      // keeps the map correct after walking indoors from outside.
      if (!located && haveGpsHold) {
        // Age the fix by real clock time where possible (works across reboots),
        // falling back to millis() for a fix taken during this same boot.
        long long ageCalc = -1;
        long long nowE = (holdEpoch > 0) ? networkEpoch() : 0;
        if (holdEpoch > 0 && nowE > 0) {
          ageCalc = nowE - holdEpoch;
        } else if (holdMs > 0) {
          ageCalc = (millis() - holdMs) / 1000;
        }

        if (ageCalc >= 0 && ageCalc < (long long)(GPS_HOLD_MS / 1000)) {
          lat       = holdLat;
          lng       = holdLng;
          sats      = holdSats;
          hdopVal   = holdPdop;
          ageS      = (int)ageCalc;
          accuracyM = 0;
          src       = "gps_hold";
          located   = true;
          Serial.printf("Using last GPS fix (%ds old): %.6f,%.6f\n", ageS, lat, lng);
        } else if (ageCalc >= 0) {
          Serial.printf("Last GPS fix is stale (%llds) - falling through to cell\n", ageCalc);
        }
      }

      // TIER 4: cell-tower location (AT+CLBS). Works anywhere with signal, but
      // coarse (~100 m - 1 km). Last resort so the card is never "lost".
      if (!located) {
        uint32_t cellRetryDelay = lastCellTrySucceeded
                                  ? CELL_REFRESH_MS
                                  : CELL_FAILURE_RETRY_MS;
        bool cellRefreshDue = (lastCellTry == 0)
                              || (millis() - lastCellTry >= cellRetryDelay);
        if (cellRefreshDue) {
          Serial.print("No trusted GNSS/BLE — refreshing cell-tower location... ");
          float clat = 0, clon = 0, cacc = 0;
          bool cellOk = modem.getGsmLocation(&clat, &clon, &cacc);
          // Record the retry time AFTER the blocking command. Otherwise a
          // 120-second timeout makes the next loop retry immediately forever.
          lastCellTry = millis();
          lastCellTrySucceeded = cellOk;
          if (cellOk) {
            cellLat       = normaliseCoord(clat, 90.0);
            cellLng       = normaliseCoord(clon, 180.0);
            cellAccuracyM = (int)cacc;
            cellFixMs     = millis();
            haveCellCache = true;
            Serial.printf("OK  %.6f,%.6f  ~%dm\n",
                          cellLat, cellLng, cellAccuracyM);
          } else {
            Serial.println("failed");
          }
        }

        if (haveCellCache && millis() - cellFixMs <= CELL_CACHE_MAX_AGE_MS) {
          lat       = cellLat;
          lng       = cellLng;
          accuracyM = cellAccuracyM;
          ageS      = (int)((millis() - cellFixMs) / 1000UL);
          src       = "cell";
          located   = true;
          Serial.printf("Using cell estimate (%ds old): %.6f,%.6f  ~%dm\n",
                        ageS, lat, lng, accuracyM);
        } else if (!cellRefreshDue) {
          Serial.println("Waiting before the next cell-tower lookup.");
        }
      }

      if (!located) {
        // No trustworthy coordinate is available, but the card, SIM and LTE
        // connection are still alive. Report that fact separately so the UI
        // never confuses "waiting for a fix" with "device switched off".
        int csq = modem.getSignalQuality();
        char heartbeat[150];
        snprintf(heartbeat, sizeof(heartbeat),
          "{\"card_id\":\"%s\",\"batt_mv\":%u,\"seq\":%lu,\"rssi\":%d}",
          CARD_ID, readBatteryMillivolts(), (unsigned long)seq++, csq);
        Serial.print("HEARTBEAT (online, waiting for position) ");
        Serial.println(heartbeat);
        int status = postJson(HEARTBEAT_RESOURCE, heartbeat);
        Serial.print("  server responded: ");
        Serial.println(status);
        return;
      }
    }
  }

  int csq = modem.getSignalQuality();

  if (capturedEpoch <= 0) capturedEpoch = bestEffortEpoch();

  char body[360];
  if (capturedEpoch > 0) {
    snprintf(body, sizeof(body),
      "{\"card_id\":\"%s\",\"lat\":%.6f,\"lng\":%.6f,\"sats\":%d,"
      "\"hdop\":%.1f,\"batt_mv\":%u,\"seq\":%lu,\"rssi\":%d,\"snr\":%.1f,"
      "\"src\":\"%s\",\"acc\":%d,\"age_s\":%d,\"captured_epoch\":%lld}",
      CARD_ID, lat, lng, sats, hdopVal,
      readBatteryMillivolts(), (unsigned long)seq++, csq, 0.0,
      src, accuracyM, ageS, capturedEpoch);
  } else {
    snprintf(body, sizeof(body),
      "{\"card_id\":\"%s\",\"lat\":%.6f,\"lng\":%.6f,\"sats\":%d,"
      "\"hdop\":%.1f,\"batt_mv\":%u,\"seq\":%lu,\"rssi\":%d,\"snr\":%.1f,"
      "\"src\":\"%s\",\"acc\":%d,\"age_s\":%d}",
      CARD_ID, lat, lng, sats, hdopVal,
      readBatteryMillivolts(), (unsigned long)seq++, csq, 0.0,
      src, accuracyM, ageS);
  }

  Serial.print(TEST_MODE ? "POST (TEST) " : "POST ");
  Serial.println(body);

  int status = postJson(RESOURCE, body);
  Serial.print("  server responded: ");
  Serial.println(status);
  if (temporaryPostFailure(status) && capturedEpoch > 0) enqueuePacket(body);
}
