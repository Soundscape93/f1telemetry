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

- **A calendar stays editable, but assigned rounds are frozen** (E6, 2026-08-02). Editing a
  calendar is a wholesale replace, and `session_assignments` carries **no FK** to the rounds table
  on purpose (invariant #4) — so nothing in the database stops an edit from re-filing a stored
  result under a different track, or orphaning it into a round number that no longer exists.
  Three options were weighed: *warn and preserve* the orphans, *warn and unassign* them, or
  *restrict the edit*. We took the third: **a round with an assigned session keeps both its
  `round_number` and its `track_id`.** The first two manage orphans; this one makes them
  impossible, which is worth more than the flexibility it costs.
  - **The check is positional, not gestural.** For each locked round *(n, t)*, the proposed
    calendar must still have a round *n* whose track is *t*. That single test covers reordering,
    inserting before, deleting before and truncating — including the case a "no reordering" rule
    would miss entirely, where inserting a round at position 3 silently renumbers an assigned round
    5 into round 6 with nothing having been dragged. It also correctly *permits* an edit that
    leaves a locked round where it was, which matters in the sandbox modes where a track may
    legitimately appear twice.
  - **Enforced in `SeasonStore.set_calendar`**, not only in the editor page: at the single write
    point the invariant is guaranteed rather than remembered, and the rule stays testable without a
    `QApplication`. `protect_assigned=False` exists for a caller that has already cleared the
    assignments itself; nothing passes it today.
  - **The cost, accepted knowingly:** once round 1 has a session assigned, nothing can be inserted
    before it. In practice a season becomes freely editable from the last assigned round onward,
    plus reordering among unassigned rounds that don't cross a locked one. That covers the real use
    case — a wrong calendar is almost always noticed before results exist.
  - **Calendar only.** Mode, number, nickname and game format are not editable: changing the format
    moves the track pool out from under the calendar (Madrid is 2026-only). A wrong-mode season is
    deleted and recreated. Allowing those edits *while a season has no assignments* is a sensible
    later feature, not part of this one.
- **Connection setup is a shared function, not a shared engine — and WAL is on** (C2, 2026-08-02).
  Each store deliberately owns its `Engine`: SQLite dislikes a connection shared across threads and
  the ingest / re-ingest workers run on their own. That rules out configuring the database once at
  construction of some central object, because *any* of the five stores may be the one that creates
  the file. Hence `storage/engine.py: create_db_engine` — every store calls it, so the database is
  opened identically no matter who got there first.
  - **`journal_mode=WAL`.** Readers stop being locked out by a writer, which is what the GUI needs
    while a minutes-long re-ingest runs, and what makes a live backup possible at all.
  - **`synchronous=NORMAL`.** Chosen from the standing position that this database is *disposable
    and rebuildable from the captures*, not from a benchmark: a full fsync per commit would buy
    durability for data we can recreate. Still crash-durable at the application level; the residual
    risk is losing the last commits to a power cut.
  - **`foreign_keys` deliberately left OFF.** SQLite defaults it off and the schema's cascades are
    ORM-level, so turning it on is a real behaviour change — and it would interact with
    `session_assignments`, which is FK-free *on purpose* (invariant #4). Revisit with Alembic
    (below), not alongside a pragma change.
- **`recorded_by` is a claim made at import time, not an identity feature** (B3, 2026-08-03). The
  column, the `CaptureMeta` field and the `ingest_capture(recorded_by=…)` parameter have existed
  since the metadata table landed, and nothing has ever set one. Three ways to fill it were weighed:
  a local "your name" setting plus an import field, embedding it in the `.f1cap` header as format
  v2, or leaving imports blank forever. **We took the first, minus the setting.**
  - **Nothing reads it.** No view, no query, no standings path consumes `recorded_by` today.
    Building a settings page and an identity flow to feed a write-only column is speculative work,
    and this project doesn't do that. So the whole of B3 collapses to *one optional text field on a
    dialog that is being built anyway* — which is why it stopped being its own item.
  - **It is a claim, not a property of the file.** The admin types who sent them the capture; the
    file itself asserts nothing. That is honest and sufficient, because the admin is exactly who
    knows. It does mean a capture that changes hands twice can be mislabelled — accepted, because
    nothing depends on the value.
  - **Why record it at all, given the shared drive shows the uploader:** the drive's record does not
    survive the copy-home step this design mandates (Drive is transport, the local archive is the
    home). Once imported, the app is the only place that answer could live.
  - **Format v2 was rejected.** Writing the name into a new `.f1cap` header would make a shared
    capture self-describing and survive any number of hand-offs — genuinely the better long-term
    shape, and what "the producing peer" above gestures at. It is also a real on-disk format change,
    with a reader/writer bump and its own risk, for a field with no consumer, and every existing
    capture would stay v1/unknown regardless. Revisit only if something actually starts reading
    provenance.
  - **Blank is fine, and it is not a one-shot.** `CaptureStore.record` replaces by hash, so a later
    re-import from the shared folder sets or corrects the value. Only a *re-ingest* can't — it feeds
    the stored value back, which is what keeps a rebuild from erasing it. Making that true in
    practice needed `CaptureStore.set_recorded_by` (B2): without it an already-held capture is
    skipped outright, and the correction path would have been documentation rather than behaviour.
- **Importing is by content, copies home, and never touches the source** (B2, 2026-08-04). The
  capture file has been the league's interchange format by design since the metadata table landed;
  this is the flow that finally uses it. Read and write are split like the prune —
  `find_importable_captures` (a walk, one `stat` per file, one `known_files()` query, no archive
  opened) is what the user is shown, and `import_captures` acts on exactly that list — because
  hundreds of megabytes should never move before a human agreed to it.
  - **The hash decides; `(name, size)` only pre-filters.** The pre-filter exists so re-scanning an
    already-imported folder doesn't decompress it again. Being a hint, it errs both ways: a renamed
    capture costs one wasted read (fine), and two genuinely different recordings sharing a name
    *and* a byte-exact size would be skipped (accepted — the game's timestamp naming plus
    multi-hundred-megabyte files makes that collision effectively impossible).
  - **Four outcomes, not two.** New → copy + ingest. Already held → skip, so re-syncing is a no-op.
    Known but the local archive is gone → copy home and `relocate`, the one path that treats the
    shared folder as a backup of last resort — and deliberately *not* re-ingested, because the
    derived rows already exist and rebuilding them is what "Re-read captures" is for. Only
    `recorded_by` differs → update in place.
  - **Copy-home is the decision, not an optimisation.** Ingesting straight from the shared folder
    would leave rows pointing at a directory that syncs, disconnects, or gets tidied up by someone
    else — the same class of problem that ruled out putting the database on a synced drive. So the
    local archive is always the home and the source is never moved, renamed or deleted. A name clash
    is numbered rather than overwritten: the hash has already said this is a recording we don't
    hold, so a clash can only be two different recordings, never a duplicate.
  - **…but a capture already inside the captures folder is ingested in place.** Found the hard way:
    importing from any folder that *contains* the data root — a home directory, a whole drive — made
    the app copy its own archives beside themselves under `-2` names. Copy-home means *get it to the
    home folder*, and a file already there is already home. This also turns the failure into a
    feature: pointing the importer at the captures folder itself is now the way to pick up a loose
    recording that was never ingested, which is the one capability the retired
    `Ingest .f1cap (test)` button had that nothing else replaced.
  - **A failed import keeps its local copy** — the inverse of `archive_and_ingest`, which deletes a
    raw only once its bytes are proven. Nothing is at risk here because the shared original is
    untouched either way, and a capture that won't parse is precisely the one the admin wants
    locally to look at.
- **A capture that moved is located by its contents, and only ever re-pointed** (B4, 2026-08-03).
  `CaptureRow.path` is advisory and the content hash is the identity, which has an unpleasant
  consequence: `find_missing_captures` can say the bytes aren't where the app looks, but *not*
  whether the file was moved or deleted. The prune handed that judgement to the user; this hands
  the app the other half of the job — go and look — so forgetting a capture stops being the only
  available answer.
  - **The search space is the known-missing rows, not the captures folder.** A row that resolves is
    already correct; scanning "everything" would let a stale duplicate found on a memory stick
    re-point a perfectly good row. So the pass asks *"where did these specific captures go?"*, never
    *"what captures are in this folder?"* — the latter question is the **import**'s, and the two are
    deliberately not the same code path.
  - **`(file name, size)` is a hint; the hash is the ruling.** Confirming a match costs a full
    decompression pass, so a candidate is read only when a `stat` says it could be one of ours, and
    accepted only when the sha256 of its decompressed payload equals the row's identity. Relocating
    on name+size alone would be right almost always — capture names are timestamps — and *silently*
    wrong the rest of the time, filing one recording's metadata against another's bytes. Almost
    always is not a property worth having here.
  - **It re-points; it does not copy home.** A capture found on an external drive leaves the row
    pointing at that drive, and goes missing again when it's unplugged. Copying into the local
    captures folder is the import flow's job (DECISIONS above: Drive is transport, the local archive
    is the home); doing it behind a button labelled "find" would move hundreds of megabytes the user
    didn't ask for.
  - **The cost, accepted knowingly:** a capture renamed *as well as* moved never reaches the hash,
    because nothing pre-filters to it. Hashing every unrecognised file in a folder to catch that
    case would mean decompressing gigabytes of strangers on the chance one is ours. It stays a prune
    job, and the guide says so.
- **Backups are `VACUUM INTO`, and are not an "open the database" action** (C3, 2026-08-02). Once
  WAL is on, copying the file with the filesystem is wrong: committed pages live in a `-wal`
  sibling, so the copy can be stale or torn. `VACUUM INTO` writes a checkpointed, defragmented
  database from one read transaction, and can therefore run *while an ingest writes* — that is why
  C3 shipped with C2 rather than after it. This does not reopen the settled "the database is never
  surfaced to the user" decision (see PACKAGING → Data layout): the action hands over a **copy** at
  a path the user chose. The live file stays unexposed and unserviceable.

## Migrations
- **Ad-hoc / additive now; Alembic later.** All schema changes so far are additive (new
  columns/tables) and handled by `create_all` (plus a planned idempotent `ensure_schema` when
  dense-trace storage lands). *Trigger to adopt Alembic:* the first non-additive migration
  (a rename / type change / drop / backfill). `create_all` does NOT alter existing tables, so an
  additive column today still requires deleting the dev DB and re-ingesting.
- **The pipeline version lives in a `meta` table, not `PRAGMA user_version`** (packaging Phase 2).
  Both were on the table. The PRAGMA is one integer for free, but it is SQLite-only, and the storage
  layer is deliberately kept engine-agnostic (it could move to Postgres if a hosted version ever
  happens) — a PRAGMA would be the first thing to break that. A *table* costs nothing to migrate
  into existence (`create_all`, the `deleted_sessions` / `captures` precedent) and generalises to
  the next piece of app-level state that belongs to no aggregate. `PIPELINE_VERSION` stays a
  separate integer from the app's SemVer: a UI-only release must not force a re-ingest, and a
  pipeline change without a release still needs the bump.
- **CI verifies the release version; it never stamps it** (packaging Phase 3). The alternative was
  writing `__version__` from the git tag inside the build job. Rejected: the artifact would then
  differ from the tagged commit, and `pip install -e .` in a checkout would report a different
  version than the exe's Help page. Instead the PR label (`major`/`minor`/`patch`) drives a real
  bump commit that reaches `main` *before* the tag, and `packaging/check_version.py` fails the build
  if the tag, `src/version.py` and `pyproject.toml` ever disagree. **The bump is committed to the
  release PR's own branch (`staging`), never pushed to `main`** — an earlier version of this note
  said the opposite and required a branch-protection bypass for GitHub Actions. That was reversed
  on 2026-08-01: protection rejects a CI push to `main` (`GITHUB_TOKEN` is not exempt), so the bump
  now rides into `main` through the PR like any other change, and no bypass exists or is needed.
  Tags are not covered by branch protection, so `tag.yml` pushing `vX.Y.Z` is still fine.
- **An unstamped database that already holds sessions counts as version 0, not "current".** It was
  written before the stamp existed, so its rows were derived by an unknown older pipeline — and in
  practice they genuinely are stale (rows saved before iteration 2c hold no tyre/brake/engine
  temperatures; before the sector work, no `track_length_m` or sector distances). Adopting them
  silently would be a lie that permanently hides recoverable data. An unstamped *empty* database is
  the opposite case: nothing has been derived, so it is stamped immediately and a first launch never
  prompts.
- **Missing capture archives do not block the new stamp; a cancel or an ingest error does.** Only
  captures still on disk can be rebuilt, so a database whose archives are gone can *never* reach a
  complete rebuild — refusing to stamp would re-offer the same impossible upgrade on every launch.
  It is stamped and the summary says how many sessions stayed stale. A cancel or a genuine failure
  is different: both are worth retrying, so the stamp stays put and the offer returns. The
  "Don't ask again" button is the same escape hatch reached deliberately.
- **The database is not protected — it is rebuildable.** Making `f1league.db` read-only for the user
  while the app can still write it is **not achievable** when both run as the same account: on
  Windows the file's owner implicitly holds `WRITE_DAC`/`WRITE_OWNER` (rewrite the ACL, then write),
  and on macOS/Linux `chmod 444` is undone with `chmod +w`. Real enforcement needs a separate
  security principal (a service account + IPC) — a client/server design for a single-user desktop
  app. And it would break us: **SQLite needs write access to the containing directory, not just the
  DB file** (`-wal` / `-shm` / `-journal` siblings), so a read-only DB file stops the *app* writing
  too; flipping the bit per launch is a race and an extra corruption vector. So the DB isn't
  defended, it's made **disposable** — captures are the source of truth and a wrecked database is one
  *Help → Re-read captures…* away from a good one. Practically: keep it in the data root, never
  surface it (no "Open database" action), expose captures/logs instead, and document "don't
  hand-edit it". Tamper *detection* was considered and dropped as cost without benefit. Queued and
  now scheduled (PRIORITIES → C2/C3, Cycle 1): WAL mode — **not enabled today** — and a backup
  action via `VACUUM INTO` (the only safe way to copy a live WAL database).
- **One data root; discoverability is solved by opening it, not by moving data.** `captures/` and
  `lap_traces/` stay under `data_root()` even though `%LOCALAPPDATA%` is hidden in Explorer. Splitting
  them out (to `Documents`, say) would end `paths.py`'s single-authority invariant, make "back up this
  folder" two folders, need a second `F1TELEMETRY_DATA_DIR` override — and lose a real benefit:
  `%LOCALAPPDATA%` is **excluded from OneDrive sync by default**, which is what you want for 1.5 GB of
  datagrams per weekend. Instead the app opens Explorer at the folder. A user-chosen captures
  directory, if ever wanted, belongs in `config.json` (`paths.config_path()` reserves it).
- **The re-ingest offer is never a gate.** It is a dialog on a painted window (fired one event-loop
  turn after start-up), the app is fully usable whichever button is pressed, and the rebuild itself
  is modeless and cancellable. Rationale: it can take minutes on a 1.5 GB weekend, and a blocking
  "please wait" on launch is exactly how a tester concludes the app has hung.
- **The missing-capture prune is manual, confirmed, and re-verified — never a sweep.** `path` is
  advisory by design, so at the row level a **moved** capture and a **deleted** one are the same
  fact: "not where the app looked". Nothing cheap can tell them apart — the content hash could, but
  proving it means decompressing and hashing every candidate archive. So the app never decides:
  `find_missing_captures` (read) and `prune_missing_captures` (write) are deliberately split, the
  user is shown every file name and last-known path, and only an explicit *Help → Clean up missing
  captures* prunes anything. Three things make that safe enough to ship without the hash rescan.
  **It re-resolves each hash at delete time** rather than trusting the list the dialog was built
  from — a confirmation box stays open for minutes and an external drive can be reconnected inside
  that window, so anything that turns up is kept and reported. **It is recoverable**: only a
  `captures` row (+ its `capture_sessions` children, by cascade) is dropped, and re-importing the
  file records it again — replace-by-hash, no duplicate. **It cannot reach the data that matters**:
  sessions, laps, season assignments, rosters and tombstones are keyed on `session_uid` and not
  FK'd to `captures` (core invariant #4), so no cascade can move a standing. The UI adds the one
  judgement a filter can't: when *every* known capture is missing it warns first, because that is
  the signature of a captures folder that moved, not of files that were deleted. *Deferred, and
  kept possible on purpose:* a "locate moved capture by hash" step slots in **between** the scan
  and the prune — it only needs a scanner, since `CaptureStore.relocate()` already exists and
  `known_files()` gives it a name+size pre-filter so only real candidates get hashed.

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
- **League standings resolve identity per classification, with tagged keys — because race numbers
  are unique only among humans.** The AI field runs the real-world numbers, so a member on 11
  shares it with Sergio Perez; the original number-keyed grouping summed the two into one row and
  the last-seen name relabelled it "Sergio Perez" (found 2026-07-30 on the 2026 league opener).
  Three rules now hold it together. (1) `ClassificationEntry.is_ai` is captured and stored
  (PIPELINE_VERSION 2); rows from before that fall back to a name-vs-`DRIVER_NAMES` heuristic
  (`looks_like_ai`), which may block the number fallback but never overrides an explicit roster
  alias — only the game's own flag (`is_ai_entry`) is authoritative enough to do that. (2)
  Resolution is ordered by evidence — online-name alias (case-insensitive, never a generic shown
  name, never an AI-flagged car), then race number *for human cars only and only when
  unambiguous*, then the entry's own identity. (3) Keys are tagged tuples (`("member", name)` /
  `("ai", name)` / `("driver", number)`) resolved for a whole classification at once
  (`LeagueRoster.session_keys`, passed to `compute_standings` as `group=`), so two cars in one
  session can never share a standings row; a surviving repeat is split by shown name and then
  vehicle index rather than merged. Two privacy-restricted humans on one race number are
  unresolvable by construction — splitting is the honest outcome, and public online names are the
  fix. AI drivers are deliberately **not** filtered out: standings stay a full-grid championship
  view, AI simply keep their own rows. A roster may now list two members on one race number, but
  only if each has an online name; and canonical member names must be unique, since they are the
  grouping key (the capture seeder qualifies a repeated name with its race number to keep that
  true when one member changes number mid-season).
  *`member_of` (canonical name) stays for identity/label uses; `member_key` is the per-entry key
  and `session_keys` the classification-wide one standings actually use.*
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
- **Missing Final Classification → reconstructed classification (Option 2).** A session whose
  Final Classification never arrived used to show 0 drivers. When the packet is absent the assembler
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
  *Correction (2026-08-02) — this entry used to open "the game sends the packet once".* It does
  not: measurement shows **5–6 copies per session** (TELEMETRY_NOTES → Authoritative sources).
  Option 2's design is unaffected — a fallback for an absent classification is still right — but
  its *trigger* is much rarer than assumed. A single dropped datagram cannot cause it; only losing
  the entire results-screen window can, which is why the v0.4.2 sleep fix mattered more than
  another reconstruction feature. This is also why Option 3 sits at P3 rather than next up
  (PRIORITIES → B5).

