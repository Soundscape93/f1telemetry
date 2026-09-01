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
- **A session that ran both dry and wet stores the *set* of conditions it saw, not a `mixed`
  flag** (E14, PIPELINE_VERSION 4). `SessionResult.weather` is the condition at the *end* of the
  session — the assembler's scaffold is last-write-wins — so a race that started dry and finished
  wet read as wet with nothing saying it changed. The fix adds `weather_seen`, the distinct
  conditions the Session packets reported in first-seen order, as a JSON column beside the
  snapshot (same additive pattern as `weekend_structure`; `ensure_schema` ALTERs it in). **The
  snapshot is untouched** — mixed is an *additional* fact, and a session that ran in one condition
  must still say which. `ui/components/weather.MIXED` is then selected on read.
  - *Why the set and not a boolean `weather_mixed`.* Same one additive column, but the boolean is a
    conclusion: once stored, "which conditions did it run in" can never be answered without another
    re-ingest, and that is exactly what a weather timeline would need. Storing the raw fact and
    reading it is what invariant #9 already does for `game_mode`, `driver_status` and `safety_car`.
    A timeline later widens this column rather than adding a second one.
  - *Why it also resolves the type mismatch.* `MIXED` is a string sentinel and deliberately not a
    `Weather` member, while the domain field is a `Weather` and the column an `int`. Deriving it at
    the one UI seam (`weather.session_weather`) means nothing ever tries to put a non-`Weather`
    value into either — the alternative shapes all end in widening the enum or the column.
  - *Why the settling filter runs at ingest, not on read.* The first 3-5 Session packets of a
    session report a placeholder condition (TELEMETRY_NOTES → "What the `weather` field reports"),
    and discarding it needs the packet times — which are gone once this is a set. Same reasoning as
    `_modal_driver_status`, `_peak_pit_status` and the safety-car rule: the assembler reduces raw
    frames to a stored judgement, and the judgement is documented where it is made.
  - *An empty set means "not captured", never "one condition"* — a row ingested before the column
    existed, or a capture holding only a session's opening seconds. Both read as not mixed.
- **Repository-per-aggregate.** One store file per aggregate root, named after it
  (`sessions.py`, `seasons.py`, future `laps.py`), each owning its table cluster; `schema.py` is
  the shared table layer. No mega-repository, no per-table files, and no abstract base until a
  second backend actually exists.
- **`session_assignments.session_uid` is NOT a foreign key** to `sessions`. Re-ingesting a
  capture replaces its session row by uid; a FK (or cascade) would wipe the manual league round
  placements. Keeping them independent means results can be re-processed freely.
