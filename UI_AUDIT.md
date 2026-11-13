# UI Audit — ABU Trackable Student ID System

Date: 30 August 2026

## Verdict

The interface is presentation-ready and does not need a redesign. It has a consistent ABU identity, clear navigation, useful information and a convincing live-tracking screen. Only three small wording/label fixes are worth making before the presentation.

## Reviewed flow

1. **Staff login — Excellent.** Strong ABU identity, clear purpose and a simple sign-in form.
2. **Dashboard — Very good.** Important numbers and the tracked student are easy to find. The large empty area below the left column is harmless on a projector.
3. **Student roster — Excellent.** Search, device status and the tracking action are immediately clear.
4. **Live tracking — Excellent.** The satellite map is the main focus, while playback, distance, stops, downloads and offline replay make the system feel complete.
5. **Activity — Very good.** The summary cards and charts explain the collected data clearly.
6. **System health — Very good.** This is especially useful before presenting because it separates the server, database, public link, card and offline files.

## Fix before presenting

1. **Clarify the saved GPS age.** The dashboard and live map can show “Last GPS fix · 2m ago” beside “No signal · 1813m ago”. The two numbers describe different things, but they look contradictory. Use wording such as “Saved GPS fix · was 2 min old when reported”.
2. **Rename the Activity column.** The column headed “Source” currently displays accuracy values such as “± few m”. Rename it to “Accuracy”; the coloured badge already communicates the source.
3. **Make the health headline precise.** When the server, database and public link are ready but the card is silent, use “System ready · waiting for card” instead of “live link needs attention”.

## Optional after the presentation

- Replace the raw `gps_hold` text on System Health with “Saved GPS position”.
- Hide the full database path from the main health screen or move it under a technical-details control.
- Give route arrows and the playback icon descriptive accessibility labels.
- Consider shortening the repeated recent-activity list on the dashboard to reduce the empty space in the opposite column.

## Accessibility notes

The pages use headings, labelled form controls, visible selected navigation, keyboard focus styling and reduced-motion support. The map’s direction markers appear as repeated arrow buttons to assistive software, and the playback control is announced only as an icon. Colour contrast and full keyboard behaviour still need dedicated testing; screenshots alone cannot prove compliance.

## Evidence

- `tmp/ui-audit/01-login.png`
- `tmp/ui-audit/02-dashboard.png`
- `tmp/ui-audit/03-students.png`
- `tmp/ui-audit/04-live-map.png`
- `tmp/ui-audit/05-live-map-details.png`
- `tmp/ui-audit/06-activity.png`
- `tmp/ui-audit/07-health.png`
