# Changelog

Notes here become the body of the GitHub Release. Write your entries under **Unreleased**;
labelling the `staging` → `main` pull request `major` / `minor` / `patch` renames that section to
the new version and bumps `src/version.py` + `pyproject.toml` **on that PR's branch**, and merging
it tags the commit and publishes the build.

Small changes are grouped on `staging`, so several of them share one release: each adds its own
bullet under **Unreleased**, and whatever is in that section when the release PR is labelled is
exactly what ships.

Every release must say whether a **re-ingest** is needed — that is "yes" whenever
`PIPELINE_VERSION` in `src/version.py` moved since the previous release.

## Unreleased

<!-- One bullet per user-visible change, plus the mandatory line
     **Re-ingest needed: yes/no** - yes whenever PIPELINE_VERSION moved.
     Carry the **Known issues** list forward from the last release and prune whatever is fixed:
     dropping it silently tells testers the issues went away. (It was lost after v0.3.0 this way.)
     Merging a PR labelled major/minor/patch turns this section into a release. -->

**Re-ingest needed: no** — `PIPELINE_VERSION` is unchanged; nothing about how captures are read or
stored moved, so existing captures, sessions and standings are unaffected.

### Added
- **Help → Back up database…** saves a copy of your database wherever you choose. It is safe to do
  while the app is busy — including in the middle of a long re-read — and the copy is always a
  complete, consistent database rather than a half-written file. Use it when you report a bug, or
  before doing anything you're unsure about. Your captures remain the real source of truth: a lost
  database can always be rebuilt from them, which a lost capture cannot.
- The app now ships its licence and its third-party notices next to the executable, and the Help
  page has a **Licences & notices** button that opens them. They cover the components the build
  bundles (Qt/PySide6, NumPy, Apache Arrow, SQLAlchemy, PyQtGraph, zstandard and the nationality
  flag icons), state that this is an **unofficial tool** with no affiliation to Formula 1, the FIA,
  EA or Codemasters, and note that captures can contain other players' online names — so share them
  only with people who expect it. The Help page carries a short version of the same notice, and the
  user guide has it as a closing section.

### Changed
- The database now uses SQLite's write-ahead logging. In practice: the app stays readable while it
  is writing, so browsing your seasons and laps during a long "re-read captures" pass no longer
  competes with it, and opening the app twice by accident is far less likely to leave one of them
  stuck. Nothing about your stored data changes and no re-read is needed — existing databases
  switch over the first time this version opens them.

### Fixed
- The track map on the lap detail page no longer keeps showing an outdated shape after new laps
  are read. The map draws one clean outline per race weekend, built from that weekend's laps, and
  the result was worked out once and then kept for the rest of the session — so recording or
  re-reading more laps from a weekend changed nothing on screen until the app was restarted. That
  included the case where a weekend had too few laps to build the clean outline: it stayed on the
  single driven line even once enough laps existed. The map is now rebuilt whenever stored laps
  change — after recording, after re-reading your captures, and after deleting a session's stored
  results — and a lap that is already open is redrawn straight away.

**Known issues**

- Recordings made **before v0.4.2 on Windows** may be missing stretches of telemetry, and with them
  the final classification, if the machine slept mid-session. Nothing can recover that — the data
  never reached the app — so re-reading those captures won't bring it back. Sessions with a missing
  classification show a reconstructed result instead.
- Switching the Windows light/dark theme while the app is open leaves some text the wrong colour —
  restart to fix.
- Dashboard, Sessions, Analytics and Bug report pages are placeholders.
- The build is unsigned: SmartScreen shows "Windows protected your PC" → **More info → Run anyway**.

## v0.4.2 — 2026-08-01

**Re-ingest needed: no** — `PIPELINE_VERSION` is unchanged; nothing about how captures are read or
stored moved, so existing captures, sessions and standings are unaffected.

### Fixed
- Recording: the computer no longer goes to sleep while a recording is running. If you record on a
  machine you aren't touching — the usual setup when the game runs on a console — Windows saw it as
  idle and slept it mid-session, and a sleeping machine receives nothing at all. That cost whole
  minutes of telemetry and, because it usually struck once the session ended, the final
  classification along with it. The screen now stays on for as long as you are recording and
  returns to your normal power settings as soon as you stop.

**Known issues**

- Recordings made **before this version on Windows** may be missing stretches of telemetry, and
  with them the final classification, if the machine slept mid-session. Nothing can recover that —
  the data never reached the app — so re-reading those captures won't bring it back. Sessions with
  a missing classification show a reconstructed result instead.
- Switching the Windows light/dark theme while the app is open leaves some text the wrong colour —
  restart to fix.
- Dashboard, Sessions, Analytics and Bug report pages are placeholders.
- The build is unsigned: SmartScreen shows "Windows protected your PC" → **More info → Run anyway**.

## v0.4.1 — 2026-08-01

**Re-ingest needed: no** — `PIPELINE_VERSION` is unchanged; nothing about how captures are read or
stored moved, so existing captures, sessions and standings are unaffected.

### Fixed
- Recording: raised the UDP receive buffer well above the OS default (Windows' 64 KB held only
  ~0.3 s of telemetry) and added a warning whenever the recorder is descheduled mid-capture, which
  silently dropped packets — including Final Classification packets — on Windows.

## v0.4.0 — 2026-08-01

**Re-ingest needed: no** — nothing about ingest changed; the nationality was already stored with
every result.

- **New:** driver standings now show each driver's nationality flag, the same flag already shown
  in the session result tables. Constructor standings are unchanged — the game reports nationality
  per driver, not per team. A driver whose nationality isn't recognised simply shows no flag.

- **New:** **Help → Clean up missing captures** clears the leftover entries of capture files you
  deleted, so re-reading your captures stops reporting them as missing. It shows you the full list
  first — file name and where each was last seen — and nothing happens until you confirm.
  **No files are deleted**: this only removes the app's record of captures that are already gone,
  and your sessions, seasons, standings and rosters are untouched. A capture that was merely
  *moved* is never forgotten by accident — the app re-checks each one as it goes and keeps any
  that turns up, and it warns you before continuing if *every* capture looks missing (usually a
  captures folder that moved, or a drive that isn't connected). If a forgotten file ever comes
  back, importing it restores its entry.

## v0.3.0 — 2026-07-31

First published build for league testers.

**Re-ingest needed: yes** — `PIPELINE_VERSION` moved to 2 so classifications record whether each
car was AI or human. The app offers the guided re-ingest on first launch; until it runs, driver
standings fall back to matching AI drivers by name.

- **Fixed:** driver standings merged an AI driver into a league member who shares their race
  number (the AI field runs the real-world numbers), so the pair showed as one row under the
  wrong name and with the wrong points total. AI and human drivers are now told apart, and two
  cars from the same session can never share a standings row. Constructor standings and session
  result tables were never affected.

- Record F1 25 / F1 26 UDP telemetry, import captures, and browse sessions, laps and standings.
- Per-user data folder (`%LOCALAPPDATA%\f1telemetry`), file logging and a crash dialog.
- Guided, cancellable re-ingest when a later build reads more out of your captures.
- Help page: check for updates, re-read captures, open the user guide, and open the data /
  captures / logs folders.
- The zip ships `USER_GUIDE.pdf` and `roster_template.csv` next to the exe.

**Known issues**

- Switching the Windows light/dark theme while the app is open leaves some text the wrong colour —
  restart to fix.
- Dashboard, Sessions and Analytics pages are placeholders.
- The build is unsigned: SmartScreen shows "Windows protected your PC" → **More info → Run anyway**.

