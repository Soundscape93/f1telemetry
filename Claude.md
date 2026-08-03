# f1telemetry

A personal desktop app that captures F1 25 / F1 26 UDP telemetry from a PS5, analyses the
player's own laps, and records league / multiplayer results and standings for a private racing
league.

**Used for:** (1) analysing own laps across a session by overlaying N laps on a shared distance
grid; (2) publishing practice/quali/race results and standings to the league (screenshot/file);
(3) possibly, later, packaging for colleagues to analyse their own laps. Colleagues are
near-term test users; a hosted multi-user version is possible but uncertain, and nothing in the
design depends on it.

> This file is the always-loaded context. Deeper material lives in `docs/` — see
> [Where to look](#where-to-look). Keep this file short; put detail in the `docs/` files.

## How we work

- **Design-first, reviewable changes.** The author writes/reviews the code by hand and values
  understanding over speed. Explain non-obvious decisions; keep diffs focused and layer-clean.
- **Confirm before editing code.** For implementation work, discuss the intended change first
  and do not modify files unless the author explicitly asks to apply it. Keep code out of the
  chat unless the author asks for it there.
- **Do not run git commits.** When a change is ready, suggest appropriate commit message(s) for
  the author to run; never execute `git commit`.
- **Releases group on `staging`.** `main` is protected — it takes PRs from `staging` only, and CI
  never pushes to it. Small feature/fix branches are PR'd into `staging`; when a group is ready,
  one PR from `staging` → `main` carries the `major`/`minor`/`patch` label. **Labelling** starts
  the version bump (committed to the PR's branch); **merging** is what tags and releases. Every
  grouped change adds its own bullet under `## Unreleased` in `CHANGELOG.md` — that section becomes
  the release notes for the whole group. See `docs/PACKAGING.md` → Versioning & dev release process.
- **Git root is nested.** The repository root is `f1telemetry/`, not the workspace root
  (`F1-TELEMETRY/`). Run git-oriented commands from `f1telemetry/`.
- **Verify before "done".** Logic is proven in a throwaway sandbox and/or the `unittest` suite
  before it's considered finished. Tests use plain `unittest` + `subTest` (not pytest).
- **Absolute imports** everywhere under `f1telemetry.src.<layer>...`.
- **Layered separation is the rule** (see `docs/ARCHITECTURE.md`). Ingest, protocol, domain,
  storage, analysis, and UI are decoupled; everything from the normalizer up is
  format-agnostic — 2025 vs 2026 differ *only* in the wire structs and parser at the bottom.

## Tech stack

- Python 3.11+ (modern syntax: `X | None`, etc.), developed on Linux; the game runs on a PS5.
  (`pyproject.toml` pins `requires-python >=3.11`; the Windows build machine uses 3.14.)
- **UI:** PySide6 (+ PyQtGraph for charts).
- **Storage:** SQLite via SQLAlchemy 2.0 (`DeclarativeBase`, `Mapped`/`mapped_column`), kept
  engine-agnostic so it *could* move to Postgres if a hosted server is ever built. Every store
  opens the database through `storage/engine.py: create_db_engine` (WAL + `synchronous=NORMAL` +
  `busy_timeout`) — each store owns its own `Engine`, so the *setup* is what's shared, not the
  engine. Add a pragma there and nowhere else.
- **Dependency manifest:** `pyproject.toml` (deps pinned `==`; `pyinstaller` under a `[package]`
  extra) — added in packaging Phase 0. Runtime third-party: PySide6, numpy, pyarrow, SQLAlchemy,
  plus lazy `pyqtgraph` (charts) + `zstandard` (new capture archives). `zstandard`'s wheel
  statically bundles libzstd, avoiding a version clash with the copy Qt loads.
- **Wire parsing:** `ctypes.LittleEndianStructure` (`_pack_ = 1`), one struct set per format.

## Repository layout

```
F1-TELEMETRY/                   # VS Code workspace root — NOT the git repo; holds untracked
                                #   data + dev scratch that stays out of version control:
  captures/                     # capture recordings — source of truth; archived after ingest,
                                #   never auto-deleted. New archives are .f1cap.zst (zstd);
                                #   existing .f1cap.gz stay readable forever
  rosters/                      # canonical per-season roster JSON:
                                #   season_<id>.json; CSV is import-only (see DECISIONS)
  diagnose_participants.py      # dev tool: raw Participants per session (read-only)
  dump_classifications.py       # dev tool: assemble() + classification dump (read-only)
  session_history_scan.py       # dev tool: Session History scan (read-only)
  *_demo.py                     # dev sandboxes: decode / parser / normalizer /
                                #   assembler / storage demos
  *.f1cap, *.db                 # loose dev captures + dev databases (demo.db, f1league.db)
  Data Output from F1 25 *.pdf  # the UDP spec PDFs (2025 v3 + 2026 season pack)
  f1telemetry/                  # ← the git repository root (code + docs + tests)
    Claude.md                   # this file
    README.md
    docs/                       # PRIORITIES (what to work on next), ROADMAP, ARCHITECTURE,
                                #   DECISIONS, TELEMETRY_NOTES, PACKAGING, USER_GUIDE
    src/
      version.py, paths.py, logging_setup.py, crash.py, update_check.py  # packaging + update check
      ingest/    recording.py (.f1cap read/write), recorder.py, sources.py,
                 archive.py (gzip/zstd codec dispatch + HashingReader), inspect.py (CLI)
      protocol/  base.py, header.py, enums.py, reference.py, registry.py, parser.py,
                 v2025/structs.py, v2026/structs.py
      domain/    models.py, captures.py, normalizer.py, season.py, calendars.py, roster.py
      session/   assembler.py
      storage/   engine.py (create_db_engine — the ONE place the DB is opened: WAL +
                 synchronous=NORMAL + busy_timeout), backup.py (VACUUM INTO),
                 schema.py, sessions.py, seasons.py, laps.py, captures.py,
                 meta.py (key/value app state — the PIPELINE_VERSION stamp)
      analysis/  standings.py
      ui/        app.py, main_window.py, help_page.py, season_roster.py, workers.py, formatting.py,
                 seasons/ (view.py=SeasonsView container + overview/create/detail/weekend
                   _page.py, labels.py) — pages coordinated by navigation signals
                 components/ (tables.py, classification_table.py, slider_row.py,
                   car_status*.py, track_map.py, trace_plot.py, …) — shared widgets
      pipeline.py               # Qt-free ingest orchestration (ingest_capture, archive_and_ingest,
                                #   check_pipeline_version + reingest_all — the Phase-2 rebuild)
    packaging/                  # PyInstaller one-folder spec (f1telemetry.spec) + entry.py, plus
                                #   the release scripts: check_version.py (verify tag ↔ version
                                #   files), bump_version.py (label-driven bump + changelog),
                                #   release_notes.py (a tag's CHANGELOG section → Release body)
    .github/workflows/          # ci.yml (suite + gates), bump.yml (label → bump on the PR
                                #   branch), tag.yml (merge to main → tag → call release),
                                #   release.yml (build → full GitHub Release)
    CHANGELOG.md                # entries accumulate under "## Unreleased"; the bump closes it
    test/                       # unittest suites (test_*.py); run from the WORKSPACE root (the
                                #   parent of this repo — absolute f1telemetry.* imports):
                                #   python3 -m f1telemetry.test.<name>            (one suite)
                                #   python3 -m unittest discover -s f1telemetry/test -t .  (all)
```

## Core invariants (the ones that bite)

Each of these has caused or prevented a real bug — treat them as load-bearing:

1. **The roster is accumulated across all Participants frames, not taken from one packet.** A
   late (post-race/podium) Participants packet can report a smaller `num_active_cars`; trusting
   a single frame leaves high-vehicle-index cars unmatched in the classification join (blank
   name / number 0 / team −1). The assembler merges every frame by vehicle index. Details in
   `docs/TELEMETRY_NOTES.md`.
2. **Per-car arrays are indexed by vehicle index, not finishing position.** The classification
   is joined to the roster by vehicle index, then sorted by position only for display.
3. **Sessions split on `header.session_uid`;** `uid == 0` frames are init noise and ignored.
4. **`session_assignments.session_uid` is deliberately NOT a foreign key** to `sessions`, so
   re-ingesting a capture (replace-by-uid) never wipes manual round placements.
5. **Slot (Q1/Q2/Q3/Sprint/Race) is derived, never stored** — but not from `session_type`
   alone: the Sprint Race and the Grand Prix *both* report `session_type` RACE (15), so they're
   told apart by their position in the weekend. `domain/season.py:weekend_slots` resolves this
   from the game's `weekend_structure` (persisted per session), falling back to `session_link_id`
   order for legacy rows — the Grand Prix is the weekend's final race; earlier races are Sprints.
6. **Traces are indexed by lap DISTANCE, not time.** The header is 29 bytes. The recorder binds
   `0.0.0.0:20777` (set the game's UDP to broadcast).
7. **Race numbers are unique only among humans**, so league identity never keys on a number
   alone: the AI field runs the real-world numbers, and an AI on 11 is not the member on 11.
   Resolution is online-name alias first (humans often capture as `"Player"` with online-name
   sharing off, hence the fallback), then race number **for human cars only** — `is_ai` is
   captured on every classification entry for exactly this. Keys are tagged and resolved a whole
   classification at a time (`LeagueRoster.session_keys`), so two cars in one session can never
   share a standings row. See DECISIONS → Identity & rosters.
8. **Format is detected per packet** from `header.packet_format` and dispatched on
   `(packet_format, packet_id)` via the registry — never a user-facing toggle.
9. **Enums are stored as raw ints** and read back via `safe_enum` (returns the member, or the
   raw int for values newer than our enum).

## Conventions

- **Module-level constants use a SINGLE leading underscore.** A double underscore triggers name
  mangling inside class bodies (`__X` → `_ClassName__X`) and has caused a `NameError`. Reserve
  `__` for class attributes you actually want mangled.
- Type hints throughout. Frozen dataclasses for domain value objects.
- Store objects are context managers (`__enter__`/`__exit__` dispose the engine); use them.

## Current status

- **Ingest / protocol / domain / storage:** complete and tested (both formats), the archive-first
  flow **verified end-to-end against a live recording**. Ingest is **archive-first**:
  `archive_and_ingest` compresses the raw capture to `.f1cap.zst` (zstd),
  ingests *from* the archive so its checksum is verified end-to-end, and deletes the raw only on
  success — a capture that fails to parse is kept as both raw and archive. Existing `.f1cap.gz`
  archives stay readable and are ingested in place (never rewritten). A `captures` metadata table
  (`CaptureStore`, keyed by a codec-independent content hash) makes captures queryable without
  decompressing them — the base for a future "import league captures from a folder" flow. A capture
  whose file **moved** can be found again by content (`pipeline.relocate_moved_captures` +
  `archive.hash_capture`, Help → Find moved captures…): name and size pre-filter, the hash decides,
  and only the known-missing rows are searched for. It re-points the row, never copies the file —
  copying home is the import flow's job.
- **Standings:** driver standings (by name or race number) and constructor standings; LEAGUE
  standings resolve drivers through the per-season roster — or, with no roster file, through the
  in-memory capture seed, which is enough on its own when every member shares their online name
  publicly. AI and human drivers sharing a race number no longer merge (invariant #7; needed
  `is_ai` on classification entries, `PIPELINE_VERSION` 2). AI drivers stay in the table as their
  own rows: driver standings are a full-grid championship view, not a members-only one.
  **Driver standings show nationality flags** (done): `StandingRow` carries a display-only
  `nationality_id`, threaded through `_Accumulator` with the same last-seen-wins rule as
  `name`/`number`, and the detail page sets the icon exactly as the classification table does.
  Constructor standings get no flags — nationality is per driver, not per team.
- **Missing Final Classification fallback:** if a session ends without a Final Classification
  packet, the assembler reconstructs a best-effort result from Lap Data + Session History
  (`Classification.is_reconstructed`), badged in the UI. Points can't be recovered (FC-only), so
  they show as a muted estimate and reconstructed sessions are excluded from standings. **The game
  sends FC 5–6× per session, not once** (measured 2026-08-01), so this fallback is rare — losing it
  takes a multi-minute recorder blackout, not a dropped datagram. See DECISIONS / TELEMETRY_NOTES;
  an accept/edit flow is deferred (ROADMAP Option 3, PRIORITIES → B5).
- **UI:** single-window shell (sidebar + persistent record/stop header + stacked pages). The
  Seasons surface is real — overview, create, per-season detail (calendar + driver & constructor
  standings), per-season LEAGUE roster CSV import, and a weekend view with round-centric session
  assignment (its capture picker can also delete an unassigned session's stored results via
  right-click; the recording on disk is kept). LEAGUE displays prefer captured public online
  names, falling back to the first
  roster `online_names` alias when captures only say `"Player"`/blank. Reusable widgets (the
  session classification table, table primitives) live in `ui/components/`, ready for the
  upcoming surfaces. The Seasons surface is split into `ui/seasons/` — a thin `SeasonsView`
  container coordinating one widget per page via navigation signals. The custom-calendar picker
  is live: `create_page.py` embeds the reusable `ui/components/calendar_picker.py`, driven by
  `(mode, format)` rules from `domain/calendars.py` (Career/My-Team = fixed-length subset;
  Grand Prix/League = reorderable sandbox with duplicates). **An existing calendar is editable**
  (`ui/seasons/edit_calendar_page.py`, the fifth seasons page): a round holding an assigned session
  keeps both its `round_number` and its `track_id`, checked positionally and enforced inside
  `SeasonStore.set_calendar` (raises `CalendarConflictError`) so the rule can't be bypassed.
  Calendar only — mode/number/nickname/format stay fixed.
  The **Laps** surface is now real: `ui/laps/` (foldable per-session lap cards + track/session
  filter → a lap detail page with the car-status graphic, damage/setup tables and stacked telemetry graphs),
  built on `LapStore.list`/`load`, the N-series-aware `analysis/traces.py`, and reusable lap
  widgets in `ui/components/`. **Lap-view iterations 2 (overlay) and 2b (Motion) are done:** the
  detail page's "Compare ▾" menu overlays the weekend's fastest / same-session / same-weekend laps on
  the shared distance grid (each channel coloured *and* line-styled per lap with a legend, plus a
  Δ-time racing-gap row; candidates from `ui/laps/comparison.py`, colour-blind palette included), and
  routing the **Motion** packet added a g-force `TracePlot` row plus a `TrackMap` XY-path panel with
  a hover marker (`cursor_moved`). The map un-mirrors the left-handed world frame and closes the loop
  so a race lap 1 draws whole; absolute rotation follows the game frame, not F1.com map art (no
  per-track assets). **2b.1 made the map canonical:** it now draws a **distance-resampled median
  racing line** over the race weekend's valid Motion laps (`analysis/track_layout` +
  `ui/laps/track_layout`), so the shape is clean and identical per track regardless of the viewed
  lap; too few laps → it falls back to the driven line. Dashboard / Sessions / Analytics remain
  placeholders.
- **Done:** lap-view **2c — a car-status graphic** (an in-game-style car silhouette with
  colour-coded tyre / engine / body-damage zones; tyres as corner gauges). SVG-authored
  `QGraphicsScene` path items (`car_status_graphic.py`) over a Qt-free, tested `car_status.py`
  model. Temperatures ingested (tyre surface/carcass on `LapTyreContext`, brake/engine on
  `CarDamage`, from the carried-forward Car Telemetry entry; re-ingest needed), threshold model +
  tests, and the widget wired into the detail page's left column with per-part tooltips (it replaced
  the `TyreBox`, removed in the post-2c polish). Body
  shapes are **Inkscape-traced** (`docs/car_template.svg` template) and parsed by `_svg_path` — now
  the full SVG command set incl. S/T smooth curves + A arcs (`test_svg_path.py`); tyres, inboard
  **brake blocks** and corner gauges are procedural (from `_CORNERS` / `_TYRE_*` / `_BRAKE_*`). The
  neon glow is on (an early transparent-viewport hover artifact was fixed via `setStyleSheet`).
  **Done since 2c — sector colouring & track geometry:** the Session packet's
  `sector_2/3_lap_distance_start` (+ `track_length`) are now persisted on the session row
  (`track_length_m` / `sector2_start_m` / `sector3_start_m`; additive migration, `None` for old rows).
  `TrackMap` colours its outline by sector (F1-map palette in `analysis/track_layout.SECTOR_COLOURS`);
  the telemetry traces mark the sector boundaries with dashed vertical lines on every row, and a
  shared vertical cursor tracks the mouse across all trace rows + the map marker (clamped to the lap's
  distance range so it can't stretch the x-axis). Always-visible sector *labels* on the map were tried
  (opaque mask, then a cut-out gap in the line) and removed — they reduced readability on complex
  layouts, so the map conveys sectors by colour alone (labels could return later as hover/tooltips).
  This used the per-session boundary **distances**, not the per-frame `sector` channel the earlier
  note assumed.
  **Canonical-map cache refresh is done** (2026-08-02): `TrackLayoutProvider.invalidate()`, reached
  unconditionally from `MainWindow._refresh_current_view()` through `LapsView.invalidate_caches()`,
  so an ingest or re-ingest can no longer leave a stale weekend layout (or a stale "too few laps →
  driven line" answer) on screen until restart. Deleting a session's stored results invalidates it
  too, via the weekend page's `sessions_changed` signal — the one non-navigation signal leaving the
  seasons surface.
  Still deferred: **corner numbers** (future work — no
  telemetry source; needs static per-track metadata, e.g. a snapshot of FastF1/MultiViewer
  `get_circuit_info`; mind the data licensing before broad distribution). Also pending: the Analytics
  surface and an edit-calendar action. See `docs/ROADMAP.md`.
- **Packaging (Phases 0–3 done; Phase 4 outstanding):** a per-user data root + `resource_path` (`paths.py`), file logging
  + crash dialog, `__version__`/`PIPELINE_VERSION` (`version.py`), a PyInstaller one-folder Windows
  build (`packaging/`), and a notify-only GitHub-Releases update check (`update_check.py` + Help
  page). Verified on Windows 11 (2026-07-25). **Phase 2 = the pipeline-version stamp + guided
  re-ingest:** `PIPELINE_VERSION` is stored in a `meta` table (`storage/meta.py`); when this build
  derives more than the stored rows hold, the app *offers* (never forces) a cancellable,
  progress-barred rebuild of every stored session from its archived capture
  (`pipeline.reingest_all` + `ReingestWorker`, also on demand from Help). Safe because season
  assignments / laps / rosters are keyed on `session_uid` and never FK'd to `sessions` (invariant
  #4). Bump `PIPELINE_VERSION` in the same commit as any ingest change that makes stored rows stale.
  Verified on the Windows 11 build (2nd build, 2026-07-26). **Two standing data decisions:** there is
  **one data root** (`%LOCALAPPDATA%` — hidden, so the app opens Explorer for the user rather than the
  data moving), and the **DB is never protected, only rebuildable** from captures (same-user file
  permissions can't enforce anything and would break SQLite's `-wal`/`-journal` siblings) — so no
  "Open database" action anywhere. **Phase 3 (done 2026-07-26) = the release pipeline:** write the
  entry under `## Unreleased`, label the **`staging` → `main` PR** `major`/`minor`/`patch`, merge.
  Labelling is what starts it — `bump.yml` bumps `version.py` + `pyproject.toml` + the changelog and
  commits that **to the PR's branch**, so the version reaches `main` through the PR like any other
  change; the merge then makes `tag.yml` tag it and call `release.yml`
  (gates + suite → `USER_GUIDE.pdf` via pandoc/xelatex on Linux → PyInstaller on Windows → a **full**
  GitHub Release). **CI never pushes a commit to `main`** — that is the branch protection rule, and
  the reason the bump moved off `main` (2026-08-01). CI **verifies** the version, never stamps it,
  so the artifact is exactly the tagged commit. The guide PDF, `roster_template.csv`, `LICENSE` and
  `NOTICE.md` ship **beside the exe** (`paths.app_dir()` —
  a third path kind, distinct from `data_root()` and `_MEIPASS`), opened from the Help page along
  with the data / captures / logs folders. Shipping the notices is an **LGPL v3 obligation** for the
  bundled Qt/PySide6, not a courtesy — the repo is *source-available, not open source* (`LICENSE`),
  and `NOTICE.md` also carries the unofficial-tool / trademark / telemetry-data disclaimer. The published build has been checked against the Phase-3
  checklist (2026-08-02) and passes; **Phase 4 is what's left** (macOS/Linux artifacts, Inno Setup
  installer, real auto-updater). See `docs/PACKAGING.md` / `docs/USER_GUIDE.md`.

## Where to look

- **`docs/ARCHITECTURE.md`** — the layered pipeline, each layer's responsibility, threading.
- **`docs/DECISIONS.md`** — why the design is the way it is (read before changing a big call).
- **`docs/TELEMETRY_NOTES.md`** — F1-UDP spec facts and quirks, and the diagnostic tools; read
  before touching the parser, normalizer, or assembler.
- **`docs/PRIORITIES.md`** — **read this first when deciding what to work on.** The confirmed
  P1/P2/P3, the Cycle 1/2/3 plan, what is done, and what is built-but-unverified. ROADMAP explains
  *what* an item is; PRIORITIES says *when* we do it, and wins on ordering.
- **`docs/ROADMAP.md`** — planned work and deferred ideas.
- **`docs/PACKAGING.md`** — the packaging/release plan: PyInstaller one-folder (Windows first),
  the `paths.py` data-root refactor, DB migration vs pipeline-version auto-reingest, GitHub
  Releases/Actions, the Windows-11 clean-machine checklist, and tester instructions. Read before
  starting Phase 0. This is the priority pre-season work.
