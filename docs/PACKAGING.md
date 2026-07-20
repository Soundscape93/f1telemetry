# Packaging & Release

How the app becomes a double-clickable desktop build that league members can run **without
Python, pip, PySide6, or anything else installed**. This file is the authoritative packaging
reference; the ROADMAP has only a short pointer. Written so a future session can start **Phase 0**
without re-deriving the discussion.

**Status:** planning only. No packaging code exists yet. No dependency manifest exists yet. All
data paths are still CWD-relative (the thing Phase 0 fixes).

**Goal / first milestone (≈2–3 weeks, before the league season):** a zipped **one-folder
PyInstaller build for Windows 11** that runs on the author's Windows boot from a clean state,
writes user data to a per-user directory (not beside the exe), records + imports + views a weekend
end-to-end, auto-migrates an old DB, logs to a file, and is shared with a few trusted testers via a
GitHub Release. macOS/Linux, installers, and real auto-update come later.

---

## Decisions (locked this session)

- **Tool: PyInstaller, one-folder.** Most battle-tested PySide6 support (official Qt hooks bundle
  the platform plugins); handles numpy / pyarrow / sqlalchemy. **One-folder**, not one-file:
  faster startup, far fewer Windows Defender / SmartScreen false positives, and inspectable. Not a
  company — no effort spent on installer polish or Qt edge cases beyond "it runs."
- **Windows first.** League testers are on Windows; it's also the cleanest artifact (no signing
  story needed for trusted testers). macOS/Linux are best-effort later.
- **Rejected for now:** Nuitka (slow builds, more pyarrow/PySide6 friction, more AV false
  positives), Briefcase (nicer native installers, but heavier and less-proven PySide6 path —
  revisit later if we want MSI/DMG/AppImage), cx_Freeze (less momentum).
- **Later upgrades, deliberately deferred:** Inno Setup installer (Start-menu entry + uninstaller)
  for Windows; Briefcase for native cross-platform installers; a real self-updater.
- **No paid signing while this is private/free:** unsigned Windows build (document SmartScreen
  click-through); no Apple Developer account / notarization (macOS builds are unsigned, documented
  right-click→Open workaround, later).

---

## The core problem: data paths (the reason Phase 0 exists)

Every data location is a **bare relative path resolved against the current working directory**:

- SQLite DB: `sqlite:///f1league.db` — the four store `_DEFAULT_URL`s + `main_window._DB_URL`.
- Captures: `main_window._CAPTURE_DIR = Path("captures")`.
- Lap traces (Parquet): `main_window._TRACE_DIR = "lap_traces"` → `LapStore(trace_dir=…)`.
- Rosters: `SeasonRosterFiles(root="rosters")` default.

This works in dev only because the app is launched from the workspace root (`F1-TELEMETRY/`), so
those folders land there. **Frozen it breaks:** CWD is unpredictable (double-click on Windows often
= `System32`), and the bundle dir is read-only. Data would be written to random or forbidden
places.

### The fix: a `paths.py` helper with two path kinds

There are **two different** location needs — do not conflate them:

