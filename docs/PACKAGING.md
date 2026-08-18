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
  partial). Two gates enforce this, and they do **not** check the same things:
  - **`bump_version.py --check`** on the PR (via `ci.yml`, only for labelled PRs) reads the
    **Unreleased** section and requires *both* the re-ingest answer and a `**Known issues**` list
    ("None" is a valid answer). This is the cheap failure — it fires while the author is still
    writing the change.
  - **`release_notes.py`** in the release preflight reads the **released** section and requires the
    re-ingest answer. This one fires *after* `tag.yml` has pushed the tag, so it is the expensive
    failure and the reason the first gate has to work.

  **Corrected 2026-08-07 (PRIORITIES → F8): the first gate did not work.** From Phase 3 until
  v0.7.0, `check()` stripped the instruction comment before testing whether the section was *empty*
  but not before testing for the re-ingest answer — and the comment quotes that very phrase, so the
  test was unconditionally satisfied. The claim "enforced twice" was false: it was enforced once, at
  the worst moment. Both tests now read the comment-stripped body. **If you add a check here, test
  it against `content`, never `body`** — and write its regression test with the real `PLACEHOLDER`,
  not a stub comment, which is why the suite missed this for four releases.
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
  auto-updater (velopack). **Scoped down and scheduled as PRIORITIES → C8a / C8b / C8c**: Linux
  only (macOS dropped), the installer in, velopack deferred. **C8a done 2026-08-07 and C8b done
  2026-08-08 — only C8c remains, and it is deferred out of the cycle**, so Phase 4 is complete as
  scoped.

### The Linux artifact (C8a)

A `linux-build` job in `release.yml` mirroring `windows-build` on `ubuntu-latest`, publishing
`f1telemetry-<tag>-linux-x64.tar.gz` with the same four files beside the binary and the same
sanity-check (`LICENSE` + `NOTICE.md` are an LGPL v3 obligation, so a missing one fails the build).

- **A tarball, not an AppImage** — "a tarball first" was already the plan; AppImage needs
  `linuxdeploy` plus a Qt plugin and is its own debugging surface.
- **`.tar.gz`, not zip** — zip does not preserve the executable bit, so the binary would need a
  `chmod +x` before it would run at all.
- **Known limit, not a defect:** a PyInstaller bundle links against the **glibc of the machine that
  built it**, so this artifact needs a distro at least as new as the runner's Ubuntu. Building for
  older distros means building in an older container, which is not worth it for a best-effort
  artifact.
- **The tag is sanitised into the archive name.** On a no-tag `workflow_dispatch` the tag defaults
  to the branch name, and a slashed branch (`ci/linux-release-artifact`) would be read as a
  directory in the output path. Latent in `windows-build` since Phase 3, reachable only by dispatch.

**The trap this job walked into first, worth not re-learning.** The initial run died in *collection*,
before any bundling: `collect_submodules("pyqtgraph")` **imports** each package to enumerate it, and
`pyqtgraph.examples` builds Qt objects at import time — so PyInstaller's isolated subprocess reached
for the `xcb` platform plugin, found no display, and **aborted (SIGABRT, exit -6)**. C7's exclusion
was a filter applied to the *result*, so the import had already happened. `on_error` cannot help:
it handles exceptions, not a child process that died.

The fix is `collect_submodules("pyqtgraph", filter=…)` — a package the filter rejects is never
recursed into, so it is never imported. **If you ever exclude a submodule from a `collect_*` call,
filter during collection, not afterwards.** The build step also sets `QT_QPA_PLATFORM=offscreen`, as
`ci.yml` does for the suite, to cover the next submodule that decides to touch Qt at import time.
Windows never hit any of this: its platform plugin initialises without a display server, which is
why a Linux artifact was the first thing to find it.

### The notices PDF (F9) — done 2026-08-08

Raised by the 4th build: `NOTICE.md` shipped as raw markdown, so a tester without a markdown viewer
opened it in Notepad and read `#` and `**`. The LGPL v3 notice for the bundled Qt is the one
document that genuinely has to arrive readable, so this is a compliance fix, not polish.

**A second pandoc invocation inside the existing `guide-pdf` job**, deliberately not a new job: the
apt install there is load-bearing (see its comment) and already paid for. Same font and geometry
set as the guide, so the two documents look like they belong together; **no `--toc`**, because a
contents page for two pages is noise. Both PDFs travel in **one upload artifact**, so each build
job's existing download step picks up the pair without a second download — and the artifact keeps
its Phase-3 name (`user-guide-pdf`), since renaming it would touch four places for tidiness alone.

- **`NOTICE.pdf` ships beside `NOTICE.md`, not instead of it.** The markdown is what
  `resolve_notices` falls back to in a source run, and what the GitHub fallback points at.
- **Both build jobs' sanity-check lists gain it** — LGPL-relevant, so a missing one fails the build
  rather than shipping quietly, exactly like `LICENSE` and `NOTICE.md`.
- **Also published as a standalone Release asset**, so the terms are reachable without a ~250 MB
  download. It rides in the `user-guide-pdf` artifact, so the `release` job's path for it is
  `artifacts/user-guide-pdf/NOTICE.pdf` — *not* `artifacts/notice-pdf/`. That job's
  `download-artifact` has no `name:`, so it lands everything under `artifacts/<artifact-name>/`,
  and a wrong path here fails **after `tag.yml` has already pushed the tag**. The `release` job is
  also skipped on a no-tag `workflow_dispatch`, so a dispatch test run cannot catch it.

**The open question is answered: *Licences & notices* prefers the PDF.** `resolve_notices` grew a
third step and is now the same shape as `resolve_guide` — **presence decides at every step, never
`is_frozen()`**, which is what makes one rule correct in both worlds:

| Build | `app_dir()` is | `NOTICE.pdf` there? | Opens |
|---|---|---|---|
| installed / release archive | beside the exe | yes, CI put it there | **the PDF** |
| source / dev run | the repo root | no — CI-built and gitignored | **the `.md`**, unchanged |
| partial extract, exe only | beside the exe | no | the GitHub URL |

The dev path is preserved by a *fact* rather than a special case: `NOTICE.pdf` is a build artifact
that never lands in the repo (`/NOTICE.pdf` joined `/USER_GUIDE.pdf` in `.gitignore`). Shipping a
PDF and then having the app's own button still open raw markdown would have defeated the item.

