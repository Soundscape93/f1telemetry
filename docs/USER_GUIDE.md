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

## 7. Checking for updates

**Help → Check for updates** compares your version with the latest GitHub release. If a newer
version exists it shows the version and a link to the download page. Updates are **manual** —
download the new zip and replace your folder. The app never auto-installs and works fully offline
(a failed check just says so).

## 8. Reporting a bug

Note your version (shown on the Help page) and attach the latest log from the `logs/` folder under
`%LOCALAPPDATA%\f1telemetry`. Describe what you did and what happened.

## Known issues

- **Switching the Windows light/dark theme while the app is open** leaves some text the wrong
  colour. Restart the app to refresh the theme.
