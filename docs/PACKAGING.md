# Packaging & Release

How the app becomes a double-clickable desktop build that league members can run **without
Python, pip, PySide6, or anything else installed**. This file is the authoritative packaging
reference; the ROADMAP has only a short pointer. Written so a future session can start **Phase 0**
without re-deriving the discussion.

**Status:** **Phases 0, 1 and 2 done.** Phase 0 = dependency manifest, `paths.py`, file logging,
crash hook, `__version__` (see "Phase 0 — done"). Phase 1 = the PyInstaller one-folder Windows build
(`packaging/` spec + entry point) **plus a notify-only update check** (pulled forward from Phase 3),
built on the author's Windows 11 boot and verified against the clean-machine checklist on
2026-07-25 (see "Phase 1 — done"). Phase 2 = the `PIPELINE_VERSION` stamp in the database plus the
guided, cancellable re-ingest of the archived captures (see "Phase 2 — done") — verified on
dev/Linux 2026-07-25; its clean-machine items are **still to be re-checked on the next Windows
build**. Dev runs are unchanged: source runs still resolve every data path against the CWD.

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

`app.py` sets `setApplicationName`/`setOrganizationName("f1telemetry")`; `paths._frozen_data_root()`
does not depend on that having run (it uses `GenericDataLocation` and appends `f1telemetry` itself,
so it works before the `QApplication` exists — logging is configured first). **As implemented, the
routing lives at the app entry points, not in the stores:** `MainWindow`, `IngestWorker`, and
`SeasonRosterFiles`'s default `root` resolve through `data_root()` together, so every production
store gets a `paths.db_url()`. The four store `_DEFAULT_URL` constants were intentionally left as
harmless relative fallbacks — no production code hits them, and every test passes an explicit temp
URL, which kept the storage layer free of import-time side effects and the suite untouched.

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

### Mechanism (Phase 2, implemented): a `PIPELINE_VERSION` separate from the app SemVer

- A `PIPELINE_VERSION` integer is stored in the DB, distinct from the app's release version. Bump
  it **only** when ingest starts producing different/new derived data.
- **A `meta` key/value table, not SQLite's `PRAGMA user_version`** — the schema is kept
  engine-agnostic (a PRAGMA is not), and a *new table* needs no migration at all: `create_all`
  creates it, the `deleted_sessions` / `captures` precedent.
- On startup: `create_all` + `ensure_schema` run first (every store does both in its constructor,
  so the silent additive migrate always precedes the comparison). Then the stored
  `PIPELINE_VERSION` is compared to the app's. If the app is higher, the app **offers a guided
  re-ingest** of the archived captures the `captures` table enumerates (by `content_hash`, with
  `path` / `codec` to reopen them).
- **An unstamped database is two different things**, and the difference is the whole upgrade story:
  *no sessions* = brand new, so it is stamped with the current version immediately (a first launch
  must never prompt); *has sessions* = it predates the stamp itself, so its rows were derived by an
  unknown older pipeline — treated as `LEGACY_PIPELINE_VERSION` (0) and offered the re-ingest. Only
  a completed rebuild (or an explicit "don't ask again") writes the new stamp.
- **Safe by design:** seasons, `season_assignments`, and laps are deliberately *not* FK'd to
  `sessions`, and `session_uid` is stable from the game — so wiping+rebuilding derived rows
  preserves standings / round assignments / rosters. `content_hash` dedupe makes it idempotent and
  resumable. (See core invariant #4 and the `capture_sessions` "which file re-ingests this uid?"
  design.)
- **UX is mandatory:** a weekend is ~1.5 GB of datagrams, so re-ingest is a **progress-barred,
  non-blocking background job** (reuses the `IngestWorker` pattern) with an explicit *"this may take
  a few minutes — the app hasn't frozen"* message. Never a silent startup gate.
- **Honest limit:** only captures whose archive is still present can be rebuilt. The result line is
  *"Updated N of M stored session(s)… X capture file(s) could not be found, so their sessions keep
  the old data."* Missing archives deliberately **do not** block the new stamp — nothing the app can
  ever do will rebuild those rows, so refusing to stamp would re-offer the same impossible upgrade
  on every launch. A cancel or a real ingest error *does* block it; both are worth retrying.
