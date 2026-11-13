# Trackable Student ID Card — Report Outline

Computer Engineering, Ahmadu Bello University, Zaria
Presentation target: 2026-08-31

**Write this in your own words.** If a sentence here doesn't sound like you, change
it. Anything you can't explain out loud should not be in your report — an examiner
will ask about exactly the sentence you don't understand.

There is a short list of words you *do* need at the end of this file. Learn those
few properly and you can defend the whole report.

---

## Chapter 1: Introduction

- **Background** — why tracking a student ID matters: campus security, knowing
  where a student is in an emergency, attendance.
- **The problem** — a normal student ID card is just printed plastic. It cannot
  tell anyone where the student is.
- **What I set out to build** — a student ID card that reports its own location
  live to a map, and that works from at least 200 metres away.
- **Limits I accepted** — a real ID card is about 85.6 × 54 × 0.76 mm. The
  development board makes my current case roughly 110.4 × 75.1 × 8.4 mm before
  printer tolerances. It is a lanyard/pocket badge, not a wallet card. **Say this
  plainly; do not hide it.**

## Chapter 2: What already exists (Literature Review)

For each one: how it works, and the single reason it did not suit this project.

- **Tap cards (RFID)** — the type used for door access. Works only a few
  centimetres from a reader. *Fails the 200 m requirement immediately.*
- **Bluetooth tags** — like an AirTag or a Tile. Range is tens of metres and drops
  further through walls. *Not reliable at 200 m.*
- **Long-range radio (LoRa)** — reaches kilometres, but the card must talk to a
  matching receiver box that you also have to build and power. *Two devices
  instead of one.*
- **GPS + mobile network trackers** — the approach used in vehicle trackers, and
  the one I chose. *The mobile network carries the data, so distance stops
  mattering.*

## Chapter 3: How the system is designed

- **The overall picture** (draw this as a diagram):
  satellites → the card → mobile network → my server → the map on screen
- **Why I changed my design as I went** — this is a real strength, so write it
  honestly:
  1. Tap cards and Bluetooth were ruled out on range.
  2. Long-range radio worked, but needed a second device to build.
  3. Separate GPS and modem parts worked, but meant a lot of wiring and a fussy
     power supply.
  4. **Final choice:** one ready-made board with everything on it — fewest parts,
     least wiring, most likely to actually work in the time I had.
- **The hardware** — one LilyGO board carrying the small computer, the mobile
  modem, the SIM slot, the location receiver and the battery charger; plus two
  aerials and a rechargeable battery.
- **The software** — the program on the card, the server program, and the web page.

## Chapter 4: How I built it

- **The program on the card** — how it starts the mobile modem, switches on the
  location receiver, connects to the mobile network, and then sends its position
  every 5 seconds. Mention the built-in test mode that sends a fake position, so
  the rest of the system could be tested indoors before the location part worked.
- **Finding out how the board really works** — *include this, it shows real
  engineering.* The manufacturer's guide suggested the location receiver was a
  separate chip wired to certain pins. I wrote a small test program that proved
  those pins produced nothing, and that the location receiver was actually inside
  the mobile modem itself. I then rewrote the program to match the real hardware.
- **The server** — receives each position, saves it, and immediately pushes it to
  the web page so the map moves without refreshing.
- **The web page** — staff login, student list with search, live map with the
  moving marker, a replay of the recorded route, and a page of recent activity.
- **Connecting the card to my laptop** — the card is on the public internet
  through the mobile network, while my laptop is not. I used a free tunnelling
  service to give my laptop a public address the card can reach.
- **The case** — a 3D-printed housing designed to fit the board, flat battery and
  antennas, with the board end open so its USB-C charging port remains reachable.

## Chapter 5: Testing and results

**Put real measured numbers here — this is your evidence chapter.**

- **First switch-on** — the log showing the modem identified itself, the SIM was
  accepted, the network connected (MTN), and data started flowing.
- **Getting a location outdoors** — how long the first fix took, how many
  satellites were visible, and the fix-quality number (mine reached 1.9, which is
  very good).
- **Behaviour indoors** — with no satellite signal the card reports its last known
  location and marks how old it is; if that gets too old it falls back to the
  rough mobile-network position.
- **Distance test** — walk the card 100 m, 200 m, 500 m away and record whether
  updates kept arriving. **The expected result is that distance made no
  difference**, because the data travels over the mobile network. Say why this
  would not have been true with radio or Bluetooth.
- **How quickly the map updates** after the card sends a position.
- **Battery life** at the 5-second reporting rate.
- **Screenshots** of the dashboard and the map during a real outdoor test.

## Chapter 6: Conclusion and recommendations

- **What I achieved** — be specific and use your measured numbers.
- **What I would improve with more time and money:**
  - a custom-made circuit board and a thinner battery, to get closer to real card
    thickness
  - more than one card (the data model and tracking pages support separate card IDs;
    each additional card must be registered and provisioned with its own credential)
  - stronger login security and an encrypted connection
  - **privacy** — student consent, limits on how long location history is kept,
    and controlling who can see it. Tracking people raises real ethical questions
    and a good report says so.
  - making the battery last longer by reporting less often when the student is
    not moving

## Appendices

- The program that runs on the card
- The test program used to work out how the board's location receiver is wired
- The server program and the web page code
- The 3D-printed case design
- What each part cost
- The logs recorded during testing

---

## The only words you must be able to explain

Learn these six. Everything else in the report can be said in plain English.

| Word | What you say |
|---|---|
| **GPS** | "A system of satellites that lets a device work out where it is on Earth." |
| **Satellite fix** | "When the device has heard from enough satellites to know its position." |
| **Fix quality** | "How spread out the satellites are. Spread out means a sharp position; bunched together means a vague one. Lower numbers are better." |
| **Mobile network / 4G** | "The same phone network a SIM card uses. My card uses it to send its position to my server." |
| **Server** | "A program running on my laptop that receives the positions, stores them, and sends them to the web page." |
| **Database** | "Where every position received is saved, so history isn't lost when the program restarts." |

If an examiner uses a word you don't know, it is completely fine to say:
**"Could you explain what you mean by that?"** That is a normal engineering
question, not a weakness.