**Two things deliberately not done.** **`LICENSE` is left as plain text** — it contains no markdown
syntax at all, so it does not have the problem F9 exists to fix, and running its hanging-indented
sub-clauses through pandoc *as markdown* would reflow and damage them. And the notices are **not
folded into `USER_GUIDE.pdf`**: *Licences & notices* would have no deep-link target, a distinctly
named standalone file is the defensible way to deliver an LGPL notice, and G3 (the German guide)
would otherwise inherit an English legal appendix.

**Known cosmetic limit, recorded so it is not filed as a bug:** `NOTICE.md`'s relative link to
`src/ui/assets/flags/ATTRIBUTION.md` does not resolve from the bundle — that path exists only under
`_internal/f1telemetry/`. Pre-existing in the shipped `.md`; the PDF inherits it. The
`[LICENSE](LICENSE)` link *does* resolve, since `LICENSE` sits beside both files.

### The installer is an admin install — decided 2026-08-07 (C8b)

The Windows Firewall allow-rule needs administrator rights, and the clean-machine checklist asserts
"launch as a **non-admin** user". Those pull in opposite directions, so the tension was resolved
explicitly rather than discovered during implementation. Three options were weighed:

| | Firewall rule | Non-admin install | Verdict |
|---|---|---|---|
| (a) per-user install, no rule | ✗ | ✓ | drops the item's main justification |
| **(b) admin install with the rule** | **✓** | **✗** | **chosen** |
| (c) per-user install + optional elevated task | ✓ | ✓ | most moving parts |

**(b) chosen.** Nearly every ordinary Windows install prompts for elevation anyway; on Windows 11 an
admin account is elevated by UAC for the install and drops straight back afterwards, and a standard
account gets the UAC credential screen. For this tester group that is normal, expected behaviour.

**(c) was rejected deliberately, not overlooked.** Inno can elevate a single task, so it would give
both properties — but it is the most complex of the three, and the failure mode lands on a tester
machine that cannot easily be debugged remotely. Simplicity wins where support access is the
scarce resource.

**The invariant that must survive this:** *the app itself still requires no administrator rights at
runtime.* Elevation is for the installer only — writing the firewall rule and the Start-menu entry.
Everything the running app writes stays under `%LOCALAPPDATA%` (`data_root()`), and nothing is ever
written beside the exe. **The checklist item changes meaning rather than disappearing:** it becomes
"install as admin, then *run* as a standard user and confirm nothing needs elevation". If a build
ever needs admin to run, that is a bug, not a consequence of this decision.

The admin requirement must be **documented** — in the user guide's install section, in the release
notes for the first build that ships an installer, and on the Release page itself.

#### C8b scope — all settled, built 2026-08-08

The script is [`packaging/installer/f1telemetry.iss`](../packaging/installer/f1telemetry.iss); it
is compiled by `release.yml`'s `windows-build` job and published as
`f1telemetry-<tag>-windows-x64-setup.exe`.

**Settled before the work started:**
- **Inno Setup**, per the original Phase 4 plan. Not Briefcase/MSI — that was weighed and deferred
  in the locked decisions above.
- **Admin (per-machine) install**, so the firewall rule can be written. See the table above.
- **The zip keeps shipping.** The installer is an *addition* to the release assets, not a
  replacement: the zip is the artifact three builds have been verified against, it is what a tester
  who cannot elevate falls back to, and the Linux tarball has no installer at all. Dropping it would
  strand both.
- **The runtime invariant:** the installed app needs no admin. `data_root()` stays
  `%LOCALAPPDATA%`; nothing is ever written beside the exe.
- **A Start-menu entry and an uninstaller** — the two things an installer is actually for beyond the
  firewall rule.

**The five open questions, answered 2026-08-08:**

- **Uninstall removes the program files and the firewall rule; it never touches the data root, and
  there is deliberately no opt-in checkbox either.** The earlier note allowed "removal offered as
  an explicit opt-in checkbox at most" — that was dropped for a reason specific to option (b), and
  it is the decisive one: **an admin uninstall runs under the *administrator's* token, while
  `data_root()` is per-user.** On exactly the machine this design targets — installed as admin, run
  by a standard user — the uninstaller would resolve the *admin's* `%LOCALAPPDATA%`, find nothing,
  delete nothing, and report success. That is not a risky feature but a broken one, and a checkbox
  that lies is worse than no checkbox. Users remove it by hand; *Help → Open data folder* puts them
  in the right place. The original argument still holds too: `captures/` is the source of truth and
  can be gigabytes, and only the database is the disposable half.
- **`netsh`, not the Firewall COM API.** Legible, and it leaves a line in the install log that can
  be read out over a chat window on a machine that cannot be debugged remotely. **Keyed by rule name
  and deleted before it is added**, so a reinstall or an upgrade replaces the rule instead of
  stacking duplicates. The delete exits nonzero on a first install, when nothing matches; that is
  fine, because Inno does not fail a `[Run]` entry on a nonzero exit code.
- **Install directory `{autopf}\F1 Telemetry`**, which `PrivilegesRequired=admin` resolves to
  `C:\Program Files`. The "nothing assumes a writable install dir" check was **done, not assumed**:
  `paths.app_dir()` is read-only at all four call sites (both `user_guide` resolvers), and frozen
  `data_root()` is `%LOCALAPPDATA%\f1telemetry`.
- **Upgrade-in-place works via `CloseApplications=yes`** — Restart Manager finds the running
  one-folder app and offers to close it, which is the file-lock problem that deferred velopack.
  **Plus an `[InstallDelete]` wipe of `{app}\_internal`**, which is the half that is easy to miss:
  Inno replaces only the files it is installing, so anything *dropped* by a later build would linger
  there forever, and a stale Qt plugin or DLL is precisely the shape of an unreproducible bug.
- **CI builds it, inside `windows-build`, after that job's bundle sanity-check.** The alternative —
  building the first one or two by hand — was rejected because it breaks two invariants stated
  outright above: *"the published artifact is exactly the tagged commit"* and *"CI verifies the
  version, it never stamps it"*. A hand-built installer comes from an unverified working tree. The
  objection it was meant to answer (the installer can now fail a release) is already covered by the
  **no-tag `workflow_dispatch` path**, which builds every artifact without publishing — the same
  escape hatch that de-risked C8a and F9. Ordering it after the sanity-check means the installer can
  only ever package a bundle already proven to carry the guide, notices, licence and template.