- `recorded_by` **is** preserved: it isn't in the capture file, but it is in the `captures` row the
  re-ingest reads, and is fed back through `ingest_capture` — without that, a re-ingest would
  actively erase it. (This corrects the earlier note that called it unrecoverable.)

---

## Auto-update & release workflow

Staged — do not build a self-updater now.

*(These two stages are the update story only — don't confuse them with the packaging phases below;
the self-updater is packaging Phase 4.)*

- **Stage 1 (shipped in Phase 1): notify-only.** GitHub Releases + an in-app "check for updates"
  that queries the Releases API, compares versions, and shows a notification with a **manual
  download link**. No self-replacement.
- **Stage 2 (later): real self-updater.** Best modern cross-platform option is **velopack**
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
- **Release zip contents:** the one-folder build, plus **`USER_GUIDE.pdf`** (convert
  `docs/USER_GUIDE.md`) and **`roster_template.csv`** at the top level. Publish a **full** GitHub
  Release — not a draft/prerelease, or `/releases/latest` returns 404 and the in-app update check
  can't see it.
- **Do not break dev:** the `sys.frozen`-aware `paths.py` keeps source runs on CWD-relative dirs.
- **Never `git commit` from tooling** (repo convention) — suggest the message, author runs it.

---

## Phased plan

- **Phase 0 — pre-package refactor (the only non-trivial code; everything depends on it): DONE.**
  See "Phase 0 — done" below.