- **Automatic round assignment is proposed, never written — and only where the identifier earns
  it** *(decided 2026-09-01, v0.11.0)*. Measured first: see TELEMETRY_NOTES → *The three link
  identifiers*, over all 72 sessions in all 33 captures. Two rules came out of it, and both end in
  a confirmation the user can decline rather than in a write.
  - **Weekend propagation — every mode.** Assigning one session to `(season, round)` offers every
    other stored session sharing its `weekend_link_identifier` for the same round. Licensed by the
    data: all 13 weekends have exactly one `track_id`, and all 7 rounds assigned by hand in this
    database contain exactly one weekend id, none mixing two. It also adds **no new trust** — the
    app already groups on this id in `domain/season.slot_for_session` and in the laps surface's
    canonical track-map cache.
  - **Season inference — career modes only.** `season_link_identifier` is a real season identifier
    only where it *differs* from `weekend_link_identifier`; in Online Custom / League Racing and in
    `game_mode` 4 the game reports the weekend's own id in that field (8 of 8 weekends), so grouping
    by it is grouping by weekend and buys nothing. Where a career id does exist it can name the
    **season**, never the **round**: no identifier carries a round number, so the round still comes
    from a track match against the calendar — and only when that track appears in it exactly once
    (a sandbox calendar may legitimately repeat one; ambiguous means ask).
  - **A slot with several attempts is never propagated.** Two attempts at one slot are
    indistinguishable in the telemetry (below), so proposing both would fill a slot twice and
    proposing one would be the silent choice this whole design refuses. Such a slot is left for the
    user. In this database that holds back exactly one slot across the 11 stored weekends.
  - **Why not a silent write.** A wrong automatic assignment is worse than no automatic
    assignment: it is invisible, it survives into standings, and `set_calendar`'s locked-round rule
    then freezes the calendar around it. The proposal costs one click and makes the mistake
    impossible.
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
- **Event packets: one `session_events` table, an allow-list of two codes, and no derived count**
  *(E15, decided 2026-09-01 after replaying all 33 captures — numbers in TELEMETRY_NOTES → Event
  packets).*
  - **A table, not JSON on the session row.** `setup_history` is the precedent for penalties alone
    (129 rows across 73 sessions), but not for overtakes — ~84 filtered rows per session, 562 in the
    worst. Splitting the two kinds across two shapes would double the read paths for one aggregate,
    so both live in one table with a `code` discriminator plus a JSON `detail` for the code-specific
    remainder. Adding `COLL` later is rows, not a migration.
  - **Keyed on `session_uid`, deliberately NOT FK'd** — `EventStore` is the repository-per-aggregate
    sibling of `LapStore` and copies its contract exactly: replace-by-uid on save, delete-by-uid on
    delete (core invariant #4). Delete / tombstone / restore therefore need the same one-line
    additions `lap_store` already has in `pipeline.delete_session`, `_re_tombstone` and
    `restore_session`, and nothing new is invented.
  - **The allow-list is `PENA` and `OVTK` only**, and which codes get ingested is part of the shape
    rather than an afterthought: `BUTN` alone is 79% of 134,208 event packets. Everything else is
    excluded for a stated reason — already available elsewhere (`SPTP`, `FTLP`, `RTMT`), no designed
    consumer (`COLL`), or a marker whose fact E17 already reads off the Session packet. The full
    table is in TELEMETRY_NOTES → *Codes deliberately not ingested*.
  - **Store the events; never store an overtake count.** The measured reason is that no aggregate
    survives scrutiny — raw `OVTK` is 4.5× the `LAP_POSITIONS` ground truth, the both-cars-racing
    filter 2.6×, and no reversal-cancel window is per-race accurate (0.61×-1.91× at the window that
    matches in total). The count the UI shows is a `len()` over rows the view has already loaded,
    never a stored aggregate — one derivation, so a re-ingest producing different rows produces a
    different count with nothing stale left behind it. **The original phrasing of this safeguard
    leaned on a list beside the count, and branch 3 dropped the list** *(2026-09-01)*: `+N / −M` in
    the details grid is now the only overtake surface, so a reader cannot check it against rows on
    screen. The derivation is unchanged and a stored aggregate's failure mode — a header reading
    `+7` above six rows — is still impossible, but a *mis-attributed* pass is now caught by
    `test_formatting.py` against real rows rather than by eye. That is the cost, taken knowingly.
  - **Exactly one filter is applied at ingest**, because it is the only rule the data supports
    without qualification: *neither car in the pit lane, neither in the garage*. It drops 58% of raw
    events and every pass of a parked car, and needs only the Lap Data frame the assembler already
    holds. Everything past it stays derived and revisable.
  - **Store field-wide, whatever a given surface displays.** Player-involved events are ~1,005
    across all 33 captures against ~6,130 field-wide — both trivial beside 440 lap rows. Widening
    later would cost a **re-ingest prompt** to recover data already on disk, and that prompt is the
    one cost this project treats as expensive (it is what the whole v0.9.0 grouping decision turned
    on). *(Clarified 2026-09-01, E15 branch 2.* This bullet read "display player-only", which was an
    argument about **overtakes** phrased over both codes. Penalties display **field-wide** — see the
    Race control box under UI — and passes display player-only; storing field-wide is what makes
    both possible.*)*
- **`session_uid == 0` is init noise for every packet except `EVENT`** *(E15, 2026-09-01)*. Core
  invariant #3 is correct for the ten packet ids the assembler routed before E15 and **false for the
  eleventh**: 37% of all penalties arrive on a zeroed header, as the game's end-of-session replay of
  the accumulated penalty log. Dropping them loses real penalties; ingesting them naively multiplies
  them by up to 7×. The merge rule reproduces the game's own `num_penalties` and `penalties_time_s`
  for 9 of 9 cars. See TELEMETRY_NOTES for the mechanism and the evidence.
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
- **Session→round assignment was round-centric, and is session-centric from v0.11.0.**
  *Originally:* open a season → a round → its weekend → assign captures, rather than a global
  sessions list — a league weekend is several sessions at one track, so matching a capture's track
  to the round made assignment nearly one-click, and it kept the weekend view and its assignment
  together. That bullet closed "*a session-centric view in the Sessions surface is a fine
  complement later*", and **v0.11.0 is that later**: assignment moves into the weekend-filtered
  Sessions overview and the round-centric weekend page is retired (E1d, below). The original
  reasoning is not overturned — the track match is *kept*, as the round half of the automatic
  proposal in → Storage — only its housing changes, because "open the round → see that weekend's
  sessions" is the flow a user expects and the Sessions surface is where sessions belong.
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
- **`Laps completed` keeps its cell; overtakes get their own** *(decided 2026-08-24, **revised
  2026-09-01 when E15 was specified**)*. The original decision called this cell a placeholder that
  "becomes real overtakes when E15 lands". That was wrong, and E15 did not do it: the cell earns its
  place — it reads `laps I completed / total laps`, it sources the count from the classification
  rather than the stored lap rows (a late-started recording stores fewer laps than were driven), and
  the `/ total` is races-only because `total_laps` is meaningless elsewhere. None of that survives
  being repurposed. Overtakes went into a **new third column** instead (below). The original
  rejection of *positions gained* still stands: it nets on-track passes against pit-stop and
  retirement shuffles, and is already the ▲/▼ glyph in the classification table beside it.
- **The details grid is 4×3, not 4×2 + a fifth row** *(decided 2026-09-01, E15)*. A fifth row would
  stretch the details / classification band further, which is worst in Q3 sessions where the
  classification is already short. A third column across the existing four rows adds the three cells
  E15 needs without changing the band's height:

  | | | |
  |---|---|---|
  | `Position` | `Started` | `Points` |
  | `Fastest lap` | `Laps completed` | `Overtakes +/−` |
  | `Difficulty` | `Conditions` | `Track & air temp` |
  | `Team & mode` | `Recorded` | `Time of day` |

  - **`Overtakes` is the player's own passes only** — `+N / −M`, made and suffered. The field-wide
    number is 250 a race and 2.6× the ground truth (Storage, above); the player's is a handful in
    almost every race — median 3 rows across the 17 races here that hold any, 5 or fewer in 12 of
    them, and 0 in six, every one of those a start from pole and a win. The one race that is not a
    handful is why the passes are a count and not a list (see the Race control box below).
    **`+0 / −0` is told apart from "not captured" by the field-wide rows**, and that is where
    storing field-wide stops being merely cheap and becomes load-bearing: a race that ran holds 52
    to 562 of them, so a real zero always has rows to prove it, while a session ingested before
    `PIPELINE_VERSION` 5 has none. The only three races here with no rows are reconstructed
    fragments — no stored laps, no Final Classification packet — where "not captured" is the
    literal truth rather than a fallback. **Races only**, em dash otherwise: the
    892 practice and 994 qualifying "passes" in the captures are almost all out-lap traffic. Same
    gate as `player_points_label`.
  - **`Started` is races only too.** `grid_position` is `0` for every non-race row in the database,
    so it takes the same em dash as `Points` beside it.
  - **`Track & air temp` over `Rain %`.** Both would be new columns riding E15's `PIPELINE_VERSION`
    4 → 5 bump at no extra prompt, so cost did not decide it. Temperature is a **top-level Session
    field — an observation**; `rain_percentage` exists only inside `weatherForecastSamples` and is a
    **probability**, which would render immediately beside `Conditions`, an observed condition. One
    real session reads 83%: beside a heavy-rain icon that invites "83% of what?", beside a clear one
    it reads as a contradiction. `ui/components/weather.py` already records why the observed field
    beats that array. Temperature also earns its keep — it is the missing context for the tyre-life
    chart, since track temp is the biggest external driver of degradation.
  - **`Time of day`, and nothing already stored, for the provenance cell.** Every already-stored
    candidate was measured and rejected: `result_reason` is garbage for a finisher (TELEMETRY_NOTES
    → Result status), `num_pit_stops` and `total_race_time_s` are already the STOPS and TIME columns
    of the table beside the grid, safety-car/red-flag counts would read "None" in 53 of 56 sessions,
    and `recorded_by` is blank for every capture recorded on this machine. `time_of_day` is a real
    clock (`0..1439` in 73/73 sessions) and pairs with `Recorded` as in-game time beside real-world
    time. **`header.session_time` is not a clock** — it is elapsed session seconds, and is what the
    E14 settle window measures.
  - All three new cells read the **first Session packet past `_WEATHER_SETTLE_S`**: the whole Session
    payload is zeroed for the opening 3-4 packets of a session. The existing constant is reused
    rather than a second one invented for the same artifact — see TELEMETRY_NOTES.
- **The Penalties box becomes the Race control box** *(decided 2026-09-01, E15)*. It holds the
  session's penalties, field-wide. Passes were weighed for the same box and **left out**
  *(decided 2026-09-01, E15 branch 3)*: a pass is not a race-control action, so the box's own title
  argues against it; the details grid's `Overtakes +/−` is on the same screen and a count line here
  would be the only number on the page stated twice; and the box's three-state honesty rule is
  about the penalty store, which a second capture state under one heading would blur. **The
  measurement decided it, and not the way the objection was first phrased** — a list would have
  *under*filled the box in 16 of the 17 races here that hold passes (median 3 rows, 5 or fewer in 12
  of them), so length was never the problem. The seventeenth is: 42 rows, of which sixteen are one
  incident inside 5.7 seconds (the whole field streaming past a car that had gone off), and **40% of
  all 95 player race rows are the same pair swapping back within 30 s** with 54% sitting in a burst
  of four or more inside ten seconds. A count absorbs that; a list of rows reads as a fault. It is
  **scrollable with the same height cap as the Laps box beside it**, so a
  race with many penalties or passes cannot keep growing the page — the same reason the
  classification table takes `scrollable=True`.
  - **The penalties half is field-wide and names every driver; the passes half is the player's**
    *(settled 2026-09-01, E15 branch 2)*. What a league reader opens a session for is what happened
    to the whole field, and a screenshot of the page should carry it. The join is
    `classification.entries` by `vehicle_index` — the only one available, since `SessionStore` does
    not persist `participants` — and it resolves **129 of 129** rows, the seven reconstructed
    classifications included. A row that cannot be resolved still renders, as `Car 14`: dropping a
    penalty because its driver is unknown is the silent loss this feature exists to undo.
  - **Non-AI-only was measured and rejected** *(same date)*. It is perfectly *reliable* — `is_ai`
    landed at `PIPELINE_VERSION` 2 and events at 5, so any session holding penalty rows carries the
    real packet value and the `looks_like_ai` name fallback is never needed — and it is still wrong.
    It drops 54 of 129 rows; it is **identical to player-only in 35 of 42 penalised sessions**,
    because 34 of them have one human in the field, so it quietly rebuilds the box this branch is
    replacing; and it **empties four boxes that held 8, 6, 3 and 1 penalties**, which is the honesty
    rule below breaking outright. Size is not the argument it was assumed to be either: the largest
    box in the database is eleven rows and the median is one, against a 500 px cap that scrolls. AI
    cars are therefore named like any other and nothing marks them — the classification table beside
    the box does not distinguish them either, and only this box doing so would make the two read as
    different kinds of thing.
  - **It is a table, and its columns are `LAP | DRIVER | OUTCOME | REASON`** *(2026-09-01, E15
    branch 2)*. Laid-out labels read as a sparse list; four aligned columns under a header read
    like the Laps table beside it, and inherit the alignment and the flag-in-the-driver-cell the
    classification table already uses. **LAP and DRIVER lead**, matching that table's POS/DRIVER
    order and, more to the point, because OUTCOME is the single word "Warning" on 70 of 129 rows —
    leading with it would put a wall of one repeated word where the varying columns belong.
    "OUTCOME" over "Penalty" because 19 of the rows are retirements, which are not penalties; over
    "Type" and "Event" because both are meta rather than about the session, and "Event"
    additionally collides with the Event-packet vocabulary this feature is built on.
  - **A collision names the other car, and the data decides which rows those are.**
    `other_vehicle_index` is all-or-nothing per infringement: present on 44 of 44 Small Collisions,
    1 of 1 Big Collision and 3 of 3 Blocking rows and absent on all 81 rows of every other kind,
    resolving to a classification entry 48 of 48 times and never naming the car itself. So the
    reason reads "… with <driver>" whenever the packet carries a second car, with no infringement
    test in between. "with" is exactly right for the 45 collisions and merely serviceable for the
    3 blocking rows, where the other car is the one *being* blocked — a second connector for three
    rows would cost more than it earns.
  - **One font weight, two columns, two meanings.** A **bold driver** is a car the game called
    human, so a league's people separate from the AI filling the grid — and it survives a lobby
    whose members hide their online names, where every one of them reads `Player` and the weight is
    the only thing left that says so. **Bold penalty text** is the sporting subset
    (`SessionPenalty.is_sporting`), which is what explains a box listing eleven penalties beside a
    classification badge reading ×1. Weight rather than colour, so nothing here can freeze a palette
    (core invariant #11).
  - **Two textual rules keep the game from contradicting itself**, both stated in
    `ui/sessions/race_control.py` rather than hidden. An invalidation loses its trailing "without
    reason" — the game's HUD wording for "the driver was shown no reason", which beside the reason
    the row prints is a denial of the rest of its own line. And an infringement that repeats the
    penalty's own words loses the repeat, so `Retired` + `Retired mechanical failure` is one
    statement rather than two (a prefix rule, not a table of pairs). Every tooltip carries both
    names exactly as the game sent them, so nothing tidied is lost — core invariant #9's spirit:
    keep the raw value, interpret on read.
  - **`places_gained` 0 and None are different facts and never share a rendering.** 0, in 75 of the
    129 rows, means "gained no places"; None, in 47, means the field does not apply. Neither earns a
    clause on the row — a box of warnings would otherwise say "0 places" eleven times — and the
    tooltip is where both are spelled out, beside the added time, which is set on only 4 rows
    (3, 3, 3 and 5 s).
  - This retires the box's two-state design *(decided 2026-08-24, closed by E15)*, which existed
    only because the detail was unstored: a penalised session used to show the aggregate plus a muted
    `Per-penalty detail (type and lap) isn't stored yet.` so it could not report itself clean. The
    detail is stored now, so the note goes and `reference.penalty_name()` / `infringement_name()` —
    written and unused since the reference tables landed — finally have their caller. The honesty
    rule that produced the two states stays, and now needs **three**. Rows are listed. No rows *but*
    a classification recording a penalty says the detail has not been read from the capture yet —
    transient, where the old note was permanent, since the re-ingest clears it. Only when neither
    has anything does the box speak, and then about the **store**: "No penalties are stored for this
    session", because a session ingested before `PIPELINE_VERSION` 5 holds no rows and cannot be
    told apart from a genuinely clean one. On a database still stamped 4 that is 7 of 56 sessions in
    the second state and 49 in the third.
- **A grid penalty rides the classification's GAP cell in practice and qualifying** *(2026-09-01,
  E15 branch 2)*. The result screen counts penalties but records no *time* for a grid drop, so
  `format_penalty_badge` renders one as a bare `⚑ ×2` that never says what it cost — and the
  non-race half of the table never showed it at all. The places come off the stored `PENA` rows
  instead (`race_control.grid_penalty_places`), **summed**, because the game issues them one at a
  time: in `972807263…` two cars each took two 5-place penalties and start ten places back, which
  `num_penalties` records only as "2". The count is dropped and the places kept — one 10-place
  penalty and two 5-place ones put the car in the same slot.
  - **GAP, not BEST.** A grid penalty is served in the *race* and changes nothing about this
    session's result, so alternating it into BEST would read as if the lap time itself had been
    penalised. GAP is a derived number and the least load-bearing column, and the mechanism is the
    one the race table already uses for its TIME cell — `_wire_penalty_alternation` now serves both.
  - **Passed in, not read here.** `build_classification_table` takes an optional `grid_penalties`
    map rather than an `EventStore`: the weekend page holds no event store and simply shows no
    badges, and a session ingested before `PIPELINE_VERSION` 5 has no rows to build one from. The
    session detail page reads the penalties **once** per render and hands the same rows to both the
    classification and the Race control box, so the two cannot disagree.
- **Tyre life is the worst wheel, not the mean of four** *(decided 2026-08-24, E1 branch 2c)*. The
  line plots `100 − max(wear)` across the four corners. The worst corner is what forces the stop,
  so it is the strategy-relevant number; a mean smooths away exactly the signal being looked for.
  Per-wheel values go in the tooltip, so nothing is lost.
- **A charted "stint" is a *run*, not a tyre set: split on fresh tyres or a return to the
  garage, never on age increments** *(decided 2026-08-24, extended 2026-08-25)*. Age is unreliable at the lap boundary — the Car Status
  snapshot straddles the game's increment, giving runs like `age 0, 2, 2, 4, 4` inside one stint —
  and a naive age-based split turned one 27-lap race into fourteen stints. Cumulative wear is
  monotonic within a stint and resets to ~0 on a new set, so a drop is the reliable boundary.
  Details and the raw evidence in TELEMETRY_NOTES.

  **Revised 2026-08-24, during implementation: a *fall* in `tyre_age_laps` is a second boundary.**
  Wear alone can miss a set change. In a career practice session a tyre-saving programme is followed
  by a qualifying simulation on a **fresh set of the same compound**, and the new set's first wear
  reading can be *higher* than the old set's last: `10198131…` (Jeddah P1) reads 9.51, then 15.92,
  then 17.97 across the change. Compound unchanged, wear never drops, so the two runs merged into
  one curve claiming a single set had worn 9.51 → 17.97 — a straightforwardly false statement about
  what happened. A fall in the age counter is the missing signal, and it is **not** the rule warned
  against above: that concerns age *increments*, which the snapshot mangles. Only a fresh set can
  put a lower number there. Verified across all 406 stored laps — it adds exactly one stint
  boundary, and changes one session of 54. The two tests are complementary, not redundant: 26 of the
  27 age falls already coincide with a wear drop, and 4 wear drops have no age fall.

  **Extended 2026-08-25: a return to the garage also ends a run, read from the fuel load.** Checking
  every session's charts showed the three tyre signals are not enough, because **a run and a set are
  different things**. In a race they coincide — the car leaves the garage once — but practice and
  qualifying are full of one set doing several runs, and of two *fresh sets of the same compound*
  doing a single lap each. Nothing in the tyre data separates the latter: a Q3 pair of new softs
  reads `age 0` on both laps, the same compound, and wear that *rises* rather than resets. Drawing
  them as one line claims a continuity that did not happen.

  `fuel_in_tank` resolves it, and is already stored 406 of 406. A full lap burns **1.06-1.96 kg**
  across every session here, and fuel cannot be added on track — so a load that rises, or barely
  falls, means the car was in the garage. Measured: **22 detections in practice and qualifying**,
  every one matching a run boundary the driver confirmed, against **1 in 322 race transitions** —
  and that one is `12316788…`, whose lap 3 is missing and whose lap 2 took 170 s. It independently
  settled two open questions about real sessions (Suzuka Q2 was two runs on one set of inters;
  Suzuka Q1 was one run).

  **Not** `tyre_age_laps == 0` on both laps, which looks like the same signal and is not: a post-pit
  out-lap reports `age 0` at wear `0.00` and the lap after it still reports `age 0`, so that rule
  breaks three race stints that are currently correct. Tested before it was rejected.

  **Replaced 2026-08-27 by what it was standing in for, and kept as the fallback (E17).** The fuel
  rule was knowingly a proxy, and `driver_status` says it outright: the assembler now stores
  `preceded_by_garage`, “the car was in the garage between the previous emitted lap and this one's
  timed run”. Measured against the whole database, the stored flag reproduces **all 11** fuel
  detections among the stored laps and rejects the **one** false positive — Shanghai sprint
  `12316788…` lap 4, where a red-flag stoppage made the fuel rise across a missing lap while the
  game's own tyre stints say the whole race ran on a single set. Fuel is now read only for laps
  ingested before `PIPELINE_VERSION` 4, and `Lap.has_lap_context` is the single test that chooses;
  both paths are tested against the same real sessions, so neither can win silently.

  It does **not** replace wear / age / compound. A race never reports `IN_GARAGE` — the game says
  `IN_PIT_AREA` for a pit stop and keeps the garage for the garage proper — so this is a fourth
  boundary beside them, not a substitute for them.
- **One lap classification feeds the Laps box, the stint split and the average pace** *(decided
  2026-08-27, E17)*. Three parts of the session detail have to agree about what a lap was, and
  before this each derived its own answer — the pace chart called a practice flying lap an in-lap
  and left it out of an average the table said nothing about. `ui/sessions/lap_context.py` now
  classifies each lap once and the other two read it, so a lap the table marks and a lap the average
  drops are the same lap by construction rather than by two modules happening to agree.

  **Stored truth first, inference only for old rows.** Out-lap is “the pit-lane timer was running as
  the lap began”, and nothing else — see the red-flag entry below for the half that was tried and
  removed. In-lap is the pit-lane
  timer still running at the line, deliberately **not** `driver_status == IN_LAP`, which the game
  sets on the *planned* in-lap and leaves set while the driver stays out (three laps early in one
  race here, six in another). Safety car and red flag come off the Session packet, which the
  assembler already routes — no Event-packet work, which is E15 and unrelated. Evidence in
  TELEMETRY_NOTES → *What `driver_status` actually reports*.

  **A red-flag restart is a standing start, not an out-lap** *(corrected 2026-08-30, E17)*. The
  first rule read the restart off `driver_status == OUT_LAP` held for most of the lap, because the
  pit-lane timer never runs on one. Manual checking of the Shanghai sprint said otherwise and the
  game agrees: it does not time the drive from the pit lane back to the grid, so that status is left
  over from a lap that was never emitted, and the lap it lands on begins at rest in the grid box.
  Scanned across all 470 emitted laps, the `driver_status` half contributed only those two laps and
  the timer alone missed no real pit exit — so the stored `is_out_lap` is now the timer alone, and
  the restart is derived in `lap_context` from `red_flagged` on the lap before, chipped `START`. It
  is the same exclusion either way; what was wrong was the reason shown for it. The same stoppage
  also makes the game report near-zero tyre wear for one lap, which used to open a false run — the
  wear boundary is now suppressed on a red-flagged lap while age and compound keep theirs. Evidence
  in TELEMETRY_NOTES → *What `driver_status` actually reports*.

  **Five indicators, one per reason a lap leaves the average**: `START`, `OUT-LAP`, `IN-LAP`,
  `SC`, `RED-FLAG`,
  as short chips in the existing Laps box with the sentence on hover. The set is chosen by a rule
  rather than by taste — *every* pace exclusion has a chip and *every* chip is a pace exclusion — and
  that equality is what makes an average readable off the page: a run whose number looks wrong can
  always be traced to the laps that did not contribute to it. `START` is in for exactly that reason:
  it was going to be the one silent exclusion left, which is the failure mode this item exists to
  remove. Chips read in the order the lap ran (`OUT IN` for a lap that left the pits and came back
  into them), not by severity. A *sixth* is a real decision rather than a small one — it would break
  the equality, so anything that is context but not an exclusion belongs somewhere else.

  **Two things this knowingly changes**, both measured end-to-end across every capture:
  **(a)** in practice and qualifying the game never times the lap the driver returns to the pits on,
  so an emitted practice lap is *never* an in-lap — the old inference labelled one in six practice
  sessions anyway and dropped a genuine flying lap out of the run average. It is now counted, which
  moves Sakhir P1's opening run from 1:22.304 to 1:23.939. The higher number is the honest one:
  `driver_status` reads `FLYING` for every frame of that lap.
  **(b)** a safety-car lap now comes *out* of the average. Shanghai `6912670…`'s final run read
  1:55.967 and actually ran 1:36.776. Where every lap of a run is excluded the average reports an em
  dash rather than a number about something else — sprint `2114813…`'s three-lap final run, an
  out-lap plus two safety-car laps, does exactly that.
- **A tyre stint is drawn only from 2 laps up, in every session type** *(decided 2026-08-24)*.
  Chosen so wet qualifying and longer quali runs still get a chart, accepting that a single-timed-lap
  dry qualifying gets none. It also earns its keep as a data filter: pit in-laps produce single-lap
  artefact stints from stale readings, and this rule drops them without a special case.

  **Confirmed 2026-08-24 against how the sessions are actually driven, after measuring what the rule
  removes.** Splitting runs correctly showed the minimum drops far more outside races than the
  original wording implied — by session type: RACE 3 of 25 runs dropped, PRACTICE_1 3 of 12,
  PRACTICE_2 2 of 8, PRACTICE_3 4 of 5, QUALIFYING_1 5 of 8, QUALIFYING_2 6 of 8, QUALIFYING_3 5 of
  10. That reads alarming and is not: it matches how the sessions are driven. **Dry qualifying is
  one flying lap per session**, so there is no stint to draw and nothing is lost; a **wet** session
  runs longer, so Suzuka's Q1/Q2/Q3 do get both charts. **P1 and P3 are practice programmes and own
  quali sims** — one or two laps, then back to the garage — so they are correctly not charted.
  **P2 is where the race simulations are driven** (Suzuka, Sakhir, Melbourne here), and those
  sessions do get their charts, which is the case that matters. A one-lap graph carries no
  information at all — it is a single point, with no degradation to show — so the floor stays at 2.
  Three was considered and rejected: the longer practice simulation runs are exactly the non-race
  case worth charting, and some are two laps.
- **No synthetic 100% starting point on the tyre-life chart** *(decided 2026-08-24)*. The first
  stored sample of stint 1 already reads ~4% wear — there is no 100% sample in the data. The y-axis
  runs 0–100% so a stint starting at 95.7% reads as "near 100" on its own; drawing an invented
  anchor point would be fabricating a measurement. Relatedly, stint offsets are computed from real
  lap *numbers*, never from list index: lap numbers are not contiguous (a red flag or a dropped lap
  leaves a gap), and an index axis would silently close that gap and misplace everything after it.
- **The session detail's track map is the driven fastest lap, not the canonical median line**
  *(decided 2026-08-24)*. The Laps surface draws the weekend's median racing line via
  `TrackLayoutProvider`; the session detail draws the player's fastest lap through
  `TrackMap.set_trace`. Two measured reasons: the provider walks every Motion lap of the whole
  weekend, ~1 s of Parquet reading on the GUI thread before its cache warms, against ~10 ms for
  one lap; and it lives in `ui/laps/`, which the Sessions surface must not import from. The
  fastest lap specifically, because an out-lap or a spin would draw an excursion as if it were the
  circuit. If this ever needs the median, the honest fix is moving the provider into
  `ui/components/` and giving it a home on the window - not a cross-surface import.
- **The classification box names the session type in its own title** *(decided 2026-08-24)*.
  It duplicates the page header, which normally argues against it - but the box is screenshotted
  and shared on its own, and a results table that doesn't say which session it is has lost the
  thing that makes it readable to someone who wasn't there.
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
- **The pace chart's y-axis is a fixed 8 s window starting just under the quickest lap**
  *(decided 2026-08-24, replaced 2026-08-25)*. This is what makes the stint-relative axis viable at all. Measured across every
  50%-distance race in the database, the first lap of each *post-pit* stint carries **+14 to +37 s**
  (the game bundles the pit loss into it). On an absolute axis those spikes sit at different x
  positions and read as "that's the stop"; on a stint-relative axis they all stack at x = 1, so an
  auto-scaled y-axis would span ~37 s and squash the real 1–3 s degradation signal into ~5% of the
  plot height. So the range is derived from the representative laps and out-laps draw as a clipped
  marker with the true time in the tooltip — measured data is never hidden, only kept from
  dictating the scale. **Stint 1 lap 1 is not excluded**: it is a race start, a much milder
  +2 to +3 s, and sometimes faster than the stint median.

  **Revised 2026-08-24, during implementation, on two further measurements.**
  **(a) The in-lap comes out of the range too.** Measured across every stint in the database, an
  in-lap runs a median **+3.68 s** over its own stint median (min −0.88, max +32.15) — the same
  order as the 1–3 s degradation signal the chart exists to show. On Shanghai Race 2 the in-lap
  (lap 13, 1:44.165 against a 1:39.004 next-worst) is the single lap setting the whole scale;
  removing it takes that chart from a 9.7 s span to 4.1 s. Unlike the out-lap, which is structural
  and certain, the in-lap is **inferred**: a stint ending immediately before the next one begins
  means the stop happened between them. The contiguity check makes it conservative — where laps are
  missing around the stop it declines to claim, as in `11708585…`, whose stint 2 ends at lap 18
  while the next opens at 22 — so it can under-report but never mislabel.
  **(b) The remaining spread is capped at 8 s, anchored at the fastest lap.** No rule can classify
  an incident lap, and they wreck the scale exactly as an out-lap does: one race here spans 49.7 s
  on four laps in the 120–140 s range. Ordinary variance stays well inside 8 s across every session
  measured, so the cap costs a consistent driver nothing — 23 of 34 chartable sessions sit under it
  untouched — and rescues a chaotic one. It is anchored at the fast end because the fastest lap is
  the reference every other lap is read against. The padding is taken from the capped span, not the
  raw one, or a 40 s spread would burn a quarter of the window on dead air below the fastest lap.
  The cost, stated: on Melbourne `14435457…` the cap clips the whole two-lap opening stint, whose
  90.5/91.7 s laps sit ~10 s off a 80.8 s best — and that spread is mostly fuel burn-off, the very
  thing the caption warns about. Every clipped lap is still plotted at the top edge with a triangle
  marker and its real time in the tooltip: 33 of 375 timed laps (8.8%), of which 14 are out-laps
  already off the scale by rule.

  **Replaced 2026-08-25: the axis is a fixed height, and the exclusions no longer scale anything.**
  Fitting the axis to the data was wrong at *both* ends, and only the wide end had been noticed. Too
  narrow is just as dishonest: a run whose laps sit within 0.3 s of each other had that 0.3 s
  stretched over the full plot height, so laps that were effectively a dead heat read as a dramatic
  fall-off. The axis is now **always exactly 8 s**, anchored so the quickest lap sits 5% above the
  floor and the remaining 7.6 s runs upward — upward because no lap can appear below the quickest
  one, so centring the window would spend half the plot on space nothing can occupy.

  Two consequences. **(a) The exclusions stop governing the scale.** With the height fixed, an
  out-lap cannot stretch the axis however slow it is, so there is nothing to exclude — the anchor
  counts *every* timed lap. `representative_laps` was deleted; `is_out_lap` and `in_lap_numbers`
  survive only to *label* the tooltips. **(b) It fixes a bug the exclusion caused.** In practice and
  qualifying the real out-lap is usually never stored (no Session History time, or it starts too far
  past the line), so a run's first stored lap is a *flying* lap and is often the quickest of the
  session. Anchoring above it put it below the axis floor, where it was drawn nowhere at all —
  Suzuka P1 silently lost its best lap this way, line and marker both. Clipping now clamps at both
  edges, and the marker is a triangle pointing the way the real value lies. Relatedly, the out-lap
  *label* now requires the lap to actually be slower than the median of its own run.

  A fixed height also makes two sessions comparable at a glance, which fitting actively prevented.

  **The known cost, accepted: mixed dry/wet sessions.** An intermediate or wet run can be 14 s off
  the dry pace, so it lands entirely on the clipped top edge — Shanghai P1 (`13974110…`) does
  exactly that with its lap 10-11 intermediate run. Widening automatically was rejected because it
  reinstates the original problem: fitting that session would need ~16 s and would compress the dry
  runs' 1-3 s degradation to under a fifth of the plot. An **opt-in** expansion is the right shape
  and is banked (ROADMAP → Other surfaces), not built. Meanwhile the laps are drawn, marked clipped,
  and carry their real times on hover.
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
- **Restore is a single-capture re-ingest with a tombstone rollback, not a cleared tombstone**
  *(decided 2026-08-24, built 2026-08-25 as E1 branch 3)*. `SessionStore.restore` only clears the
  tombstone, which is the *smaller* half of the job: the session's rows are gone, so clearing it
  alone leaves nothing behind but permission for a future ingest to re-create it. `pipeline
  .restore_session` does the real thing — find a capture holding the uid, clear the tombstone,
  ingest **that one file**. One file is enough because `ingest_capture` replaces by uid, and it is
  idempotent for the same reason. Re-deriving one session by decompressing every archive in the
  database is what the guided re-ingest under Help already is.

  **The ordering is the safety property, and it is why this function exists.** `ingest_capture`
  reads `deleted_uids()` at the *start*, so the tombstone has to be cleared **before** the ingest —
  which opens a window where the uid is un-tombstoned with **no session row**. That state is worse
  than a deleted session: the next *full* re-ingest silently resurrects a session the user believes
  is gone, and nothing anywhere says so. So everything decidable is decided before the tombstone is
  touched, and every failure after it rolls back. `SessionStore.delete` cannot perform that
  rollback — it returns `False` and writes nothing when there is no session row — hence
  `SessionStore.tombstone`, which merges a tombstone with no row required.

  **There are two half-states, not one.** The plan named the first; the second turned up while
  building it. *(a) Cleared, no row* — the ordinary failure (a corrupt archive, or a capture that
  turned out not to hold the uid); the tombstone is simply re-written. *(b) Cleared, row present* —
  a capture holding several sessions, where ours was saved before a later one raised. Left alone
  that session would sit in Sessions **and** in the deleted list at once, so the rollback deletes
  the resurrected row and takes its laps with it, exactly as `delete_session` does. The tombstone is
  re-written last in both cases with the *original* values, `deleted_at` included — a failed restore
  is not a new deletion and must not re-date one in the manager.

  **The capture is verified, never assumed.** `capture_sessions` rows go stale (pruned, re-recorded,
  written by an older ingest), so the sessions the ingest returns are checked for the uid rather
  than trusting the row that pointed there; a miss rolls back and says so. Passing `capture_store`
  through to the ingest *corrects* such a row on the way past (`record` replaces by hash with what
  the file actually holds), so that refusal leaves the session honestly shown as having no capture.

  **A missing archive fails honestly, and "no capture row at all" is a different answer.** An
  unfindable archive leaves the tombstone alone and names the file, because Help → *Find moved
  captures…* may bring it back. A uid no `captures` row mentions can *never* be restored, which is
  why the manager needs **Forget** — clear the tombstone without restoring — or the row is
  unremovable. **Several findable captures are refused rather than guessed at**: two copies are
  usually a member's original plus an imported copy, they can differ in completeness (someone
  stopped recording early), and nothing can tell which is better without decompressing both, so the
  caller chooses and passes a `content_hash`. `restorable_captures` is shared between that chooser
  and the restore itself, so the list offered and the list accepted cannot drift apart.

  Both halves are covered by `test/ingest/test_restore_session.py`, and the whole flow was proven
  against real archives before any page leaned on it: a real restore rebuilt a session with its laps
  and traces, an injected failure over a real capture rolled back to an identical tombstone, and a
  genuinely missing archive refused with the tombstone untouched.
