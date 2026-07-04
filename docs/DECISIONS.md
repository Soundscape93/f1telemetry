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
- **Dense per-lap traces stored as files (Parquet/npz) referenced by the lap row, not as SQLite
  rows.** ~5,400 samples per 90 s lap at 60 Hz — wrong shape for row storage. (Not yet built.)
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
- **Enums stored as raw ints, read via `safe_enum`.** The game's enums grow across title
  updates; `safe_enum` returns the member or the raw int so an unknown value never crashes load.
- **Captures are gzip-archived after ingest, not compressed while recording.** Recording stays
  a dumb append of raw datagrams (no CPU/complexity on the live path, and a crash mid-capture
  loses nothing to a half-written compressed stream); `IngestWorker` archives to `.f1cap.gz`
  only after a successful ingest. gzip because it's stdlib (zero deps for colleagues);
  archiving is non-fatal — on failure the raw capture is kept and the UI says so. Reads go
  through `open_capture`, so both forms replay/re-ingest identically. *Revisit:* the ROADMAP
  hybrid (metadata in DB + zstd payload) replaces the codec choice when it lands.

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

## Conventions
- **Module-level constants use a single leading underscore.** A double underscore name-mangles
  inside class bodies and has caused a `NameError`. Reserve `__` for genuinely mangled class
  attributes.