- **Phase 1 — Windows package + notify-only update check: DONE (2026-07-25).** PyInstaller
  one-folder spec + entry point (`packaging/`); hidden imports for pyqtgraph/zstandard; heavy Qt
  modules excluded; flag SVGs bundled. Built on the Win11 boot and passed the clean-machine
  checklist. The notify-only update check (`src/update_check.py` + the Help page's "Check for
  updates") was pulled forward from Phase 3. See "Phase 1 — done" below.
- **Phase 2 — migration / reingest: DONE (2026-07-25, dev).** `PIPELINE_VERSION` stamped in a `meta`
  table + startup detect + a cancellable, progress-barred re-ingest from `captures`. See
  "Phase 2 — done" below.
- **Phase 3 — CI + release:** GitHub Actions Windows build on tag → Release (the notify-only update
  check already shipped in Phase 1). PR-label-driven version bump + auto-Release is the planned shape.
- **Phase 4 — reach + polish:** macOS/Linux artifacts (unsigned), Inno Setup installer (a natural
  home for the Windows Firewall allow-rule so testers never see the prompt), later a real
  auto-updater (velopack).

---

## Phase 0 — done

Landed modules and what they do:

- **`src/version.py`** — `__version__` (SemVer) + `PIPELINE_VERSION` (kept independent; the latter
  gates the Phase 2 re-ingest). `app.py` sets `app.setApplicationVersion(__version__)` and logs it
  at startup.
- **`src/paths.py`** — the path authority. `data_root()` (env override → frozen per-user dir →
  CWD), `resource_path(*parts)` (`_MEIPASS`-aware, keyed relative to the `src` package), plus
  `db_url()`, `captures_dir()`, `trace_dir()`, `rosters_dir()`, `logs_dir()`, `config_path()`.
- **`src/logging_setup.py`** — `configure_logging()`: a rotating file log at
  `data_root()/logs/f1telemetry.log` (2 MB × 5), plus a console handler in dev only. Called first
  in `main()`.
- **`src/crash.py`** — `install_excepthook(log_file)`: logs any uncaught exception and shows a
  `QMessageBox` pointing at the log. Installed after the `QApplication`. (Worker threads already
  emit `failed`; a `threading.excepthook` is a later add.)
- **`pyproject.toml`** (repo root) — the dependency manifest, deps pinned `==` to the validated
  versions, with `pyqtgraph`/`zstandard` listed explicitly (Phase 1 must force-include them) and
  `pyinstaller` under an optional `package` extra. Version is a static mirror of `src/version.py`
  (CI will stamp both in Phase 3).

### Contract Phase 1 must honor (bundled assets)

`resource_path(*parts)` resolves frozen assets under
`sys._MEIPASS / "f1telemetry" / "src" / *parts`. So the PyInstaller `datas` entry for the flag SVGs
must ship them at **`f1telemetry/src/ui/assets/flags/`** inside the bundle (preserve the
`f1telemetry/src/...` layout). Add any future runtime asset the same way and read it via
`resource_path`.

---

## Phase 1 — done

Built and verified on the author's Windows 11 boot on 2026-07-25 (clean-machine checklist below).

- **`packaging/f1telemetry.spec`** (one-folder) + **`packaging/entry.py`** (entry point →
  `f1telemetry.src.ui.app:main`). The spec finds the repo root by the `src/` marker (robust to
  whether `SPECPATH` resolves to the repo root or the `packaging/` subdir), puts the parent on
  `pathex` so `f1telemetry.src.*` imports resolve, ships the flag SVGs at
  `f1telemetry/src/ui/assets/flags` (honoring `resource_path`), force-includes **pyqtgraph** +
  **zstandard** (+ `zstandard.backend_c`, `PySide6.QtSvg`) as hidden imports, and excludes the heavy
  Qt modules. Build: `pip install -e ".[package]"` then `pyinstaller packaging/f1telemetry.spec`
  from the repo root → `dist/f1telemetry/`. (The `.spec` is force-tracked past the `*.spec` gitignore
  rule via a `!packaging/f1telemetry.spec` negation.)
- **Notify-only update check** — `src/update_check.py` (stdlib `urllib`, GitHub Releases API, a tiny
  SemVer compare, never raises; `GITHUB_OWNER`/`GITHUB_REPO` constants) + `UpdateCheckWorker`
  (off the GUI thread) + the Help page's "Check for updates" button and a manual-download dialog. No
  self-replacement; offline / rate-limit / bad response all fold into a calm "couldn't check"
  message. `test/test_update_check.py` covers version compare + fetch/parse/error paths (no network).
- **Frozen-only bugs found & fixed** (only reachable in a packaged build, so untested until now):
  `paths.py` `_frozen_data_root` did `str / str` (QStandardPaths returns a `str`) → wrap in
  `Path(base)`; `crash.py` `setWindowTable` typo → `setWindowTitle` (the crash dialog itself was
  crashing); `recorder.py` had `return` inside a `finally` (swallowed exceptions) → moved after it.

### Known issues (Phase 1 build)

- **Live Windows light/dark switch** doesn't fully recolor the UI. `app._install_theme_refresh`
  (on `QStyleHints.colorSchemeChanged`) re-polishes widgets so backgrounds follow, but **QSS-styled
  label text keeps its old colour** — a `setStyleSheet` pins the palette-derived text colour. Fix
  deferred (move those labels' font sizing off `setStyleSheet` onto `QFont`, or re-apply palette on
  the signal). Workaround: **restart the app after switching the Windows theme.**
- **pyqtgraph bloat:** the contrib hook pulls in `pyqtgraph.examples.*` (harmless, pure `.pyc`).
  Trim via `excludes` in a later size pass before wider distribution — not worth destabilizing a
  verified build now.

---

## Phase 2 — done

Verified against a real dev database on 2026-07-25 (Linux/source run). The Windows items are folded
into the clean-machine checklist below and are **still to be re-checked on the next build**. No new
dependency and no new bundled asset — the PyInstaller spec is untouched.

- **`src/storage/schema.py` → `MetaRow`** — the `meta` key/value table (TEXT values, so the table
  stays generic; the store parses the one integer key it owns). A new table ⇒ `create_all` handles
  it, no migration.
- **`src/storage/meta.py` → `MetaStore`** — repository-per-aggregate sibling for the one thing that
  belongs to no aggregate. `get`/`set` plus `pipeline_version()` / `set_pipeline_version()`. An
  unparseable stamp (hand-edited, corrupt) reads as *unstamped* rather than crashing start-up.
  `LEGACY_PIPELINE_VERSION = 0` lives here.
- **`src/storage/sessions.py` → `SessionStore.stored_uids()`** — reads only the primary-key column,
  so the re-ingest can size its work and report "N of M" without hydrating every classification.
- **`src/pipeline.py`** — the Qt-free half: `PipelineState` (CURRENT / UPGRADE_AVAILABLE / AHEAD),
  `check_pipeline_version` (the gate, including adopting a fresh database), `resolve_capture_path`
  (recorded path → `captures_dir()/file_name` fallback, because `CaptureRow.path` is advisory and a
  data root moves between a dev checkout and a frozen build), `ReingestSummary` (+ `is_complete`,
  which decides whether the stamp moves) and `reingest_all`. Archives are ingested **in place** via
  `ingest_capture` — never `archive_and_ingest` — so nothing is re-compressed and no file is ever
  deleted by a re-ingest. One bad archive is recorded and skipped rather than aborting the pass.
- **`src/ui/workers.py` → `ReingestWorker`** — the `IngestWorker` pattern verbatim: stores created
  on *its* thread, disposed in one `finally`, heavy imports inside `run`. Cancellation is a
  `threading.Event` polled **between** captures, so a capture is never interrupted half-way and the
  store never holds a partial session. Stamps `PIPELINE_VERSION` only when `summary.is_complete`.
- **`src/ui/main_window.py`** — the check fires via `QTimer.singleShot(0, …)` so the window is
  painted before any dialog appears (and after every store's constructor has migrated). Three-button
  offer: *Update now* / *Not now* / *Don't ask again* — the last stamps without rebuilding, the
  escape hatch for someone whose archives are gone, without which the prompt could never terminate.
  A modeless `QProgressDialog` reports "capture i of n" with the *"the app hasn't frozen"* line; the
  record/ingest buttons are disabled for the duration and the visible view is refreshed at the end.
  A `PipelineState.AHEAD` database (written by a *newer* build) is logged and left alone —
  re-ingesting there would downgrade the derived data.
- **`src/ui/help_page.py` → `reingest_requested`** — a "Re-read captures…" button, so *Not now* is
  not a wait-for-next-launch dead end. The page emits; `MainWindow` owns the worker (it also owns
  the record/ingest jobs this must not run alongside).
- **Tests:** `test/storage/test_meta.py` (stamp round-trip, replace-not-accumulate, corrupt value,
  the `LEGACY < PIPELINE_VERSION` invariant) and `test/ingest/test_reingest.py` (the gate's states,
  path resolution, rebuild accounting, missing archive, one-bad-archive, cancel, `recorded_by`
  survival, progress). Fixture-free: `reingest_all`'s `ingest` hook is injected, the same style as
  `check_for_update`'s `urlopen`.

### When to bump `PIPELINE_VERSION`

Bump the integer in `src/version.py` **in the same commit** as an ingest change that makes stored
rows stale — a new capture-derived column, a changed derivation, a new trace channel. Do *not* bump
it for UI-only work or for an additive column whose value doesn't come from the packets. The release
notes' "re-ingest needed?" line is then simply "yes" whenever the number moved.

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
- [ ] **Re-ingest (Phase 2)** — a **fresh** `%LOCALAPPDATA%\f1telemetry` shows **no** prompt on first
      launch, and `meta` holds the current `pipeline_version`.
- [ ] **Re-ingest** — a **pre-Phase-2 DB** offers the upgrade once; **Not now** leaves the app fully
      usable and the offer returns next launch.
- [ ] **Re-ingest** — **Update now** on a real weekend: the progress dialog counts captures, the app
      stays responsive (switch pages while it runs), and the result line reads "N of M".
- [ ] **Re-ingest** — after it completes, relaunching is silent, and seasons / round assignments /
      rosters are unchanged.
- [ ] **Re-ingest** — **Cancel** mid-pass recovers cleanly and the offer returns next launch; closing
      the window mid-pass doesn't hang shutdown.
- [ ] **Re-ingest** — a capture moved out of `captures/` is reported as missing, and the stamp is
      still written (the prompt must not recur forever).
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
- **Auto-reingest slow / archives missing.** *Handled in Phase 2:* the rebuild is optional,
  cancellable, idempotent/resumable and progress-barred, and the summary names how many sessions
  stayed stale because their archive is gone.
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
