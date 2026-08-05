# Priorities

The **confirmed** working order for open work, agreed 2026-08-02. ROADMAP is the catalogue of
*what exists as an idea*; this file is *what we decided to do about it, and when*. When the two
disagree, this file wins for ordering and ROADMAP wins for detail.

Item IDs (A1, B2, …) are stable — quote them in commits, branches and chat so a future session
can pick up mid-plan. **Keep this file current:** when an item ships, move it to *Recently
closed* with a date rather than deleting it, so the next session can tell "done" from "forgotten".

Status legend: **open** · **needs verification** (built, unproven) · **blocked** (waiting on
something external) · **done**.

---

## Cycle plan

**Cycle 1 — correctness, truth and release hygiene.** Small items that group into one
`patch`/`minor` release on `staging`. Rationale: these are cheap, several are promises already
made in the docs, and none of them depend on anything unbuilt.

- A1 track-map cache invalidation — **done 2026-08-02**
- C2 WAL mode + C3 database backup (`VACUUM INTO`) — **done 2026-08-02**
- E6 edit-calendar action — **done 2026-08-02**

**Cycle 1 is complete.** Everything above shipped to `staging`; the grouped `staging` → `main`
release PR is what turns it into a version. **Cycle 2 is next** — do not start it without
re-reading the cycle plan above.
- The documentation-truth pass (A2, F1, F2, F4 + the stale-doc corrections) — **done 2026-08-02**

