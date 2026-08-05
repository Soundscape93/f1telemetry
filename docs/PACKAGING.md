# Packaging & Release

How the app becomes a double-clickable desktop build that league members can run **without
Python, pip, PySide6, or anything else installed**. This file is the authoritative packaging
reference; the ROADMAP has only a short pointer. Written so a future session can start **Phase 0**
without re-deriving the discussion.

**Status:** **Phases 0, 1, 2 and 3 done.** Phase 0 = dependency manifest, `paths.py`, file logging,
crash hook, `__version__` (see "Phase 0 — done"). Phase 1 = the PyInstaller one-folder Windows build
(`packaging/` spec + entry point) **plus a notify-only update check** (pulled forward from Phase 3),
built on the author's Windows 11 boot and verified against the clean-machine checklist on
2026-07-25 (see "Phase 1 — done"). Phase 2 = the `PIPELINE_VERSION` stamp in the database plus the
guided, cancellable re-ingest of the archived captures (see "Phase 2 — done") — verified on dev/Linux
2026-07-25 and re-verified on the 2nd Windows build 2026-07-26. Phase 3 = the label-driven release
pipeline (GitHub Actions → a full GitHub Release), the CI-generated `USER_GUIDE.pdf`, and the Help
page's guide + folder actions (see "Phase 3 — done"); its clean-machine items were **checked on the
published build and pass** (confirmed 2026-08-02). Dev runs are unchanged: source runs still resolve
every data path against the CWD. What remains of packaging is **Phase 4** — see
[`docs/PRIORITIES.md`](PRIORITIES.md), where it is Cycle 3.

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

## Data layout & the database

Both decisions below were re-examined in the Phase-2 wrap-up (2026-07-26) and **kept**. Recorded here
so they don't get re-opened: the reasoning is the point, not the conclusion.

### One data root, with actions that open it

`captures/` and `lap_traces/` stay under `data_root()` with everything else, even though
`%LOCALAPPDATA%` is hidden in Explorer by default. Moving the user-visible data elsewhere (Documents,
say) was considered and rejected:

- `data_root()` would stop being the single path authority — the whole reason `paths.py` exists.
- "Back up this folder" becomes two folders, and a tester will back up one of them.
- `F1TELEMETRY_DATA_DIR` would need a second override, or would silently relocate only half the data.
- **`%LOCALAPPDATA%` is excluded from OneDrive/Documents sync by default**, which is exactly right for
  multi-GB captures. `Documents\` would have OneDrive users silently uploading 1.5 GB per weekend —
  a worse support problem than a hidden folder.

The discoverability fix is **the app opening Explorer for the user**, not a different location
(Phase-3 item 2). If a user-chosen captures directory is ever wanted, the clean route is a setting in
`config.json` — `paths.config_path()` already reserves the file. Don't pre-build it.

### The database is not protected — it's rebuildable

Making `f1league.db` read-only for the user while the app can still write it **is not achievable**,
and attempting it would break the app:

- **Windows:** the file's owner implicitly holds `WRITE_DAC`/`WRITE_OWNER`, so a user who can't write
  the file can always rewrite its ACL and then write it. A restrictive ACL is a speed bump, not
  protection.
- **macOS/Linux:** `chmod 444` is undone with `chmod +w`; the owner can always change modes.
- Real enforcement needs a **different security principal** (a service account owning the file, with
  IPC) — a client/server architecture for a single-user desktop app.
- Decisive: **SQLite needs write access to the containing directory, not just the DB file** — it
  creates `-wal` / `-shm` / `-journal` siblings. A read-only DB file stops *the app* writing too.
  Flipping the bit per launch is a race and an extra corruption vector; it would produce more corrupt
  databases than it prevents.

So the DB is not defended, it's made **disposable**: captures are the source of truth, and a wrecked
database is one *Help → Re-read captures…* away from a good one (Phase 2 shipped exactly that).
The practical measures are therefore:

- keep it in `data_root()` and **don't surface it** — no "Open database" action anywhere in the UI;
- expose **captures** and **logs** instead, which is what a tester actually needs;
- **document** "don't hand-edit the database" in the user guide, together with the rebuild route;
- **DONE 2026-08-02 (PRIORITIES → C2/C3): WAL mode + a "Back up database…" action.** Shipped
  together, because `VACUUM INTO` is what makes WAL safe to hand around.
  **WAL** lives in `storage/engine.py`. The five stores are repositories over the same file and
  each builds its own engine (SQLite dislikes a connection shared across threads; the ingest
  workers have their own), so connection setup had to be a shared *function* — `create_db_engine`
  — rather than a shared engine: whichever store opens the database first must leave it configured
  as any other would. It sets `journal_mode=WAL` (a reader is no longer locked out by a running
  ingest — the double-launch concern, and what a minutes-long re-ingest needs),
  `synchronous=NORMAL` (WAL's usual companion; still crash-durable at the application level, and
  the residual power-cut risk is acceptable precisely because this database is disposable — see
  above) and `busy_timeout=10s`. `foreign_keys` is deliberately **not** set: SQLite defaults it
  off, the cascades here are ORM-level, and enabling it would interact with the intentionally
  FK-free `session_assignments`. That is an Alembic-era decision, not a WAL one.
  **The backup** is `storage/backup.py` → `backup_database()`, surfaced as Help → *Back up
  database…*. It is allowed to run *during* an ingest — a single read transaction that neither
  blocks the writer nor tears — which is the whole point of pairing it with WAL. Note it does not
  contradict the "no Open database action" rule above: it writes a **copy** to a path the user
  picked, and never exposes the live file. Implementation notes for anyone touching it: `VACUUM`
  cannot run inside a transaction (needs `AUTOCOMMIT`), `VACUUM INTO` refuses an existing
  destination (the caller unlinks, after the save dialog has asked), and the destination is a
  **bound parameter** so Windows backslashes and quoted filenames can't break the statement.

Tamper *detection* was considered and dropped: cost without benefit for a private league app.

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
- Implemented in Phase 3 as **`.github/workflows/release.yml`**: `preflight` (version + notes gate,
  then the test suite) → `guide-pdf` (Linux) + `windows-build` (PyInstaller) → `release`.
  Only `windows-latest` builds today; `macos-latest` / `macos-14` (arm) / `ubuntu-latest` are Phase 4.
- **Windows** folder → zip is the clean primary artifact. **macOS** builds are unsigned/unnotarized
  → Gatekeeper blocks (right-click→Open; no Apple account while free). **Linux** → a tarball first;
  AppImage later.
- **Any checkout CI makes must be in a folder named `f1telemetry`** (`actions/checkout` with
  `path: f1telemetry`): imports are absolute `f1telemetry.src.*` and the spec puts that folder's
  *parent* on `pathex`.

### Versioning & dev release process

- One `__version__` in the package. SemVer `MAJOR.MINOR.PATCH`. Keep **`PIPELINE_VERSION` separate**
  (bumped only when ingest output changes). `1.0.0` is reserved for "packaging finished / ready for
  users outside the league"; until then everything is `0.x.y`.
- **Label-driven release.** Write the entry under `## Unreleased` in `CHANGELOG.md` → label the
  **`staging` → `main` PR** `major` / `minor` / `patch` → merge. Labelling (not merging) is what
  starts it: `.github/workflows/bump.yml` bumps `src/version.py` + `pyproject.toml`, renames the
  Unreleased section to `## vX.Y.Z — <date>`, and commits that **to the PR's head branch**
  (`staging`). Merging the PR carries that commit into `main`, where
  `.github/workflows/tag.yml` tags it and calls `release.yml`. **A PR with none of those labels
  releases nothing** — that is the "no release" path, not a failure.
