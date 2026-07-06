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
  - *1a — persistence backbone (no UI).* Assembler captures the player's setup **history** and
    per-lap tyre context; new `laps.py` store persists lap rows + Parquet trace files + setup
    history; ingest writes the trace files. Verified by an ingest→load round-trip + the suite.
  - *1b — lap view.* Foldable lap cards (track+flag / time / session) + filter/search, and a lap
    detail page (lap #, sectors, tyre compound/age/wear, setup panel, simple 4-box tyre graphic,
    single-lap telemetry graphs). Reusable card / plot / tyre / setup widgets in `ui/components/`.
  - *2 — same-context overlay.* Overlay best-lap / same-session / same-weekend laps on the shared
    distance grid + delta trace. Built on the N-series-aware trace-prep module from 1a.
  - *2b — g-force channel.* Additive `LapTrace` channel (Motion frame-join; 2026 int16/1000),
    once overlay works.
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
- **Done:** captures are gzip-archived to `.f1cap.gz` after a successful ingest
  (`ingest/archive.py`; see ARCHITECTURE → Capture compression).
- **Loose ends:**
  - The diagnostic tools (`ingest/inspect.py`, `diagnose_participants.py`,
    `dump_classifications.py`) open captures with plain `open()`, so they can't read a
    `.f1cap.gz` — route them through `open_capture`.
  - `compressed_capture_path` appends `.f1cap.gz` to the *full* filename, producing a doubled
    extension (`x.f1cap` → `x.f1cap.f1cap.gz`, e.g. `captures/league_race.f1cap.f1cap.gz`);
    `x.f1cap.gz` (append only `.gz`) would still satisfy `is_compressed_capture`. Renaming the
    scheme means also handling the already-archived files.
- **Future — a hybrid.** Store capture **metadata in the database** (so captures are queryable
  without decompressing), keeping the payload compressed on disk; and likely **switch the
  payload codec from gzip to zstd (Zstandard)** — better compression ratio *and* faster than
  gzip. Shape TBD (metadata-in-DB + blob-on-disk split, with the codec chosen at that point).

## Possible, uncertain
- **Hosted multi-user league platform** — signup / authorization, colleagues upload their own
  results. Would be additive: reuse the version-agnostic domain + storage; the schema is already
  kept engine-agnostic (SQLite → Postgres only if this happens). Nothing current depends on it.
- **Mobile / web access** for colleagues — a long-term direction, not planned.
