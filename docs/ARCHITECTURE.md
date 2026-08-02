# Architecture

## The pipeline

```
Sources ─► Parser (+registry) ─► versioned wire structs ─► Normalizer ─► Session Assembler ─► Storage ─► Analysis ─► UI
                                     (v2025 / v2026)         (pure)         (stateful)         (SQLite)
```

The single organising idea: **the 2025-vs-2026 difference lives only at the bottom** — the
wire structs and the parser that decodes them. Format is detected per packet from
`header.packet_format` and dispatched on `(packet_format, packet_id)` via a registry dict.
From the **Normalizer up, everything is version-agnostic** and never branches on format. Adding
a future format = a new struct submodule + registry entries; nothing downstream changes.

## Layers

### ingest/ — bytes in, bytes/packets out
- **`recording.py`** — the `.f1cap` capture format. Header: magic `b"F1TELCAP"` + `uint16`
  format version. Then records of `double recv_time` (unix seconds) + `uint32 length` +
  `length` payload bytes. Length-prefixed to preserve UDP datagram boundaries (the parser
  decodes one whole datagram at a time); timestamped so realtime replay reproduces original
  timing. `read_header` / `read_packet` (and the writer) live here.
- **`recorder.py`** — `SessionRecorder`: binds `0.0.0.0:20777` (via `LiveUDPSource`), writes
  datagrams to a `.f1cap`. Cooperative stop via a `threading.Event` checked at each
  socket-timeout cycle. (The Qt wrapper is `RecorderWorker` in `ui/workers.py`.)
- **`sources.py`** — `PacketSource` ABC; `LiveUDPSource`; `FileReplaySource` (realtime or fast).
  Opens files through `archive.open_capture`, so it replays `.f1cap`, `.f1cap.gz`, and
  `.f1cap.zst` alike.