1. **`data_root()` — per-user writable data** (DB, captures, lap_traces, rosters, logs, config).
   - **Frozen:** `QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)` →
     - Windows `%LOCALAPPDATA%\f1telemetry\`
     - macOS `~/Library/Application Support/f1telemetry/`
     - Linux `~/.local/share/f1telemetry/`
     - (Use **AppLocal**, non-roaming — do not roam multi-GB captures. Supersedes the earlier
       ROADMAP note that said `AppDataLocation`.)
   - **Dev / source (not `sys.frozen`):** keep today's CWD-relative behavior so the existing
     workspace-root `f1league.db` / `captures/` / `rosters/` keep working unchanged.
   - **Override:** `F1TELEMETRY_DATA_DIR` env var wins in both cases (power users / dev / tests).
   - Sub-layout under the root: `f1league.db`, `captures/`, `lap_traces/`, `rosters/`, `logs/`,
     `config.json`.
2. **`resource_path(name)` — bundled read-only assets** (flag SVGs at `flags.py`, `car_template.svg`
   if ever read at runtime, future assets).
   - **Frozen:** resolve under PyInstaller's `sys._MEIPASS`.
   - **Source:** the repo path.
   - Never in `data_root()`. These must also be added to PyInstaller's `datas` so they ship.

`app.py` already sets `setApplicationName`/`setOrganizationName("f1telemetry")`, so `QStandardPaths`
needs nothing extra. `SeasonRosterFiles` already takes an injectable `root`; `LapStore` already
takes `trace_dir` — so the blast radius is mostly `main_window.py`'s constants plus the four store
`_DEFAULT_URL`s. Route captures, DB, traces, and rosters through `data_root()` **together**.

---

## Dependencies

- **Runtime third-party:** PySide6, numpy, pyarrow, sqlalchemy. **Lazy/optional:** pyqtgraph
  (charts + track map), zstandard (new capture archives). Everything else is stdlib.
- **A dependency manifest must be created first** (none exists today) — `pyproject.toml` or
  `requirements.txt`. CI and PyInstaller both need it, and it pins the versions the build is
  reproducible against. This is a Phase 0 deliverable.
- **Lazy imports are a trap for the packager:** pyqtgraph and zstandard are imported inside
  branches, so PyInstaller may miss them and ship the *fallback* (the "install pyqtgraph" hint
  instead of the real track map; gzip instead of zstd). Both must be **explicit hidden imports**
  and verified *working*, not merely "doesn't crash." zstandard's wheel statically bundles libzstd
  (avoids a clash with the copy Qt loads) — keep that wheel.

### Include / exclude

- **Include:** the `src` package; PySide6 (QtCore/GUI/Widgets + platform + styles plugins);
  numpy; pyarrow; sqlalchemy; **pyqtgraph**; **zstandard**; **flag SVG assets** (as `datas`).
- **Exclude:** `test/`, `docs/` (except runtime assets), Qt modules we don't use — **QtWebEngine**
  (huge), QtQml/Quick, Qt3D, QtMultimedia, QtNetwork/Bluetooth if unused; matplotlib/tkinter/IPython
  if pulled transitively; numpy/pyarrow test data.

---

## DB migration & pipeline-version auto-reingest

Three change types — this is what decides "must the user re-ingest?":

1. **Additive schema** (new column with a default): already automatic and silent via
   `storage/migrations.py:ensure_schema` (`ADD COLUMN` on startup, idempotent, runs after
   `create_all`). No re-ingest, no data loss. Covers *most* changes. New columns must carry a
   `server_default` so old rows back-fill.
2. **Additive column that needs real values from the packets** (e.g. the sector-distance /
   track-length work): the column is added safely, but old rows only get correct values on a
   re-ingest. No crash; data is stale until re-derived.
3. **Non-additive** (rename / retype / drop / backfill): needs **Alembic** — adopted only at the
   first such migration (deferred; additive-only until then).

### Mechanism (planned): a `PIPELINE_VERSION` separate from the app SemVer

- Store a `PIPELINE_VERSION` integer in the DB (a `meta` row or SQLite `PRAGMA user_version`),
  distinct from the app's release version. Bump it **only** when ingest starts producing
  different/new derived data.
- On startup: run `create_all` + `ensure_schema` first (silent additive migrate). Then compare the
  stored `PIPELINE_VERSION` to the app's. If the app is higher, **detect it and offer a guided
  re-ingest** of the archived captures the `captures` table enumerates (by `content_hash`, with
  `path` / `codec` to reopen them).
- **Safe by design:** seasons, `season_assignments`, and laps are deliberately *not* FK'd to
  `sessions`, and `session_uid` is stable from the game — so wiping+rebuilding derived rows
  preserves standings / round assignments / rosters. `content_hash` dedupe makes it idempotent and
  resumable. (See core invariant #4 and the `capture_sessions` "which file re-ingests this uid?"
  design.)
- **UX is mandatory:** a weekend is ~1.5 GB of datagrams, so re-ingest is a **progress-barred,
  non-blocking background job** (reuse the `IngestWorker` pattern) with an explicit *"this may take
  a few minutes — the app hasn't frozen"* message. Never a silent startup gate.
- **Honest limit:** only captures whose archive is still present can be rebuilt. Surface
  *"N of M sessions updated; the rest are missing their capture archive."* `recorded_by` is the one
  field a re-ingest can't restore (it isn't in the file).

---

## Auto-update & release workflow

Staged — do not build a self-updater now.

- **Phase 1 (now): notify-only.** GitHub Releases + an in-app "check for updates" that queries the
  Releases API, compares versions, and shows a notification with a **manual download link**. No
  self-replacement.
- **Phase 2 (later): real self-updater.** Best modern cross-platform option is **velopack**
  (delta updates, GitHub-Releases appcast); per-OS alternatives are Sparkle (mac) / Squirrel (Win);
  `tufup` (TUF-based) is a Python-native option. Full self-replace is fiddly with a *running*
  one-folder app on Windows (file locks) — deferred deliberately.

### GitHub Actions

- Prereq: the dependency manifest.
- Matrix: `windows-latest` (priority), later `macos-latest` + `macos-14` (arm) and `ubuntu-latest`.
  Each runs PyInstaller, uploads its artifact; a tag push (`v*`) creates a Release and attaches the
  artifacts, body from the changelog.
- **Windows** folder → zip is the clean primary artifact. **macOS** builds are unsigned/unnotarized
  → Gatekeeper blocks (right-click→Open; no Apple account while free). **Linux** → a tarball first;
  AppImage later.

### Versioning & dev release process

- One `__version__` in the package (CI can stamp it from the git tag). SemVer `MAJOR.MINOR.PATCH`.
  Keep **`PIPELINE_VERSION` separate** (bumped only when ingest output changes).
- Release: bump version → update `CHANGELOG.md` → tag `vX.Y.Z` → push → CI builds + publishes.
  Notes for friends must state **"re-ingest needed? yes/no"** and list known issues (the app is
  partial).
- **Do not break dev:** the `sys.frozen`-aware `paths.py` keeps source runs on CWD-relative dirs.
- **Never `git commit` from tooling** (repo convention) — suggest the message, author runs it.

---

## Phased plan

- **Phase 0 — pre-package refactor (the only non-trivial code; everything depends on it):**
  dependency manifest; `paths.py` (`data_root()` + `resource_path()`, frozen-aware, env override,
  dev-preserving); route all stores + assets through it; **file logging** to `logs/`; **global
  exception hook → crash dialog + log**; `__version__`. The app must run correctly from an
  arbitrary CWD writing to the user dir — *before* any PyInstaller work.
- **Phase 1 — Windows package:** PyInstaller one-folder spec (hidden imports for
  pyqtgraph/zstandard, exclude heavy Qt modules, bundle flag SVGs); build on the Win11 boot; pass
  the clean-machine checklist below.
- **Phase 2 — migration / reingest:** `PIPELINE_VERSION` + startup detect + progress-barred
  auto-reingest from `captures`.
- **Phase 3 — CI + release:** GitHub Actions Windows build on tag → Release; in-app update check
  (notify-only).
- **Phase 4 — reach + polish:** macOS/Linux artifacts (unsigned), Inno Setup installer, later a
  real auto-updater (velopack).

---

## Clean-machine test checklist (Windows 11)

Run on the author's Windows 11 boot; ideally from a fresh user with no Python installed.

- [ ] Launch by **double-click** from a folder that is *not* the repo (proves CWD independence).
- [ ] Launch as a **non-admin** user; nothing tries to write beside the exe.
- [ ] Machine with **no Python** installed at all.
- [ ] Qt starts — **no "could not load the Qt platform plugin"** error.
- [ ] HiDPI/scaling correct on the laptop panel (fonts/layout).
- [ ] **Recording:** UDP socket binds → **Windows Firewall prompt appears → Allow** (document it);
      a `.f1cap` lands in `captures/` under `%LOCALAPPDATA%\f1telemetry`.
- [ ] **Ingest** a real capture: sessions/laps written; **Parquet traces** written and readable
      (pyarrow works in the bundle).
- [ ] **Track map + telemetry traces render** (pyqtgraph bundled — the *real* widget, not the
      install hint).
- [ ] New captures written as **zstd** (zstandard bundled); a zstd file from another member imports.
- [ ] **Flag SVGs render** (bundled `resource_path()` resolves).
- [ ] Start against an **old DB** → additive columns added silently; against a **fresh** machine →
      DB created cleanly.
- [ ] Kill mid-record → app recovers on next launch.
- [ ] Open the app **twice** → SQLite doesn't wedge (WAL mode; handle "database is locked").
- [ ] **Logs** written to `logs/` and human-readable; an induced exception shows the crash dialog.
- [ ] Note SmartScreen behavior and the exact click-through for the tester doc.

---

## Risks & fallbacks (keep this list; revisit if packaging misbehaves)

- **Qt platform plugin missing** → app won't start. Fallback: verify on a clean machine; PyInstaller
  Qt hooks normally cover it.
- **pyqtgraph / zstandard missed** (lazy imports) → app silently ships the fallback. Fallback:
  explicit hidden imports + a startup self-check that warns if a "real" feature degraded.
- **pyarrow bloat / Windows DLL-load quirks** (~100 MB+). Fallback: verify Parquet read/write early;
  worst case a startup capability probe.
- **Unsigned Windows exe / SmartScreen** "unknown publisher." Fallback: one-folder (fewer flags) +
  documented "More info → Run anyway"; code-signing cert only if it scares testers.
- **macOS Gatekeeper** (unsigned). Fallback: documented right-click→Open; notarize later if ever.
- **Auto-reingest slow / archives missing.** Fallback: optional + resumable + progress; surface
  un-upgradable sessions.
- **Self-updater complexity on Windows** (file locks while running). Fallback: stay notify-only.

---

## What's easy to forget (end-user & dev-support reality)

These are **Phase 0 / documentation requirements**, not afterthoughts:

1. **File logging + crash dialog** — a windowed build has **no console**; without these you and the
   testers are blind to errors. Highest-value non-obvious item. (Phase 0.)
2. **In-game UDP setup doc** — the F1 game must be told to send UDP telemetry to the recorder's
   IP/port (recorder binds `0.0.0.0:20777`); without it nothing records. Biggest support-ticket
   source. (Tester doc.)
3. **Windows Firewall prompt** on first record — tell testers to **Allow**.
4. **Capture sharing flow** — captures are hash-identified and portable *by design*; give the
   league a concrete "drop files here / Import folder" procedure (builds on the `captures` metadata
   table + the planned shared-folder import).
5. **Where's my data?** — document `%LOCALAPPDATA%\f1telemetry` (and the mac/Linux equivalents) so
   users can back up / send the DB when reporting a bug.
6. **Bundled zstandard** so one member's captures are readable by all (codec consistency).
7. **Known-issues note per build** (the app is partial) so testers report *new* bugs.
8. **WAL mode / double-launch** — minor but real SQLite locking.

---

## Tester / end-user instructions (to write with the first build)

A short README/onboarding for league members should cover:

- **Install/run:** unzip, run the exe; the SmartScreen click-through.
- **Enable UDP telemetry in the F1 game** — where the setting is, the recorder IP + port
  (`20777`), broadcast on.
- **Allow the Windows Firewall prompt** the first time you record.
- **Recording a weekend** when the author isn't available.
- **Sharing captures** back to the league (copy files / import folder).
- **Where your data lives** (`%LOCALAPPDATA%\f1telemetry`) and how to back it up.
- **Reporting a bug:** attach the log from `logs/` + note the version; the known-issues list.
- **Upgrade note:** whether a new build needs a re-ingest, and that it may take a few minutes.

---

## OS notes

- **Windows (first):** primary target. Unsigned; SmartScreen documented. `%LOCALAPPDATA%` data
  root. Firewall prompt on record. Inno Setup installer is a later nicety.
- **macOS (later):** unsigned/unnotarized while free → Gatekeeper right-click→Open. Universal/arm
  build via `macos-14` runner. `~/Library/Application Support` data root.
- **Linux (later):** tarball or one-folder first; AppImage later. `~/.local/share` data root. xcb
  platform plugin must be present.