**A seventh, found by the clean-machine run: the uninstaller refuses to run while the app is open.**
Uninstalling with F1 Telemetry running deleted the documents beside the exe but left
`f1telemetry.exe` and `_internal` behind — Windows will not remove a running executable or its
loaded DLLs — producing a **half-removed install**, which is worse than either outcome on its own.
`CloseApplications=yes` covers *Setup* but does not save the *uninstaller*, which is itself holding
`{app}`. Fixed rather than documented around, with an `InitializeUninstall` guard offering
Retry/Cancel. **That hook is the whole point: returning `False` aborts before anything is removed**,
so a refusal leaves the installation exactly as it was. Detection is `tasklist` piped through
`find` — legible, no mutex needed in the app, no DLL import, and `find`'s exit code *is* the answer.
The uninstaller runs elevated, which matters: it therefore also sees an instance left open by a
**different user**, which is exactly the case a per-machine admin install makes likely. A failure of
`Exec` itself deliberately reports "not running", because a broken detector must never become a
program that cannot be uninstalled.

**A sixth decision the scope had not listed: the firewall profile.** `profile=private,domain`,
**not public.** This is a home-LAN listener whose parser reads untrusted datagrams, and it mirrors
what the Windows prompt itself ticks by default. **The consequence is a silent failure and must stay
documented:** if Windows has the home network classified as *Public*, the rule does not apply, no
packets arrive, and there is no error. It is in `USER_GUIDE.md` §2, the Help → Setup panel and the
release notes.

**And one deliberate omission.** There is **no "launch the app now" checkbox**, which an installer
would normally offer. The installer runs elevated, so a post-install launch would hand the app an
**admin token** — creating the data root in the wrong user profile on exactly the standard-user
machine this design targets, and disproving the runtime invariant on its very first run. The
Start-menu entry is the way in.

**The installed app not recording, and why the installer now asks for a restart.** The
clean-machine run showed the installed build receiving no telemetry while the **byte-identical**
binary from the release zip recorded fine on the same machine, network and port. This took several
days and produced two wrong conclusions before the right remedy; the wrong turns are recorded
below because they are the more useful half.

**The remedy: Windows must restart before the installer-created firewall rule is effective.**
Measured repeatedly — install, press Record immediately, no telemetry arrives *while `pktmon`
confirms the packets are reaching the NIC*; restart, press Record, works, same game session. The
failing window spanned several minutes, so this is **not** propagation latency that waiting would
clear, and the app process in the failing run was launched *after* the rule existed, so it is
**not** per-process staleness either. Hence `AlwaysRestart=yes` and a custom `FinishedRestartLabel`
saying why — the failure is silent, so an unexplained reboot would be declined and the user would
land in exactly the state it prevents.

**The mechanism is unnamed — corrected 2026-08-15, and this is the third theory to be withdrawn.**
This paragraph used to assert "most likely a stale path→rule association cached by the firewall
service after the exe at that path is replaced". **That is disproven:** clean *first* installs fail
too, where no previous exe ever existed at that path. **We ship the remedy, not a theory.** What is
measured is narrow and worth stating exactly:

- **The drop is in WFP, not in this app.** Firewall OFF → the installed build records. Firewall ON
  with the correct allow rules → silent. The app binds correctly (`Get-NetUDPEndpoint` shows
  `0.0.0.0:20777` owned by `f1telemetry.exe` during the failing window) and the packets reach the
  NIC (`pktmon`).
- **A reboot is the only remedy that has ever worked**, reproducibly, across separate user accounts
  and devices.

**Falsified, listed so nobody re-derives them:**

| Theory | How it died |
|---|---|
| stale path→rule association after the exe is replaced | clean first installs fail, with no previous exe at that path |
| a firewall *policy change* is what refreshes it | in the failing window, disabling and re-enabling this very rule did **not** fix it, and an unrelated policy touch (create + delete a dummy rule) did **not** either |
| the rule is written only to the registry, not the live service | `Get-NetFirewallRule` reads the running service and shows it present and `Enabled` straight after install |
| `ActiveStore` vs `PersistentStore` drift | both stores identical (Allow, Enabled, Dir=In, Protocol=17, program-scoped) |
| a Block rule outranks the allow | no Block rules for the binary in either store |
| a stale process holding the port | one bound socket, owned by the running app |
| a UDP port exclusion conflict | the reserved range is 50000–50059 |
| rule shape (`localport` etc.) | never isolated — see the three-shapes table below. Not implicated |

**`MpsSvc` cannot be restarted at all** — measured 2026-08-15, and stronger than the "frequently
refuses to stop" this paragraph used to say. `sc.exe sdshow mpssvc` shows the `BA` ACE carrying no
`WP` (stop) right, so **nothing stops the Windows Firewall service, even elevated**. A reboot is the
only way to cycle it, which is a cleaner account of "only a reboot works" than any theory about rule
caching — but it is an observation about the service, not a mechanism for the drop. Other rejected
alternatives: `netsh advfirewall reset` (wipes every rule on the system); `gpupdate` (irrelevant —
this is a local rule, not Group Policy).

**One diagnostic came back inconclusive and was not retried:** a WFP `netevents` capture returned an
empty XML (74 bytes, 0 `CLASSIFY_DROP`), which cannot distinguish "no drops" from "collection
captured nothing" — `netevents` needs its keyword/category setting configured separately.
`pfirewall.log` with `LogBlocked=True` has not been read.

**The bisection that opened it up.** Disabling the Private profile
(`Set-NetFirewallProfile -Profile Private -Enabled False`) made the installed app record
immediately; re-enabling it stopped delivery. One command, after two days of reading rule output.
**Reach for that first next time** — it separates "the firewall is involved" from everything else
in seconds.

**Three rule shapes, and the confound that invalidated the conclusion drawn from them.** Edited
live with `netsh` rather than rebuilt:

| Rule | Result |
|---|---|
| `program` + UDP + `localport=20777` | failed |
| `program` + UDP, no port | worked ← shipped |
| UDP + `localport=20777`, no program | worked ← rejected anyway: any binary could then receive |

These are **observations, not a causal finding.** *Every one of those "worked" results immediately
followed a firewall policy change* — which appears to be what actually refreshed the rule. A clean
install carrying the port-less rule still failed until Windows was restarted. **Rule shape was
never isolated.** The port-less form is kept because it matches what Windows itself writes from the
first-record prompt, not because it was proven to fix anything.

**Genuinely eliminated, and by measurement rather than argument.** The firewall-off run recorded
successfully from the installed exe in Program Files, and a later run had the installed app and the
release zip **recording the same broadcast simultaneously**, producing two capture files within
seconds of each other. Between them those two results close: the **Program Files path**, the
**space in the folder name**, **Start-menu launch context**, **working directory**, **standard-user
context**, the packaged **`_internal`** path, any **zip-vs-installed binary difference**, **stale
firewall rules**, and **MultiViewer or another duplicate listener**. Do not re-test these.

