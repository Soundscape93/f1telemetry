# Decisions

A lightweight log of *why* the design is the way it is. Read before overturning a big call;
update when a new one is made. Each entry: the decision, the reasoning, and (where relevant)
what would trigger revisiting it.

## Language & wire parsing
- **`ctypes.LittleEndianStructure` (`_pack_ = 1`), one struct set per format.** Mirrors the C
  structs 1:1 with native unsigned types and packed nested arrays. Java was ruled out for
  lacking unsigned integer types.
- **Format boundary at the bottom only.** The 2025/2026 difference lives in the wire structs +
  parser; dispatch on `(packet_format, packet_id)` via a registry. Everything from the
  normalizer up is version-agnostic. *Revisit:* never — this is the core architectural bet.

## Storage
- **SQLite via SQLAlchemy 2.0, kept engine-agnostic.** The shipped desktop app stays on SQLite;
  the schema avoids engine-specific features so it *could* move to Postgres only if a central
  hosted server is ever built.
- **Dense per-lap traces stored as Parquet files referenced by the lap row, not as SQLite
  rows.** ~5,400 samples per 90 s lap at 60 Hz — wrong shape for row storage. **Parquet over
  npz** (both were on the table): columnar, compresses well, self-describing, and inspectable /
  queryable later without loading the whole array; the cost is a `pyarrow` dependency, which is a
  size consideration for the frozen colleague build but acceptable. One file per lap, path
  referenced from the `laps` row; written during ingest into a writable trace directory (see
  `data_root()`, ROADMAP → Packaging). (Lap-view iteration 1a.)
- **Laps, per-lap tyre context, and setup are persisted (lap-view iteration 1a).** The assembler
  already builds `Lap`s + dense `LapTrace`s and can populate setup/tyre data, but `SessionStore`
  historically kept only the classification + session metadata and dropped the rest. A new
  `laps.py` store (repository-per-aggregate) persists the lap rows + Parquet trace refs; per-lap
  tyre context (compound/age from Car Status; wear/damage/blisters from Car Damage) **and the full
  non-tyre car damage** (wings, floor, diffuser, sidepod, brakes, gearbox, engine + engine
  sub-wears, fault/blown/seized flags) are snapshotted at each lap boundary and stored on the lap
  row. *Why snapshot at the lap boundary:* wear/damage are cumulative over a stint, so a lap's
  "usage" is the reading as the car crosses the line, not a per-frame channel. *Why the full Car
  Damage now (not just tyres):* the packet is already parsed and already snapshotted, so capturing
  all of it is a normalizer/storage-only change — deferring it would just cost a second additive
  migration later. It's split by UI consumer: tyre fields live on `LapTyreContext` (tyre
  widget/graphic), the rest on a `CarDamage` value object (car-body graphic + damage table), with
  no field in both.
- **Setup is a per-session change *history*, not one static snapshot.** A player can return to the
  garage mid-session and change setup (laps 1–5 setup A, 6–10 setup B); a single stored setup
  would mislabel every lap after the change in the lap detail view. So `SessionResult` carries an
  ordered `setup_history` of `SetupSnapshot(from_lap, setup)` values; the assembler diffs the
  player's Car Setups packet (a frozen-dataclass `==`) and appends a snapshot stamped with the
  current lap whenever it changes. The lap detail resolves the active setup as the latest snapshot
  with `from_lap <= lap_number` — not duplicated per lap. Stored as a JSON column on the session
  row (small, session-scoped, same pattern as `tyre_stints`), so no extra table. *First
  implementation stays dumb:* record-on-change + dedupe consecutive identical setups; if the game
  emits transitional values during a garage visit we may get an extra snapshot or two — acceptable,
  and debouncing can be added later without touching the model or schema.
- **Repository-per-aggregate.** One store file per aggregate root, named after it
  (`sessions.py`, `seasons.py`, future `laps.py`), each owning its table cluster; `schema.py` is
  the shared table layer. No mega-repository, no per-table files, and no abstract base until a
  second backend actually exists.
- **`session_assignments.session_uid` is NOT a foreign key** to `sessions`. Re-ingesting a
  capture replaces its session row by uid; a FK (or cascade) would wipe the manual league round
  placements. Keeping them independent means results can be re-processed freely.
