// ============================================================================
// SIID-01 GPS PROBE — diagnostic only, NOT the project firmware.
//
// Purpose: find out how GPS is actually provided on this specific board.
// Three possibilities are tested:
//   TEST 1  external GPS chip (e.g. L76K) on UART pins RX=22 / TX=21
//   TEST 2  same, with the pins swapped (in case of a silkscreen/pin inversion)
//   TEST 3  the A7670 modem's OWN built-in GNSS, via raw AT commands
//
// Flash this, read the serial monitor at 115200, and whichever test produces
// data tells us which GPS source the real firmware must use.
// ============================================================================

#define MODEM_TX_PIN      26   // ESP32 -> modem RX
#define MODEM_RX_PIN      27   // ESP32 <- modem TX
#define MODEM_PWRKEY_PIN  4
#define MODEM_POWERON_PIN 12
#define MODEM_RESET_PIN   5

HardwareSerial SerialAT(1);
HardwareSerial SerialGPS(2);

void powerOnModem() {
  pinMode(MODEM_POWERON_PIN, OUTPUT);
  digitalWrite(MODEM_POWERON_PIN, HIGH);

  pinMode(MODEM_RESET_PIN, OUTPUT);
  digitalWrite(MODEM_RESET_PIN, LOW);

  pinMode(MODEM_PWRKEY_PIN, OUTPUT);
  digitalWrite(MODEM_PWRKEY_PIN, LOW);  delay(100);
  digitalWrite(MODEM_PWRKEY_PIN, HIGH); delay(1000);
  digitalWrite(MODEM_PWRKEY_PIN, LOW);
}

// Send a raw AT command and echo whatever the modem replies.
void at(const char *cmd, uint32_t waitMs) {
  Serial.printf("\n>> %s\n", cmd);
  while (SerialAT.available()) SerialAT.read();   // flush stale bytes
  SerialAT.print(cmd);
  SerialAT.print("\r\n");
  uint32_t t = millis();
  while (millis() - t < waitMs) {
    while (SerialAT.available()) Serial.write(SerialAT.read());
  }
  Serial.println();
}

// Count bytes arriving on the GPS UART with a given pin assignment.
int probeGpsUart(int rxPin, int txPin, uint32_t ms) {
  SerialGPS.begin(9600, SERIAL_8N1, rxPin, txPin);
  delay(200);
  int n = 0;
  String sample = "";
  uint32_t t = millis();
  while (millis() - t < ms) {
    while (SerialGPS.available()) {
      char c = SerialGPS.read();
      n++;
      if (sample.length() < 120) sample += c;
    }
  }
  SerialGPS.end();
  Serial.printf("   bytes=%d\n", n);
  if (n > 0) { Serial.print("   sample: "); Serial.println(sample); }
  return n;
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n\n===== SIID-01 GPS PROBE =====");

  powerOnModem();
  SerialAT.begin(115200, SERIAL_8N1, MODEM_RX_PIN, MODEM_TX_PIN);
  Serial.println("waiting for modem to boot (10s)...");
  delay(10000);

  at("AT", 1500);
  at("ATI", 2000);

  Serial.println("\n--- TEST 1: external GPS UART, RX=22 TX=21 ---");
  int t1 = probeGpsUart(22, 21, 4000);

  Serial.println("\n--- TEST 2: external GPS UART, pins swapped RX=21 TX=22 ---");
  int t2 = probeGpsUart(21, 22, 4000);

  Serial.println("\n--- TEST 3: modem built-in GNSS (AT commands) ---");
  at("AT+CGNSSPWR?", 2000);      // is the GNSS power switch supported?
  at("AT+CGNSSPWR=1", 12000);    // power the GNSS engine on
  delay(3000);
  at("AT+CGNSSINFO", 4000);      // A76xx-style position query
  at("AT+CGPSINFO", 4000);       // alternative/older query
  at("AT+CGNSSMODE?", 2000);     // which constellations
  at("AT+CGNSSTST=1", 3000);     // start streaming NMEA to the AT port

  Serial.println("\n--- TEST 3b: NMEA streaming out of the AT port (8s) ---");
  uint32_t t = millis();
  int n = 0;
  while (millis() - t < 8000) {
    while (SerialAT.available()) { Serial.write(SerialAT.read()); n++; }
  }
  Serial.printf("\n   AT-port NMEA bytes=%d\n", n);

  Serial.println("\n===== SUMMARY =====");
  Serial.printf("TEST1 external GPS (22/21) bytes : %d\n", t1);
  Serial.printf("TEST2 external GPS (21/22) bytes : %d\n", t2);
  Serial.printf("TEST3b modem GNSS NMEA bytes     : %d\n", n);
  Serial.println("Whichever is > 0 is the GPS source this board uses.");
}

void loop() {
  // Keep dumping anything the modem sends, in case GNSS starts streaming late.
  while (SerialAT.available()) Serial.write(SerialAT.read());
}