**Four wrong turns, which are the real lesson.** **`pktmon` cannot fix a firewall** — it is an ETW
observer with no path to WFP policy, so an early "it started working when I ran pktmon" was pure
correlation, and chasing it cost a day. **`Domain,Private` is a superset of `Private`, not a
mismatch** — profiles are the set a rule applies to, so narrowing it fixes nothing and would only
break a domain-joined machine later. **One successful observation is not a fix** — a single clean
run was accepted as proof the problem was test state, written up as closed, and the failure
returned on the next build; the same mistake was then made again with the rule shape. And **test
without a control and you measure nothing**: several failures were recorded without confirming the
game was sending at that moment. **Run the release zip alongside** — it binds the same port and
receives the same broadcast, so "the game wasn't sending" can never explain a result again.

Because of that history, the clean-machine checklist requires the install → restart → record path
to pass **twice from scratch**, not once.

**Accepted 2026-08-09 on exactly that basis, and C8b closed.** Two full clean passes, identical both
times: before restarting, the installed app received nothing **while the release zip recorded from
the same broadcast as a control**; closing and reopening the installed app did not help; after
restarting, it recorded immediately and a `.f1cap` appeared. The control is what makes the result
trustworthy — it makes "the game wasn't sending" unavailable as an explanation, which is precisely
how the three earlier false conclusions were reached.

**The restart is also required after an in-place upgrade, not only after a fresh install.** Tested
2026-08-09: install v0.8.0 → restart → records; run the *same* installer over the top → **records
no longer** until Windows is restarted again. So the requirement attaches to *running the
installer*, in any form. The user guide, the release notes and Setup's own restart page all say so.

**The accepted final invariant for C8b:** a standard user can launch the installed app with **no UAC
and no firewall prompt**, and **after restarting Windows** recording works, writing captures to that
user's `%LOCALAPPDATA%\f1telemetry`. The reboot is a documented requirement, not a defect to keep
chasing.

**What is still not known, stated plainly so nobody re-derives a false answer.** This section used
to name two candidate triggers that "were never separated, because every test changed both at once":
(a) the **exe at the rule's path being replaced**, and (b) the **rule being deleted and re-added**.
**Both are now dead as framed — corrected 2026-08-15:**

- **(a) is falsified.** Clean *first* installs fail, where no previous exe existed at the rule's
  path. Exe replacement cannot be the trigger, because the failure happens without it.
- **(b) survives only as a possible trigger, never as a remedy.** Re-adding the rule *late* does not
  help: in the failing window, disabling and re-enabling the app's own rule changed nothing, and an
  unrelated policy touch changed nothing. Whatever (b) sets, a second policy write does not clear it.

The `localport` predicate is **not** the cause — that claim was made, was wrong, and is retracted;
`LocalPort: Any` is kept only because it matches what Windows itself writes from the first-record
prompt.

**The one variant still un-run**, and it is now *opportunistic rather than a prerequisite*: an exact
`netsh advfirewall firewall delete rule name="F1 Telemetry (UDP 20777)"` followed by the installer's
own `add rule` line, then record without rebooting. It differs from what was tested — disable/enable
reuses the same rule object, delete/add creates a new one — but given that disable/enable *and* a
dummy-rule policy touch both failed, the odds are low. **It no longer gates C8d**, because C8d was
deferred on other grounds (see below) and because (a)'s death already answers the question it was
posed to settle: the reboot attaches to the installer-created rule itself, not to updating.

**Experiment #6 — "run a real v0.7.0 → v0.8.0 upgrade" — is not runnable, and should not be
re-scheduled.** v0.8.0 is the **first** release that shipped an installer, so there is no earlier
installer-based release to upgrade from. The nearest available equivalent — running the same
installer over an existing install — was measured on 2026-08-09 and fails, which is what the
in-place-upgrade paragraph above records.

**A7 was folded into C8b rather than deferred, and the reason is worth keeping.** A restart
*request* can be declined, and the failure that follows is silent — which reproduces the exact
false bug report C8b exists to prevent, so the feature would have shipped with a hole in its own
justification. `MainWindow` now replaces `Recording - waiting for telemetry ...` after
`_NO_TELEMETRY_HINT_MS` of zero datagrams with a line naming the restart case and the Public-network
case. **No first-run detection**, which is what kept it small: the trigger is zero packets, and the
advice is correct whenever it fires.

Scoping it surfaced something worth knowing: `Recorder.record` calls `on_status` **inside** its
`for data in self.source` loop, so a socket receiving nothing produces **no UI updates at all** —
the label sat on "waiting" forever. Hence a `QTimer` in the UI rather than a change to the Qt-free
recorder. It also **narrows a standing preference** that setup guidance belongs in docs rather than
status text: justified here because this cause reaches a user who is already past the docs.

**A6 stays open** — the app still says nothing between `listening on…` and a finished capture. In
fairness it would not have shortened this hunt: the GUI already showed a zero packet count. The
firewall bisection and the simultaneous-recording control are what did the work.

**Guarded by `test/test_installer_script.py`.** An `.iss` cannot be unit-tested meaningfully, but
the rule hard-codes a port and an exe name that Python owns, and the failure when they drift is the
worst kind — a rule that opens the wrong port, a recording that receives nothing, no error anywhere.
The suite closes the chain `.iss` ↔ `LiveUDPSource`'s default ↔ `main_window._PORT`, the last read
as *text* because every suite here is deliberately Qt-free. It also pins inbound/UDP,
delete-before-add, uninstall cleanup, admin-with-no-override, and the absence of `postinstall`.

**And when it ships:** the clean-instance run must be repeated, checking the *new* invariant —
installed as admin, then **run as a standard user** with nothing needing elevation. The existing
checklist item changes meaning rather than disappearing.

### The open question C8b left: should the installer write the firewall rule at all?

**Recorded 2026-08-15, because the trade-off genuinely moved.** When C8b was decided, the installer
rule was free — it removed a prompt and cost nothing. It is no longer free: it costs a Windows
restart on **every** install and update. That is a different bargain from the one that was struck,
so it is written down rather than treated as settled forever.