- **The tombstone read model lives in `storage/sessions.py`, not in `domain/`** *(decided
  2026-08-25)*. `SessionStore.deleted_sessions()` returns `DeletedSession` (uid, deleted_at,
  track_id, session_type, recorded_at) — the descriptive rows `deleted_uids()` cannot feed. It is
  defined beside the store rather than in `domain/models.py` because a tombstone is **not a domain
  concept**: no normalizer emits one, no assembler builds one, no analysis reads one. It exists only
  because rows persist. The repo's actual rule is *stores return domain dataclasses for domain
  concepts* — `assignment_for` already returns a bare `tuple[int, int]`, `known_files` a set of
  pairs — so this follows `pipeline`'s habit of keeping `DeleteOutcome` / `ReingestSummary` beside
  the functions that return them. `CaptureMeta` stays in `domain/` because it is an aggregate root
  with its own identity that the whole app reasons about; this is a flag with four descriptive
  fields. **Known limitation:** the tombstone carries `session_type` but not `weekend_structure`,
  so a deleted **Sprint Race** reads as "Race" in the manager — it reports type 15 exactly as an
  ordinary race does, and only the weekend it sat in separates them (invariant #5). Narrower than it
  first looked: a sprint weekend's *Grand Prix* reports RACE_2 (16), which needs no weekend context,
  so only type 15 is genuinely ambiguous. Widening the tombstone to fix that is not worth it; the
  view says so in a tooltip.
- **The deleted-sessions manager refuses nothing itself** *(decided 2026-08-25, built 2026-08-26 as
  E1 branch 4)*. The page confirms, and picks the capture when several hold the session — the two
  things that need a person and therefore the GUI thread. Everything else is decided by
  `pipeline.restore_session` and worded once in `ui/formatting.restore_message`, arriving through
  the worker's `done` rather than `failed` because **a refusal is a normal answer here**, not a
  crash: a missing archive, a capture row that went stale, a session no capture mentions.

  **Why not pre-empt the obvious ones.** The page already knows an archive is missing — it drew
  "archive not found" in that row. Refusing locally would cost one short-lived worker and buy a
  second place where that sentence lives, and the two would drift: the page would keep offering a
  file the restore had started refusing, or refuse one it would have accepted. Both halves read the
  *same* list, `pipeline.restorable_captures`, for exactly that reason, and the one decision the
  page does make is passed as a **content hash** — never a path, because the identity is the content
  and files move between the click and the worker.

  **The chooser's accessor is a property, and that is a scar.** It was a method; a call site dropped
  the parentheses and returned the bound method, which PySide6 cannot convert for a
  `Signal(str, str)` — it prints to stderr and passes an **empty string** rather than raising. The
  pipeline read that as "no choice was made" and refused as ambiguous, so a user picking a file
  watched the app ignore them with a message that sounded deliberate. A property cannot be left
  uncalled, and the caller now refuses any hash it did not just offer.
- **Forget clears a tombstone without restoring, and says so in those words** *(decided 2026-08-20,
  built 2026-08-26)*. Without it a tombstone can be **unremovable**: a session whose `captures` rows
  were pruned — or that was ingested before capture metadata existed — can never be restored, and
  the row would sit in the manager for the life of the database. Forget is `SessionStore.restore`
  alone: the stored results do not come back, but the uid stops being skipped, so a later import or
  re-read of that recording stores the session again.

  **The dialog has to overcome the word.** "Forget" reads naturally as *delete it for good*, which
  is the opposite of what it does, so the confirmation states both halves outright — nothing comes
  back now, and the session is no longer skipped. It emits no `sessions_changed`: no stored session
  changed, and the overview's count re-reads when it is shown.
- **Every non-sprint race type is labelled "Race", never "Race 2"** *(decided 2026-08-26)*. A sprint
  weekend in this database reports `weekend_structure = [1, 10, 11, 12, 15, 5, 6, 7, 16]` — the
  Sprint as RACE (15) and the Grand Prix as **RACE_2 (16)** — so `slot_label` printing the prettified
  enum name put "Race 2" on the Grand Prix in Sessions, Laps, Seasons and the weekend page. The
  weekend's final race is the Grand Prix and earlier races are Sprints (invariant #5), which
  `weekend_slots` already resolves **by position**; the ordinal inside the enum name is an artefact
  of the wire format and not something a user has any use for. Fixing it in `slot_label` rather than
  per surface is what makes it one line instead of six, and it also makes the number useful where
  there is no weekend to resolve against at all: a tombstone reading 16 is a Grand Prix on its own.

- **A weekend slot holds every attempt, and the app never picks one** *(decided 2026-09-01,
  v0.11.0)*. A restarted or re-driven session keeps the same season, weekend and session link ids,
  the same `session_type` and the same track as the attempt it replaces — only `session_uid` and
  `recorded_at` differ (TELEMETRY_NOTES → *The three link identifiers*). `weekend_slots` mapped
  sessions into a dict keyed by type, so the second attempt **overwrote the first and vanished**:
  measured live, weekend `3602002284` holds 8 stored sessions and rendered 7, silently losing the
  later Practice 2. That is A8, fixed as part of this release.
  - **`WeekendSlot` carries all of a slot's attempts, in recorded order, and the view lists them
    all.** A restart usually means something went wrong in the earlier run, and which attempt
    "counts" is a judgement about that session, not a fact in the telemetry — nothing stored can
    distinguish them. Taking the newest would be a silent decision dressed as a rule, and taking
    the oldest is no better.
  - **Assignment stays explicit, and never replaces.** Assigning a later attempt to a round does
    not unassign an earlier one; the user unassigns the other attempts themselves, and may then
    delete them through the shared guarded delete. The automatic proposal in → Storage skips
    multi-attempt slots for the same reason.
  - **Only the unassigned pool is ambiguous.** `rounds_with_results` returns the sessions actually
    assigned to a round, so once the user has chosen, `grand_prix_session` and the calendar's
    Results column see one attempt and nothing downstream has to think about this at all.
- **The weekend-filtered overview shares the normal overview's *rules*, not its widget tree**
  *(decided 2026-09-01, v0.11.0)*. Routing Seasons into a weekend-filtered Sessions overview gives
  the surface two display modes, which was accepted deliberately (PRIORITIES → E1d) — the question
  was how to keep them from becoming two implementations that drift.
  - **What is shared is a Qt-free rules module** (`ui/sessions/weekend_view.py`), which decides
    *which* rows a view shows and *in what order*, returning session rows and pending/skipped slot
    rows, **plus one card widget** (`ui/components/session_card.py`). The two pages stay separate
    thin `QWidget`s over that spine and own only their own chrome.
  - **Not inheritance.** The pages differ in chrome, not in logic: a subclass would inherit a
    header with a "Deleted sessions (n)" button and a track/session search box it does not want —
    the weekend *is* the filter — so the base `__init__` would have to grow hooks for a population
    of one. The reusable part is `reload()`, which does query → slot resolve → filter → build →
    empty state in one pass; overriding it means inheriting the widget tree but not the behaviour.
    And the drift being guarded against is in the **rules** — ordering, labels, what a card says —
    which a Qt-free module makes impossible *and* unit-testable, where inheritance would make it
    merely unlikely and untestable without a `QApplication`.
  - **Repo precedent settles it.** There is no page-to-page inheritance anywhere in `src/ui` —
    every page is a direct `QWidget`, and the only widget subclasses are two leaf renderers
    (`_TitleButton`, `CarStatusGraphic`). Sharing already happens by *builder*
    (`build_classification_table`, called by three unrelated pages) and by *Qt-free rules module*
    (`race_control.py`, `lap_context.py`, `tyre_stints.py`). This is that pattern, not a new one.
  - **Not a mode flag on one class** either: `if self._weekend is None:` would thread through
    `reload`, the card builder, the meta line, the header and the empty state, which moves the
    drift inside one file rather than removing it.
- **Pending and Skipped slot rows are the filtered overview's job, and they live in the rules
  module** *(decided 2026-09-01, v0.11.0)*. A filtered list of *stored* sessions cannot express a
  session that does not exist, so routing Seasons into Sessions would have silently dropped the one
  thing the weekend page said that a session list cannot — that Practice 3 was **skipped** rather
  than merely absent. `weekend_view` therefore emits slot rows for uncaptured positions, and the
  skipped-vs-pending rule (a gap *before* the latest captured session is Skipped; one after it is
  still to come) moves out of the weekend page's `_pending_slot_row` into that module with unit
  tests. Both real cases are in this database: Practice 3 skipped in weekend `3602002184`, and
  Q1/Q2/Q3 still pending before a stored Race in `4046315905`.
- **League display names on the Sessions surface read the saved roster file only — no seeding**
  *(E1c, decided 2026-09-01)*. `SeasonRosterFiles.roster_for` falls back to seeding a roster from
  captures, and seeding needs `rounds_with_results`, which hydrates **every session in the season** —
  37 in this database. That is not something to run on the GUI thread while painting a list, and it
  was the stated reason E1c was deferred out of E1 in the first place. So the Sessions surface
  resolves a session's season through `season_assignments` and loads that season's **saved** roster
  JSON (`SeasonRosterFiles.load`), which touches no sessions at all.
  - **What this costs, knowingly:** a LEAGUE season whose roster file the user never created reads
    exactly as it does today — the entry's own captured name, so a member captured as `"Player"`
    stays `"Player"`. It degrades to the current behaviour rather than to something worse, and the
    fix is the "Create roster file" button that already exists on the season detail page.
  - **An unassigned session has no season, so it has no roster**, and that is correct rather than a
    gap: nothing links it to a league.
  - **The roster-mode test is `ROSTER_SEASON_MODES`, not `mode == LEAGUE`** — and the two disagree
    in the code today. `seasons/detail_page.py` gates on `ROSTER_SEASON_MODES` (LEAGUE **and**
    GRAND_PRIX, the domain's own definition of a season raced against other people), while
    `seasons/weekend_page.py:186` gates on `mode != SeasonMode.LEAGUE`. The consequence is not
    hypothetical: this database's only real league — *Mittwoch League*, season 1 — is a
    **GRAND_PRIX** season, because 2026 leagues run in multiplayer GP lobbies where League Racing
    has no DLC cars (the reason `ROSTER_SEASON_MODES` exists at all). So the weekend page shows
    that league raw captured names today, while the season detail page beside it resolves them.
    E1c uses `ROSTER_SEASON_MODES`, which incidentally means the Sessions surface will read
    *better* than the weekend page it is due to replace, rather than merely catching up.
- **Share exports a PNG the app renders itself, not a screenshot of its own widgets** *(E19,
  decided 2026-09-01)*. The output is pasted into a league WhatsApp chat, replacing hand-taken
  screenshots.
  - **Rendered, not captured.** `widget.grab()` is the size of the user's window, carries the
    current theme (dark-on-dark reads wrong in a chat), includes scrollbars — and the Race control
    box is height-capped at `_MID_ROW_MAX_H` and *scrolls*, so a capture would **cut the penalty
    list off**, which is exactly the information the export exists to carry. Rendering our own
    layout also fixes a light palette, so the file is theme-independent.
  - **PNG, not PDF, for a session.** An image lands in the chat readable without a tap; a PDF
    arrives as a document that has to be opened. Prototyped against the worst session in this
    database (Shanghai, 22 drivers, 11 penalty rows): `QTextDocument` → `QImage` → PNG gives
    1080 × 1290 px at 168 KB. 1080 px keeps text legible after WhatsApp re-encodes a photo, and
    1:1.19 is a near-square that reads on a phone rather than a tall strip.
  - **No new dependency, and no packaging change.** `QTextDocument`, `QImage` and `QPdfWriter` are
    all in `QtGui`; the bundle excludes `QtPdf`/`QtPdfWidgets`, which are the *reader* modules and
    are not needed. Verified working with those exclusions in place.
  - **The clipboard is the real path.** `QApplication.clipboard().setImage(...)` pastes straight
    into WhatsApp Desktop with no file at all; Save-As is the fallback, defaulting to a new
    `paths.exports_dir()` under `data_root()` — the same class of per-user writable data as
    `rosters/` and `logs/`, never `app_dir()`, which is for files shipped *with* the app.
  - **A weekend exports as N PNGs in one folder**, reusing the per-session renderer unchanged,
    rather than as a multi-page PDF: eight sessions stacked into one image is ~10 000 px tall and
    unreadable, and one file per session is what a league admin posts anyway — one message each.
  - **Every string the export decides is Qt-free and unit-tested** (`share_document.py`), with a
    thin painter over it (`share_image.py`), the same split as `race_control.py`.

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
