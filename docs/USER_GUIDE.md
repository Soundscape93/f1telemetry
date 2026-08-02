# F1 Telemetry — User Guide

F1 Telemetry captures F1 25 / F1 26 UDP telemetry, analyses your laps, and tracks league /
multiplayer results and standings. This guide covers installing and running the Windows build, the
one-time game + firewall setup, and day-to-day use.

> The same setup notes are always available inside the app under **Help → Setup / Configuration**.

## 1. Install & run

1. Download the latest release zip from the project's GitHub **Releases** page.
2. Unzip it and keep the whole `f1telemetry` folder together and run
   **`f1telemetry.exe`** from inside it.
3. **SmartScreen** may warn ("Windows protected your PC") because the build is unsigned — click
   **More info → Run anyway**. This is expected for a small, unsigned app.

No Python or other installs are needed; everything is bundled.

Next to `f1telemetry.exe` you'll also find **`USER_GUIDE.pdf`** (this guide) and
**`roster_template.csv`** (section 5). Inside the app, **Help → Open user guide** opens the PDF.

## 2. First-time setup

### In-game telemetry (F1 game → Settings → Telemetry Settings)

- **UDP Telemetry:** On
- **UDP Broadcast Mode:** On
- **UDP Port:** 20777
- **UDP Format:** 2025 or 2026 (older formats are not supported)
- Set your **telemetry / online name to Public** so driver names come through in captures.

On console (PS5/Xbox) set the same options — the recorder listens on `0.0.0.0:20777`, so broadcast
reaches it over your Network.

### Windows Firewall

The first time you record, Windows shows a firewall prompt — click **Allow**. If you dismissed or
denied it, recording won't receive packets and the prompt won't reappear (Windows remembers the
denial). To fix it: open **Windows Defender Firewall → Inbound Rules**, delete the **f1telemetry**
rule, then press **Record** again to get a fresh prompt.

## 3. Recording a session

Press **Record session(s)** in the header, drive your session, then **Stop**. The capture is saved,
compressed (zstd), and imported automatically. The record control is available from every page.

## 4. Importing & sharing captures

Captures are portable, content-hashed files (`.f1cap.zst`). Share them with league members; use the
**Ingest .f1cap** button to import one you received — both new `.zst` and older `.gz` files work.

## 5. League / multiplayer rostering

If members don't set their online name to Public, import a driver **roster CSV** per season
(**Seasons → pick a season → import roster**).

The CSV needs a **header row** with these columns:

- `name` — canonical name shown in standings (required)
- `race_number` — the stable per-driver anchor (required; unique integer)
- `online_names` — optional; the name(s) they appear under in telemetry when public, multiple
  separated by semicolons

Column names are case-insensitive. Example:

```
name,race_number,online_names
Lewis,44,xxLewis
Max,33,xxMax;Verstappen33
Charles,16,xxCL16xx
```

A blank template (`roster_template.csv`) is included in the release zip, and can also be saved from
**Help → Setup / Configuration → Save a blank template CSV…**.

## 6. Where your data lives

Your database, captures, lap traces, rosters and logs are stored under:

```
%LOCALAPPDATA%\f1telemetry
```

Back up this folder to preserve your seasons and captures. The exact path is shown on the Help page.

This folder is **hidden in Explorer by default** — you don't need to go looking for it. Use
**Help → Open data folder**, **Open captures folder** or **Open logs folder** and the app opens
Explorer there for you.

**Please don't hand-edit `f1league.db`** with DB Browser for SQLite or similar tools. It's easy to
break the app's data that way, and it makes bug reports much harder to diagnose. You don't need to:
your captures are the real source of truth, so if the database ever misbehaves, **Help → Re-read
captures…** rebuilds it from them.

### Backing up your database

**Help → Back up database…** saves a copy wherever you choose. It is safe to use at any time, even
while the app is recording or part-way through re-reading your captures — the copy is always a
complete, working database, never a half-written one.

Two things to know about what a backup is *for*:

- **Your captures matter more.** A lost database can be rebuilt from your captures; a lost capture
  is gone for good. Back up the `captures` folder first, and treat the database copy as a
  convenience.
- **It is what to attach to a bug report.** If something looks wrong in your standings or laps, a
  backup lets the problem be reproduced exactly. Remember it contains other players' online names,
  so send it only to someone you'd share your captures with (see *Reporting a bug*).

## 7. Checking for updates

**Help → Check for updates** compares your version with the latest GitHub release. If a newer
version exists it shows the version and a link to the download page. Updates are **manual** —
download the new zip and replace your folder. The app never auto-installs and works fully offline
(a failed check just says so).

## 8. After an update: re-reading your captures

Some updates read **more** out of a capture than earlier versions did (extra temperatures, track
geometry, new chart channels). Existing sessions in your database were stored before that, so they
can't show the new details until they're rebuilt.

When that's the case, the app asks once at start-up:

- **Update now** — re-reads every saved capture and rebuilds your stored sessions. A progress window
  shows which capture it's on. **This can take a few minutes for a full weekend** — the app has not
  frozen, you can keep using it, and you can cancel at any time (it stops after the capture it's
  working on, and picks up again later — nothing is left half-finished).
- **Not now** — nothing happens; you'll be asked again next time you start the app.
- **Don't ask again** — stops the question for good. Use this if you no longer have the capture
  files.

You can also start it yourself at any time from **Help → Re-read captures…**.

**Your seasons, round assignments and imported rosters are kept** — only the data read out of the
captures is rebuilt, and sessions you deleted stay deleted.

Only captures that are still in your `captures` folder can be rebuilt. If some are missing, the app
says so ("*N of M sessions updated*") — those sessions keep their old data, which is harmless: they
simply won't show the newest details.

### Cleaning up captures you deleted

Deleting a capture file leaves its entry behind, so every re-read keeps reporting it as missing.
**Help → Clean up missing captures** clears those leftovers. It shows the full list first — file
name and where each was last seen — and nothing happens until you confirm.

**No files are deleted** — it only removes the app's *record* of captures that are already gone.
Sessions, seasons, standings and rosters are untouched, and if a file ever turns up again,
importing it puts its entry straight back.

A capture that was only **moved** should be put back rather than forgotten: move it into your
`captures` folder (or import it again) and it's found. If the app says *every* capture is missing,
check **Help → Open captures folder** first — that usually means the folder itself moved or is on a
drive that isn't connected.

## 9. Reporting a bug

Note your version (shown on the Help page) and attach the latest log from the `logs/` folder under
`%LOCALAPPDATA%\f1telemetry` (the Help page can open that folder for you). Describe what you did and
what happened. Don't send a hand-edited database — see section 6.

## Known issues

- **Switching the Windows light/dark theme while the app is open** leaves some text the wrong
  colour. Restart the app to refresh the theme.

## Licence & notices

**F1 Telemetry is an unofficial fan-made tool.** It is not affiliated with, authorised by, or
endorsed by Formula 1, the FIA, EA or Codemasters. F1 and related marks, and all team, driver and
circuit names, belong to their respective owners.

**The app only listens to your own game.** It records the UDP stream your copy of the game
broadcasts on your own network — it never connects to the publisher's servers and never modifies
the game.

**Your captures, your responsibility.** Recordings can contain other players' online names and
results. Share them only with people who expect it, and follow the game's own terms of service.

**Results are best-effort, not official.** Lap times, standings and telemetry are read from a UDP
stream that can drop packets, especially over Wi-Fi. A session that ends without a final
classification is reconstructed from what's available and clearly marked in the app.

The app is source-available, not open source: you may download and run the official builds, but
redistribution and reuse need permission. The full licence and the third-party notices — Qt/PySide6
under LGPL v3, and the MIT-licensed nationality flags among others — are in `LICENSE` and
`NOTICE.md`, shipped next to the app and available from **Help → Licences & notices**.
