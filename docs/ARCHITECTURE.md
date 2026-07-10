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
  Opens files through `archive.open_capture`, so it replays `.f1cap` and `.f1cap.gz` alike.
- **`archive.py`** — capture compression (see [Capture compression](#capture-compression)):
  `archive_capture` gzips a capture, `open_capture` opens either form transparently,
  `is_compressed_capture` / `compressed_capture_path` are the naming helpers.
- **`inspect.py`** — diagnostic CLI (`python -m f1telemetry.src.ingest.inspect <capture>`):
  per-`(format, packet_id)` tally, byte total, and duration for one capture. Reads through the
  same recording layer as the analysis, so corruption surfaces the same way here as downstream.

### protocol/ — datagrams into typed packets
- **`base.py`** — `_Struct` = a packed `LittleEndianStructure`.
- **`header.py`** — the packet header (29 bytes), identical across formats:
  `packet_format`, `packet_id`, `session_uid`, `player_car_index`, `frame_identifier`, …
- **`enums.py`** — `PacketId`, `SessionType`, `ResultStatus`, `ResultReason`, `Formula`,
  `Weather`, tyre/ERS enums, and `safe_enum(EnumCls, value)` → member or raw int (enums grow).
- **`reference.py`** — id→name lookups: `track_name`, `team_name`, `driver_name`,
  `nationality_name`, backed by `TEAM_NAMES` / `DRIVER_NAMES` (the driver table is partial —
  see ROADMAP). Unknown ids return `"Unknown … (n)"`.
- **`registry.py`** — `build_registry()` maps `(format, packet_id)` → struct class.
- **`parser.py`** — `PacketParser.parse(payload)`: reads the header, looks up the struct,
  checks `len(payload) == sizeof(struct)`, returns the typed packet (or `None`); tracks
  `parsed` / `skipped_unknown` / `skipped_malformed`.
- **`v2025/structs.py`, `v2026/structs.py`** — the per-format `ctypes` layouts.

### domain/ — version-agnostic models + pure conversion
- **`models.py`** — frozen dataclasses: `SessionResult` (metadata, hierarchy keys, roster,
  laps, classification, `game_mode`), `Participant`, `Classification`, `ClassificationEntry`
  (incl. `race_number`), `TyreStint`, `Lap`, `LapTrace` (parallel numpy arrays, distance-indexed).
  `LapTrace` also carries four **optional** motion channels — `pos_x`, `pos_z`, `g_lat`, `g_long`
  (iteration 2b) — None on laps captured without the Motion packet (`OPTIONAL_CHANNELS`, kept
  distinct from the nine required `CHANNELS` so `analysis/traces.py` and the overlay are unaffected).
- **`normalizer.py`** — pure, stateless: `normalize_session`, `normalize_participants`,
  `normalize_classification`, `merge_participant` (roster union across frames),
  `telemetry_sample`, `build_trace`, and the `Sample` tuple. Reads struct fields by name; the
  field-name contract is documented in the module docstring.
- **`season.py`** — the user-authored season layer: `SeasonMode` (MY_TEAM / DRIVER_CAREER /
  GRAND_PRIX / LEAGUE — *our* categorisation, not the game's `m_gameMode`), `Season`,
  `SeasonRound`, `RoundResults`.
- **`calendars.py`** — `official_calendar(year)` preset track-id orders for 2025 / 2026.
- **`roster.py`** — `LeagueMember`, `LeagueRoster.member_for(entry)` /
  `member_of(entry)` (online-name-first, race-number fallback), `league_display_name(entry,
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
  - carries the player's latest Car Status ERS fields forward into each sample;
  - *(lap-view iteration 2b)* carries the player's latest **Motion** entry forward into each sample
    (world position + g-force, format-normalized via `motion_sample`), adding the track-map /
    g-force `LapTrace` channels; carry-forward (not a hard frame-join) so a Motion-less stream
    still builds laps;
  - *(lap-view iteration 1a)* diffs the player's **Car Setups** packet to build a `setup_history`
    (a new snapshot stamped with the current lap whenever the setup changes), and snapshots per-lap
    **tyre context** + full non-tyre **car damage** at each lap boundary (compound/age from Car
    Status, wear/damage from Car Damage);
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
  their per-lap tyre context, with each lap's dense `LapTrace` written to a **Parquet file**
  referenced by the lap row (not SQLite rows — see DECISIONS). Write: `save_laps` (replace-by-uid,
  rows + files) / `delete`. Read: `list(uid)` returns a session's laps **without** their traces
  (cheap, for the overview), `load(uid, lap_number)` returns one fully-hydrated lap **with** its
  trace (detail page; the iter-2 overlay calls it per selected lap), `load_laps(uid)` the full set.
  The session's setup **history** (`setup_history`) is a JSON column on the session row, not a lap
  concern. Repository-per-aggregate (own table cluster; `schema.py` stays the shared layer).
- Stores are context managers (dispose the engine on exit).

### analysis/ — derived facts
- **`standings.py`** — `StandingRow`; `by_driver_name` / `by_race_number` keys;
  `compute_standings(sessions, key, display)`; `standings_for_rounds`;
  `league_standings_for_rounds(rounds, roster)`. Points sum across race-type sessions only 
  (RACE_SESSION_TYPES); the game leaves stale last-race points in non-race classifications' 
  m_points, so other session types are skipped. LEAGUE driver standings resolve through the per-season
  roster and display via `league_display_name`; non-league seasons stay name-keyed. Constructor
  standings aggregate captured in-game `team_id`s. Lap/trace analytics are intentionally
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
  `ui/laps/track_layouts.py`.

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
  `build_classification_table(session, name_of)` — the results grid shown for one session
  (race vs best-lap columns) — plus `display_name_fn(roster)`, the roster→name resolver passed
  as `name_of`. The weekend view composes the table from here today; the future Sessions / Laps
  surfaces reuse the same builder.
  The lap-detail widgets also live here: `tyre_box.py` (`TyreBox` — the 4-box RL/RR/FL/FR tyre
  graphic mapped to the on-car FL FR / RL RR layout, `wheel_grid_cells()` the tested placement),
  `damage_panel.py` / `setup_panel.py` (`build_damage_table` / `build_setup_table` over the Qt-free
  `damage_rows` / `setup_rows`, rendered via `tables.build_kv_table` — a shared key/value table with
  bold section headers), and `trace_plot.py` (`TracePlot` — stacked, distance-linked telemetry via
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
- **`seasons/`** — the seasons surface, split into a thin container plus one widget per page.
  `view.py` holds `SeasonsView`: it owns a `QStackedWidget` of the four pages (overview → create
  → detail → weekend) and does nothing but wire their **navigation signals** to page switches —
  each page owns its own widgets, its own route state (e.g. the loaded season/round id), and its
  own data operations (create, delete, assign, roster create/import). Pages never reference
  siblings; they emit intent (`season_requested`, `weekend_requested`, `create_requested`,
  `cancelled`, `overview_requested`, `detail_requested`) and the container decides what shows.
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
  lap via `LapStore.load` and composes the `components/` lap widgets — lap info + tyre box, the
  damage and setup tables (setup resolved by `SessionResult.setup_for_lap`), and the `TracePlot`.
  When the lap carries Motion it also shows a `TrackMap` panel, wired to the plot's `cursor_moved`
  signal so hovering a trace moves the marker round the circuit (iteration 2b). The map draws the
  **canonical median line** for the whole race weekend when available (iteration 2b.1), falling back
  to the driven lap's own line; `track_layouts.py` (`TrackLayoutProvider`, Qt-free) does the
  cross-store walk — every valid Motion lap across the sessions sharing this one's `weekend_link_id`
  at the same `track_id` — feeds them to `analysis.track_layout.build_layout`, and caches the result
  keyed `(weekend_link_id, track_id)`. Its
  "Compare ▾" menu (iteration 2) lists candidate laps from `comparison.py` and drives `TracePlot`'s
  overlay; `comparison.py` (Qt-free, unit-tested) enumerates them by scope — weekend-fastest,
  same-session, same-weekend — as `LapRef`s loaded on demand via `LapStore.load`. Session uids travel
  through signals as `str` (uint64-safe). Track-country flags are deferred (no `track_id → country`
  map exists yet).
- **`workers.py`** — `RecorderWorker` / `IngestWorker` (`QThread`s). `IngestWorker` builds its own
  `SessionStore` **and** `LapStore` in-thread (SQLite dislikes cross-thread connections) and passes
  the `LapStore` into `ingest_capture`, so app-side ingest writes laps + Parquet traces (under an
  injectable `trace_dir`, default `lap_traces/` at the CWD) — not just the classification. Then it
  gzip-archives the capture after a successful ingest (archive failure is reported, never fatal).
- **`formatting.py`** — Qt-free presentation helpers (winner time / gap / +laps / status;
  best-lap-or-status; `is_race`, `slot_label`), unit-testable without importing PySide6.
- **`pipeline.py`** (`src/pipeline.py`) — `ingest_capture(path, store)`, extracted so ingest is
  testable without Qt.

## Capture compression

Captures record uncompressed (the recorder appends raw datagrams as they arrive), then are
**gzip-archived after a successful ingest**: `IngestWorker` calls
`archive_capture(path)` once `ingest_capture` has produced at least one session, which writes
`<name>.f1cap.gz` (via a `.tmp` file + atomic `os.replace`) and removes the original.
Key properties:

- **Archiving is non-fatal.** If compression fails the ingest still succeeds; the UI reports
  "capture kept uncompressed" and the raw `.f1cap` stays on disk. An existing destination is
  never overwritten (`FileExistsError`).
- **Reading is transparent.** `open_capture` picks `gzip.open` vs `open` by extension, and
  `FileReplaySource` goes through it — so replay, re-ingest, and the file-picker
  (`*.f1cap *.f1cap.gz`) all work on either form. The `.f1cap` record framing is unchanged;
  gzip is a pure outer wrapper.
- **Compressed captures remain the source of truth** — nothing is deleted until the compressed
  copy is fully written.

Future direction (see ROADMAP): a hybrid with capture *metadata in the database* and the
payload compressed on disk, likely moving the codec from gzip to zstd.

## Threading

Recording and ingest run on `QThread`s so the UI stays responsive. SQLite dislikes a connection
shared across threads, so the **`IngestWorker` creates its own store in-thread**, while the UI
reads through stores owned by the main window on the GUI thread — both pointing at the same
database file. The recorder's cooperative stop is an `Event` checked each socket-timeout cycle.

## Invariants (see also CLAUDE.md and DECISIONS.md)

- Distance-indexed traces; format isolation at the parser; roster accumulation across frames;
  vehicle-index joins; session split on `session_uid`; non-FK session assignments; slot derived
  from `session_type`; enums via `safe_enum`.
