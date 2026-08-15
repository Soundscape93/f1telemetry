# F1 Telemetry — User Guide

F1 Telemetry captures F1 25 / F1 26 UDP telemetry, analyses your laps, and tracks league /
multiplayer results and standings. This guide covers installing and running the Windows build, the
one-time game + firewall setup, and day-to-day use.

> The same setup notes are always available inside the app under **Help → Setup / Configuration**.

## 1. Install & run

There are two downloads on the project's GitHub **Releases** page. Both give you the same app.

### Option A — the installer (recommended)

1. Download **`f1telemetry-<version>-windows-x64-setup.exe`**.
2. Run it. **Windows will ask for administrator rights** — see the note below for why.
3. **SmartScreen** may warn ("Windows protected your PC") because the build is unsigned — click
   **More info → Run anyway**. This is expected for a small, unsigned app.
4. **Restart Windows when Setup asks.** This one matters — see the warning below.
5. Launch **F1 Telemetry** from the Start menu.

> **Restart before your first recording — and after every update.** The installer adds the Windows
> Firewall rule for you, but Windows doesn't put it into effect until it restarts. If you skip the
> restart, the app starts fine and **Record looks like it is working — but no telemetry arrives,
> and nothing tells you why**. If that happens, restart and try again. (The app will also hint at
> this after a few seconds of receiving nothing.)
>
> This applies **every time you run the installer**, including installing a new version over an
> existing one — not just the first install.

Once restarted, recording works the first time with no firewall prompt to click (section 2). The
installer also adds a Start-menu entry and an uninstaller.

> **Administrator rights are needed to install, and never to run.** Adding a firewall rule is a
> system-wide change, which is the only reason Windows asks. Once installed, F1 Telemetry runs as
> an ordinary program under your own account, and everything it saves stays in your own user
> folder (section 6). If it ever asks for administrator rights to *start*, that is a bug — please
> report it.

**Updating:** run the new installer over the top. Close the app first, or let the installer ask,
and **restart Windows afterwards** — the firewall rule needs it again after every install. Your
captures, database and rosters are untouched.

**Uninstalling:** Settings → Apps → F1 Telemetry → Uninstall. This removes the program and the
firewall rule. It deliberately **does not delete your captures or database** — those are yours and
can be many gigabytes. Remove them by hand if you want them gone (Help → Open data folder shows
you where they are).

### Option B — the zip

Use this if you can't or would rather not grant administrator rights.

1. Download the latest release zip.
2. Unzip it, keep the whole `f1telemetry` folder together, and run **`f1telemetry.exe`** from
   inside it.
3. Click through the same SmartScreen warning as above.

The zip needs no administrator rights at all, but nothing sets up the firewall rule for you — you
click **Allow** on the Windows prompt the first time you record (section 2).

No Python or other installs are needed with either option; everything is bundled.

Either way, next to `f1telemetry.exe` you'll also find **`USER_GUIDE.pdf`** (this guide),
**`roster_template.csv`** (section 5), and **`LICENSE`** + **`NOTICE.pdf`** (*Licence & notices*, at
the end of this guide). With the installer that folder is `C:\Program Files\F1 Telemetry`; you
rarely need to go there, because **Help → Open user guide** and **Help → Licences & notices** open
these from inside the app.

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

**If you used the installer, this is already done** — the rule was added during installation and
there is nothing to click. **But it only takes effect after you restart Windows** (section 1). If
recording receives nothing right after installing, that restart is the first thing to try.

**If you run the zip build,** Windows shows a firewall prompt the first time you record — click
**Allow**. If you dismissed or denied it, recording won't receive packets and the prompt won't
reappear (Windows remembers the denial). To fix it: open **Windows Defender Firewall → Inbound
Rules**, delete the **f1telemetry** rule, then press **Record** again to get a fresh prompt.

**Either way, the rule only covers *private* networks** — which is what a home network should be,
and what Windows' own prompt ticks by default. If Windows has your home network classified as
**Public**, no telemetry will arrive and there will be no error message to tell you so. Check
under **Settings → Network & internet → your network**, and set it to **Private network**.

