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
- Stores are context managers (dispose the engine on exit).

### analysis/ — derived facts
- **`standings.py`** — `StandingRow`; `by_driver_name` / `by_race_number` keys;
  `compute_standings(sessions, key, display)`; `standings_for_rounds`;
  `league_standings_for_rounds(rounds, roster)`. Points sum across all sessions (quali scores 0,
  so no session-type filtering needed). LEAGUE driver standings resolve through the per-season
  roster and display via `league_display_name`; non-league seasons stay name-keyed. Constructor
  standings aggregate captured in-game `team_id`s. Lap/trace analytics are intentionally
  in-memory and desktop-bound.

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
- **`workers.py`** — `RecorderWorker` / `IngestWorker` (`QThread`s); `IngestWorker` builds its
  own store in-thread and gzip-archives the capture after a successful ingest (archive failure
  is reported, never fatal).
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