- **`recorded_at` is the session's *earliest capture packet time*, not the ingest time.** A
  single recording often holds several attempts of the same session (a crash/restart, or a
  re-driven quali), and they need distinct, chronological timestamps to be told apart in the UI.
  `ingest_capture` reads the capture's per-packet `recv_time` and stamps each assembled session
  with its first packet's wall-clock; the later attempt (the keeper) therefore sorts *after* the
  aborted ones. This is why the pipeline reads the capture directly rather than via
  `FileReplaySource`, which drops `recv_time`. Sessions stored before this existed keep their
  old ingest-time stamp until their capture is re-ingested.
- **Deleting a session tombstones its uid; re-ingest skips tombstoned uids.** A capture holds
  every session it recorded, including aborted attempts the user deleted on purpose (a
  crash/restart, a re-driven quali). Re-ingesting that capture — to refresh denormalized data
  after a code change, or just to re-import — would otherwise silently resurrect them.
  `SessionStore.delete` therefore records a `deleted_sessions` row (uid + track/type/recorded_at
  for a future 'deleted sessions' view), and `ingest_capture` skips those uids. `restore(uid)`
  clears the tombstone for a deliberate re-import; `save()` stays a dumb primitive (the skip is
  policy in the orchestrator, not the store). Fresh recordings are unaffected — their uids are
  new. The tombstone is a *new table*, so `create_all` adds it to existing DBs with no migration
  (unlike an added column). *Revisit:* if we ever want delete-without-tombstone, it becomes a
  second explicit action rather than the default.
- **Enums stored as raw ints, read via `safe_enum`.** The game's enums grow across title
  updates; `safe_enum` returns the member or the raw int so an unknown value never crashes load.