*Order note:* C2/C3 moved ahead of E6 (the P1 table below lists E6 first). E6 is the largest of
the three and the only one carrying an open design question — what happens to session assignments
whose round a calendar edit removes or re-points (`session_assignments` has no FK to rounds,
invariant #4). C2/C3 are storage-layer and self-contained, so they ship while that is decided.

**Cycle 2 — league data flow.** The one substantial feature block, and the direction the whole
capture-as-interchange design was built for. **Two branches, not three** — see the order note.

- B4 locate a moved capture by content hash — **done 2026-08-03**
- B2 league capture import from a shared folder, carrying B3's one field — **done 2026-08-04**

**Cycle 2 is complete.** Both branches are on `staging` and share the `## Unreleased` section; the
grouped `staging` → `main` release PR (label **`minor`**) is what turns them into a version.
**Cycle 3 is next** — do not start it without re-reading the cycle plan above.

*B2 scope, confirmed 2026-08-03 and delivered:* the shared/manual capture import flow; an
**optional** "Recorded by" text field on the import prompt (blank is fine, no validation); and a
**proper user-facing import action** — the header's `Ingest .f1cap (test)` button retired and
replaced by something presented as the real way to import a capture someone sent you, not as a dev
affordance. Explicitly **not** in scope, and not built: any settings page, profile or identity
feature.

*Order note (revised 2026-08-03):* the listed order was B2 → B3 → B4; it is **reversed** for B4.
Both items need the same primitive — hash a capture on disk without parsing it — and B4 is the
small consumer that puts `archive.hash_capture` in place and proves it on real archives before the
large feature leans on it. B4 also fixes a live foot-gun rather than adding surface: a *moved*
capture was indistinguishable from a *deleted* one, and the only action offered was the one that
forgets it. ROADMAP already said B4 "slots in between `find_missing_captures` and
`prune_missing_captures`", and that split was already in the code.

**B3 is dropped as its own item — decided 2026-08-03.** The column, the domain field and the
`recorded_by` plumbing all exist; nothing sets a value and — the deciding fact — **nothing reads
one**. A settings page and an identity flow to feed a write-only column is speculative work. Its
stated justification was also overstated: only a *re-ingest* can't backfill it, while a *re-import*
sets it (replace-by-hash), so leaving it blank loses nothing irreversibly. It becomes one optional
"Recorded by" text field on B2's import dialog — cheap because that dialog is being built anyway,
and filled at the one moment the admin actually knows the answer. What it buys, precisely: the
shared drive shows who *uploaded*, but that record does not survive the copy-home step the design
mandates, so after import the app is the only place the answer could live. Embedding it in the
`.f1cap` header (format v2) was weighed and **rejected as unwarranted** by anything current: a real
on-disk format change for a field with no consumer.

**Cycle 3 — release-phase process.** Effectively the rest of the C block: Phase 4 packaging
reach, the installer, the real auto-updater, and the remaining build-robustness items. Promoted
above the big UI surfaces deliberately — testers are real, new surfaces are not yet needed.

*Order confirmed 2026-08-05, with one change from the list as first written.* The listed order put
C8 — the largest and riskiest — first. It runs **last** instead, and C6 moves ahead of C7:

- C5 `threading.excepthook` — **done 2026-08-05**
- C6 startup capability self-check — **done 2026-08-05**
- C7 pyqtgraph bloat trim — **after C6, not before.** PACKAGING's own risk register gives the
  mitigation for "pyqtgraph/zstandard missed → the app silently ships the fallback" as "explicit
  hidden imports + a startup self-check". C7 edits the spec's `excludes` — the exact operation
  whose failure mode is that silent degrade — so C6 is the instrument that makes C7 verifiable
  rather than hopeful. Reversed, the trim is done blind.
- C4 clean-instance test (Windows Sandbox / second user account) — run against a build carrying
  C5–C7. Not code: a checklist the author executes, producing doc updates only.
- C8 Phase 4 — see the split below.

**C8 is three deliverables under one ID, and only two are in this cycle — decided 2026-08-05.**
- **C8a macOS/Linux artifacts → Linux only.** `release.yml` already runs an `ubuntu-latest` job for
  the guide PDF, so a tarball is nearly free, and the author develops on Linux, so it has a real
  consumer. **macOS is deliberately dropped from the cycle:** no known user, a runner to pay for,
  and an unsigned build walking into Gatekeeper.
- **C8b Inno Setup installer + Windows Firewall allow-rule → in.** The firewall prompt is
  PACKAGING's #3 "easy to forget". **Open question to settle before code:** the allow-rule needs
  elevation, while the clean-machine checklist asserts "launch as a non-admin user" — so it is
  either a per-user install with no rule, or an elevated install with one.
- **C8c velopack auto-updater → deferred out of Cycle 3.** PACKAGING already calls full
  self-replace on a *running* one-folder Windows app "fiddly… deferred deliberately". It is a .NET
  toolchain that would replace the zip artifact verified across three builds, for a handful of
  testers whose notify-only path was confirmed working against a real Release on 2026-08-02. It
  buys the least and risks the most.

*Not in Cycle 3, but noted:* **A4** (Windows light/dark switch leaves text miscoloured) sits in P2
and has shipped as a known issue in every release since v0.3.0. It is packaging-phase polish
during the packaging cycle — the strongest candidate for promotion if the cycle has room.

**Deliberately after Cycle 3:** E1/E2 (Sessions surface + deleted-sessions manager), E3
(Analytics), E5 (Bug report page). See *Deferred* below for why.

---

## P1 — next

| ID | Item | Status | Detail in |
|---|---|---|---|
| A1 | Canonical track-map cache is never invalidated on re-ingest | **done 2026-08-02** | ROADMAP → Laps 2b.1; DECISIONS → UI |
| A2 | Final Classification is sent repeatedly, not once — docs corrected | **done 2026-08-02** | TELEMETRY_NOTES; DECISIONS |
| E6 | Edit-calendar action on the season detail page | **done 2026-08-02** | ROADMAP → Seasons UI 2c |
| C2 | Enable WAL mode | **done 2026-08-02** | PACKAGING → Data layout & the database |
| C3 | "Back up database…" via `VACUUM INTO` | **done 2026-08-02** | PACKAGING → Data layout & the database |

Nothing is left in P1. See *Recently closed* for what each item settled. The one loose thread it
left — the "open the app twice" check having passed *before* WAL existed — is now **closed**: it was
re-run under WAL on 2026-08-05 and passes.

## P2 — after P1

| ID | Item | Status | Detail in |
|---|---|---|---|
| B2 | League capture import from a shared folder | **done 2026-08-04** | ROADMAP → Capture compression; DECISIONS → Storage |
| B3 | `recorded_by` is plumbed but never set | **done 2026-08-04** (one field on B2's import prompt) | ROADMAP → Capture compression |
| B4 | Locate a moved capture by content hash | **done 2026-08-03** | ROADMAP → Capture compression; DECISIONS → Storage |
| A4 | Windows light/dark switch leaves text miscoloured | open | PACKAGING → Phase 1 known issues |
| C4 | Clean-instance test (Sandbox / second user account) | open | PACKAGING → Testing on a clean instance |
| E7 | Setup slider ranges | **confirmed 2026-08-02** — see below | DECISIONS → UI |
| F6 | Carry the CHANGELOG known-issues list forward every release | process | CHANGELOG header comment |

**E7 is resolved as a question, not as code.** The ranges in `setup_panel._SETUP_SPEC` are
confirmed correct for **2026** packets. 2025 is expected to be fine too: the only range
difference between the 2025 and 2026 cars is **tyre pressure**. Remaining (small) work is to
verify the 2025 tyre-pressure bounds and record the source in `_SETUP_SPEC`.

## P3 — later / opportunistic

| ID | Item | Detail in |
|---|---|---|
| A5 | Isolate `ES_DISPLAY_REQUIRED` from `ES_SYSTEM_REQUIRED`; managed-machine lock untested | ROADMAP → recorder stalls |
| B5 | Reconstructed-race points: accept / edit / store (Option 3) | ROADMAP → Storage & analysis |
| B6 | One roster shared across seasons (`roster_path`) | DECISIONS → Identity & rosters |
| C5 | `threading.excepthook` for worker threads | **done 2026-08-05** — Cycle 3; PACKAGING → Phase 0 |
| C6 | Startup capability self-check (degraded pyqtgraph/zstandard) | **done 2026-08-05** — Cycle 3; PACKAGING → Risks |
| C7 | pyqtgraph bloat trim (`pyqtgraph.examples`) | PACKAGING → Phase 1 known issues |
| C8 | Phase 4: macOS/Linux, Inno Setup installer, velopack auto-updater | PACKAGING → Phased plan |
| D2 | Alembic — adopt at the first non-additive migration (trigger-based) | DECISIONS → Migrations |
| D3 | Persisted `track_layouts/*.parquet` cache | DECISIONS → UI |
| D4 | True geometric centerline (needs Motion Ex / track width) | DECISIONS → UI |
| D5 | Re-validate the 2c colour thresholds against real telemetry | DECISIONS → UI |
| E4 | Dashboard surface | ROADMAP → Other surfaces |
| E8 | Track-country flag on lap cards (no `track_id → country` map) | ROADMAP → Laps 1b |
| E9 | Corner numbers on the track map (**licensing caveat**) | DECISIONS → UI |
| E10 | Sector labels as map hover/tooltips | DECISIONS → UI |
| E12 | Team colour swatches (only if team identity needs to be scannable) | DECISIONS → UI |
| E13 | Move the capture/database actions off Help into their own surface | ROADMAP → Other surfaces |

---

## Needs verification

Built or believed-done, but never proven. Each names *how* it gets proven, so it can be picked
up opportunistically rather than scheduled.

- **B1 — GP-multiplayer roster grouping.** `ROSTER_SEASON_MODES` was widened to include
  `GRAND_PRIX` (the 2026 league runs in Grand Prix multiplayer), but the league's *normal* state
  — drivers captured as `"Player"` with telemetry restricted, grouped by race number via
  `roster.member_key` — has never been tested on a real capture. **Plan:** the author sets their
  own online name/ID to restricted at the next race, **scheduled for ~2026-08-12** (confirmed
  2026-08-05). Deliberately *not* asking other members to change their settings, since they'd risk
  leaving them restricted afterwards. Season-critical if wrong (standings), so verify before
  trusting a full season's table. **When it runs, capture the session and check it against
  `LeagueRoster.session_keys` before assuming the standings are right** — a wrong grouping shows up
  as two members merged into one row, or one member split across two.
- **E11 — track map rotation.** Possibly already correct; unconfirmed. **Plan:** compare the
  rendered map against the in-game track map when recording the next sessions — which is the same
  ~2026-08-12 race B1 is waiting on, so both can be settled from one capture. Note that absolute
  rotation deliberately follows the game's world frame, **not** F1.com broadcast art
  (DECISIONS → UI) — so "different from broadcast" is expected and is not the thing being checked.
- **A5 — `ES_DISPLAY_REQUIRED`.** Never isolated from `ES_SYSTEM_REQUIRED`; dropping it is a
  one-line experiment that would stop the screen staying lit. Also untested against a
  policy-managed machine, where a *lock* cannot be prevented (only sleep can).

## Recently closed

- **C6 — startup capability self-check.** Done 2026-08-05; the second item of Cycle 3, and the
  prerequisite for C7. `src/capabilities.py` (Qt-free) probes four things — charts (pyqtgraph),
  capture compression (zstandard), lap traces (pyarrow) and the bundled flag SVGs — and returns a
  frozen `Capability` each. `MainWindow` logs all four on every launch and dialogues only when
  something is degraded, deferred a turn like the pipeline check and ordered **before** it: a build
  that lost pyqtgraph is worth saying before offering a multi-minute re-ingest. **No Help-page
  surface, deliberately** — Help already hosts five actions that aren't Help content (E13).
  **The one decision worth not re-litigating: probe depth is per capability.** A capability is
  probed by *importing* it, because only an import catches a module that is present but won't load
  (pyarrow's Windows DLL quirk — `find_spec` says yes while the import fails). pyqtgraph is the
  exception, probed by `find_spec` alone, because importing it would undo the laziness that keeps
  start-up quick — and the regression this exists for, *a bundle that never shipped it*, needs no
  import to see. **That is precisely what C7 risks**, which is why the order was reversed.
  **Two limits, chosen not discovered:** a module present-but-broken-at-import reads OK for
  pyqtgraph (not silent — it raises into the log on the first lap opened, which is what decided the
  split); and `traces` can never actually report degraded today, because a broken pyarrow kills
  `main_window`'s import before the window exists, making it a start-up crash rather than a silent
  degrade. That probe earns its place as a log line a tester's report carries, and stops being
  vacuous if the `LapStore` import ever goes lazy.
  A probe that throws is reported as a **degraded capability**, not dropped — failing loud beats a
  self-check that quietly shortens its own report. Covered by `test/test_capabilities.py`, whose
  logging cases are real regression tests: `assertLogs` formats each record, so a reversed `%s`
  fails the suite instead of vanishing into logging's internal error handler. One did, on the way.
- **C5 — `threading.excepthook`, and the crash-dialog thread bug it uncovered.** Done 2026-08-05;
  the first item of Cycle 3. The hook itself is nearly a no-op today and that is worth knowing
  rather than rediscovering: **`threading.excepthook` never fires for a `QThread`** (the
  interpreter calls it from `Thread._bootstrap_inner`, which QThread does not go through), and
  every worker here is a QThread. It is a net for future bare-`Thread` work and for third-party
  threads.
  **The defect found while scoping it is the substance.** Every worker's `finally` sits *outside*
  its `except` — `IngestWorker`, `ReingestWorker`, `RelocateWorker` and `ImportWorker` all dispose
  stores there — so an exception from `store.close()` escapes `run()` entirely, reaches
  `sys.excepthook` via PySide6, and had `crash._show_dialog` constructing a `QMessageBox` **on the
  worker thread**. Building a QWidget off the GUI thread is undefined behaviour in Qt and can abort
  the process: the crash handler was able to convert a survivable error into a hard crash.
  **Three decisions worth not re-litigating.** `_report` checks the thread and shows the dialog
  *directly* when already on the GUI thread — a start-up crash happens before `app.exec()`, so a
  uniformly-queued call would never be delivered. Off-thread it emits through a queued-connection
  `QObject` relay, built by `install_excepthook` on the GUI thread so the object *lives* there.
  And **only strings cross the boundary**, never the exception — its traceback would pin worker
  frames alive across threads.
  Covered by `test/test_crash.py` (Qt-free): both hooks log and chain to the previous hook,
  `KeyboardInterrupt` / `SystemExit` pass through unlogged, and `_report` builds no dialog when
  there is no GUI thread. **Verified by hand through `UpdateCheckWorker`** (Help → Check for
  updates), whose `result_ready.emit` is already outside its try/except — no capture, database or
  recording needed to make an exception escape a worker thread.
- **B2 / B3 — league capture import, and the one field `recorded_by` became.** Done 2026-08-04;
  the last of Cycle 2. *Help → Import captures…* walks a chosen folder, copies anything new into
  the local captures folder and ingests it. Read and write are split like the prune, so the count
  and the total size are shown before a thread starts and the pass acts on exactly the list the
  user agreed to.
  **Four outcomes decided by content hash**, never by name: *new* → copy home + ingest; *already
  held* → skip; *known but the local archive is gone* → copy home + `relocate` (the shared folder
  as backup of last resort, deliberately **without** re-ingesting — rebuilding derived rows is
  "Re-read captures"' job); *only `recorded_by` differs* → update in place.
  **Copy-home is the point, not an optimisation:** the shared drive is transport, the local archive
  is the home, so no row is left pointing at a folder that syncs or disconnects. The source is never
  touched. A name clash is **numbered**, not overwritten — the hash already ruled, so a clash can
  only be two *different* recordings sharing a name. **A capture already inside the captures folder
  is ingested in place** — learned in testing, by importing from a home directory containing the
  data root and watching the app copy its own archives beside themselves under `-2` names. That fix
  also restores the one capability the retired test button had: point the importer at the captures
  folder to pick up a loose recording that was never ingested.
  **One inversion of `archive_and_ingest`, on purpose:** a capture that fails to ingest **keeps**
  its local copy. Nothing is at risk (the shared original is untouched), and a capture that won't
  parse is exactly the one worth having locally to look at.
  **B3 closed as one optional field**, as decided the day before. `CaptureStore.set_recorded_by` is
  the piece that makes "a re-import can correct it" true rather than aspirational — without it an
  already-held capture is simply skipped and the value could never change. Nothing reads
  `recorded_by` yet; E13 is the first thing that plausibly would.
  **Retired the `Ingest .f1cap (test)` header button**, which had been marked dev-only in code while
  `USER_GUIDE.md` §4 documented it as *the* import path — wrong in one place or the other since
  v0.3.0. The header now carries only the record control.
  Covered by `test/ingest/test_import.py` (19 cases) plus one in `test_captures.py`. Qt wiring
  verified by hand — and it earned its keep: three bugs (a `Signal` arity mismatch that silently
  stalled the progress dialog, a missing `_close_import_dialog`, and the copy-beside-itself above)
  were only reachable through the real app, because every test suite here is deliberately Qt-free.
  **Left behind:** Help now hosts five actions that aren't Help content — filed as **E13**.
- **B4 — locate a moved capture by content hash.** Done 2026-08-03; the first item of Cycle 2.
  *Help → Find moved captures…* walks a folder the user picks and re-points a `captures` row at the
  file it finds. The point is not the feature but the gap it closes: `find_missing_captures` can
  only say the bytes aren't where the app looks, so until now a *moved* capture and a *deleted* one
  were the same thing to the app and the only action offered was the one that forgets it.
  **Three decisions worth not re-litigating.** The search space is **only the known-missing rows** —
  a row that resolves is already correct, and re-pointing it at a second copy found on a memory
  stick would be a regression, not a fix. **Name and size pre-filter; the hash rules** — a candidate
  is read only when `(basename, size)` matches a missing row (a `stat`) and accepted only when the
  sha256 of its decompressed payload matches, so a folder full of strangers is cheap and one
  recording's metadata can never be filed against another's bytes. And it **re-points rather than
  copies home**: copying into the local captures folder is what B2's import is for, and doing it
  here would silently duplicate hundreds of MB behind a button that says "find".
  **Accepted limits, chosen not discovered:** a capture renamed *as well as* moved never reaches the
  hash (still a prune job), and one found on an external drive goes missing again when the drive is
  disconnected — that is what `relocate` means.
  `archive.hash_capture` is `ingest_capture`'s read pass isolated; `test_hash_is_codec_independent`
  now asserts the two agree, so the scan path and the ingest path can't drift about what a capture
  *is*. Threaded (`RelocateWorker`), unlike the prune, because confirming a match costs a
  decompression pass per candidate.
  **Two latent defects fixed on the way** — this is the first production caller of
  `CaptureStore.relocate`, which was annotated `-> None` but returns `bool`, and derived `file_name`
  with `rsplit("/")`: the *entire path* on Windows, which would have corrupted the very field
  `known_files()` and `resolve_capture_path`'s fallback key on. `MainWindow._busy()` replaced a
  guard copy-pasted at four call sites; this was the fourth worker, and a handler that forgot one
  would let two jobs write the same SQLite file from two threads.
  Covered by 12 cases in `test/ingest/test_reingest.py`. The Qt wiring has **no automated test** —
  every UI suite here is deliberately Qt-free — so it was verified by hand.
- **A3 — "missing middle laps".** Verified 2026-08-03 and closed. A full test race on Windows under
  v0.5.0 recorded every lap continuously, confirming the root cause was the machine sleeping
  mid-session (fixed in v0.4.2) and not anything in ingest. The original symptom — laps 1–2 then
  ~16–18 — was lost telemetry, never a parsing fault, so there was nothing to fix here once v0.4.2
  landed.
  **Do not reopen this on the wrong symptom.** The same race showed a single missing lap number,
  which is *correct*: a red flag makes the game skip one lap (restart is on lap *n+2*), documented
  in TELEMETRY_NOTES → "A red flag skips a lap number". One missing number after a slow lap is the
  game; several consecutive laps missing, usually with the Final Classification gone too, is lost
  telemetry.
- **E6 — edit-calendar action.** Done 2026-08-02; the last item of Cycle 1. `EditCalendarPage` is a
  fifth page in `SeasonsView`, reusing the create page's `CalendarPicker` unchanged — which is what
  it was factored into `components/` for.
  **The open design question is now answered: option (c), restrict the edit.** A round with an
  assigned session keeps **both** its `round_number` and its `track_id`, which makes orphaning
  impossible rather than merely manageable (options (a) warn-and-preserve and (b) warn-and-unassign
  both accepted orphans and were rejected). The rule collapses to a **positional check** — for each
  locked round *(n, t)*, the proposed calendar must still have round *n* at track *t*. One check
  covers reorder, insert-before, delete-before and truncate, including the case a plain "no
  reordering" rule misses: inserting a round at position 3 renumbers an assigned round 5 into
  round 6 without anything being dragged. It also correctly *permits* an edit that leaves a locked
  round where it was, which matters where a track may legitimately repeat.
  **Enforced in `SeasonStore.set_calendar`, not only in the page** — the invariant is guaranteed at
  the single write point rather than remembered at one call site, and it is testable without Qt.
  `protect_assigned=False` is the documented escape hatch; nothing passes it.
  **Deliberate limitation, chosen not discovered:** once round 1 has a session assigned, nothing can
  be inserted before it — the calendar becomes freely editable from the last assigned round onward,
  plus reordering among unassigned rounds that don't cross a locked one. Recorded in DECISIONS.
  **Deliberately skipped:** greying out locked rows in the picker (fighting Qt's `InternalMove`
  drag-drop to reject specific drops is fiddly and untestable here) — the page names the locked
  rounds up front instead, and refuses at save. Also out of scope: editing mode / number / nickname
  / game format. Changing the format would move the track pool out from under the calendar (Madrid
  is 2026-only); a wrong-mode season is still deleted and recreated. Allowing that *before any
  session is assigned* is a reasonable future P2/P3.
- **C2 / C3 — WAL mode and a `VACUUM INTO` backup.** Done 2026-08-02, one branch, as PACKAGING
  required ("`VACUUM INTO` is what makes WAL safe to hand around"). The blocker was structural, not
  technical: all five stores are repositories over the *same* file and each builds its own engine
  (deliberately — SQLite dislikes a connection shared across threads and the ingest workers have
  their own), so there was no shared place a pragma could live. `storage/engine.py` now owns
  `create_db_engine`, and connection setup is a shared **function** rather than a shared engine.
  It sets `journal_mode=WAL`, `synchronous=NORMAL` and `busy_timeout=10s`.
  **Two decisions worth not re-litigating:** `synchronous=NORMAL` is justified by the standing
  "the database is disposable and rebuildable from captures" position, not by a benchmark — full
  fsync per commit buys durability for data we can recreate; and `foreign_keys` is deliberately
  **left off**, because SQLite defaults it off, the schema's cascades are ORM-level, and enabling
  it would interact with the intentionally FK-free `session_assignments` (invariant #4). That
  belongs with the Alembic trigger (D2), not with WAL.
  `storage/backup.py` is `VACUUM INTO` behind `backup_database()`. Three things it had to get
  right, each verified rather than assumed: `VACUUM` cannot run inside a transaction
  (`AUTOCOMMIT`), `VACUUM INTO` **refuses** an existing destination (so the caller unlinks after
  the save dialog has already asked), and the path is a bound parameter so Windows backslashes and
  quotes in a filename can't break the statement. The action is deliberately *not* blocked during
  an ingest — one read transaction that neither blocks the writer nor tears, which is the entire
  reason C3 pairs with C2. It is **not** the "Open database" action the project rules out: it
  writes a copy to a path the user chose and never exposes the live file.
  **The loose end it left is closed:** the Phase-1 "open the app twice" checklist item had passed
  *before* WAL existed, so its result meant "the contention never happened", not "WAL handled it".
  Re-run under WAL on **2026-08-05 — passes**, so the mechanism itself is now proven rather than
  merely un-triggered. PACKAGING's checklist item is ticked.
- **A1 — canonical track-map cache invalidation.** Done 2026-08-02.
  `TrackLayoutProvider.invalidate()` clears the whole cache (per-key would be wrong: an ingest can
  touch any weekend, a re-ingest touches all of them), reached through
  `DetailPage.invalidate_layouts()` / `LapsView.invalidate_caches()` from
  `MainWindow._refresh_current_view()`. Two things the fix turned on that are worth remembering:
  the cache stored `None` as a real value — "this weekend has fewer than `_MIN_LAPS` usable Motion
  laps, fall back to the driven line" — so a weekend that *became* buildable stayed on the driven
  line; and invalidation had to be **unconditional** rather than routed through the visible-page
  refresh, which would have reproduced the bug whenever the ingest finished while Seasons was
  showing. A lap already on screen is redrawn via the new `DetailPage.reload()`. Covered by
  `test/ui/test_track_layout_provider.py` (Qt-free, fake stores). Both ROADMAP and DECISIONS had
  promised this before any release to users, and v0.3.0 onward shipped without it — hence P1.
  **Scope was widened once during the work:** the weekend page's "Delete from database…" also
  changes which laps exist but never reached the ingest path, so it left the same stale map. It now
  emits `sessions_changed`, re-emitted by `SeasonsView` and connected in `MainWindow` to
  `LapsView.invalidate_caches` — the first non-navigation signal to leave the seasons surface,
  since pages never reference siblings. The Qt wiring itself has **no automated test**: every
  existing UI suite is deliberately Qt-free (no `QApplication` anywhere), so it was verified by
  hand instead.
- **F7 — Licence, third-party notices and the F1 disclaimer.** Done 2026-08-02. The repo stays
  **public** under a *source-available* `LICENSE` (read it, run the official builds, build it
  privately — but no redistribution, modified builds or reuse elsewhere without permission).
  Going private was considered and rejected: a private repo **cannot serve the update check**,
  because `/releases/latest` and release assets both 404 for unauthenticated clients and
  `src/update_check.py` ships no token by design. Forking on GitHub itself can't be forbidden
  (GitHub's ToS grants every user that right), so the licence targets redistribution instead.
  `NOTICE.md` carries the unofficial-tool/trademark disclaimer, the data-responsibility and
  accuracy notes, and the third-party licences — shipping it beside the exe is an **LGPL v3
  obligation** for the bundled Qt/PySide6, not a courtesy, so `release.yml`'s bundle
  sanity-check now fails without it. A separate public `f1telemetry-releases` repo was discussed
  and **deliberately deferred** until there are non-tester users; nothing depends on it.
- **C1 — Phase-3 clean-machine checklist on a downloaded Release zip.** Done (confirmed
  2026-08-02); the author intends to re-run it for most future releases. PACKAGING build history
  updated.
- **D1 / F3 — `DRIVER_NAMES` completeness.** Done: every entry from both UDP spec PDFs is now in
  `protocol/reference.py` (97 entries). The "partial, ~11 entries" claim was stale in three files
  and is corrected.
- **The "open the app twice" check.** Run on both Windows instances with Record pressed and no
  game running — nothing wedged. That run predated WAL, so it proved only that the contention never
  happened; **re-run under WAL on 2026-08-05 and passes**, which does prove the mechanism. Closed.
- **A2 / F1 / F2 / F4 and the stale-doc sweep.** This commit.

## Deferred, with reasons

- **E1 Sessions surface + E2 deleted-sessions manager → after Cycle 3.** Not the small view it
  looks like: it means building the Sessions view, linking parts of it to the Laps view, and then
  *reworking the existing Seasons view*, which would inherit data from both. That is a
  cross-surface rework, so it waits until the release process is settled. (E2's store side is
  already done — `deleted_uids` / `is_deleted` / `restore` — so only its UI is pending, and it
  most likely lives inside E1.)
- **E3 Analytics → after Cycle 3.** Large, and it wants a season of accumulated data behind it.
- **E5 Bug report page → after Cycle 3.** Currently a placeholder in `_SECTIONS`; most of what it
  would do (open logs, show version) the Help page already does.
- **B5 reconstructed-points Option 3 → P3.** Less urgent than it looked: A2 shows the Final
  Classification arrives 5–6× per session, so reconstruction is rare, and v0.4.2 removed its main
  cause. Belongs with league-management (per-league scoring tables) when that happens.
- **B1 out of Cycle 1** — not because it is unimportant (it is season-critical) but because it is
  gated on a real race, not on us. See *Needs verification*.

## Not tracked here

`checklist_2nd_build.md` and similar files at the **workspace root** are the author's scratch
copies for moving between Windows and the shared drive. They are outside the git repo, are not
project documentation, and should not be treated as an open-work source.