| | Installer rule + reboot (**current**) | No rule; Windows first-run prompt |
|---|---|---|
| A **standard user** can get a rule | ✓ — admin wrote it at install | **✗ — the prompt needs admin credentials** |
| Silent / unattended install | ✓ | ✗ — nobody to click |
| `domain` profile covered | ✓ | ✗ — the prompt ticks Private only |
| Recoverable when it goes wrong | ✓ — re-run the installer | ✗ — a dismissed prompt cannot be recalled |
| GPO has `DisplayNotification` off | unaffected | **silent drop, and no clue why** |
| Reboot required | **✗ — every install and update** | ✓ — none |

**The answer for now is keep the rule**, and the decisive row is the first one. C8b's whole target
model is *installed by an admin, run by a standard user*. In that model the Windows prompt cannot
produce a rule at all — the standard user gets a credential dialog they cannot satisfy, or (under
GPO) nothing whatsoever. Dropping the rule does not trade a reboot for a prompt; it trades a
**documented, requested, one-time reboot** for a **silent, irrecoverable, standard-user-facing
failure** on exactly the machine this design targets. Every failure mode in the right-hand column is
silent, and silence is the single thing this entire investigation exists to eliminate. The reboot is
also mitigated three ways already: Setup asks with a custom label that says why, `USER_GUIDE.md` says
it in three places, and A7 backstops a user who declines.

**The experiment that would decide it, if it is ever worth deciding:** build the installer with the
two `netsh` lines removed, install, record. If the prompt-created rule works immediately, the reboot
is confirmed as attaching specifically to the netsh-written rule rather than to installing as such.
**That is a reopening of C8b, not a small check** — treat it accordingly.

### C8d — assisted update: designed, and deliberately deferred

**Deferred out of Cycle 4 on 2026-08-15.** `Help → Check for updates` would gain "download the
installer and launch it". The design below is recorded so it does not have to be re-derived; see
[`PRIORITIES.md`](PRIORITIES.md) for why it waits and what brings it back.

**Why it waits:** the reboot eats most of the value (C8d removes *browse, find, download, run* and
leaves *elevate, close, reboot*); it would be the app's **first path that downloads a binary and
executes it**, which is a new trust boundary in an app that otherwise only reads UDP and files; and
A4 — a known issue in every release since v0.3.0 — costs the tester group more, more often.

**The flow, if it is built.** Notify (exists) → confirm → download with progress and cancel →
verify → launch Setup → the app quits. The app **never restarts itself and never touches the
reboot**; Setup owns that.

- **The warning before launching is mandatory**, and names three things in order: Windows will ask
  for administrator rights; F1 Telemetry will close; **Windows must restart before recording works
  again**. Without that third line C8d actively makes things worse, by making updates easier and
  therefore more frequent, each one landing a user in the silent-failure state.
- **Downloads go to `%LOCALAPPDATA%\f1telemetry\updates`** via a new `paths.updates_dir()` beside
  `logs_dir()` — `paths.py` stays the single path authority, `F1TELEMETRY_DATA_DIR` is honoured for
  free, and *Help → Open data folder* already puts a user in the right place if the launch fails and
  they must run it by hand. **Not `%TEMP%`**: Windows may clean a ~250 MB download mid-flight, and
  it is not a path you can talk someone to over a chat window. Never beside the exe — that is
  Program Files and read-only.
- **Cleanup is one rule: prune the folder on entry**, before a download starts, plus a best-effort
  prune at start-up. No timers, no age arithmetic. **Never delete after launching** — Setup is still
  reading the file, and that race is the trap worth naming. Every unlink is `try`/`except`, since
  Windows refuses to delete a file in use.
- **Verification, in order:** the URL comes from the API response and is never user-supplied, HTTPS
  only → the **asset name** must match `f1telemetry-<tag>-windows-x64-setup.exe` derived from the
  tag, which is also the version check → **size** against the asset's `size` field (mandatory;
  catches truncation) → **sha256** against the asset's `digest` field when GitHub supplies one,
  computed while streaming so it is free, skipped when absent. **No signature check** — the build is
  unsigned by standing decision, so do not pretend to verify one. Stated honestly: size + digest from
  the same API buys integrity against corruption, **not** against a compromised GitHub account; only
  code signing would. **If C8d is built, publishing a `SHA256SUMS` asset from `release.yml` is a
  precondition, not a follow-up.**
- **Launch with a plain detached process start.** Inno's Setup re-launches itself elevated because of
  `PrivilegesRequired=admin`, so UAC appears without the app doing anything special — exactly as
  double-clicking does. No explicit `runas`/`ShellExecuteW`: an extra code path, harder to test, no
  benefit. Quit only once the start returns success; on failure show the file location. The whole
  flow refuses to start while recording or a job runs (`MainWindow._busy()`).
- **Per build type:** installed Windows → the full flow. **Windows zip → release page only**, because
  running the installer would silently convert the user to a Program Files install and orphan the zip
  folder. **Linux tarball → release page only** (no installer artifact exists). **Source/dev → release
  page only.** Detection is a **marker file the installer drops beside the exe**, checked by
  presence — reusing the rule F9 established for `resolve_notices` (*presence decides, never
  `is_frozen()`*): one `[Files]` line in the `.iss`, one Qt-free predicate, testable on Linux.
  `[InstallDelete]` wipes `_internal`, not `{app}`, so the marker survives upgrades.
- **Where the code would live:** `src/update_download.py` (Qt-free, injectable `urlopen` exactly like
  `update_check`), a `ReleaseInfo.assets` field defaulted so the frozen dataclass stays compatible,
  `UpdateDownloadWorker` in `ui/workers.py` shaped like `ReingestWorker`, and `HelpPage` **emitting**
  while `MainWindow` owns the worker — it has to, since it owns `_busy()` and the quit decision.
- **No new no-telemetry detection is needed.** A7 already fires on zero datagrams and names the
  restart case; it is correct after an assisted update for the same reason it is correct after a
  manual one. Gating it on "a matching firewall rule exists" was considered and **rejected**: it means
  parsing `netsh` output or taking a COM dependency, Windows-only and fragile, to drop half of one
  sentence. **A6** is the open half worth building, not a second hint.

**Worth doing without C8d, and much cheaper (~15 lines in `help_page.py`):** point the update
dialog's button at the matching setup asset's `browser_download_url` instead of the release page —
the browser handles the download and SmartScreen — and **say in the dialog that installing an update
needs administrator rights and a Windows restart**. That second half is worth doing on its own: the
dialog currently says nothing about the reboot, which is the most important fact about updating this
app.

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