- **Grouping small changes: `staging` is the integration branch.** Small feature/fix branches are
  PR'd into **`staging`**, not `main`, so several of them can ride one release when that makes more
  sense than releasing each alone. When the group is ready, open **one PR from `staging` → `main`**
  and put the version label **on that PR only**. Consequences worth remembering: the small PRs into
  `staging` are unlabelled and therefore release nothing (the "no release" path above — and
  `bump.yml` ignores them anyway, since it runs only when the PR's base is `main`), and
  `CHANGELOG.md` under `## Unreleased` must accumulate an entry from **every** grouped change — the
  staging→main PR is what turns that whole section into one version, so anything missing from it is
  missing from the release notes. The label reflects the *group*: one `minor` feature among several
  `patch` fixes makes the release `minor`. A required `source-branch` check enforces the "only
  `staging` merges into `main`" half, because GitHub can restrict *who* merges but not *which
  branch* a PR comes from. Emergency fixes route through `staging` too.
- **Branch off `staging`, never off `main`.** A feature/fix branch based on `main` misses whatever
  is already on `staging` but unreleased, so it is developed against a stale base and its merge
  base is some older common ancestor rather than current `staging` — which shows unrelated changes
  in the PR diff and invites phantom conflicts. Branching off `staging` makes the merge base
  `staging` itself, so the PR diff is exactly the change. Keep branches short-lived and merge
  `staging` back in if it moves while you work.
- **Merge strategy: squash into `staging`, merge commit into `main`.** Feature/fix → `staging` is
  **squashed**, so `staging` carries one tidy commit per change. `staging` → `main` uses a **merge
  commit** (settled from v0.4.2), because a squash there discards the ancestry link: `main` then
  holds content identical to `staging` but with no shared history, the two branches diverge
  permanently, and reconciling them needs a `Merge branch 'main' into staging` back-merge. That
  back-merge is what pushed the `chore(release):` commit off the branch tip and broke the release
  guards during v0.4.2 (see the guard note below). A merge commit keeps the histories connected and
  makes the back-merges unnecessary.
- **CI never pushes a commit to `main`** — every change arrives through a PR, which is what the
  branch protection rule requires. This is why the bump lands on the PR branch rather than on
  `main`: the older workflow ran `git push origin HEAD:main`, which protection rejects
  (`GITHUB_TOKEN` is not exempt). Tags are *not* covered by branch protection, so `tag.yml`
  pushing `vX.Y.Z` is fine — just don't add a protected-tag rule for `v*` without exempting it.
- **CI verifies the version, it never stamps it** (`packaging/check_version.py`). The bump is a real
  commit that reaches `main` *before* the tag exists, so the tag points at source that already
  carries the version: the published artifact is exactly the tagged commit, and an editable install
  in a checkout reports the same version as the exe's Help page. A build-time stamp would break both.
- **`tag.yml` keys on the version file, not the commit subject.** Every push to `main` runs it; it
  reads `source_version()` and releases only when no `vX.Y.Z` tag exists yet, so ordinary merges are
  a silent no-op and it works whether the release PR is merged or squashed.
- **`tag.yml` calls `release.yml` directly** (a `workflow_call`), instead of relying on the tag push
  to trigger it: a tag pushed with the default `GITHUB_TOKEN` does **not** trigger `on: push: tags`
  workflows (GitHub's recursion guard). The `push: tags` trigger is kept anyway, because a tag *you*
  push by hand does trigger it.
- **Two guards exist because the bump runs mid-PR, and both are load-bearing.** (1) `bump.yml` skips
  when the branch tip is already a `chore(release):` commit — labels get removed and re-added, and a
  second bump would double the version. (2) `ci.yml`'s changelog gate skips for the same reason:
  after a bump the Unreleased section is deliberately empty again, so re-running `--check` on the
  push the bump itself triggered would fail the release PR. That gate must check out
  `pull_request.head.sha`, since the default `pull_request` checkout is the *merge* commit, whose
  subject is never `chore(release):`.
- Notes for friends must state **"re-ingest needed? yes/no"** and list known issues (the app is
  partial). This is enforced twice: `bump_version.py --check` on the PR (via `ci.yml`, only for
  labelled PRs) and `release_notes.py` in the release preflight.
- **Local checks** before merging: `python packaging/bump_version.py --check` (silence = the
  Unreleased section is release-ready) and `python packaging/check_version.py` (no argument — the two
  version files agree). The tag forms of both only make sense *after* a bump has happened, or if you
  are tagging by hand.
- **Release zip contents:** the one-folder build, plus **`USER_GUIDE.pdf`** (convert
  `docs/USER_GUIDE.md`), **`roster_template.csv`**, **`LICENSE`** and **`NOTICE.md`** at the top
  level. The last two are **not optional**: the bundle links Qt/PySide6 under **LGPL v3**, which
  requires the licence notice to reach whoever receives the binary, so the `windows-build` job
  copies them in and the bundle sanity-check fails without them. Publish a **full** GitHub
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
- **Phase 2 — migration / reingest: DONE (2026-07-25).** `PIPELINE_VERSION` stamped in a `meta`
  table + startup detect + a cancellable, progress-barred re-ingest from `captures`. Verified on dev
  and re-verified on the Windows 11 build (2nd build). See "Phase 2 — done" below.
- **Phase 3 — CI + release: DONE (2026-07-26).** Label-driven version bump → tag → GitHub Actions
  Windows build → a full GitHub Release, plus the CI-generated `USER_GUIDE.pdf` and the Help page's
  guide / folder actions. See "Phase 3 — done" below.
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
  `QMessageBox` pointing at the log. Installed after the `QApplication`. **Extended by C5
  (Cycle 3):** a second hook, `install_threading_excepthook`, because Python has two —
  `sys.excepthook` never fires for a plain `threading.Thread`, whose failures the interpreter
  routes to `threading.excepthook` and whose default prints to a stderr a windowed build does not
  have. Nothing uses a bare `Thread` today (every worker is a `QThread`, which `threading.excepthook`
  does *not* cover), so that half is a net for future work.
  **The load-bearing half is the thread rule:** the dialog is only ever built on the GUI thread.
  Every worker's `finally` sits outside its `except` (`IngestWorker`, `ReingestWorker`,
  `RelocateWorker`, `ImportWorker` all dispose stores there), so an exception from `store.close()`
  escapes `run()`, reaches `sys.excepthook` via PySide6, and used to construct a `QMessageBox` on
  the worker thread — undefined behaviour in Qt, and able to abort the process from inside the
  crash handler. `_report` now shows the dialog directly when it is already on the GUI thread (a
  start-up crash precedes `app.exec()`, so a queued call would never be delivered) and otherwise
  emits through a queued-connection `QObject` relay built on the GUI thread by
  `install_excepthook`. Only strings cross the boundary — never the exception, whose traceback
  would pin worker frames alive.
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

---

## Phase 3 — done

Landed 2026-07-26. The scope below was agreed in the Phase-2 wrap-up; "What landed" at the end of
the section lists the files, and the release process itself is documented under "Versioning & dev
release process" above.

**1. `USER_GUIDE.pdf` generation + a Help-page action that opens it.** The Help page deliberately
stays a short setup/troubleshooting card; the guide is the long form. The release zip already
specifies the PDF **at the top level**, beside the exe — keep it there (a tester who never opens the
app still finds it) and do *not* bundle it inside `_internal/` where `resource_path()` would hide it.

This needs a **third path kind**, distinct from both existing ones — worth stating plainly because
it's easy to reach for the wrong helper:

| Kind | Frozen resolves to | Helper |
|---|---|---|
| per-user writable | `%LOCALAPPDATA%\f1telemetry` | `data_root()` |
| bundled read-only | `sys._MEIPASS/f1telemetry/src/…` (= `_internal/…`) | `resource_path()` |
| **beside the exe** | `Path(sys.executable).parent` | **`app_dir()` — to add** |

In a one-folder PyInstaller 6 build these genuinely differ: `sys.executable` is
`dist/f1telemetry/f1telemetry.exe` while `_MEIPASS` is `dist/f1telemetry/_internal`.

Open it with a three-step fallback so the action can never dead-end:

1. `USER_GUIDE.pdf` beside the exe (packaged build);
2. else `docs/USER_GUIDE.md` in the source tree (dev runs — `QDesktopServices` hands it to whatever
   opens `.md`);
3. else the guide **on GitHub** (`…/blob/main/docs/USER_GUIDE.md`) — the `update_check`
   `GITHUB_OWNER`/`GITHUB_REPO` constants already exist, so this costs nothing and works even for
   someone who unzipped only the exe.

Belongs in Phase 3 rather than earlier **because the artifact doesn't exist yet**: the md→PDF step
(pandoc on `windows-latest`, or checked in) is a Phase-3 CI decision, and shipping the button first
would mean only fallback (3) ever runs.

**2. "Open folder" actions on the Help page.** `%LOCALAPPDATA%` is hidden by default, which is a real
discoverability problem for the capture-sharing workflow — but the fix is opening Explorer *for* the
user (`QDesktopServices.openUrl(QUrl.fromLocalFile(...))`), not moving the files. Add **Open data
folder**, **Open captures folder**, **Open logs folder**. The Help page already *displays* the data
root as selectable text, so this is the natural upgrade. No "Open database" action — see below.
Can land any time; needs no release artifact to verify.

**3. Nothing else moves.** See "Data layout & the database" for the two placement decisions that were
re-confirmed rather than changed.

### What landed

- **`src/paths.py` → `app_dir()`** (frozen: `Path(sys.executable).parent`; source: the repo root)
  and **`source_docs_dir()`**. The third path kind, per the table above.
- **`src/user_guide.py`** — Qt-free `resolve_guide()` returning a `GuideTarget` (a local path *or* a
  URL — the caller must know which, since only a path goes through `QUrl.fromLocalFile`). The three
  steps are injectable, so the chain is tested without a frozen build.
- **`src/ui/help_page.py`** — "Open user guide" and **"Licences & notices"**, plus a row of
  **Open data / captures / logs folder** buttons (`_FOLDER_ACTIONS` → `QDesktopServices.openUrl`)
  and an **About** block carrying the unofficial-tool / trademark / data-responsibility summary
  (`_ABOUT_HTML`; the full text is `NOTICE.md`). `QDesktopServices` reports failure only
  by returning `False`, so `_open()` surfaces that in a dialog — a windowed build has no console.
  Still no "Open database" action, deliberately.
- **`packaging/check_version.py`** — the verify-don't-stamp gate (tag ↔ `src/version.py` ↔
  `pyproject.toml`). **`packaging/bump_version.py`** — the bump arithmetic + the `## Unreleased`
  rewrite, and `--check`, the PR gate. **`packaging/release_notes.py`** — extracts a tag's section
  as the Release body.