## 3. Recording a session

Press **Record session(s)** in the header, drive your session, then **Stop**. The capture is saved,
compressed (zstd), and imported automatically. The record control is available from every page.

## 4. Importing & sharing captures

Captures are portable, self-contained files (`.f1cap.zst`). They are the league's exchange format:
when someone else drove a race you need results for, they share their capture and you import it.

**Sharing.** Copy the file out of your `captures` folder (Help → *Open captures folder*) and put it
wherever the league shares things — a Drive folder, a memory stick, a chat message. A sensible tree
is `<League>/<Season>/<Round>-<Track>/`.

**Importing.** **Help → Import captures…**, then pick the folder the captures are in. The app looks
through it (subfolders included), tells you how many new captures it found and how much will be
copied, and asks — optionally — **who recorded them**. Confirm and it copies each one into your own
`captures` folder and reads it. Both new `.zst` and older `.gz` files work.

Worth knowing:

- **The originals are left alone.** Nothing is moved, renamed or deleted from the folder you picked.
  Your `captures` folder becomes the home copy, so a capture stays readable when the drive is
  disconnected or someone tidies up the shared folder.
- **Re-running it is safe.** Captures are recognised by their *contents*, not their file name, so
  anything already imported is skipped — even if it was renamed along the way. Importing a synced
  folder every few weeks does no harm.
- **It doubles as a recovery.** If you deleted your local copy of a capture but it's still in the
  shared folder, importing brings it back and reconnects it to your stored sessions.
- **"Who recorded them?" is optional.** Leave it blank if you don't know. It's worth filling in
  because once the capture is on your machine, the shared drive can no longer tell you who put it
  there. Import the same captures again with a different name to correct it.
- You can cancel part-way. Captures already brought in stay; the rest simply aren't imported yet.

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

### Changing a season's calendar

Picked the wrong tracks, or the wrong order? Open the season and click **Edit calendar**. You can
add, remove and reorder rounds with the same picker used when the season was created.

**Rounds that already have sessions assigned are locked** — they keep both their position and their
track, and the editor lists them before you start. This protects your results: round 5's stored race
belongs to round 5 *at that track*, so letting it drift would file it under the wrong Grand Prix.
If an edit would move or remove a locked round, the save is refused and names the rounds involved.

To change a locked round anyway, open that round's weekend and unassign its sessions first — the
round then unlocks. In practice this is rarely needed: a wrong calendar is usually spotted before
any results have been assigned, and at that point the whole thing is freely editable.

The season's mode, number, nickname and game format can't be changed here. If one of those is
wrong, delete the season and create it again.

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

### Captures the app can no longer find

If the app reports captures as missing, do these two things **in order** — the first looks for them,
the second gives up on them.

**1. Help → Find moved captures…** Point it at the folder your recordings are in now — an old
captures folder, an external drive, wherever they ended up — and it searches it, subfolders
included. Anything it recognises is matched up again, and those sessions become re-readable
straight away.

It identifies a capture by its **contents**, not its name, so it can't confuse someone else's
recording with yours. **Nothing is moved, copied or deleted** — only the app's note of where each
capture lives. Two things to know: a capture you *renamed* as well as moved won't be recognised, and
one found on an external drive will go missing again when you disconnect that drive (copy it into
your `captures` folder if you want it permanently).

**2. Help → Clean up missing captures.** For captures that really are gone — deleted, rather than
moved. Their leftover entries are what make every re-read keep reporting them. It shows the full
list first — file name and where each was last seen — and nothing happens until you confirm.

**No files are deleted** — it only removes the app's *record* of captures that are already gone.
Sessions, seasons, standings and rosters are untouched, and if a file ever turns up again,
importing it puts its entry straight back.

If the app says *every* capture is missing, that usually means the folder itself moved or is on a
drive that isn't connected — check **Help → Open captures folder**, then use *Find moved captures…*
rather than cleaning up.

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
`NOTICE.pdf`, shipped next to the app and available from **Help → Licences & notices**. The same
notices also ship as `NOTICE.md` for anyone who prefers the plain-text source; the button opens the
PDF when it is present.