## UI
- **PySide6 + PyQtGraph.** Chosen over a web stack / NiceGUI / DearPyGui for the analytics-heavy
  workload and the existing Python investment; the hosted-web future is uncertain and would be
  additive later, reusing the UI-agnostic domain/storage.
- **Fonts go through `ui/style.py`, never through a stylesheet** *(decided 2026-08-15, A4)*.
  Setting **any** stylesheet on a widget hands its painting to `QStyleSheetStyle`, which resolves
  and *caches* a palette for that widget at apply time. A label styled only
  `"font-size: 20px; font-weight: 600"` therefore freezes the **old theme's** default text colour
  into itself — despite never asking for a colour — and the `unpolish`/`polish` pass in
  `app._install_theme_refresh` does not force it to recompute. That was A4: a live light/dark
  switch left every heading in the previous theme's colour until restart, in every release from
  v0.3.0 to v0.8.0. So: **`apply_font` / `apply_heading` / `apply_bold`, and no stylesheet on a
  widget whose text should follow the palette.** A stylesheet that sets `color:` **explicitly** is
  fine and stays: the cached palette never reaches the text. `test/ui/test_styles.py` is the gate —
  it fails on any font-bearing stylesheet that does not set a colour, so this cannot re-accumulate
  silently. The helpers also settle `font-weight: 600` as `QFont.Weight.DemiBold`, never
  `setBold(True)`, which is 700 and would thicken every heading in the app.
