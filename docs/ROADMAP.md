# Roadmap

Planned work and deferred ideas. Not a commitment — a place to park intent so a future session
(or the VS Code chat) has the context. Roughly ordered by when it's likely to matter.

## Seasons UI — remaining
- **Done: 2b — per-season rosters + league standings.** `rosters/season_<id>.json` is the
  canonical per-season roster for LEAGUE seasons. Viewing a LEAGUE season is **read-only**: if
  no roster file exists yet, the detail page *shows* a roster seeded in memory from captured
  names/numbers (merged over the previous league season's file), but writes nothing. The file is
  created only by an explicit action — a "Create roster file" button materializes the seed so it
  can be hand-edited, or CSV import writes it. The user picks a CSV from their own storage, the
  app validates it, and writes the canonical JSON; the CSV remains outside the app and is never
  the live roster path. League standings group drivers by their resolved member's **race number**
  (`LeagueRoster.member_key`), so two roster-unknown humans both shown as `"Player"` never
  collapse into one row. LEAGUE
  driver standings use `league_standings_for_rounds`; career/My-Team/Grand Prix stay on
  `standings_for_rounds`. LEAGUE detail/weekend displays prefer captured public online names;
  if the capture only says `"Player"` or blank, display falls back to the first roster
  `online_names` alias. The CSV `name` column is only a human helper/canonical identity for
  assigning aliases and race numbers, not the preferred display label. Constructor standings
  stay based on captured in-game `team_id`s for official/F1 World cars. CSV import contract:
  required columns are `name` and `race_number`; optional column is `online_names`. Header names
  are matched case-insensitively and tolerate spaces/underscores. `race_number` must parse as an
  integer and be unique. `online_names`, when present, is a semicolon-separated list of public
  telemetry names/aliases for that member. Unknown extra columns are ignored.
- **2c — custom-calendar picker. DONE.** A season's calendar can be authored by hand, with the
  constraints the game actually enforces per mode: Career/My-Team pick a fixed-length subset
  (10/16/24) of the official order; Grand Prix/League are a reorderable sandbox with duplicates
  allowed (League open-ended, Grand Prix capped at 28). Rules live in `domain/calendars.py`
  (`calendar_rules`), the widget in `ui/components/calendar_picker.py`. *Next here:* surface the
  same picker as an edit-calendar action on the detail page (the store already has
  `set_calendar()`).

## Other surfaces (currently placeholders)
- **Sessions** — a list of every captured session; likely also a *session-centric* assignment
  path (complement to the round-centric one in the weekend view). The per-session detail renders
  its classification via `ui/components/classification_table.py` (the same builder the weekend
  view uses). *Groundwork:* `SessionStore.delete(uid)` exists and is wired to a right-click
  "Delete from database…" on the weekend capture picker (unassigned captures only — an assigned
  session must be unassigned first, which drops it back into the picker). Delete removes the
  stored results only; the `captures/` recording is kept, so a re-ingest recreates the session.
  This action moves to (or is shared with) the Sessions surface when it lands. The picker shows
  a "Recorded" column stamped from the capture's real packet time (see DECISIONS → `recorded_at`),
  so repeated attempts of one session are separable by time — the keeper is the latest.
- **Deleted-sessions manager** — a view listing tombstoned sessions (track / type / recorded-at,
  already stored on `deleted_sessions`) with a Restore button. The store side is done
  (`SessionStore.deleted_uids` / `is_deleted` / `restore`; delete tombstones by default and
  `ingest_capture` skips tombstoned uids); only the UI is pending. Likely lives on the Sessions
  surface.
- **Laps** — per-lap browser + lap detail; the next surface to build, and the driver for the
  dense-trace persistence below. Scoped into iterations (see DECISIONS → the Laps/Analytics split):
  - *1a — persistence backbone (no UI). DONE (commit 73d2c35).* Assembler captures the player's
    setup **history** and per-lap tyre context + full car damage; `laps.py` store persists lap rows
    + Parquet trace files + setup history; `ingest_capture` writes the trace files.
  - *1b — lap view. DONE.* `analysis/traces.py` (N-series-aware trace prep); reusable lap widgets in
    `ui/components/` (tyre box, damage/setup key-value tables, `TracePlot`); the `ui/laps/` surface
    (foldable per-session cards + filter → single-lap detail page); `LapStore.list`/`load` read API;
    and the app-side ingest wiring (`IngestWorker` builds a `LapStore`). Track-country flag on cards
    deferred — no `track_id → country` map exists. Detail-view polish: the lap timing is a single
    compact row (tyre+lap · sectors · lap time · valid); trace graph zoom/pan removed (plots are
    full-height, always fit to the whole lap); throttle/brake has a colour-blind palette toggle
    (green/red ↔ Okabe-Ito blue/orange) persisted via `QSettings` (new `ui/settings.py`).
  - *2 — same-context overlay. DONE.* The lap detail page's "Compare ▾" menu overlays laps on the
    shared distance grid: scopes are the weekend's **fastest lap**, **same-session** laps, and
    **same-weekend** laps (other sessions sharing the `weekend_link_id` — same track). Every channel
    is drawn per lap with a legend (in its own row above the plots) plus a bottom **Δ-time** row (the
    racing gap vs the viewed lap, from `time_deltas`). `ui/laps/comparison.py` enumerates candidates
    (a `LapRef` per lap, labelled `Lap N - Slot`); the "Fastest" scope spans the whole weekend and is
    omitted when the viewed lap *is* the fastest. Overlaid laps differ by both **colour and line
    style** (solid/dash/dot/…) and honour the persisted colour-blind palette (Okabe-Ito). All UI
    wiring over the N-series `analysis/traces.py` — no analysis rewrite. *Next here: iteration 2b.1.*
  - *2b — g-force channel + track-layout view. DONE.* Routes the **Motion** packet (carried forward
    into each sample, like Car Status — not a hard frame-join, so a Motion-less stream still builds).
    Adds four optional `LapTrace` channels: `g_lat`/`g_long` (2026 int16 ÷ 1000; the lone
    format-divergent channel) drawn as a new `TracePlot` row, and `pos_x`/`pos_z` (world coords)
    driving a new `TrackMap` panel — an equal-aspect plotted **XY path from telemetry** (no per-track
    image assets; works for any circuit). Hover a trace → nearest sample → marker on the map (via
    `TracePlot.cursor_moved` + a pyqtgraph `SignalProxy`). `read_trace` tolerates pre-2b files, so
    old laps degrade gracefully (map/g-row omitted) without re-ingest. *Map orientation:* the
    left-handed world frame is un-mirrored by negating one axis (fixes CW/CCW); the loop is closed so
    a race lap 1 (grid past the S/F line) still draws whole. **Absolute rotation follows the game's
    world frame, not the F1.com map art** — matching broadcast orientation would need a per-track
    rotation constant, deliberately not shipped (kept asset-free); a possible later opt-in.
  - **2b.1 — canonical track-map refinement (DONE).** The map now draws the **same clean shape every
    time** for a track, decoupled from the driven line, hover intact. A **canonical centerline =
    distance-resampled median racing line** (`analysis/track_layout.build_layout`): resample each
    usable lap's `pos_x`/`pos_z` onto one shared distance grid (out-of-range → NaN), then per-point
    `nanmedian` (1000 points). Robust to excursions/defending/missed apexes, and self-heals the
    lap-1 S/F gap (other laps cover it). Valid because F1 track world coords are fixed geometry —
    laps aggregate in raw world space with no per-lap alignment (deliberately not `traces.align`,
    which would shrink to the overlap and re-open that gap). **No Motion Ex needed** for this
    median-line version; a *true geometric* centerline would need Motion Ex / track-edge / track-width
    data and stays deferred. **Scope is the whole race weekend** (a lone quali session rarely has ≥3
    valid timed laps): `ui/laps/track_layouts.TrackLayoutProvider` gathers valid Motion laps across
    the sessions sharing a `weekend_link_id` at the same `track_id`, builds the layout, and caches it
    keyed `(weekend_link_id, track_id)`. `TrackMap.set_layout` draws it; below `_MIN_LAPS` (3) usable
    laps it falls back to `set_trace` (the driven line). **Hover unchanged:** `cursor_moved` still
    emits a distance; the marker snaps to the nearest index on the canonical layout (both
    distance-indexed, same world frame). *Sector colouring — DONE (post-2c).* The Session packet
    already carries sector-boundary **distances** (`sector_2/3_lap_distance_start`) + `track_length`,
    now persisted on the session row (`track_length_m` / `sector2_start_m` / `sector3_start_m`,
    additive migration). `TrackMap` splits its outline into three coloured arcs
    (`analysis/track_layout.sector_bounds` + `SECTOR_COLOURS`, F1-map red/cyan/yellow); the traces mark
    the boundaries with dashed vertical lines every row, and a shared vertical cursor spans all trace
    rows + the map marker (clamped to the lap's distance range so hovering past the end can't stretch
    the x-axis). Always-visible map sector *labels* were tried (opaque mask, then a cut-out gap in the
    line) and removed — poor readability on complex layouts; the map uses colour alone (labels may
    return as hover/tooltips). The per-frame `sector` channel guessed at earlier proved unnecessary.
    **Corner
    numbers — future work:** no telemetry source; the clean route is a static per-track metadata
    snapshot (corner number + distance-from-S/F) transcribed from FastF1/MultiViewer
    `get_circuit_info`, keyed by our `track_id` and scaled by `track_length_m`. **Licensing:** that
    data is community/unofficial (MultiViewer; FastF1 is non-commercial/personal-use) — fine for
    private, friends-only use, but revisit/replace before any broad public distribution.
    **Priority:** deferred behind league-readiness work (packaging, GP roster import, cache
    refresh) — a visual enhancement only, not needed before the next league season.
    *Still deferred:* **Automatic cache refresh** — the provider's in-memory cache isn't
    invalidated on a mid-run re-ingest, so a stale weekend layout survives until app restart; fine
    for personal/testing use, to be made automatic before any release to friends/users (likely after
    2c, unless it bites earlier). A persisted `track_layouts/*.parquet` cache also stays deferred.
  - *2c — car-status graphic.* A car silhouette (in-game neon style, tyres as corner gauges) with
    colour-coded tyre / engine / body-damage zones. Rendered as SVG-authored `QGraphicsScene` path
    items over a Qt-free, tested `car_status.py` model; three threshold rules (tyre + engine wear
    60/80, aero/body stricter 15/40, temperatures as compound-keyed two-sided bands — see DECISIONS).
    ~90% of the data was already stored (tyre wear/damage/blisters on `LapTyreContext`; full car
    damage on `CarDamage`). **Phase A (data backbone) — DONE:** the only new ingest, the
    temperatures, is captured — tyre surface/carcass temps on `LapTyreContext`, brake/engine temps on
    `CarDamage`, snapshotted at the lap boundary from the carried-forward Car Telemetry entry
    (`tyres_surface_temperature` / `tyres_inner_temperature` / `brakes_temperature` /
    `engine_temperature`; requires re-ingest). **Phase B (threshold model) — DONE:** Qt-free
    `car_status.py` (`damage_parts` / `tyre_corners`), unit-tested. **Phase C (widget) + visual polish
    — DONE.** `CarStatusGraphic` renders the car — Inkscape-traced body regions, chassis/nose outline,
    floor-edge wings and front suspension — coloured by the model with per-part tooltips, plus four
    procedural corners (on-car tyre + inboard brake block + dashed connector to a wear/temp corner gauge),
    wired below the tyre box on the detail page. The `_svg_path` parser was extended to the full Inkscape
    command set (S/T smooth curves, A arcs; `test_svg_path.py`) so parts are authored visually — see the
    Inkscape workflow + `docs/car_template.svg` in DECISIONS. *Optional later:* fold
    `tyre_box._wear_color` into `car_status` (shared 60/80 rule).
- **Analytics** — the genuinely cross-session work: same-track-different-season lap comparison,
  lap-time trends, AI-difficulty analysis, team-performance trends, ERS-deployment views. (The
  single-lap and same-context overlay graphs moved into the Laps surface — see above.) In-memory
  `LapTrace` analytics stay desktop-bound regardless of any web future.
- **Dashboard** — recent sessions / summaries (the record header already lives above it).

## Packaging (before sharing a built app with colleagues)
- **A single writable data root (`data_root()`), not CWD-relative paths.** Today `captures/`,
  `rosters/`, and the SQLite DB are all bare relative paths (`Path("captures")`,
  `SeasonRosterFiles(root="rosters")`, the DB path), resolved against the *current working
  directory*. Fine in dev (launched from the workspace root); broken once frozen
  (PyInstaller/briefcase), where the code lives inside a read-only bundle and CWD is
  unpredictable. Add one helper that returns the OS per-user data dir when packaged
  (`QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)` → `~/.local/share/…`,
  `%APPDATA%\…`, `~/Library/Application Support/…`) and the repo folder in dev, then route
  captures, rosters, and the DB through it *together*. `SeasonRosterFiles` already takes an
  injectable `root`, so it's ready for this.
- **Auto-update + version-gated data backfill (two *separate* concerns).**
  - *Auto-update (distribution):* GitHub Actions builds per-OS frozen artifacts, publishes a
    Release; the app checks the Releases API on startup and an updater downloads/swaps the build.
    Rougher in Python than the C#/ClickOnce world — a real option is `tufup` (TUF-based). Per-OS
    fiddly; packaging-time work.
  - *Data backfill:* `ensure_schema` adds a new column but can't fill a *capture-derived* value in
    old rows (e.g. `nationality_id`, upcoming `best_lap_num`) — those need re-deriving from the
    capture. For end users with many sessions, manual re-ingest is painful. Plan: store a
    "backfill version" in a metadata table; on startup, if the app expects a higher version, run a
    **background, non-blocking, idempotent** re-ingest of retained captures (reuse the
    `IngestWorker` pattern, show progress) — *not* a startup gate. Already safe to automate: ingest
    replaces by uid, tombstones aren't resurrected, round assignments survive (no FK). Best-effort:
    only sessions whose capture still exists can be back-filled (surface "N of M updated").
    Decoupled from auto-update — it matters even with manual updates. Lever: persisting more
    capture-derived data now means fewer future columns need a capture-reparse backfill (some
    become fast pure-SQL migrations instead).

## Storage & analysis
- **Reconstructed-race points — accept / edit / store (Option 3, deferred).** Option 2 shipped:
  a missing Final Classification packet yields a reconstructed classification
  (`Classification.is_reconstructed`), badged in the UI, with a **muted, display-only** points
  estimate and **excluded from standings** (see DECISIONS, TELEMETRY_NOTES). Option 3 adds the
  human-in-the-loop half: an **accept/edit workflow** to confirm or hand-correct the estimated race
  points (persisted, distinct from game-reported), a **manual editor** for the points cells, and
  **re-including** the confirmed values in `compute_standings` / `compute_constructor_standings`.
  Needs a points-source distinction on the entry and belongs with **league-management** (per-league
  scoring tables) — until then estimates never reach a championship.
- **Dense-trace persistence (in progress — lap-view iteration 1a).** Store `LapTrace`s as
  **Parquet** files referenced by the lap row (~5,400 samples/lap at 60 Hz — not SQLite rows; npz
  was the alternative, Parquet chosen — see DECISIONS), plus an ingest entry point that writes
  them. Lands with the new `laps.py` store, per-lap tyre context, and the session setup history.
- **`storage/migrations.py` — `ensure_schema(engine)`. DONE.** Landed with the first additive
  column (`nationality_id`), not trace storage: inspects tables and `ADD COLUMN`s anything the ORM
  defines but the DB lacks, wired into `SessionStore` after `create_all`, idempotent. New additive
  columns must carry a `server_default` so the ADD COLUMN back-fills existing rows. Note this only
  creates the column — filling a *capture-derived* value in old rows still needs a re-ingest (see
  Packaging → data backfill).
- **Alembic.** Adopt at the first *non-additive* migration (rename / type change / drop /
  backfill). Until then, additive-only + `ensure_schema`.
- **Complete `DRIVER_NAMES`.** The AI driver-id table is partial (~11 entries); fill it from the
  spec appendix so AI driver-id lookups resolve. `diagnose_participants.py` surfaces which ids
  are still unresolved.

## Capture compression
- **Done — the hybrid landed.** Ingest is archive-first (`pipeline.archive_and_ingest`): compress
  the raw to `.f1cap.zst` first, ingest *from* the archive (checksum-verified end-to-end), delete
  the raw only on success — a failed ingest keeps both raw and archive. New archives are **zstd**
  (level 3: ~18% smaller than gzip-6 and several times faster; benchmarked); existing `.f1cap.gz`
  stay readable and are ingested in place. Capture **metadata is in the DB** (`captures` +
  `capture_sessions`, `CaptureStore`, keyed by a codec-independent content hash) so captures are
  queryable without decompressing. The diagnostic tools read through `open_capture`. See
  ARCHITECTURE → Capture compression and DECISIONS → Storage.
- **Next — league capture import.** Build on the metadata table: an "import new captures from a
  shared folder" flow (dedupe on content hash, `CaptureStore.known_files()` pre-filter, populate
  `recorded_by`). This is the shared-league-data direction; see DECISIONS → Storage.
- **Deferred loose end:** `recorded_by` is plumbed through `ingest_capture` / `CaptureMeta` but
  never set — no UI/QSetting wires it yet. It's the one capture field a re-ingest can't backfill
  (it isn't in the file), so the column exists now; wiring waits for the import flow above.

## Possible, uncertain
- **Hosted multi-user league platform** — signup / authorization, colleagues upload their own
  results. Would be additive: reuse the version-agnostic domain + storage; the schema is already
  kept engine-agnostic (SQLite → Postgres only if this happens). Nothing current depends on it.
- **Mobile / web access** for colleagues — a long-term direction, not planned.
