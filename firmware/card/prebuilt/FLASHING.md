# Prebuilt firmware (LilyGO T-A7670, board "ESP32 Wrover Module")

Built from `firmware/card/card.ino` on 2026-09-29 (Arduino build
`arduino_native_https_build`, compiled right after the last source edit).
The baked-in settings are whatever `card.ino` holds: APN `internet.ng.airtel.com`,
server `frill-relay-nacho.ngrok-free.dev:80`, device key `siid-card-demo-2026`.
If you need a different SIM APN or ngrok address, edit `card.ino` and rebuild
in the Arduino IDE instead of using these files.

## Option A: one file (easiest)

```
esptool.py --chip esp32 --port COM5 --baud 921600 write_flash 0x0 card.ino.merged.bin
```

## Option B: separate parts

```
esptool.py --chip esp32 --port COM5 --baud 921600 write_flash \
  0x1000  card.ino.bootloader.bin \
  0x8000  card.ino.partitions.bin \
  0xe000  boot_app0.bin \
  0x10000 card.ino.bin
```

Replace `COM5` with your port (`/dev/ttyUSB0` on Linux, `/dev/cu.*` on macOS).
Install esptool with `pip install esptool`. A browser flasher such as
https://espressif.github.io/esptool-js/ also works: load `card.ino.merged.bin`
at address `0x0`.