- **UI text is sized in pixels, on one scale: 20px titles, 18px sub-headings, 14px body, 11px
  small** *(decided 2026-08-15, alongside A4)*. A4 found 11 `px` sizes mixed with 4 `pt` ones, the
  `pt` ones a leftover rather than a decision — and since 1pt is 1.333px at 96 DPI they rendered
  *larger* than everything around them, which is how the Help page title ended up a quarter bigger
  than every other page title. They were converted to the scale above, not to their DPI
  equivalents, because matching pixel-for-pixel would have preserved the inconsistency in new
  units. **`ui/style.py` offers no point-size path at all**: a second unit is precisely what let
  the two drift apart, so re-adding one should require a reason good enough to write down here.
  The gate fails on any `setPointSize` under `src/ui`, with one documented exemption —
  `car_status_graphic.py`'s `QGraphicsSimpleTextItem` labels are scene-graph text transformed with
  the view, not styled widget labels, so the widget scale does not apply to them.
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
- **Bundled imagery is open-licensed only — no third-party logos.** The nationality flags are
  flag-icons (MIT), vendored under `src/ui/assets/flags/` with the licence reproduced in
  `ATTRIBUTION.md`; anything else we ship must clear the same bar. That rules out **team logos**
  and **platform/publisher marks** (Steam / PlayStation / Xbox / EA, and the F1 marks themselves):
  they are copyrighted artwork *and* registered trademarks, no open licence exists for them,
  Wikipedia's non-free "fair use" rationale does not transfer to a redistributed app, and the
  game's own licence conveys nothing to a third-party tool. Putting a build in a public release
  zip is redistribution, and team branding in the UI would also imply an endorsement that doesn't
  exist. **Team identity is text** (`team_display_name` — nominative use, fine); if it ever needs
  to be more scannable the safe route is a hand-authored `team_id → colour` swatch (a colour value
  isn't protectable), optionally plain-text initials in our own font, and — only if someone asks —
  a *manual* user-supplied override folder the app never ships or fetches for them.
- **A standings row's nationality is display-only, and only drivers get a flag.** Driver standings
  show the same flag as the session result table, so `StandingRow` carries a `nationality_id` —
  but it is a *label*, never part of driver identity: grouping stays on the tagged keys above, and
  the field is updated last-seen-wins like `name`/`number`, so a merged driver shows their most
  recent round's flag. Constructor standings get **no** flag: the packet reports nationality per
  driver, not per team, so there is nothing truthful to render for a team row (and a team's flag
  would be branding, which the rule above rules out anyway).
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
  timed laps, so `ui/laps/track_layout.TrackLayoutProvider` gathers every valid Motion lap across
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
- **Canonical-map cache refresh — now P1, no longer deferred.** The provider's in-memory cache is
  not invalidated on a mid-run re-ingest (a stale weekend layout persists until app restart). This
  was filed as "fine for personal use, make it automatic before any release" — but releases have
  since shipped (v0.3.0 onward) with it outstanding, so it is now **PRIORITIES → A1, Cycle 1**.
  A persisted `track_layouts/*.parquet` cache stays deferred (P3, D3).
- **Lap detail composes reusable components over the 1a data split; visuals follow the game HUD.**
  The lap detail page (`ui/laps/detail_page.py`) is assembly only — it maps the 1a model straight to
  widgets: `LapTyreContext` → `TyreBox` (4 corners in on-car FL FR / RL RR order — **since removed,
  see the post-2c note at the end of this entry**), full `CarDamage`
  → `build_damage_table`, `SessionResult.setup_for_lap(n)` → `build_setup_table`, `LapTrace` →
  `TracePlot`. Damage/setup use a shared key/value table (`build_kv_table`) so no view rebuilds one.
  Tyre `_wear_color` thresholds mirror the F1 HUD: **<60 % green, 60–79 % orange, ≥80 % red**. Setup
  fields that are raw game values (differential on/off-throttle, engine braking, brake pressure,
  brake bias) are shown as plain numbers, **not** percentages. The elaborate car-body render stays
  deferred to **iteration 2c** (a car silhouette with colour-coded tyre + damage zones); ~90 % of
  its data is already stored (`LapTyreContext` + `CarDamage`), so its only new ingest is tyre
  carcass/surface + brake temperatures — until then, 1b's simple 4-box + table form stands.
  *Post-2c (2026-07-16): `TyreBox` was retired* — the car graphic's corner gauges cover tyres well
  enough, so `components/tyre_box.py` is gone. Tyre age moved to the "Car Status" title line
  (compound icon + "N laps old") and per-wheel blisters / tyre damage into the corner-gauge
  tooltips. The damage table gained a **Diffuser** row and de-duplicated **Sidepod**, and the setup
  panel became slider rows (`setup_fields` + the reusable `components/slider_row.py`), so
  `setup_rows` no longer exists.
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
  `TyreBox` can be retired later if the graphic covers tyres well enough — not in 2c. *(It was, in the
  post-2c polish pass; the left column is now the graphic alone.)*
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
  live in `_OUTLINES`); and the viewport ground shows through a too-faint fill, which is
  why the floor fences use `_PANELS`' solid fill rather than the `_STRUCTURAL` wash.

  **`_BACKGROUND` is a fixed dark grey, and until 2026-08-18 it was never applied at all** — the
  stylesheet was a plain string containing the literal text `background: _BACKGROUND`, so Qt
  dropped the declaration and the viewport had been effectively transparent for its whole life
  (which is what the "gotcha" above was really describing). With the colour actually reaching the
  widget, the *light* grey it named turned out to read badly: the whole point of the graphic is
  neon-on-dark, and a pale slab washed the glow out. It is now `#0d1117`, the canvas colour of the
  same palette family as `MUTED_TEXT` and this widget's tooltip — deliberately a step *darker* than
  the tooltip's `#1c242e`, so the tooltip still reads as a surface floating above the panel rather
  than merging into it. It stays **fixed rather than theme-derived** for the original reason: the
  colour-coding must mean the same thing on a light and a dark desktop.
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