- **Captures are archived after recording, not compressed while recording.** Recording stays
  a dumb append of raw datagrams (no CPU/complexity on the live path, and a crash mid-capture
  loses nothing to a half-written compressed stream); compression happens at ingest. *Ordering
  (Phase C, done):* ingest is **archive-first** — the raw is compressed (original kept), the
  **archive** is ingested so its frame checksum is verified end-to-end, and the raw is deleted
  only on a successful ingest. So a capture that fails to parse is kept as *both* raw (for
  debugging) and archive (uploadable) — which is why archiving is no longer gated on ingest
  succeeding. Archiving is still non-fatal: if compression itself fails the raw is ingested
  directly and kept, and the UI says so. *Codec (done):* new archives are **zstd** (`.f1cap.zst`,
  level 3 — benchmarked ~18% smaller than gzip-6 *and* several times faster); the original gzip
  choice (stdlib, zero deps) is superseded, but `open_capture` reads `.f1cap.gz` **forever** and
  re-ingesting one leaves it a `.gz` (never rewritten). `zstandard` joins pyarrow/pyqtgraph as a
  hand-installed dep (its PyPI wheel bundles libzstd statically, dodging a clash with Qt's copy).
  The earlier *Revisit* (ROADMAP hybrid replaces the codec) is now **resolved** — it landed with
  the capture-metadata table (see the three league-sharing bullets below).
- **League data is shared as capture files; the database stays local, single-writer, and
  derived.** A league needs someone else's recording when the admin can't attend a weekend.
  Putting the SQLite DB on a synced cloud folder (Drive/Dropbox/OneDrive) was considered and
  **rejected**: SQLite's guarantees rest on POSIX locking and on the DB file and its journal/WAL
  staying mutually consistent, and sync clients honour neither — they upload whole files on their
  own schedule, so a mid-transaction snapshot ships a torn file. There is also no merge for a
  binary B-tree: concurrent edits produce a "conflicted copy" and someone's work vanishes
  silently. And the DB is only half the data — the Parquet traces and capture archives sync
  independently of it, so rows would point at files a peer doesn't have yet. Instead the
  **capture file is the interchange format**: immutable, write-once, the one shape sync handles
  perfectly. Sharing is a Drive folder (`<League>/<Season>/<Round>-<Track>/`, season in the tree
  because a track folder alone collapses seasons and contributors); captures are copied local
  after import, so Drive is transport and the local archive stays the home. The admin's DB is the
  canonical league dataset and everyone else contributes captures — curation (round assignment,
  rosters, calendars) stays with the admin. *Why this needs no merge code:* `session_uid` is a
  game-generated 64-bit id, so contributors' sessions can't collide; `SessionStore.save()` is a
  replace-by-uid, so re-import is idempotent; and `recorded_at` is the capture's own packet
  wall-clock, so sessions from different machines sort correctly against each other (modulo a
  contributor's PC clock being wrong). If the DB is ever lost or corrupted, re-ingest rebuilds it.
  *Packaging dependency:* league members run the **full app**, not a cut-down recorder — they are
  the first external test users (their own career/practice sessions, the existing views, feedback
  and bugs), and capture contribution is a side effect of that, not the point. *Revisit:*
  multi-admin editing — other members assigning rounds or editing rosters — is what would force a
  real hosted backend (Postgres + object storage, since traces and payloads can't live in a
  relational DB); indefinitely future, and nothing here blocks it.
- **Auto-ingest after recording is fine for league captures; the three concerns are already
  decoupled.** The Record button auto-ingests, then archives. A contributor's local ingest does
  not affect what they upload: ingest is a pure read, and no local identity leaks into the file
  because `session_uid` comes from the game, not from an autoincrement. So recording, local
  ingest, and sharing need no separation — the contributor's DB is just their own private
  projection of the same capture. Two consequences to know: **tombstones are local** —
  `ingest_capture` skips the *ingesting* store's `deleted_uids()`, so a contributor deleting an
  aborted attempt doesn't delete it for the admin, who must re-do it. That's correct, not a gap:
  you shouldn't silently inherit someone else's curation calls. And **archiving is currently
  gated on ingest succeeding** (`IngestWorker`: `if sessions:`), so a capture that fails to
  parse — the one most worth sending the admin — is left raw at ~10x the size, as is a capture
  whose sessions are all tombstoned. *Fix when the hybrid lands:* archive because recording
  finished, not because ingest liked the result.
- **Hybrid capture storage (metadata in DB + payload on disk) lands before the session view.**
  Not an architectural ordering but a deadline one: once the league season starts captures
  accumulate immediately, and both halves are retroactive-forever — every weekend archived under
  the old codec is a re-compress pass later, and every capture ingested before the metadata table
  exists needs a backfill. Doing it first makes the league dataset uniform from day one, and the
  migration is cheap because capture metadata is a **new table** (`create_all` handles it, per the
  `deleted_sessions` precedent); only new columns on existing tables force a re-ingest. The
  metadata is designed as a **manifest for sharing**: a **content hash** (exact dedupe on import
  regardless of filename, so re-syncs are no-ops) and the **producing peer** (one column now; the
  difference between "someone recorded Monza" and an auditable league dataset). The codec switch
  itself is not re-decided here — see the gzip bullet's *Revisit* above — but it carries one hard
  constraint: **`open_capture` must keep reading `.f1cap.gz` forever.** It currently hard-codes
  that suffix via `is_compressed_capture`; the new codec is an addition to the reader, never a
  replacement, so every existing recording stays importable.

## Migrations
- **Ad-hoc / additive now; Alembic later.** All schema changes so far are additive (new
  columns/tables) and handled by `create_all` (plus a planned idempotent `ensure_schema` when
  dense-trace storage lands). *Trigger to adopt Alembic:* the first non-additive migration
  (a rename / type change / drop / backfill). `create_all` does NOT alter existing tables, so an
  additive column today still requires deleting the dev DB and re-ingesting.

## Identity & rosters
- **League driver identity resolves by race number first.** Leagues enforce unique numbers, so
  it's zero-friction and stable. Online name is a stronger key *when public*, but colleagues
  usually have online-name sharing off (captured as `"Player"`); `network_id` is per-lobby and
  useless across lobbies. The roster maps both online name and number → a canonical member,
  online-name-first with number fallback. Display is a separate choice: for LEAGUE views, show
  the captured public online name when present; if the capture says `"Player"` or blank, show
  the first roster `online_names` alias. The roster `name` field is a human helper/canonical
  identity for assigning aliases/numbers, not the preferred display label.
- **Roster is a per-season canonical JSON file** (convention: `rosters/season_<id>.json`),
  seeded from the names/numbers already in that season's captures — or copied from the previous
  season's file. Rationale: a roster belongs to one championship, and league membership drifts
  between seasons, so each season resolving against its own roster is historically correct; and
  it stays a hand-editable file rather than DB content needing an editor UI. No schema change.
- **Viewing a season is read-only; writing the roster file is an explicit action.** Rendering a
  LEAGUE season loads the saved file if present, otherwise *shows* an in-memory seed (from
  captures, merged over the previous league season) without touching disk. The file is created
  only when the user asks — a "Create roster file" button materializes the seed, or CSV import
  writes it. Earlier the file was written as a side effect of first open; making a plain "view"
  mutate disk was surprising, and it also meant the previous-season lookup ran on the render
  path. Read-only rendering + explicit persistence keeps the file hand-editable while a view
  stays a view. `SeasonRosterFiles` splits this into `load` / `seed` (in-memory) / `roster_for`
  (load-or-seed, read-only) / `create_from_captures` (seed + save) / `import_csv`.
- **League standings group by the resolved member's race number, not by canonical name.**
  `LeagueRoster.member_key` returns the matched member's race number (or the entry's own number
  when unmatched). Number-based because league numbers are unique per driver, so two
  roster-unknown humans who both show as `"Player"` never collapse into one standings row — a
  name-based key would have merged them. Display is still `league_display_name` (public alias
  first). *`member_of` (canonical name) stays for identity/label uses; the grouping key is
  separate.*
  CSV is a user-friendly import format only: the user can pick a CSV from their own storage,
  the app validates/parses it, then writes the per-season JSON. The CSV file is not copied into
  the app and is not remembered as the live roster path, avoiding broken references if a user
  moves or deletes it. CSV import requires `name` and `race_number` columns, with optional
  `online_names`; header matching should be case-insensitive and tolerate spaces/underscores.
  Race numbers must be unique integers. Multiple online names are semicolon-separated, and extra
  columns are ignored so users can keep spreadsheet notes in the same file. `online_names` are
  the league display aliases; `name` is only a helper/canonical identity.
  Constructor standings remain based on captured in-game `team_id`s, because league mode uses
  official/F1 World cars. If custom league constructors become real, add an explicit roster
  constructor field at that point.
  *Revisit:* if sharing one roster across seasons becomes common, add an (additive) `roster_path`
  column.
- **Roster accumulation over last-write-wins (bug fix + principle).** The assembler builds the
  session roster by merging *all* Participants frames (union by vehicle index, keeping the most
  complete identity), not from a single packet. A late post-race/podium Participants packet can
  report a reduced `num_active_cars`; last-write-wins left high-index cars unmatched in the
  classification join (blank name / number 0 / team −1). See TELEMETRY_NOTES.
- **Missing Final Classification → reconstructed classification (Option 2).** The game sends the
  Final Classification packet *once*; a recording stopped a beat early or a single dropped datagram
  loses it, and the results table then showed 0 drivers. When the packet is absent the assembler
  now synthesizes a best-effort result (`reconstruct_classification`) from the last Lap Data frame +
  per-car Session History. **What's recovered exactly:** finishing order, laps, best lap, tyre
  stints, total race time (sum of Session History lap times = the game's "race time without
  penalties"), and penalty time (`LapData.penalties`). **The one gap is championship points** —
  FC-only, in no telemetry packet — left 0. Reconstructed results carry
  `Classification.is_reconstructed` (persisted via an additive `SessionRow.is_reconstructed`
  column, auto-migrated by `ensure_schema`). *Why not guess points into the field:* `points` feeds
  `compute_standings`, so a fabricated value silently corrupts the championship — and standard
  scoring can't know classified-DNF or custom-league rules. Instead: the UI **badges** the table
  "reconstructed" and shows a **muted, display-only estimate** (`~25`; GP `25-18-…-1` / sprint
  `8-…-1`, no fastest-lap point per 2025+ regs, blank for non-finishers), and **standings exclude**
  reconstructed sessions entirely. *Deferred (Option 3):* an accept/edit/store workflow that lets
  the user confirm or hand-correct reconstructed race points, a manual editor, and re-including the
  confirmed values in standings — to land with league-management (see ROADMAP).

## UI
- **PySide6 + PyQtGraph.** Chosen over a web stack / NiceGUI / DearPyGui for the analytics-heavy
  workload and the existing Python investment; the hosted-web future is uncertain and would be
  additive later, reusing the UI-agnostic domain/storage.
- **Single window; pages swap in a `QStackedWidget`; drill-downs are nested stacks.** Avoids a
  pile of top-level windows. Modal dialogs are fine for discrete actions (delete confirm, file
  picker); full surfaces are pages, not windows.
- **The record/stop control is a persistent header owned by the `QMainWindow`, not a page.** The
  recorder worker's lifecycle belongs to the long-lived window; putting the control on the
  Dashboard page would mean building that worker wiring twice when it later needs to be reachable
  everywhere. As a bonus the capture can be started/stopped from any page.
- **Session→round assignment is round-centric** (open a season → a round → its weekend → assign
  captures), rather than session-centric (a global sessions list). A league weekend is several
  sessions at one track, so matching a capture's track to the round makes assignment nearly
  one-click, and it keeps the weekend view and its assignment together. *A session-centric view
  in the Sessions surface is a fine complement later.*
- **Presentation helpers are Qt-free** (`ui/formatting.py`): the fiddly result-cell logic
  (winner time / gap / +laps / status) is a pure module so it's unit-testable without a display
  and reusable across views.
- **Result-cell gaps include post-race penalties** (`total_race_time_s + penalties_time_s`) so
  the displayed gaps line up with the classified finishing order.
- **Custom-calendar authoring is driven by `(SeasonMode, game_format)` rules, not a single
  toggle.** The game constrains a custom calendar differently per mode, so `calendar_rules()` (in
  `domain/calendars.py`) returns a `CalendarRules` value object and one widget
  (`ui/components/calendar_picker.py`) renders whichever face it describes. Career / My Team = a
  *preset subset*: pick exactly 10/16/24 of the official calendar with its order frozen (checklist
  face). Grand Prix / League = a *sandbox*: any count, freely reordered, duplicate tracks allowed
  (add/reorder face). The game rules stay in the pure domain layer so they're unit-testable
  without Qt; deriving them from `SeasonMode` doesn't violate the "SeasonMode is decoupled from
  the game's `game_mode`" note (that note is about the granular per-session id). The picker lives
  in `components/` (not inline in the create page) so a future edit-calendar surface reuses it via
  the existing `SeasonStore.set_calendar()`. *Track pools:* Madrid (42) is 2026-only; reverse
  layouts (39/40/41) are offered in the sandbox. *League cap:* left **open-ended** — EA's Racenet
  documents no maximum and its league pages are login-gated, so no limit is enforced; revisit if a
  real cap surfaces.

- **Single-lap telemetry graphs and same-context overlay live in the Laps surface; only
  cross-session trends stay in Analytics.** The ROADMAP originally filed "overlay N laps on a
  shared distance grid / lap delta / ERS view" under Analytics. In practice those graphs are most
  useful right where you're inspecting a lap, so the Laps surface owns single-lap graphs (iter 1b)
  and same-context overlay — weekend-fastest / same session / same weekend (**iter 2, done**).
  Analytics keeps the genuinely *cross-session* work: same-track-different-season comparison and
  higher-level trends (lap-time trends, AI-difficulty, team performance). Building the
  trace-preparation module **N-series-aware from iteration 1a** paid off: iter 2 was pure UI wiring
  over `align` + `time_deltas` (overlay + delta row) plus `ui/laps/comparison.py` (candidate
  enumeration), with no change to `analysis/traces.py`. G-force + track position are now additive
  `LapTrace` channels from the Motion packet (**iteration 2b, done**; 2026 g-force is int16/1000).
- **The overlay separates laps by colour *and* line style, and reuses the persisted colour-blind
  setting.** Telling 5+ laps apart by colour alone is hard — especially for red-green colour-vision
  deficiency — so each overlaid lap carries both a palette colour and a line pattern
  (solid/dash/dot/dash-dot/…); the reference (viewed) lap is solid. Under the colour-blind toggle the
  default palette's red+green is replaced by the **Okabe-Ito** set, and the *same* `laps/trace_colorblind`
  QSetting drives both the single-lap throttle/brake pair and the overlay (one preference, persisted,
  applied live by redrawing). The two-channel throttle/brake row keeps solid=throttle / dashed=brake
  for its channel distinction and leans on colour for the lap; every single-channel row uses the
  per-lap line style. The lap-name legend sits in its **own layout row above the plots** (not
  anchored inside a viewbox) so it never covers a trace. "Fastest" spans the whole weekend and is
  hidden when you're already viewing that lap — a lap can't overlay itself.
- **The track map is an asset-free plotted XY path, un-mirrored and loop-closed (iteration 2b).**
  `TrackMap` draws the circuit from the lap's own `pos_x`/`pos_z` telemetry rather than sourcing a
  per-track image/mini-map — so it works for every circuit (including league/custom) with zero
  assets, and lives in the same coordinate space as the hover marker, making highlighting exact.
  Two corrections make it read right: (1) F1's world frame is **left-handed**, so a raw `(X, Z)`
  top-down plot is *mirrored* — the lap runs the wrong way round (CW vs CCW); negating one axis
  restores true handedness. (2) A race **lap 1** starts at the grid slot, past the S/F line, so its
  trace misses the line→grid straight; **closing the path loop** fills that gap generally (a no-op
  for a full flying lap). *Deliberate limitation:* absolute rotation follows the game's world frame,
  **not** the F1.com broadcast art — matching that orientation would require a per-track rotation
  constant, which contradicts the asset-free goal. *Revisit:* add an optional per-track rotation
  table only if broadcast-matching orientation is explicitly wanted; direction + shape are already
  correct without it. Store **raw** world coords (normalise/transform only at render) so no
  information is thrown away.
- **Canonical track map is a distance-resampled *median racing line*, not one lap's line (iteration
  2b.1).** 2b drew the *selected lap's* raw `pos_x`/`pos_z`, so the shape shifted lap to lap
  (defending, missed apex, off-track, a wider line). 2b.1 makes the map identical-and-clean per track
  by aggregating: resample each usable lap onto one shared distance grid and take the per-point
  `nanmedian` (`analysis/track_layout.build_layout`; `_GRID_NUM` = 1000 points). Grid points outside
  a lap's own distance span are masked to NaN so it doesn't vote where it has no data; the grid runs
  min-start..max-end across the laps so its endpoints are always covered (no leading/trailing NaN).
  The median is robust to single-lap excursions and self-heals the lap-1 S/F gap (other laps cover
  it). It's valid *without* any alignment step because **F1 track world coordinates are fixed
  geometry** — the same point is the same `pos_x`/`pos_z` across laps and sessions; deliberately
  *not* built on `traces.align` (which shrinks to the laps' overlap and would re-open that gap).
  **No Motion Ex needed:** this is a *median racing line*, the honest achievable version; a *true
  geometric centerline* would need track-edge / track-width data (Motion Ex) and stays deferred.
  **Scope is the race weekend, not one session:** a single qualifying session rarely has ≥3 valid
  timed laps, so `ui/laps/track_layouts.TrackLayoutProvider` gathers every valid Motion lap across
  the sessions sharing a `weekend_link_id` at the same `track_id`, builds the layout, and caches it
  keyed `(weekend_link_id, track_id)`. Below `_MIN_LAPS` (3) usable laps → `build_layout` returns
  `None` and `TrackMap` falls back to `set_trace` (the driven line); the handedness/loop-close
  corrections live in `TrackMap._render`, shared by both paths, and `TrackLayout` keeps raw coords.
  Hover is unchanged for the user — both the viewed lap and the canonical layout are distance-indexed,
  so `cursor_moved` (a distance) snaps the marker to the canonical layout's nearest index.
- **Sector colouring (done post-2c) uses the Session packet's boundary distances, not a per-frame
  channel.** The Session packet carries `sector_2/3_lap_distance_start` (absolute metres) and
  `track_length`; persisting three nullable columns on the session row (`track_length_m` /
  `sector2_start_m` / `sector3_start_m`, additive migration) is far cheaper than adding a per-frame
  `sector` trace channel (new Parquet column, re-ingest of every lap) that the earlier note assumed —
  and both need a re-ingest anyway. `TrackMap` splits the distance-indexed outline at the two
  boundaries (`sector_bounds`) into three arcs coloured to the F1-map palette. *Always-visible on-map
  sector labels were tried and removed:* two approaches — an opaque label mask, then a gap cut from the
  arc's own samples — both hurt readability on complex/overlapping layouts (masked or broke unrelated
  nearby track; awkward on corner-dense sections) and resisted a robust, tuning-free placement, so the
  map now conveys sectors by **colour alone** (labels may return later as hover/tooltips). The traces
  reuse the same two distances only for dashed boundary lines (text labels there would clutter the
  stacked rows). Old rows are `None` → single colour. *Corner numbers stay deferred (future work):* no
  telemetry source exists; the clean route is a static per-track metadata snapshot (corner number +
  distance-from-S/F) transcribed from FastF1/MultiViewer `get_circuit_info`, keyed by our `track_id`
  and scaled by `track_length_m`. **Licensing reminder:** that corner data is community/unofficial
  (MultiViewer; FastF1 is non-commercial/personal-use) — fine for private, friends-only use, but must
  be revisited/replaced before any broad public distribution of the app.
- **Canonical-map cache refresh stays deferred.** The provider's in-memory cache is not
  invalidated on a mid-run re-ingest (a stale weekend layout persists until app restart) — fine for
  personal/testing use, to be made automatic before any release (likely after 2c; see ROADMAP);
  a persisted `track_layouts/*.parquet` cache also stays deferred.
- **Lap detail composes reusable components over the 1a data split; visuals follow the game HUD.**
  The lap detail page (`ui/laps/detail_page.py`) is assembly only — it maps the 1a model straight to
  widgets: `LapTyreContext` → `TyreBox` (4 corners in on-car FL FR / RL RR order), full `CarDamage`
  → `build_damage_table`, `SessionResult.setup_for_lap(n)` → `build_setup_table`, `LapTrace` →
  `TracePlot`. Damage/setup use a shared key/value table (`build_kv_table`) so no view rebuilds one.
  Tyre `_wear_color` thresholds mirror the F1 HUD: **<60 % green, 60–79 % orange, ≥80 % red**. Setup
  fields that are raw game values (differential on/off-throttle, engine braking, brake pressure,
  brake bias) are shown as plain numbers, **not** percentages. The elaborate car-body render stays
  deferred to **iteration 2c** (a car silhouette with colour-coded tyre + damage zones); ~90 % of
  its data is already stored (`LapTyreContext` + `CarDamage`), so its only new ingest is tyre
  carcass/surface + brake temperatures — until then, 1b's simple 4-box + table form stands.
- **pyqtgraph is a hand-managed runtime dep, like pyarrow.** There's no requirements file; both are
  installed by hand. `TracePlot` lazy-imports pyqtgraph and shows an install hint if it's missing, so
  the app and the test suite stay importable without it. (pyqtgraph is now installed in the dev env.)
- **The car-status graphic (iteration 2c) is authored as SVG paths but rendered as `QGraphicsScene`
  path items, in the in-game neon top-down style.** Considered three backends: (a) templated QtSvg —
  rebuild an SVG string with substituted `fill`s and feed `QSvgRenderer`; (b) tinted PNG assets —
  rejected (raster, per-part tinting fiddly, against the asset-free house style); (c) **chosen:** draw
  the car once in a vector editor, import each id'd path as a `QGraphicsPathItem`. Rationale: `QPainterPath`
  is a superset of SVG path geometry, so fidelity is identical across backends and the shapes can trace
  the game's car-status screen freely (neon silhouette; the four tyres pulled out to corner gauges showing
  wear % + carcass temp, joined by dotted connectors). The path-item route gives the cleanest per-part
  recolour (`item.setBrush()`, no XML string rebuild), native per-part `setToolTip()` / hover hit-testing,
  and needs no extra `QtSvg` dependency. As with the rest of the lap surface, the logic is a **Qt-free,
  unit-tested `car_status.py`** mapping `CarDamage` + `LapTyreContext` → per-part `(status, colour)`, so the
  render backend stays swappable. Placement: keep 1b's `TyreBox`, add the graphic **below it on the left**;
  the exact-number Damage/Setup tables stay on the right (visual overview left, precise values right). The
  `TyreBox` can be retired later if the graphic covers tyres well enough — not in 2c.
  *Realization (Phase C + visual polish, DONE):* shapes are authored as SVG path `d` strings parsed to
  `QPainterPath` by a small in-widget parser (`_svg_path`) and rendered as path items. The parser handles
  the full command set Inkscape/Figma emit — M/L/H/V/C/**S/T** smooth curves and **A** elliptical arcs
  (arcs via the SVG-spec F.6 endpoint→centre conversion, approximated by ≤90° cubics in `_arc_to`),
  abs + rel — but deliberately does **not** read `transform`, so an authored path must carry its geometry
  in `d` with any transform flattened (`test_svg_path.py`). **Authoring workflow (see `docs/car_template.svg`):**
  trace each part in Inkscape over a 420×560 canvas (= the `_VIEWBOX`), Store-transformation = Optimized,
  `Object to Path`, then copy the `d` into the relevant list. Parts are grouped by how they render:
  `_BODY_PARTS` (damage-coloured, one path per damage channel — the two sidepod ids share one channel),
  `_STRUCTURAL` (closed neutral shapes, faint translucent fill — the halo), `_PANELS` (closed shapes with a
  **solid** light-grey fill — the floor-edge wings), `_OUTLINES` (**stroke-only open** shapes, no fill — the
  chassis/nose), and `_ARMS` (front suspension, stroke-only). Tyres + brakes + gauges are **procedural**,
  not authored: each corner draws an on-car tyre block, an inboard brake block (coloured by brake temp), and
  a dashed connector out to a corner gauge (wear % + carcass temp), positioned from `_CORNERS` / `_TYRE_*` /
  `_BRAKE_*`, so moving a tyre is a one-line change. The neon glow (`QGraphicsDropShadowEffect`) is **on** —
  an early black-box-on-hover artifact was fixed via the viewport `setStyleSheet`, not by disabling the glow.
  *Two Qt fill gotchas learned + relied on:* an open path is implicitly closed when filled (so genuine
  2-point straight strokes are fill-safe and may share a filled path, but a curved/kinked "open" shape must
  live in `_OUTLINES`); and the `background: transparent` viewport shows through a too-faint fill, which is
  why the floor fences use `_PANELS`' solid fill rather than the `_STRUCTURAL` wash.
- **2c colour thresholds are three separate rules, not one (with tyre temps keyed by compound).**
  Researched against F1 24/25 community data; where the game's exact values are undocumented we use a
  clearly-labelled tunable fallback. (1) **Monotonic wear/damage, tyre + engine:** reuse the existing HUD
  rule — green <60 %, orange 60–79 %, red ≥80 % — for tyre wear/damage/blisters *and* all power-unit
  component wear (ICE/MGU-K/MGU-H/turbo/ES/CE, gearbox). Engine reuses the tyre rule deliberately: in-game
  the engineer warns ~60 % (part orange) and ≥80 % the component is effectively spent (dropped gears / power
  loss / replacement due). The engine block is coloured by the **worst** of its sub-wears. (2) **Aero/body
  damage** (front/rear wing, floor, diffuser, sidepods) uses a **stricter** fallback — green <15 %, orange
  15–39 %, red ≥40 % — because a partly-damaged wing already costs real downforce, so reusing the 60/80 wear
  rule would flag it far too late. (3) **Temperatures are two-sided bands** (cold ⇄ optimal ⇄ hot), and the
  tyre window is **compound-specific** — the operating range differs per compound and we already store
  `actual_compound`, so thresholds key off it (e.g. C1 optimal ~90–115 °C … C5 ~70–90 °C … C6 ~65–85 °C;
  inters/wets lower). Carcass/core is the primary readout; surface runs a few °C hotter. Brake temps use a
  broad band (~250–1000 °C working, red above). Every threshold is a named constant in one place; the temp
  windows and aero cutoffs are community-/estimate-sourced, not official — *revisit* once observed against
  real telemetry. *New ingest 2c needs:* only the temperatures (tyre surface + carcass, brakes, engine) —
  snapshotted at the lap boundary like the existing tyre context; all wear/damage is already stored.
  **Storage split (Phase A, done):** tyre surface/carcass temps go on `LapTyreContext` (two additive
  nullable `laps` columns `tyre_surface_temp` / `tyre_carcass_temp`); brake + engine temps go on
  `CarDamage` inside its existing JSON blob (zero new columns) — grouping brake temp beside brake damage
  and engine temp beside engine wear. The assembler carries the latest Car Telemetry entry forward (like
  Car Status) and reads it in `normalize_tyre_context` / `normalize_car_damage` at the line. Pre-2c rows
  load with zero-temp defaults; a re-ingest populates them.

## Conventions
- **Module-level constants use a single leading underscore.** A double underscore name-mangles
  inside class bodies and has caused a `NameError`. Reserve `__` for genuinely mangled class
  attributes.