- **`archive.py`** — capture compression (see [Capture compression](#capture-compression)):
  `archive_capture` writes a capture in a chosen codec (`CODEC_*`; new archives default to zstd),
  `open_capture` opens any form transparently by suffix, `capture_codec` /
  `is_compressed_capture` / `compressed_capture_path` are the naming helpers, and `HashingReader`
  hashes+sizes the decompressed payload as it streams past (the capture's codec-independent id).
- **`inspect.py`** — diagnostic CLI (`python -m f1telemetry.src.ingest.inspect <capture>`):
  per-`(format, packet_id)` tally, byte total, and duration for one capture. Reads through
  `open_capture`, so it handles raw, gzip, and zstd captures alike.

### protocol/ — datagrams into typed packets
- **`base.py`** — `_Struct` = a packed `LittleEndianStructure`.
- **`header.py`** — the packet header (29 bytes), identical across formats:
  `packet_format`, `packet_id`, `session_uid`, `player_car_index`, `frame_identifier`, …
- **`enums.py`** — `PacketId`, `SessionType`, `ResultStatus`, `ResultReason`, `Formula`,
  `Weather`, tyre/ERS enums, and `safe_enum(EnumCls, value)` → member or raw int (enums grow).
- **`reference.py`** — id→name lookups: `track_name`, `team_name`, `driver_name`,
  `nationality_name`, backed by `TEAM_NAMES` / `DRIVER_NAMES` (both complete against the F1 25 v3
  and 2026 season-pack specs as of 2026-08-02). Unknown ids return `"Unknown … (n)"`.
- **`registry.py`** — `build_registry()` maps `(format, packet_id)` → struct class.
- **`parser.py`** — `PacketParser.parse(payload)`: reads the header, looks up the struct,
  checks `len(payload) == sizeof(struct)`, returns the typed packet (or `None`); tracks
  `parsed` / `skipped_unknown` / `skipped_malformed`.
- **`v2025/structs.py`, `v2026/structs.py`** — the per-format `ctypes` layouts.

### domain/ — version-agnostic models + pure conversion
- **`models.py`** — frozen dataclasses: `SessionResult` (metadata, hierarchy keys, roster,
  laps, classification, `game_mode`), `Participant`, `Classification` (carries `is_reconstructed`
  — True when synthesized from telemetry because no Final Classification packet arrived),
  `ClassificationEntry`
  (incl. `race_number` and `is_ai` — AI vs human, which league identity resolution depends on),
  `TyreStint`, `Lap`, `LapTrace` (parallel numpy arrays, distance-indexed).
  `LapTrace` also carries four **optional** motion channels — `pos_x`, `pos_z`, `g_lat`, `g_long`
  (iteration 2b) — None on laps captured without the Motion packet (`OPTIONAL_CHANNELS`, kept
  distinct from the nine required `CHANNELS` so `analysis/traces.py` and the overlay are unaffected).
- **`normalizer.py`** — pure, stateless: `normalize_session`, `normalize_participants`,
  `normalize_classification`, `reconstruct_classification` (best-effort classification from Lap
  Data + Session History when no Final Classification packet arrived; sets `is_reconstructed`),
  `merge_participant` (roster union across frames),
  `telemetry_sample`, `build_trace`, and the `Sample` tuple. Reads struct fields by name; the
  field-name contract is documented in the module docstring.
- **`season.py`** — the user-authored season layer: `SeasonMode` (MY_TEAM / DRIVER_CAREER /
  GRAND_PRIX / LEAGUE — *our* categorisation, not the game's `m_gameMode`), `Season`,
  `SeasonRound`, `RoundResults`.
- **`calendars.py`** — `official_calendar(year)` preset track-id orders for 2025 / 2026.
- **`roster.py`** — `LeagueMember`, `LeagueRoster.member_for(entry)` / `member_of(entry)` /
  `member_key(entry)` (online-name-first, race-number fallback **for human cars only**) and
  `session_keys(entries)` — the classification-wide resolver standings use, which guarantees two
  cars in one session never share a row. `is_ai_entry` / `looks_like_ai` separate the game's own
  AI flag from the `DRIVER_NAMES` fallback for rows stored before `is_ai` was captured.
  `league_display_name(entry,
  roster)` (captured public alias first, roster `online_names[0]` fallback for `"Player"`/blank),
  `load_roster` / `save_roster`, CSV import parsing, roster seeding from round results, and
  roster merging. CSV remains an import format; `rosters/season_<id>.json` is the canonical app
  file. In roster data, `name` is a helper/canonical identity while `online_names` are the league
  display aliases.

### session/ — the stateful sequencer
- **`assembler.py`** — `SessionAssembler` / `_SessionBuilder` / `assemble(packets)`. Splits the
  stream into sessions on `session_uid`; within a session it:
  - **accumulates the roster across all Participants frames** (union by vehicle index via
    `merge_participant`) — the fix for the classification join miss (see TELEMETRY_NOTES);
  - joins the player's Lap Data + Car Telemetry rows by `frame_identifier` into trace `Sample`s,
    splits laps on `current_lap_num`, keeps a trace only if it started near the line;
  - takes lap **timing from Session History** (authoritative), not live Lap Data;
  - captures the **final classification** from the Final Classification packet; if none arrived,
    falls back to `reconstruct_classification` (last Lap Data frame + per-car Session History),
    setting `Classification.is_reconstructed`;
  - carries the player's latest Car Status ERS fields forward into each sample;
  - *(lap-view iteration 2b)* carries the player's latest **Motion** entry forward into each sample
    (world position + g-force, format-normalized via `motion_sample`), adding the track-map /
    g-force `LapTrace` channels; carry-forward (not a hard frame-join) so a Motion-less stream
    still builds laps;
  - *(lap-view iteration 1a)* diffs the player's **Car Setups** packet to build a `setup_history`
    (a new snapshot stamped with the current lap whenever the setup changes), and snapshots per-lap
    **tyre context** + full non-tyre **car damage** at each lap boundary (compound/age from Car
    Status, wear/damage from Car Damage; *(iteration 2c)* tyre surface/carcass temperatures on the
    tyre context and brake/engine temperatures on the car damage, read from the carried-forward Car
    Telemetry entry);
  - *(fuel fix)* captures per-lap **start-of-lap fuel** (`Lap.fuel_in_tank`) from Car Status
    `fuel_in_tank` — the first finite fuel reading of the lap's selected timed run (the run trimming
    already drops the formation lap / out-laps / in-laps, so this is fuel at the racing S/F line,
    falling lap by lap). Distinct from the static garage `Setup.fuel_load`, which is no longer shown
    as live fuel;
  - emits one `SessionResult` per session (the last flushed at stream end).

### storage/ — SQLite persistence (repository-per-aggregate)
- **`schema.py`** — the shared SQLAlchemy table layer.
- **`sessions.py`** — `SessionStore`: persists classification + session metadata + `game_mode`;
  `session_uid` stored as TEXT (uint64 high-bit); tyre stints as a JSON column; enums as raw
  ints → `safe_enum` on load; `save()` is idempotent (replace-by-uid).
- **`seasons.py`** — `SeasonStore`: create/get/list/delete seasons, `set_calendar`,
  `assign_session` / `unassign_session`, `assignments_for_season`,
  `rounds_with_results(season_id, session_store)`. Tables: `seasons`, `season_rounds`,
  `session_assignments`. **`session_assignments.session_uid` is NOT a FK** to `sessions`, so
  re-ingest never wipes manual placements.
- **`laps.py`** *(lap-view iteration 1a; read API 1b)* — `LapStore`: persists the player's laps and
  their per-lap tyre context (and per-lap start-of-lap fuel, the additive-nullable `fuel_in_tank`
  column), with each lap's dense `LapTrace` written to a **Parquet file**
  referenced by the lap row (not SQLite rows — see DECISIONS). Write: `save_laps` (replace-by-uid,
  rows + files) / `delete`. Read: `list(uid)` returns a session's laps **without** their traces
  (cheap, for the overview), `load(uid, lap_number)` returns one fully-hydrated lap **with** its
  trace (detail page; the iter-2 overlay calls it per selected lap), `load_laps(uid)` the full set.
  The session's setup **history** (`setup_history`) is a JSON column on the session row, not a lap
  concern. Repository-per-aggregate (own table cluster; `schema.py` stays the shared layer).
- **`captures.py`** *(hybrid capture storage)* — `CaptureStore` over `captures` +
  `capture_sessions`: what recordings exist, what sessions each holds, and where each was last
  seen — so a capture is queryable without decompressing it. Keyed by a **content hash of the
  decompressed payload** (codec-independent, so a gzip→zstd re-archive keeps its identity);
  `record` is replace-by-hash (idempotent re-import). `for_session(uid)` is the backfill
  re-ingest lookup; `known_files()` is the cheap name+size pre-filter for a folder scan. The
  `capture_sessions` list includes sessions ingest *skipped* as tombstoned — it describes the
  file, not the store's curation of it. `session_uid` is deliberately not a FK (mirrors
  `session_assignments` / `laps`). `recorded_by` is plumbed but unset (reserved for league import) —
  a re-ingest feeds the stored value back so it isn't erased.
- **`meta.py`** *(packaging Phase 2)* — `MetaStore` over a `meta` key/value table: app-level state
  that belongs to no aggregate. Today one key, `pipeline_version` — the `PIPELINE_VERSION` the
  stored *derived* data was produced by, compared on startup against this build's to offer a guided
  re-ingest. A table rather than SQLite's `PRAGMA user_version` because the schema is kept
  engine-agnostic, and a new table needs no migration. A corrupt/unparseable value reads as
  unstamped rather than crashing start-up.
- Stores are context managers (dispose the engine on exit).
- **Filesystem paths** — all *writable* data (DB, `captures/`, `lap_traces/`, `rosters/`, `logs/`,
  `config.json`) and bundled *read-only* assets (the flag SVGs) resolve through **`src/paths.py`**,
  the single path authority: `data_root()` is the CWD in dev (unchanged) and a per-user dir when
  frozen, with `F1TELEMETRY_DATA_DIR` overriding both; `resource_path()` is `_MEIPASS`-aware. The
  app entry points (`MainWindow`, `IngestWorker`, `SeasonRosterFiles`) route through it; callers
  never hard-code these locations. See [`docs/PACKAGING.md`](PACKAGING.md).

### analysis/ — derived facts
- **`standings.py`** — `StandingRow`; `by_driver_name` / `by_race_number` keys;
  `compute_standings(sessions, key, display, group)`; `standings_for_rounds`;
  `league_standings_for_rounds(rounds, roster)`. Points sum across race-type sessions only 
  (RACE_SESSION_TYPES); the game leaves stale last-race points in non-race classifications' 
  m_points, so other session types are skipped. **Reconstructed classifications
  (`is_reconstructed`) are also skipped** — they have no official points (only a UI estimate), so
  they never enter a championship until an accept/confirm flow lands (Option 3, see ROADMAP).
  LEAGUE driver standings resolve through the per-season roster's `session_keys` (`group=`, a
  whole classification at a time — race numbers are unique only among humans) and display via
  `league_display_name`; AI drivers keep their own rows rather than being filtered; non-league
  seasons stay name-keyed. Constructor standings aggregate captured in-game `team_id`s. Lap/trace analytics are intentionally
  in-memory and desktop-bound.
- **`traces.py`** *(lap-view iteration 1b)* — trace preparation for plotting, pure numpy: an
  `AlignedTrace` value object plus `shared_distance_grid` / `resample` / `align` (resample N traces
  onto one shared distance grid; discrete channels — gear/DRS/ERS mode — are rounded), `elapsed_time`
  / `time_delta` / `time_deltas` (the racing "gap" trace, integrated from speed over distance), and
  `downsample` (stride-decimate parallel arrays for the chart). **N-series-aware** (every entry point
  takes a *list* of traces) — exactly what the iteration-2 overlay is built on: the overlay/delta are
  pure UI wiring over `align` + `time_deltas`, with no change to this module.
- **`track_layout.py`** *(lap-view iteration 2b.1)* — the canonical track-map builder, pure numpy: a
  `TrackLayout` value object plus `build_layout(traces)` — resample each lap's `pos_x`/`pos_z` onto
  one shared distance grid (min-start..max-end, out-of-range → NaN so a lap doesn't vote past its
  span) and take the per-point `nanmedian`, giving one clean median racing line per track. Robust to
  single-lap excursions and self-heals the lap-1 S/F gap; returns `None` below `_MIN_LAPS` (3) so the
  caller falls back to the driven line. Deliberately *not* built on `traces.align` (which shrinks to
  the laps' overlap and would re-open that gap). Store-free — the weekend lap gathering lives in
  `ui/laps/track_layout.py`.

### ui/ — PySide6, single window
- **`app.py`** — builds the `QApplication`, launches the shell.
- **`main_window.py`** — the `QMainWindow` shell: a sidebar (`QListWidget`), a **persistent
  record/stop header** shown on every page, and a `QStackedWidget` that swaps pages in place.
  The window **owns the recorder/ingest workers and the UI-side stores** (disposed on close).
- **`season_roster.py`** — UI-side roster file convention helper (Qt-free, so unit-testable):
  path calculation for `rosters/season_<id>.json` and the load/seed/persist split —
  `roster_for` loads the saved file or returns an in-memory capture seed (read-only, so a view
  never writes), while `create_from_captures` and `import_csv` are the explicit writes.
  Previous-season merge is only computed when seeding, via a lazy `all_seasons` callable. Kept
  out of storage because rosters are files, not DB rows.
- **`components/`** — shared, view-agnostic widgets so every surface renders the same way
  instead of rebuilding tables inline. `tables.py` holds the pure Qt primitives (`cell`,
  `tidy_table`, `fit_table_height`, `clear_layout`); `classification_table.py` holds
  `build_classification_table(session, name_of, is_sprint_race)` — the results grid shown for one
  session (race vs best-lap columns); for a **reconstructed** race it renders a muted, display-only
  points estimate (`~25`, GP/sprint table by `is_sprint_race`) in place of official points — plus
  `display_name_fn(roster)`, the roster→name resolver passed
  as `name_of`. The weekend view composes the table from here today; the future Sessions / Laps
  surfaces reuse the same builder.
  The lap-detail widgets also live here: `damage_panel.py` (`build_damage_table` over the Qt-free
  `damage_rows`, rendered via `tables.build_kv_table` — a shared key/value table with bold section
  headers), `setup_panel.py` (`build_setup_table` over the Qt-free `setup_fields`, rendered as
  slider rows via `slider_row.py`'s `SetupSliderRow` / `SliderMarkerBar`; the field list and
  in-game ranges live in `_SETUP_SPEC`), and `trace_plot.py` (`TracePlot` — stacked, distance-linked telemetry via
  pyqtgraph, lazily imported so it degrades to an install hint if absent). `set_traces` draws either
  one lap (per-channel colours, the 1b look) or an **overlay** of several: aligned on a shared grid,
  coloured *and* dash-styled per lap, with a legend row above the plots and a bottom Δ-time row;
  `set_colorblind` swaps in the Okabe-Ito palette (persisted via `ui/settings.py`) for both modes.
  A g-force row is appended when the lap carries Motion, and `TracePlot` emits `cursor_moved` (the
  mouse-x mapped to a lap distance, via a pyqtgraph `SignalProxy`). `track_map.py` (`TrackMap`,
  iteration 2b) is the track-layout panel: an equal-aspect XY path plotted from `pos_x`/`pos_z` (no
  track-image assets — works for any circuit), with a marker driven by `cursor_moved`. `set_layout`
  draws the canonical median line for the track (iteration 2b.1); `set_trace` is the driven-lap
  fallback; both share a `_render` that negates one axis to correct the left-handed world frame's
  mirror and closes the path loop so a race lap 1 (grid past the S/F line) still draws a complete
  outline.
  The car-status graphic (iteration 2c) is a two-part split: `car_status.py` is a **Qt-free model**
  (`damage_parts` / `tyre_corners` map a lap's `CarDamage` + `LapTyreContext` onto per-part
  `Status` + colour via three threshold families — wear 60/80, aero 15/40, compound-keyed temp
  bands; unit-tested in `test_car_status.py`), and `car_status_graphic.py` (`CarStatusGraphic`) is
  the thin renderer over it: an in-game-style top-down car whose body regions and four corner tyre
  gauges are drawn as `QGraphicsPathItem`s and recoloured from the model, with native per-part
  tooltips. Body/structural shapes are authored in Inkscape as SVG path `d` strings parsed into
  `QPainterPath`s (`_svg_path` — full M/L/H/V/C/S/T/A/Z, abs+rel; `test_svg_path.py`), grouped by
  render style (`_BODY_PARTS` damage-coloured, `_STRUCTURAL` faint fill, `_PANELS` solid fill,
  `_OUTLINES` stroke-only, `_ARMS` suspension); the four corners (on-car tyre + inboard brake block +
  dashed connector + wear/temp gauge) are drawn procedurally from `_CORNERS` / `_TYRE_*` / `_BRAKE_*`.
  The SVG-authored → QGraphicsScene path-item approach from DECISIONS; authoring template in
  `docs/car_template.svg`.
- **`seasons/`** — the seasons surface, split into a thin container plus one widget per page.
  `view.py` holds `SeasonsView`: it owns a `QStackedWidget` of the four pages (overview → create
  → detail → weekend) and does nothing but wire their **navigation signals** to page switches —
  each page owns its own widgets, its own route state (e.g. the loaded season/round id), and its
  own data operations (create, delete, assign, roster create/import). Pages never reference
  siblings; they emit intent (`season_requested`, `weekend_requested`, `create_requested`,
  `cancelled`, `overview_requested`, `detail_requested`) and the container decides what shows.
  One signal is deliberately **not** navigation: `sessions_changed`, emitted by the weekend page
  when its delete action removes a session's stored results and re-emitted by `SeasonsView` for
  `MainWindow` to fan out. It exists because other surfaces derive cached state from those rows
  (the laps surface's canonical track map), and the same no-sibling-references rule means the
  weekend page cannot invalidate that itself.
  A `_show_*` switches the page first, then calls its `load`/`reload`, so a vanished-target
  fallback signal re-navigates last and wins. Pages: `overview_page.py` (season cards / empty
  state + delete), `create_page.py` (the form + create), `detail_page.py` (calendar + standings +
  LEAGUE roster panel), `weekend_page.py` (round-centric session assignment: a capture picker
  filtered to the round's track, plus each assigned session's foldable classification).
  `labels.py` holds the shared `mode_label` / `format_label` / `season_title` helpers.
  LEAGUE detail/weekend pages are roster-aware: they load-or-seed the season JSON read-only, offer
  a "Create roster file" button and CSV import, use `league_standings_for_rounds`, and render
  names through `display_name_fn` (captured public alias first, roster `online_names` fallback)
  injected into `race_winner_summary` and the classification tables built via `components/`.
- **`laps/`** — the Laps surface, same thin-container pattern as `seasons/`: `view.py` (`LapsView`)
  owns a `QStackedWidget` of two pages and wires their navigation signals. `overview_page.py` lists
  foldable per-session cards (track + session label header, lap-count/best/recorded meta; expand →
  the session's laps with time + tyre + validity; double-click a lap → detail) with a track/session
  filter + valid-only toggle, reading laps cheaply via `LapStore.list`. `detail_page.py` loads one
  lap via `LapStore.load` and composes the `components/` lap widgets. The left column holds the
  `CarStatusGraphic` (iteration 2c — it replaced the removed `TyreBox` in the post-2c polish, and
  carries tyre age on its title line with blisters/tyre damage in the corner-gauge tooltips); the
  right holds the damage and setup tables (setup resolved by `SessionResult.setup_for_lap`); below
  sits the `TracePlot`.
  When the lap carries Motion it also shows a `TrackMap` panel, wired to the plot's `cursor_moved`
  signal so hovering a trace moves the marker round the circuit (iteration 2b). The map draws the
  **canonical median line** for the whole race weekend when available (iteration 2b.1), falling back
  to the driven lap's own line; `track_layout.py` (`TrackLayoutProvider`, Qt-free) does the
  cross-store walk — every valid Motion lap across the sessions sharing this one's `weekend_link_id`
  at the same `track_id` — feeds them to `analysis.track_layout.build_layout`, and caches the result
  keyed `(weekend_link_id, track_id)`. Its
  "Compare ▾" menu (iteration 2) lists candidate laps from `comparison.py` and drives `TracePlot`'s
  overlay; `comparison.py` (Qt-free, unit-tested) enumerates them by scope — weekend-fastest,
  same-session, same-weekend — as `LapRef`s loaded on demand via `LapStore.load`. Session uids travel
  through signals as `str` (uint64-safe). Track-country flags are deferred (no `track_id → country`
  map exists yet).
- **`workers.py`** — `RecorderWorker` / `IngestWorker` (`QThread`s). `IngestWorker` builds its own
  `SessionStore`, `LapStore`, **and** `CaptureStore` in-thread (SQLite dislikes cross-thread
  connections) and calls `pipeline.archive_and_ingest`, so app-side ingest archives the capture,
  writes laps + Parquet traces (under an injectable `trace_dir`, which the app supplies from
  `paths.trace_dir()`),
  and records capture metadata — not just the classification. All three stores are disposed in a
  single `finally`. It's a thin wrapper: the archive/ingest/delete ordering lives in the pipeline.
- **`formatting.py`** — Qt-free presentation helpers (winner time / gap / +laps / status;
  best-lap-or-status; `is_race`, `slot_label`), unit-testable without importing PySide6.
- **`pipeline.py`** (`src/pipeline.py`) — the Qt-free ingest orchestration, extracted so it's
  testable without Qt: `ingest_capture(path, store, ...)` (parse → assemble → persist, plus the
  capture-metadata scan) and `archive_and_ingest(...)` (the archive-first flow the worker wraps —
  see [Capture compression](#capture-compression)). *(Packaging Phase 2)* it also owns the
  pipeline-version gate and the guided rebuild: `check_pipeline_version(meta_store, session_store)`
  → `PipelineState` (CURRENT / UPGRADE_AVAILABLE / AHEAD, adopting an unstamped *empty* database),
  and `reingest_all(...)` → `ReingestSummary`, which re-derives every stored session from the
  capture archives `captures` enumerates. It ingests archives **in place** (`ingest_capture`, never
  `archive_and_ingest`: nothing re-compressed, nothing deleted), resolves each capture through
  `resolve_capture_path` (recorded path → captures-dir fallback, since `CaptureRow.path` is
  advisory), skips a capture whose archive is gone rather than failing, and polls its `cancelled`
  predicate **between** captures so a session is never left half-written. Idempotent and resumable:
  replace-by-uid + replace-by-hash, and the no-FK invariants mean rebuilding derived rows never
  touches standings, round placements or rosters.
  It also owns the **missing-capture prune**, split read-from-write so the user confirms a list
  before anything is forgotten: `find_missing_captures(...)` → the `CaptureMeta`s
  `resolve_capture_path` can no longer find (the same definition of "missing" `reingest_all`
  reports), and `prune_missing_captures(...)` → `PruneSummary`, which drops those `captures` rows
  (children by cascade) so a re-ingest stops listing archives that will never come back. It
  **re-resolves every hash at delete time** rather than trusting the caller's list, keeping
  anything that turned up meanwhile; it touches no file and no session. See DECISIONS → Storage.

## Capture compression

Captures record uncompressed (the recorder appends raw datagrams as they arrive), then ingest is
**archive-first** (`pipeline.archive_and_ingest`, wrapped by `IngestWorker`):

1. **Archive the raw first**, keeping the original — `archive_capture(path, remove_original=False)`
   writes `<name>.f1cap.zst` (via a `.tmp` file + atomic `os.replace`).
2. **Ingest the archive.** The decompressor verifies the archive's own frame checksum end-to-end
   as `ingest_capture` streams it to EOF, so a corrupt archive fails the ingest.
3. **Delete the raw only after a successful ingest** — never before its bytes are proven readable
   in the archive.

Key properties:

- **A failed ingest keeps both files.** The raw survives for debugging *and* a small archive
  exists to upload/share — this is the one capture most worth sending. Archiving is non-fatal too:
  if compression itself fails, the raw is ingested directly and kept, and the UI says so. An
  existing destination is never overwritten (`FileExistsError`).
- **New archives are zstd (level 3); gzip stays readable forever.** `capture_codec` dispatches
  `open_capture` on the suffix, and `FileReplaySource` goes through it — so replay, re-ingest, and
  the file-picker work on `.f1cap`, `.f1cap.gz`, and `.f1cap.zst` alike. zstd-3 was benchmarked as
  ~18% smaller than gzip-6 *and* several times faster to write (the flat knee of the ratio curve).
  The `.f1cap` record framing is unchanged; compression is a pure outer wrapper.
- **An already-archived input is ingested in place** — re-ingesting a `.gz`/`.zst` re-compresses
  nothing and deletes nothing.
- **Capture metadata comes free from the ingest read.** `HashingReader` wraps the decompression
  stream, so a capture's content hash (over the *decompressed* payload — codec-independent) and
  payload size fall out of the pass ingest already makes; `CaptureStore` records them (plus the
  sessions the file holds) without a second decompression. This is the base for a future "import
  league captures from a folder" flow (dedupe on hash, `known_files()` pre-filter). See
  DECISIONS → Storage and ROADMAP.

## Threading

Recording and ingest run on `QThread`s so the UI stays responsive. SQLite dislikes a connection
shared across threads, so the **`IngestWorker` creates its own stores in-thread** (session, lap,
capture — disposed in a `finally`), while the UI reads through stores owned by the main window on
the GUI thread — both pointing at the same database file. The recorder's cooperative stop is an `Event` checked each socket-timeout cycle.
That cycle is also the recorder's own health check: `LiveUDPSource` asks for a large `SO_RCVBUF`
(the OS default — 64 KB on Windows — holds only ~0.3 s of stream, so a descheduled process loses
everything past it) and warns when one iteration runs far longer than the socket timeout, which
distinguishes *we weren't running* from *the game wasn't sending*. `RecorderWorker.run` wraps the
capture loop in `keep_awake()` (`src/keep_awake.py`) so the machine can't sleep mid-recording — a
recorder is often the only thing a machine is doing, and a slept machine receives nothing at all
because the NIC goes down with it. The request lives on the worker thread because
`SetThreadExecutionState` is per-thread; it is a no-op off Windows.

**`ReingestWorker`** (packaging Phase 2) follows the same shape for the guided rebuild: its four
stores (session, lap, capture, meta) are built on its own thread and disposed in one `finally`, it
reports `progress(index, total, file_name)` to a modeless progress dialog, and its cooperative stop
is a `threading.Event` polled between captures — a capture is never interrupted mid-way, so the
store never holds a partial session. It writes the new `PIPELINE_VERSION` stamp only when the pass
completed without errors or a cancel. `MainWindow` disables the record/ingest controls while it
runs, so there is never a second writer.

## Invariants (see also CLAUDE.md and DECISIONS.md)

- Distance-indexed traces; format isolation at the parser; roster accumulation across frames;
  vehicle-index joins; session split on `session_uid`; non-FK session assignments; slot derived
  from `session_type`; enums via `safe_enum`.