- **The session detail view shows points only for races and sprints — because the stored value is
  wrong elsewhere** *(decided 2026-08-24, E1 branch 2b)*. This looks like a presentation choice and
  is not. Checked against the real database: `PRACTICE_1` player rows carry `points 25`, and
  `QUALIFYING_1` rows carry `25` and `8`. The game reports a carried-over championship figure in
  the Final Classification packet for non-race sessions, so rendering it would state a number that
  is simply untrue. The cell is gated on `is_race(session_type)` (with `slot.is_sprint_race` for
  the sprint table) and shows an em dash otherwise.
- **`Laps completed` stands in for overtakes until E15** *(decided 2026-08-24)*. On-track overtakes
  are not stored — `OVTK` events exist in every capture but the assembler never reads Event packets
  (PRIORITIES → E15). The cell shows `laps I completed / total laps` meanwhile. Chosen over
  *positions gained*, which is not the same thing (it nets out on-track passes against pit-stop and
  retirement shuffles) **and** is already rendered as the ▲/▼ glyph in the classification table
  beside it. **When E15 lands this cell becomes real overtakes** — it is a placeholder with a named
  successor, not a permanent field.
- **The penalties box has two states, not one** *(decided 2026-08-24)*. Only the aggregate is
  stored (`num_penalties`, `penalties_time_s` on the player's classification entry — real: eight
  rows currently carry `1 penalty / +3s`); type and lap are not. So a clean session shows
  `No penalties were recorded for this session.`, and a penalised one shows the aggregate **plus** a
  muted `Per-penalty detail (type and lap) isn't stored yet.` A single empty state would print "no
  penalties" for a session that demonstrably had one — the box would be lying rather than merely
  incomplete.