- **`.github/workflows/`** — `release.yml` (preflight → guide-pdf + windows-build → release),
  `bump.yml` (label on the release PR → bump committed to that PR's branch), `tag.yml` (merge to
  `main` → tag → call release), `ci.yml` (suite + version agreement on every PR, the changelog gate
  on labelled PRs, and the source-branch gate that keeps `main` reachable only from `staging`). All
  Python steps pin **3.14**, matching the boot the verified Windows builds were made on.
- **`CHANGELOG.md`** — Keep-a-Changelog shape; `## Unreleased` is where entries accumulate.
- **Tests:** `test/test_user_guide.py` (the fallback chain), `test/test_bump_version.py` (bump
  arithmetic, the changelog rewrite, and that the instruction comment never counts as release notes),
  plus `AppDirTest` in `test/test_paths.py`.
- **Unchanged on purpose:** `packaging/f1telemetry.spec`. The PDF ships *beside* the exe, so it must
  not become a `datas` entry — that would bury it in `_internal/` where `resource_path()` hides it.

The PDF is built on **`ubuntu-latest` with `--pdf-engine=xelatex` + DejaVu**, not on the Windows
runner: pandoc alone cannot emit a PDF, a TeX install on Windows is slow and fragile, and the guide
contains `→` / `—` / `…`, which the default Latin Modern font silently drops.