- **Live Windows light/dark switch** doesn't fully recolor the UI (PRIORITIES → **A4**, Cycle 4).
  `app._install_theme_refresh` (on `QStyleHints.colorSchemeChanged`) re-polishes widgets so
  backgrounds follow, but **QSS-styled label text keeps its old colour**. Workaround:
  **restart the app after switching the Windows theme.**

  **Root cause corrected 2026-08-06 — the earlier note was wrong, and wrong in a way that would
  have misdirected the fix.** It said a `setStyleSheet` "pins the palette-derived text colour".
  There is no palette-derived colour anywhere: `palette(` appears **three times in the whole
  codebase**, all three inside `ui/style.py`'s docstring explaining why we *don't* use it.

  What actually happens: setting **any** stylesheet on a widget hands its painting to
  `QStyleSheetStyle`, which resolves and caches a palette for that widget *at apply time*. A label
  styled only `"font-size: 20px; font-weight: 600"` therefore carries the **old theme's default
  text colour** frozen into it — despite never having asked for a colour at all — and the
  `unpolish`/`polish` pass doesn't force that cached rule to recompute.

  So the fix the old note guessed at is right, for a different reason: a label with *no* stylesheet
  follows the palette natively.

  **Scope re-measured 2026-08-15 by AST (not grep), and it was larger than recorded.** The old
  "27 font-only calls across 15 files" was wrong twice: those 27 are not font-*only*, and font-only
  is not the actionable set. There are **54 `setStyleSheet` calls across 15 files** under `src/ui/`
  (none anywhere else, and no application-wide stylesheet), which split as:

  | What the call sets | Calls | Verdict |
  |---|---|---|
  | Font properties only | 19 | 🔴 freezes the colour |
  | `font-weight` + `margin-top` captions | 5 | 🔴 |
  | Widget blocks (`QToolButton`/`QPushButton`/`QListWidget::item`) | 5 | 🔴 |
  | `background: transparent` labels | 2 | 🔴 |
  | `"MUTED_TEXT_QSS"` passed as a *literal string* | 2 | 🔴 + a bug of its own |
  | Muted-only (`color: #8b949e`) | 17 | 🟢 explicit colour, unaffected |
  | Muted + font | 1 | 🟡 move the font out, keep the colour |
  | Muted + `font-style` + padding | 2 | 🟢 |
  | `car_status_graphic` view/tooltip block | 1 | 🟢 |

  **33 calls freeze a text colour, not 27.** The rule is simply *any* stylesheet without an explicit
  `color:`; a font property is incidental to it. The two earlier numbers are both reproducible and
  both measure the wrong thing — `grep 'font-'` gives **29**, `grep 'font-size\|font-weight'` gives
  **27** (it misses the two that are `font-style: italic` only).

  Three wrinkles that will bite whoever does it:
  * **`px` and `pt` were both in use — A4 standardised the UI on `px`** *(decided 2026-08-15)*.
    Measured: **11 `px`, 4 `pt`**, the `pt` ones all in `help_page.py` and `laps/detail_page.py`.
    They were a leftover from when those files were written, not a decision, and because 1pt is
    1.333px at 96 DPI they rendered *larger* than the rest of the UI — the Help title at ~27px
    against every other page title's 20px. The four sites were converted to the app's scale
    (**20px titles, 18px sub-headings, 14px body, 11px small**) rather than to their DPI
    equivalents, which would have preserved the inconsistency in new units. This is a **visible
    size change**: the Help title and the lap-detail title shrink to match every other title.
    `ui/style.py` deliberately offers **no point-size path**, since that is what lets two scales
    drift apart again; `test/ui/test_styles.py` fails on any `setPointSize` under `src/ui`. One
    documented exemption: `car_status_graphic.py`'s `QGraphicsSimpleTextItem` labels, which are
    scene-graph text transformed with the view, not styled widget labels.
  * **`font-weight: 600` is `QFont.Weight.DemiBold`, which is exactly 600. `setBold(True)` is
    `Bold` == 700** — a visibly heavier face on every heading in the app, and the most likely way
    to silently regress this fix. `ui/style.py` exports `HEADING_WEIGHT` so no call site chooses.
  * **`MUTED_TEXT_QSS` labels stay styled.** Their `#8b949e` is a *deliberately fixed* colour that
    reads on both grounds (see `ui/style.py` for why `palette(mid)` was tried and rejected), so
    they are already theme-independent and must not be "fixed". Where a label carries **both** a
    muted colour and a font size, only the font moves out; the colour rule stays.

  **Two latent bugs found by the same measurement** (both a missing `f` prefix, neither is A4):
  `slider_row.py` passed the *identifier* `"MUTED_TEXT_QSS"` as a stylesheet, so the setup panel's
  min/max labels had never been muted; and `car_status_graphic.py` had `background: _BACKGROUND`
  inside a plain string, so the fixed light-grey ground that exists specifically "so the neon reads
  the same on light & dark mode" had never been applied. Both fixed alongside A4.

  **A4a done 2026-08-15.** 32 label sites moved to `QFont` behind `apply_font` / `apply_heading` /
  `apply_bold` in `ui/style.py`, with a guard test (`test/ui/test_styles.py`) that fails if a
  font-bearing stylesheet without an explicit colour reappears. It left the **five widget blocks** —
  sidebar, season cards, the two collapse toggles, the Compare button — whose `padding` / `border` /
  `text-align` have no `QFont` equivalent.

  **A4b done 2026-08-18, four of those five.** Sidebar → item size hints
  (`fontMetrics().height() + 16`, measured pixel-identical at 33px rows) plus
  `setViewportMargins(4, 0, 4, 0)`; the two toggles → `setAutoRaise(True)` + `apply_bold` +
  a minimum height (28px, matching); the Compare button → a minimum size off its natural hint.
  Each **removes** the stylesheet rather than working around its caching, so the widgets follow the
  palette natively like every other label.

  **The `colorSchemeChanged` re-apply hypothesis was never confirmed, and was sidestepped rather
  than relied on.** The theory — that `w.setStyleSheet(w.styleSheet())` would force
  `QStyleSheetStyle` to re-resolve its cached palette — could not be tested: under the offscreen
  platform with Fusion a stylesheet'd `QListWidget` recolours correctly on a palette change, so the
  sandbox never reproduced the symptom and therefore could not test the remedy. Removing the
  stylesheets made the question moot. **It remains unproven** — do not cite it as a mechanism.

  **The season card is a deliberate, measured exception.** `QPushButton { text-align: left;
  padding: 12px 14px; }` has no non-QSS equivalent: dropping the sheet gives a 25px-tall *centred*
  button against the current 43px left-aligned card, `QCommandLinkButton` renders 230px tall, and
  a `QPushButton` hosting its own layout collapses to a 43×25 size hint because the button's hint
  ignores its child layout. Against that, **no misbehaviour was ever observed on this widget** on
  either Linux or Windows. Keeping one documented stylesheet beat a visual regression taken to fix
  something nobody had seen go wrong.

  **The symptom was Windows-only.** All 32 A4a label sites reproduced and verified on Ubuntu, but
  the sidebar — the one remaining *visible* case — never misbehaved on Linux and only ever showed
  on Windows. That matches `app._install_theme_refresh`'s own docstring note that item views can
  keep their old ground, and it means the "mostly verifiable on the dev box" claim held for labels
  but not for item views.