- **Tyre life is the worst wheel, not the mean of four** *(decided 2026-08-24, E1 branch 2c)*. The
  line plots `100 − max(wear)` across the four corners. The worst corner is what forces the stop,
  so it is the strategy-relevant number; a mean smooths away exactly the signal being looked for.
  Per-wheel values go in the tooltip, so nothing is lost.
- **Tyre stints are split on wear *dropping*, never on `tyre_age_laps`** *(decided 2026-08-24)*.
  Age is unreliable at the lap boundary — the Car Status snapshot straddles the game's increment,
  giving runs like `age 0, 2, 2, 4, 4` inside one stint — and a naive age-based split turned one
  27-lap race into fourteen stints. Cumulative wear is monotonic within a stint and resets to ~0 on
  a new set, so a drop is the reliable boundary. Details and the raw evidence in TELEMETRY_NOTES.
- **A tyre stint is drawn only from 2 laps up, in every session type** *(decided 2026-08-24)*.
  Chosen so wet qualifying and longer quali runs still get a chart, accepting that a single-timed-lap
  dry qualifying gets none. It also earns its keep as a data filter: pit in-laps produce single-lap
  artefact stints from stale readings, and this rule drops them without a special case.
- **No synthetic 100% starting point on the tyre-life chart** *(decided 2026-08-24)*. The first
  stored sample of stint 1 already reads ~4% wear — there is no 100% sample in the data. The y-axis
  runs 0–100% so a stint starting at 95.7% reads as "near 100" on its own; drawing an invented
  anchor point would be fabricating a measurement. Relatedly, stint offsets are computed from real
  lap *numbers*, never from list index: lap numbers are not contiguous (a red flag or a dropped lap
  leaves a gap), and an index axis would silently close that gap and misplace everything after it.