**The apt set is load-bearing, and `--no-install-recommends` is a trap here.** Two of the packages
pandoc's default LaTeX template needs are only *Recommends* of `texlive-xetex`, so they are silently
skipped — and each one fails the build with an error that names a font, not a package:

| Missing | Error | Comes from |
|---|---|---|
| `pzdr.tfm` (ZapfDingbats, used by `hyperref`'s xetex driver) | `Font \XeTeXLink@font=pzdr … not loadable` | `texlive-fonts-recommended` |
| `lmodern.sty` | `LaTeX Error: File 'lmodern.sty' not found` | `lmodern` |

`fontspec` / `unicode-math` need no extra line — they are hard dependencies
(`texlive-xetex` → `texlive-latex-extra` → `texlive-latex-recommended`). The full set is therefore
**`pandoc texlive-xetex texlive-fonts-recommended lmodern fonts-dejavu`**, and `ci.yml` builds the
PDF on every PR so a gap can never take a release down again.

**If a release job does fail after the tag was pushed** (`tag.yml` tags before `release.yml` runs),
don't delete the tag and don't bump again: fix the workflow on `main` with an **unlabelled** PR, then
**Actions → release → Run workflow** with **tag = the existing tag**. The dispatch uses the *fixed*
workflow file from `main` but checks out the *tagged* source, so the artifact is still exactly the
tagged commit.

---

## Clean-machine test checklist (Windows 11)

Run on the author's Windows 11 boot; ideally on a clean Windows instance (see below).

- [ ] Launch by **double-click** from a folder that is *not* the repo (proves CWD independence).
- [ ] Launch as a **non-admin** user; nothing tries to write beside the exe.
- [ ] Launched on a **clean Windows instance** — see "Testing on a clean instance" below. (The old
      wording was "a machine with no Python installed", which is only a *proxy* for the properties
      that actually matter: no missing VC++ runtime, the Qt platform plugin resolving, no dev-only
      PATH/env leakage, and a fresh `%LOCALAPPDATA%`.)
- [ ] Qt starts — **no "could not load the Qt platform plugin"** error.
- [ ] HiDPI/scaling correct on the laptop panel (fonts/layout).
- [ ] **Recording:** UDP socket binds → **Windows Firewall prompt appears → Allow** (document it);
      a `.f1cap` lands in `captures/` under `%LOCALAPPDATA%\f1telemetry`.
- [ ] **Recorder scheduling:** after a recording of 15+ min with the laptop **untouched**, `logs/`
      shows `stay-awake active for this recording` and **no `recorder stalled` lines**, and the
      machine never slept. A capture can land and still be missing minutes of data — those log
      lines are the only direct signal. If stalls still appear, note their intervals: ~5 minutes
      apart points at the system idle timer (see ROADMAP → *Windows recorder stalls*). The same log
      records the granted receive-buffer size at every record press.
- [ ] **Stay-awake released:** after **Stop**, `logs/` shows `stay-awake released` and the machine
      returns to its normal sleep/lock behaviour — the request must not outlive the recording.
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
- [x] Open the app **twice** → SQLite doesn't wedge. **Re-tested under WAL, 2026-08-05 — passes.**
      The first run (2026-08-02, Record pressed, no game running) predated C2, so its result only
      meant "the contention never happened", not "WAL handled it". This run is against
      `storage/engine.py`'s WAL + `busy_timeout`, so the mechanism is actually exercised.
- [ ] Help → **Back up database…** writes a `.db` beside where the user chose, the status line
      reports its size, and the copy opens as a working database. Worth doing **while a re-ingest
      runs** — that is the case C2/C3 exist for.
- [ ] **Logs** written to `logs/` and human-readable; an induced exception shows the crash dialog.
- [ ] Note SmartScreen behavior and the exact click-through for the tester doc.

Phase-3 items (first *published* build — these need the Release, not just a local build):

- [ ] Installed from the **Release zip downloaded from GitHub**, not a local `dist/` folder.
- [ ] `USER_GUIDE.pdf`, `roster_template.csv`, `LICENSE` and `NOTICE.md` are visible **beside the
      exe**, not in `_internal/`.
- [ ] Help → **Open user guide** opens the bundled PDF (proves `app_dir()`, not `_MEIPASS`).
- [ ] Help → **Licences & notices** opens the bundled `NOTICE.md` (the LGPL notice for the bundled
      Qt has to reach the user — the GitHub fallback means a failure here is silent otherwise).
- [ ] Help → **Open data folder** / **captures** / **logs** each open Explorer at the right folder.
- [ ] Help → **Check for updates** against the real published Release says "up to date" (this path
      has never run against an existing Release — until now the API answered 404).
- [ ] The Release page shows the changelog section as its body, including the re-ingest line.

### Testing on a clean instance

**Do not uninstall Python from the dev boot.** It costs the dev environment and still isn't clean:
`%LOCALAPPDATA%\Programs\Python`, `%APPDATA%\Python`, pip caches and PATH entries survive, and the
VC++ redistributable (which the bundle genuinely depends on) stays regardless. Options, cheapest
first:

1. **Windows Sandbox** — the right tool: a disposable clean Windows instance that boots in seconds,
   maps a host folder, and resets on close. No ISO, no licence, no upkeep. **Windows 11 Pro /
   Enterprise / Education only** (Settings → Optional Features → *Windows Sandbox*; needs
   virtualization enabled in BIOS) — **not available on Windows Home**.
2. **A second local Windows user account** — two minutes, no virtualization, and the fallback when the
   boot is Home. Catches per-user PATH leakage, a fresh `%LOCALAPPDATA%`, the firewall prompt as a
   non-admin, and a **per-user Python install** (the installer's default). Misses machine-wide
   installs and the system VC redist. Delete the account after a successful build test.
3. **The first external tester** — a league member's PC *is* a clean machine. Make sure they know to
   send `logs/` if it won't start; this is the real sign-off.

### Build history

- **1st build (2026-07-25, Phase 1).** Full checklist passed on the author's Windows 11 boot. Found
  and fixed three frozen-only bugs (see "Phase 1 — done").
- **2nd build (2026-07-26, Phase 2).** Rebuilt and re-run through the whole checklist including all
  six Phase-2 re-ingest items — all pass. Three items **deliberately skipped**, not missed:
  - *clean instance / no Python* — the dev boot has Python + every requirement installed; deferred to
    a second user account (likely Windows Home) or Sandbox, per above;
  - *old-DB additive-column migration* — **N/A this phase**: Phase 2 added a new *table* (`meta`),
    no new columns on existing tables, so there was nothing for `ensure_schema` to ALTER;
  - *SmartScreen behaviour / user-doc click-through* — belongs with the published artifact in
    Phase 3's release workflow.
- **3rd build (Phase 3) — done, confirmed 2026-08-02.** The first build produced *by CI* and
  published as a Release (v0.3.0, then v0.4.x). The Phase-3 checklist items above were run against
  the downloaded zip and pass, including the two that had never executed before: *Check for updates*
  against a real published Release (the API used to answer 404) and *Open user guide* resolving
  through `app_dir()` rather than `_MEIPASS`. The author intends to re-run this checklist for most
  future releases.
- **Still not covered by any build so far:** the **clean-instance** run (Windows Sandbox or a second
  user account — see below) and the **SmartScreen click-through wording** for a first-time external
  tester. Both are PRIORITIES → C4.

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
   users can back up / send the DB when reporting a bug. It's **hidden in Explorer by default**, so
   documenting the path isn't enough on its own: the app should open the folder for the user
   (Phase-3 item 2). Never expose the database itself — see "Data layout & the database".
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
- **Where your data lives** (`%LOCALAPPDATA%\f1telemetry`) and how to back it up — plus the in-app
  actions that open it, since the folder is hidden by default.
- **Reporting a bug:** attach the log from `logs/` + note the version; the known-issues list. And
  **don't hand-edit the database** — if it's misbehaving, re-read the captures instead.
- **Upgrade note:** whether a new build needs a re-ingest, and that it may take a few minutes.

---

## OS notes

- **Windows (first):** primary target. Unsigned; SmartScreen documented. `%LOCALAPPDATA%` data
  root. Firewall prompt on record. Inno Setup installer is a later nicety.
- **macOS (later):** unsigned/unnotarized while free → Gatekeeper right-click→Open. Universal/arm
  build via `macos-14` runner. `~/Library/Application Support` data root.
- **Linux (later):** tarball or one-folder first; AppImage later. `~/.local/share` data root. xcb
  platform plugin must be present.