- **pyqtgraph bloat — DONE 2026-08-06 (PRIORITIES → C7), and it was not where the weight was.**
  The contrib hook plus our own `collect_submodules("pyqtgraph")` pulled in `pyqtgraph.examples.*`:
  a demo application with its own `__main__` and ~40 example scripts, unreachable from here (this
  app touches pyqtgraph through two lazy imports, `trace_plot` and `track_map`). Now filtered out
  of `hiddenimports` *and* `collect_data_files`, with an `excludes` entry as a backstop.

  **Measured: 577 MB → 576 MB, i.e. 0.17 %.** The change is right on hygiene grounds — a demo app
  with an entry point no longer travels inside a distributed binary, and the spec states its intent
  instead of collecting blindly — but it is not a size fix, and the CHANGELOG deliberately carries
  no entry for it.

  **Deliberately one subpackage only.** `pyqtgraph.opengl`, `.canvas`, `.flowchart`, `.console` and
  `.multiprocess` look equally unused, but several are reachable from pyqtgraph's own `__init__` and
  its lazy attribute machinery; trimming those is how you ship a build that works until one specific
  widget is opened.

  **How to verify a trim — the obvious check lies.** In a one-folder build with `noarchive=False`,
  pure-Python modules go into the **PYZ**, not onto disk, so a file search finds nothing either way.
  And `build/f1telemetry/Analysis-00.toc` records the `Analysis()` *configuration*, so it necessarily
  still matches `pyqtgraph.examples` once the exclude exists — a guaranteed false positive. The two
  lists that decide what ships are:

  ```
  grep -c "pyqtgraph\.examples" build/f1telemetry/PYZ-00.toc       # → 0
  grep -c "pyqtgraph\.examples" build/f1telemetry/COLLECT-00.toc   # → 0
  grep -c "pyqtgraph"           build/f1telemetry/PYZ-00.toc       # → 384, still all there
  ```

  Then confirm it for real: `capabilities.py`'s charts probe is `find_spec`-based and cannot prove
  pyqtgraph *renders*, so **open a lap detail page in the built app** and check the traces and track
  map draw. A frozen bundle can be pointed at dev data with
  `F1TELEMETRY_DATA_DIR=<dir> ./dist/f1telemetry/f1telemetry`, which makes this a Linux-side check
  rather than a Windows build. Note the capability lines land in `<data dir>/logs/`, **not** on the
  console — a frozen windowed build installs no console handler.

- **Where the size actually is (measured 2026-08-06, Linux one-folder, `_internal` = 555 MB).**
  Recorded so nobody re-runs this hunt:

  | | | |
  |---|---|---|
  | pyarrow | 146M | required |
  | PySide6 | 128M | required |
  | **scipy + scipy.libs** | **73M** | **not a dependency of this app** |
  | libpython3.13.so | 35M | required |
  | numpy.libs | 28M | required |
  | zstandard | 23M | required |
  | **pandas** | **18M** | **not a dependency** |
  | **pillow.libs** | **14M** | **not a dependency** |

  scipy, pandas and pillow are transitive — pyqtgraph optionally imports scipy and pillow for image
  paths never taken here, and pyarrow drags pandas. Sweeping all 384 pyqtgraph submodules is what
  makes those optional imports visible to PyInstaller. That is **~105 MB, 18 %**, against C7's 1 MB.
  Filed as **PRIORITIES → C9**, deliberately *not* folded into C7: it is exactly the over-reach C7's
  own spec comment warns about, and it needs a Windows build of its own since the composition
  differs there (`libgtk`, the `.libs` layout).

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

**This is a template, re-run per release — the boxes stay unticked on purpose.** Per-build results
belong in *Build history* below, so the next release starts from a clean list instead of having to
untick the previous one. **Last full run: v0.7.0 on 2026-08-07 — passed** (Windows Sandbox + the
W11 boot); see the 4th build entry for what was covered where and what was not.

- [ ] Launch by **double-click** from a folder that is *not* the repo (proves CWD independence).
- [ ] **The C8b invariant — install as admin, then run as a standard user.** This item *changed
      meaning* when the installer landed; it used to read "launch as a non-admin user". Installing
      elevates (that is what the firewall rule needs); **launching must not**. Log in as a standard
      user, start it from the Start menu, and confirm no UAC prompt, nothing written beside the exe,
      and a `%LOCALAPPDATA%\f1telemetry` belonging to *that* user. If a build ever needs admin to
      run, that is a bug, not a consequence of the admin install.
- [ ] **Installer:** UAC prompts (credential screen on a standard account); installs to
      `C:\Program Files\F1 Telemetry`; Start-menu entry appears.
- [ ] **The firewall rule is real.** `netsh advfirewall firewall show rule
      name="F1 Telemetry (UDP 20777)" verbose` reports `Enabled: Yes`, `Direction: In`,
      `Protocol: UDP`, `Profiles: Domain,Private`, `LocalPort: Any`, and `Program:` pointing at the
      installed exe.
- [ ] **Setup asks to restart, and the page says WHY** — not Inno's generic default text.
- [ ] **BEFORE restarting:** record → **no telemetry**, and after ~25s the status line names the
      restart. **Run the release zip alongside: it MUST record**, or the game wasn't sending and
      the run is void. If the *installed* app records here, say so — the restart requirement would
      be over-cautious and can be narrowed.
- [ ] **AFTER restarting:** launch as a **standard user** → record → **packets arrive and a
      `.f1cap` appears** in *that* user's `%LOCALAPPDATA%\f1telemetry\captures`, with no UAC and no
      firewall prompt. **This, not the rule existing, is the test.**
- [ ] **Repeat the whole install → restart → record path a second time, from scratch.** One pass is
      not acceptance: it was accepted three times during C8b and was wrong every time, twice
      reaching these docs as a settled conclusion.
- [ ] **Upgrade in place:** run the installer over an existing install → still **one** firewall rule
      and **one** entry in Apps & features. Repeat with the app **running** → Restart Manager offers
      to close it and the install completes.