- **The pace and tyre-life charts are stacked full-width on a shared *stint-relative* x-axis**
  *(decided 2026-08-24, superseding the left/right split agreed earlier the same day)*. Two
  decisions in one, both measured rather than assumed:
  **(a) Stacked, not side by side.** The default window is `resize(900, 600)`, so a half-width plot
  is ~320 px — roughly **8 px per lap** over a 38-lap race, too tight to pick out a single slow lap.
  Full-width gives ~18 px/lap. It also matches `trace_plot.py`'s existing idiom (stacked plots
  sharing one axis) and lets wear fall-off and pace fall-off be read on one vertical line.
  **(b) Stint-relative, not absolute race lap.** Degradation is a function of stint age, so every
  stint restarts at stint lap 1 and the axis runs to the longest stint; that is what makes two
  compounds comparable. The real race lap goes in the tooltip.
- **On the pace chart, out-laps are plotted but excluded from the y-axis range** *(decided
  2026-08-24)*. This is what makes the stint-relative axis viable at all. Measured across every
  50%-distance race in the database, the first lap of each *post-pit* stint carries **+14 to +37 s**
  (the game bundles the pit loss into it). On an absolute axis those spikes sit at different x
  positions and read as "that's the stop"; on a stint-relative axis they all stack at x = 1, so an
  auto-scaled y-axis would span ~37 s and squash the real 1–3 s degradation signal into ~5% of the
  plot height. So the range is derived from the representative laps and out-laps draw as a clipped
  marker with the true time in the tooltip — measured data is never hidden, only kept from
  dictating the scale. **Stint 1 lap 1 is not excluded**: it is a race start, a much milder
  +2 to +3 s, and sometimes faster than the stint median.
