# How to explain this project — in plain words

This is the one to read before your defence. No jargon, nothing you can't back up.
If a sentence here feels like it isn't yours, cross it out and say it your way.

**Golden rule: never say a word you can't explain.** If you don't know a term,
don't use it. "It finds its location and sends it to my server over the mobile
network" is a *better* answer than a sentence full of abbreviations, because you
can defend every word of it.

---

## 1. The project in one breath

> "I built a student ID card that can be tracked. It finds its own location using
> GPS, sends that location over the mobile network to my server, and the server
> shows the student's position live on a map."

That's it. If you say nothing else, say that.

---

## 2. The three parts

**The card** — a small circuit board with a battery, worn on a lanyard. It has:
- a **GPS receiver** (the same thing your phone uses to find itself)
- a **SIM card and mobile modem** (like a phone, so it can send data)

**The server** — a program running on my laptop. It receives the locations, saves
them, and immediately pushes them to the web page.

**The dashboard** — the web page staff sign into. It shows the student list, a
search box, and a live map.

---

## 3. How the location actually gets from the card to the screen

Say this as a five-step story:

1. The card asks the satellites where it is.
2. It packs that location into a small message.
3. It sends the message over the mobile network — the same network a phone uses.
4. My server receives it, saves it, and pushes it to the web page instantly.
5. The marker on the map moves.

**Every 5 seconds, all over again.**

---

## 4. Why this works over 200 m — the key point

This is the question you should *want* them to ask.

> "The card and my laptop never talk to each other directly. The card talks to a
> mobile network tower, exactly like a phone. So the distance between the card and
> my laptop doesn't matter at all — 5 metres or 5 kilometres works the same. That's
> why 200 metres was never a problem for this design."

If they ask why you didn't use Bluetooth or radio:

> "Those need the two devices to be in range of each other, so the distance
> becomes the hard part. Using the mobile network removes that problem completely."

---

## 5. The clever bit — what happens indoors

This is your strongest talking point. Satellites are the thing examiners
understand least, and it's where your project does something thoughtful.

> "Satellite signals can't get through a roof, so GPS stops working indoors. My
> system handles that in three steps:
>
> 1. **Outdoors** it uses GPS — accurate to a few metres.
> 2. **When it goes indoors** and loses the satellites, it keeps showing the last
>    real GPS position, and labels it 'Last GPS fix' with how old it is.
> 3. **If there's no recent GPS at all**, it asks the mobile network roughly where
>    it is. That's only accurate to a few hundred metres, so the screen says
>    'Cell tower' and draws a circle showing the uncertainty."
>
> "The system never pretends to be more accurate than it really is."

**That last sentence is worth marks.** Being honest about accuracy is engineering
maturity, not a weakness.

---

## 6. The words you WILL see on your own screen

Only these. You need to be able to explain them, so here they are in plain terms.

| On screen | What you say if asked |
|---|---|
| **Satellites** | "How many satellites the card can currently see. More is generally better." |
| **Fix quality** | "How well spread out the satellites are in the sky. If they're spread around you, the position is sharp. If they're bunched together, it's vague. **Lower numbers are better** — mine got down to 1.9, which is very good." |
| **Signal strength** | "How strong the mobile network signal is, out of 31." |
| **Accuracy** | "How far off the position could be. A few metres for GPS, a few hundred metres for the cell-tower method." |
| **Located by** | "Which of the three methods produced this position — GPS, last GPS fix, or cell tower." |
| **Packet** | "A counter — how many messages the card has sent since it started." |

---

## 7. What each technology is, in one line

If they ask "what did you use?", you don't need to list everything. Say the four
that matter, and only expand if pushed.

| Thing | One-line answer |
|---|---|
| **The board** | "A LilyGO development board that has the microcontroller, the 4G modem, the GPS and battery charging all built onto one board." |
| **The card's program** | "Written in C++ using the Arduino environment." |
| **The server** | "Written in Python, using Flask — a small web framework." |
| **The database** | "SQLite — a simple file-based database that stores every location received." |
| **The web page** | "Plain HTML, CSS and JavaScript. The map uses Leaflet, a free mapping library." |

**If asked why you chose them, the honest answer is the best one:**

> "I chose the option with the fewest parts that still met the requirement, because
> I had limited time and needed it to actually work."

That's a real engineering reason. Use it.

---

## 8. Questions they'll probably ask, and short answers

**"Why is it not as thin as a real ID card?"**
> "Because it has a battery, a GPS receiver and a mobile modem inside. A real card
> is 0.76 mm. My current case is about 110 by 75 by 8.4 mm, so it is worn on a
> lanyard or carried as a pocket badge. Making it ISO-card sized
> would need a custom-made circuit board, which is beyond this project."

**"What if the student goes inside a building?"**
> "It keeps showing the last GPS position and marks it as older, and if that gets
> too old it falls back to the mobile-network position, which is less accurate but
> still tells you roughly where they are."

**"What if the battery dies or they remove the card?"**
> "Then it stops reporting, and the dashboard shows the device as offline. That's a
> real limitation of any tracker, and I mention it in my recommendations."

**"Is this secure / what about privacy?"**
> "Access to the dashboard requires a login. For a real deployment you'd also need
> student consent, encryption of the location data, and rules about how long it's
> kept. I've listed those in my recommendations chapter."

**"Why only one student is trackable?"**
> "Because I built one card. The system already supports more — the database and
> the student list handle multiple devices. Adding a second card needs no software
> change."

**"Could someone else track the student?"**
> "Not through the dashboard — it requires a login. But the location is sent over
> plain, unencrypted internet in this version, so a production system should use
> an encrypted connection. That's in my recommendations."

---

## 9. If you get asked something you don't know

Do not guess. Say:

> "I don't know that off the top of my head, but what I can tell you is…"

and go back to something you *do* know. Examiners respect that far more than a
wrong confident answer — and a wrong confident answer invites more questions.

---

## 10. Your demo, in order

1. Double-click **START_DEMO.cmd**, sign in, and open **System Health**. Green
   checks mean the laptop side is ready; the card and tunnel checks mean live
   tracking is ready.
2. Show the student list, search **U19CO1011**.
3. Click **Track student** — explain that the server checks whether the device has
   reported recently before opening the map.
4. On the map, point at the marker, position source and accuracy. The marker moves
   gradually instead of jumping between reports.
5. Select a recorded day and walk. The orange line is cleaned GPS data, arrows
   show direction, and purple circles show places where the card stayed for at
   least one minute.
6. Show the safety-zone circle. A real satellite fix crossing its edge creates an
   alert; a rough cell-tower estimate is not trusted to create one.
7. Play the route, then download its PDF report.
8. If the internet fails, use **Save offline replay**. The browser keeps a local
   presentation copy and displays a simple bundled campus map.

**Always have the recorded run as a backup.** Live demos fail; recordings don't.

### Four new ideas in very plain language

- **Smoothing:** several believable GPS points are averaged carefully so one bad
  jump does not make the line zigzag. The original points are still saved.
- **Store and forward:** if LTE disappears, the card keeps up to 20 reports in
  its own memory and sends them later with their original times.
- **Safety zone:** a circle around an allowed area. The system remembers whether
  the card was inside and reports when that state changes.
- **Session:** one continuous walk. If reports stop for more than three minutes,
  the next report begins another walk instead of drawing a false line across the gap.