- [ ] **Uninstall, app closed:** program files and firewall rule both gone (`show rule` reports no
      match), and `%LOCALAPPDATA%\f1telemetry` **still present with captures intact** — this is
      deliberate, not a miss.
- [ ] **Uninstall, app open → Cancel:** the guard's dialog appears, and cancelling leaves the
      installation **completely intact** — relaunch it to confirm. This is the item the original
      behaviour got wrong, so it is the one worth actually performing rather than assuming.
- [ ] **Uninstall, app open → close it → Retry:** the uninstall then completes normally.
- [ ] **The zip still works standalone** (it is the no-elevation fallback, so it must not rot):
      unzip, run, and the first-record firewall *prompt* appears as before.
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
- **4th build (v0.7.0) — done 2026-08-07. This is PRIORITIES → C4, and it closes it.** Run against
  the **Release zip downloaded from GitHub**, on **Windows Sandbox** *and* the author's W11 boot.
  Every Phase-3 item passes, and the two things no build had ever covered are now covered: the
  **clean-instance** run and the **SmartScreen click-through wording**.

  **Windows Sandbox is confirmed as the right tool for this** (option 1 above), with one structural
  limit worth knowing before planning the next run: **the Sandbox cannot record.** It is a VM with
  internet but no route to the home network, so the PS5 never reaches it. Everything downstream of
  recording was tested there by **copying capture files in and ingesting them**, which covers ingest,
  lap traces, the track map, re-ingest and the backup. Only the live-recording items need the W11
  boot.

  **Three items not ticked, and they are not equivalent:**
  - *Old DB → additive columns* — **N/A for v0.7.0**, not skipped: C5/C6/C7/F8 touched no schema, so
    `ensure_schema` had nothing to ALTER (same reasoning as the 2nd build). The other half of that
    line *was* covered — a fresh `%LOCALAPPDATA%` created a DB cleanly with `meta` holding the
    current `pipeline_version` and no prompt.
  - *Pre-Phase-2 DB offers the upgrade* — **carried forward, not re-proven.** It passed on the 2nd
    build (2026-07-26) and nothing since has touched `check_pipeline_version`; reproducing it needs a
    legacy unstamped populated database that would have to be manufactured.
  - *Kill mid-record → recovers on next launch* — **open.** Unreachable in the Sandbox (see above)
    and not run on the boot. Low risk — it passed on an earlier release and the recording flow has
    not changed since — but it is genuinely unverified on v0.7.0, so it sits in
    PRIORITIES → *Needs verification* for the next real session.

  **Two findings from the run:**
  - **Help → Check for updates fails inside the Sandbox and works on the W11 boot.** Recorded so it
    is not investigated as an app bug later: the Sandbox's network isolation is the likely cause, and
    the W11 result is the one that counts.
  - **A4 (light/dark text colour) is confirmed still present on v0.7.0** — noticed while checking
    HiDPI/scaling, which is otherwise correct. The CHANGELOG known-issues entry stays accurate, and
    A4 remains Cycle 4's first item.

  **One improvement raised:** `NOTICE.md` ships as raw markdown, so a tester without a markdown
  viewer reads `#` and `**` in Notepad. `release.yml` already runs pandoc/xelatex for the guide, so
  a second invocation is cheap — filed as PRIORITIES → **F9**, and **closed 2026-08-08**: see
  *The notices PDF (F9)* under the phased plan above.

---

## Risks & fallbacks (keep this list; revisit if packaging misbehaves)

- **Qt platform plugin missing** → app won't start. Fallback: verify on a clean machine; PyInstaller
  Qt hooks normally cover it.
- **pyqtgraph / zstandard missed** (lazy imports) → app silently ships the fallback. Fallback:
  explicit hidden imports + a startup self-check that warns if a "real" feature degraded —
  **the self-check is now built (C6, Cycle 3): `src/capabilities.py`.**
- **pyarrow bloat / Windows DLL-load quirks** (~100 MB+). Fallback: verify Parquet read/write early;
  worst case a startup capability probe — **also covered by `src/capabilities.py`**, with the
  caveat recorded below.

### The startup capability self-check (C6)

`src/capabilities.py` is Qt-free and only *reports*; what to do about a degraded build is the
caller's call. `MainWindow` runs it one event-loop turn after the window paints — **before** the
pipeline-version check, since a build that lost pyqtgraph is worth mentioning before offering a
multi-minute re-ingest — logs one line per capability on **every** launch, and shows a single
warning dialog naming the consequences only when something is degraded. Deliberately **no Help-page
surface**: Help already carries five actions that aren't Help content (PRIORITIES → E13).

Four capabilities are probed: charts (pyqtgraph), capture compression (zstandard), lap traces
(pyarrow) and the bundled flag SVGs.

**Probe depth is per capability, and that is the design.** A capability is probed by *importing*
it, because an import is the only thing that catches a module which is present but will not load —
pyarrow's Windows DLL quirk is the named example, and `find_spec` says yes while the import still
fails. The single exception is **pyqtgraph**, probed with `find_spec` alone: importing it here
would undo the laziness that keeps start-up quick, and the regression this module exists for — *a
bundle that never shipped it* — is visible without importing. **That is what makes C6 the
prerequisite for C7**, whose entire risk is an `excludes` edit silently dropping pyqtgraph.

Two limits, chosen rather than overlooked:

1. A module *present but broken at import* reads OK for pyqtgraph. Not silent, though — it raises
   into the log the first time a lap is opened, and that difference is what decided the split.
2. `traces` can never actually report degraded today: a broken pyarrow kills `main_window`'s module
   import (`→ storage.laps → trace_files`) before the window exists, so it is a start-up crash
   caught by `crash.py`, not a silent degrade. The probe earns its place as a log line a tester's
   report can carry, and stops being vacuous the day that import becomes lazy.

A probe that throws is reported as a **degraded capability**, not dropped — a self-check that can
take start-up down is worse than no self-check, but one that quietly shortens its own report is
worse still. `check_capabilities(probes=…)` is injectable so the aggregation is testable without a
broken environment. Covered by `test/test_capabilities.py`.
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
3. **Windows Firewall prompt** on first record — tell testers to **Allow**. **Largely retired by
   C8b:** the installer writes the rule, so installer users never see the prompt. It still applies
   to the **zip** build. What replaces it as the thing to tell testers is the *Public network* trap:
   the rule covers private/domain profiles only, so a home network Windows has classified as Public
   receives nothing, silently.
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