- **The lap-time chart is "observed lap time by stint", and the fuel caveat is stated rather than
  corrected for** *(decided 2026-08-24)*. A stint-relative overlay conflates tyre degradation with
  **fuel burn-off**: the car sheds ~1.1-1.3 kg per lap, so a later stint is partly faster because it
  is lighter, not only because of the compound — and the shared axis puts that difference exactly
  where a reader will credit it to the tyre. Three consequences: **(a)** the chart is titled
  *observed lap time by stint*, never "tyre performance" or "degradation"; **(b)** the caveat is
  captioned in the UI; **(c)** **no fuel correction is applied here**, because a correction needs a
  track- and car-dependent kg→seconds coefficient, and picking one silently would swap an honest raw
  number for a confident estimate on a page whose job is "what actually happened".
- **Fuel-corrected lap time is an Analytics (E3) item, not session detail** *(decided 2026-08-24)*.
  The data is ready — `fuel_in_tank` is stored per lap, 406 of 406 populated, so this needs no new
  ingest — but it is a *derived, corrected* metric needing a coefficient, an estimation method and a
  way to express its uncertainty, and Analytics is where cross-session derived work already belongs.
  Session detail stays raw observed fact. If it ever reaches this chart it must be an explicit
  opt-in toggle, never the default, so the raw number is always what you see first.
- **A lap row in the session detail opens on a *single* click, unlike the laps overview's
  double-click** *(decided 2026-08-24)*. In the laps overview the row is also a fold target, so the
  first click is already spoken for; in the session detail the row's only job is to open the lap.
  Recorded here because the inconsistency is deliberate and will otherwise be reported as a bug.
- **The fastest-lap blue and personal-best green are shared tokens in `ui/style.py`** *(decided
  2026-08-24)*. `FASTEST_LAP_BLUE = "#2f81f7"` for the session's fastest lap and
  `PERSONAL_BEST = "#3fb950"` for my own fastest when it is not the session's, used identically on
  the session detail, the laps box, the Laps view and the Sessions overview. The green is the
  `_POS_COLORS` gain-green promoted out of `classification_table.py`, where it was private. Both
  set `color:` explicitly, which is the one kind of stylesheet A4 leaves alone.

## Localization

*Decided 2026-08-06, before any string was touched. The work itself is PRIORITIES → G block,
scheduled for Cycle 5; the approach is settled now because it is cheap to choose and expensive to
retrofit — every UI string written between now and then is written in one style or the other.*

**Why at all:** the league is Swiss and most members would rather read German. English stays the
source language and the fallback.

### Qt's `tr()` + `QTranslator`, not a Python dictionary of strings

A Python module mapping keys to translated strings was considered first — no build step, plain
Python to edit, trivially testable — and **rejected**. The deciding fact is **standard dialogs**.

This app is built on `QMessageBox`: import, relocate, prune, backup, re-ingest, the crash dialog,
the capability warning. Their buttons — OK / Cancel / Yes / No / Save / Open — are drawn by Qt
itself, and **Qt ships translations for them** (`qtbase_de.qm`). Install that through
`QTranslator` and they are German for free. A Python dict cannot reach them: you would get German
body text beside English buttons in *every dialog in the app*, which is precisely the
half-translated look that reads as unfinished, and the only workaround is replacing every standard
button by hand.

Two further reasons, both concrete here rather than general:

- **Plural forms.** This app counts constantly — "N of M sessions", "N captures found", "capture i
  of n". `tr("%n lap(s)", "", n)` handles that; a dict needs a hand-rolled plural rule per language.
- **Extraction.** `pyside6-lupdate` finds every `tr()` call, so a string cannot be silently
  forgotten. At ~363 candidate user-facing strings under `src/ui/`, "remember to add it to the
  dict" is not a workable rule.

**Accepted costs, chosen not discovered:** `pyside6-lupdate` / `lrelease` join the build; the
`.qm` files ship as bundled assets through `resource_path` (the same pattern as the flag SVGs, and
`capabilities.py` already gives the probe pattern for confirming a bundled asset actually shipped);
and translations are edited as `.ts` XML in Qt Linguist rather than as a Python file in the editor.

### A glossary is required before translation starts

Some terms stay English on purpose — *Session*, *Season*, *Lap* are the vocabulary the game and the
league already use in English. **That list must be written down before G2 begins.** Left implicit it
gets re-litigated string by string and lands inconsistently, which is worse than either choice made
uniformly.

### The locale is `de-CH`, not `de`

Swiss Standard German **does not use ß** — always `ss` (*Strasse*, not *Straße*). Tagging the
translation `de` and fixing it later means re-reading every translated string, so the tag is chosen
up front. `de-CH` falls back to `de` for anything unsupplied, so nothing is lost by being specific.

## Conventions
- **Module-level constants use a single leading underscore.** A double underscore name-mangles
  inside class bodies and has caused a `NameError`. Reserve `__` for genuinely mangled class
  attributes.
