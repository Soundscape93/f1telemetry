# E1/E2 — Sessions surface + deleted-sessions manager: agreed plan

**Status: planned and approved, not started. No code written.** Agreed 2026-08-20 against
`staging` at `ee97af3`. This file exists so the work can be picked up cold in a later session —
it carries the decisions, the API shapes, the gotchas found while reading the code, and the
branch order. PRIORITIES stays the index; this is the detail.

Read alongside: `PRIORITIES.md` (E1/E2/E3/E5 rows), `ROADMAP.md` → Other surfaces,
`DECISIONS.md` → UI, `ARCHITECTURE.md` → `ui/`, and `../Claude.md` invariants #3, #4, #10, #11.

---

## Baseline verified when this plan was written

- **v0.8.1 published** — GitHub release, 2026-08-18 20:38 UTC, 5 assets (Windows zip +
  `setup.exe`, Linux `tar.gz`, `USER_GUIDE.pdf`, `NOTICE.pdf`). Tag `v0.8.1` = `156ade5`, on
  `origin/main`.
- **`docs/cycle4-order-eblock` merged into `staging`** — squash-merged as `ee97af3` (#35). The
  local branch head `b8fa4a7` is not an ancestor (squash), but the diff against `staging` for
  `docs/PRIORITIES.md` is empty, so the content is in.
- **Working tree clean**, `staging` in sync with `origin/staging`.
- **Suite green** — `python3 -m unittest discover -s f1telemetry/test -t .` → 491 tests, OK
  (6 skipped).

## One decision still open

**How E1/E2 is framed relative to Cycle 4.** The session that produced this plan was told
E1/E2 is *not* Cycle 4 work. The docs as merged say the opposite, in three places, all dated
2026-08-18 and all on the branch confirmed merged above:

- `PRIORITIES.md` cycle plan — *"The rest of Cycle 4 is the E-block, and its order is now
  decided — 2026-08-18: E1/E2 → E3 → E5 … E1/E2 is next."*
- `PRIORITIES.md` P2 rows — E1 and E2 both read `open — Cycle 4, next item`.
- `PRIORITIES.md` → *Deferred* — *"E1/E2, E3 and E5 are no longer deferred — moved into Cycle 4
  on 2026-08-18."*

**Nothing in the plan below depends on the answer** — the cycle label changes doc wording only,
so this file is written cycle-neutral. Settle it before editing `PRIORITIES.md`; if the E-block
is being pulled back out of Cycle 4, that leaves Cycle 4 containing only A4/A4b, i.e. closed.

---

## Bugs found while reading the code (fixed as part of this work)

These were discovered during planning, not previously recorded. Two of them ship in `staging`
today.

1. **The weekend picker can delete an assigned session.** `ui/seasons/weekend_page.py`
   `_reload_capture_picker` filters on `s.session_uid not in self._assigned_uids`, and
   `_assigned_uids` holds **only the current round's** assignments. A session assigned to round 3
   therefore appears in round 5's picker (same track, or with *Show captures from all tracks*
   ticked), and right-click → *Delete from database…* deletes it — orphaning its
   `season_assignments` row and silently removing a result from the standings. Meanwhile
   `SessionStore.delete`'s docstring asserts *"callers delete only unassigned sessions, so there
   is nothing to clean up"*: it states an invariant the UI does not keep. **Closed by branch 1.**
2. **Deleting a session orphans its laps and traces.** Nothing calls `LapStore.delete`. Deleting
   a session leaves its lap rows and its Parquet files under `lap_traces/<uid>/` on disk forever.
   They are invisible (the laps overview iterates stored sessions), but they are still there.
   **Closed by branch 1**, inside `pipeline.delete_session`.
3. **`LapsView.refresh` is defined twice** — `ui/laps/view.py`, two identical bodies, the second
   silently wins. Harmless, trivial. **Swept up in branch 2.**

---

## The six design decisions

### 1. Restore = single-capture re-ingest, with tombstone rollback

`SessionStore.restore()` only clears the tombstone. The real feature is:
`CaptureStore.for_session(uid)` → `pipeline.resolve_capture_path(meta, captures_dir)` →
`ingest_capture(path, session_store, lap_store, capture_store, recorded_by=meta.recorded_by)`.
`ingest_capture` replaces by uid, so ingesting one file holding the uid is sufficient and
idempotent. Full re-ingest as a Restore button would decompress every archive in the database to
rebuild one session — that tool already exists under Help.

Three points that shape the implementation:

- **Ordering + rollback.** `ingest_capture` reads `deleted_uids()` at the *start*, so the
  tombstone must be cleared **before** ingesting. That opens a window: if the ingest then fails,
  the uid is un-tombstoned with no session row — a half-state where the next *full* re-ingest
  silently resurrects a session the user believes is still deleted. Restore must re-tombstone on
  failure. `SessionStore.delete()` cannot do that rollback: it returns `False` and writes nothing
  when no session row exists.
- **Verify the capture actually contained it.** `capture_sessions` rows can be stale. After
  ingest, check the returned `list[SessionResult]` contains the uid; if not, roll the tombstone
  back and say so, rather than leaving a cleared tombstone and no session.
- **Multiple captures for one uid.** Resolve every `CaptureMeta` from `for_session`, keep those
  whose archive is findable, then: exactly one → use it and name it in the confirm dialog; more
  than one → **ask**, with a one-line chooser (file name · recorded by · size · ingested at),
  defaulting to newest `ingested_at`. Two copies are usually a member's original plus an imported
  copy, but they can differ in completeness (someone stopped recording early) and the app cannot
  tell which is better without decompressing both. A silent guess would quietly pick the worse
  recording.

**Missing archive → fail honestly, tombstone untouched.** Two cases, two messages:

- capture row exists, file unresolvable → *"The recording for this session can't be found
  (`<file>`). Restore needs it — try Help → Find moved captures…, or import it again."* Tombstone
  stays, row stays in the manager.
- **no capture row at all** (pruned via `prune_missing_captures`, or ingested before
  `capture_store` was wired) → restore is impossible, ever. This is why the manager needs a second
  action, **Forget**: clear the tombstone *without* restoring, so a future import or re-ingest of
  that capture brings the session back. Without it the tombstone is an unremovable row.

### 2. Delete refuses assigned sessions, enforced at a pipeline write point

**Refuse, do not clean up.** Invariant #4 exists so a re-ingest never wipes manual round
placements; a *delete* must not either, and delete's whole premise is that the capture survives
and the session can come back — an assignment silently dropped on the way out would not. Refusing
costs the user one Unassign click and is reversible; cleanup is not.

**Enforced in `pipeline`, not in the UI.** `SessionStore` must not import `SeasonStore`
(repository-per-aggregate), so the guard goes where multi-store orchestration already lives, beside
`reingest_all` and `import_captures`:

    pipeline.delete_session(session_uid, session_store, season_store, lap_store=None)
        -> DeleteOutcome

1. `season_store.assignment_for(uid)` → if assigned, refuse, carrying season id + round number in
   the result.
2. otherwise `session_store.delete(uid)`, then `lap_store.delete(uid)` (bug 2 above).

`SessionStore.delete` stays as the primitive; its docstring changes from asserting the invariant
to naming its enforcer.

### 3. Delete is shared — one implementation, two entry points

Keep it in the weekend picker (where you notice a duplicate attempt *while* assigning) **and** add
it to Sessions. One implementation at two levels:

- **Logic:** `pipeline.delete_session` — the only write point, Qt-free, unit-tested.
- **Dialogs:** `ui/components/session_actions.py`, exposing
  `confirm_and_delete(parent, uid, session_store, season_store, lap_store) -> bool`, so the confirm
  text and the refusal message cannot diverge. `components/` is the neutral home — putting it in
  `ui/sessions/` would make a seasons page import from a sibling surface.
- **Signal:** both call sites emit `sessions_changed` upward. `SessionsView` gets its own, wired in
  `main_window` to `LapsView.invalidate_caches` exactly like the existing `SeasonsView` connection.
  `_refresh_current_view` learns about the new view.

### 4. E1 scope — session-centric assignment is OUT

**In:** overview with foldable cards, expandable summary, minimal detail shell over
`build_classification_table`, shared guarded delete, deleted-sessions manager, restore.

**Out — E1b, session-centric assignment.** `DECISIONS.md` already frames it as *"a fine complement
later"*. It is a *write* into `season_assignments` from a context with no season: it needs a
season+round picker with its own validation (track match? slot already filled? move vs. assign?),
which is a feature with its own design questions, not a widget. It lands more safely once the
surface exists to host it.

**Out — E1c, league display names.** The weekend page resolves them via `display_name_fn(roster)`,
and `SeasonRosterFiles.roster_for` needs a season plus `rounds_with_results`, which hydrates every
session in the season — not something to run on the GUI thread while painting a list. Sessions v1
uses the default `name_of` (the entry's own driver name), so a league member captured as `"Player"`
reads as `"Player"` here and by their roster name in the weekend view. **Write this down in
DECISIONS — it will otherwise be reported as a bug.**

### 5. E13 — decide the boundary now, build later; `recorded_by` belongs there

Not implemented as part of E1/E2. The boundary goes into the docs *now* so E1 does not quietly
absorb capture-shaped content:

- **Sessions (E1)** answers *"what did I record, and what happened in it"* — sessions, results, laps.
- **Captures (E13)** answers *"what files do I have, where are they, who sent them"* — the
  `captures` table (file, size, codec, sessions, **recorded by**, last seen) plus the five actions
  currently misfiled under Help.

**`recorded_by` belongs on Captures, not Sessions.** It is a property of the *file*: one session can
live in two captures with different `recorded_by` values, so there is no single truthful value for a
session row. ROADMAP already calls a captures surface *"the first thing that would actually read
`recorded_by`"*.

The one capture-shaped thing Sessions does need, read-only: a **"Source capture"** line on the detail
page (file name, plus "archive not found" when unresolvable). It is the fact Restore depends on, and
the natural hand-off point to E13 later.

### 6. Branch split — five, in this order

Each PRs into `staging` **unlabelled**; the grouped `staging` → `main` PR carries the version label.
Branch off `staging`, never `main`.

| # | Branch | Contents | Re-ingest |
|---|---|---|---|
| 0 | `feature/store-ai-difficulty` | `ai_difficulty` through normalizer → `SessionResult` → `SessionRow` → mapping; `PIPELINE_VERSION` 2→3 | **yes** |
| 1 | `fix/session-delete-guard` | `SeasonStore.assignment_for` / `assigned_uids`; `pipeline.delete_session`; `ui/components/session_actions.py`; weekend page moved onto it; "assigned to R*n*" marker in the picker | no |
| 2 | `feature/sessions-surface` | `src/ui/sessions/` container + overview + detail shell; `SessionsView.sessions_changed`; main_window wiring replacing the placeholder; new Qt-free formatting helpers; the duplicate `LapsView.refresh` swept up | no |
| 3 | `feature/restore-session` | `SessionStore.tombstone` + `deleted_sessions()`; `pipeline.restore_session` with rollback; `RestoreWorker` | no |
| 4 | `feature/deleted-sessions-manager` | `ui/sessions/deleted_page.py`, Restore + Forget, capture chooser, main_window worker wiring | no |

**Why 0 is separate and first.** `ai_difficulty` is parsed in both `protocol/v2025/structs.py` and
`protocol/v2026/structs.py` and then **dropped** — `normalize_session` never reads it, and it is on
neither `SessionResult` nor `SessionRow`. It is the one item on the summary list that is not free:
~6 lines across 4 files, an additive column (`ensure_schema` handles it), **and a
`PIPELINE_VERSION` bump**, because it is exactly the "additive + needs values from packets" class
the gate exists for — existing rows show `—` until a re-ingest. Keeping it out of branch 2 keeps
the Sessions branch UI-only and keeps the re-ingest prompt attached to the commit that explains it.
**Confirmed worth the bump, 2026-08-20.**

**Why 3 lands before 4, shipping briefly-unused code.** Repo precedent: B4's order note — put the
primitive in place and prove it on real archives *before* the large feature leans on it. Restore
orchestration is the risky half (tombstone rollback, stale `capture_sessions`, missing archives)
and is fully unit-testable with no Qt.

**Why 1 precedes the rest of the UI work.** It is a bug fix that stands alone regardless of whether
E1 ever ships, and branch 2 needs `delete_session` and `session_actions.py` to exist.

---

## Shapes

Constraints that apply to every new widget: mirror the container pattern (`SeasonsView` /
`LapsView` — thin container over `QStackedWidget`, `_show_*` coordination, pages in their own
modules, `showEvent` → refresh, **pages never reference sibling pages**); reuse `ui/components/`;
join the existing `sessions_changed` wiring rather than inventing a parallel mechanism; A4 style
rules (no font-bearing stylesheet without an explicit colour, no `pt` sizing, `apply_heading` /
`apply_font` / `apply_bold`, `MUTED_TEXT_QSS` for muted text, never `palette(mid)`); never
construct a QWidget off the GUI thread, and stores used by a worker are created on the worker
thread and disposed in `finally`.

### Sessions overview — `src/ui/sessions/overview_page.py`

Mirrors `ui/laps/overview_page.py` almost line-for-line, which is the point.

    Sessions                                                [ Deleted sessions (2) ]
    [ Filter by track or session…                         ]

    ▸ Bahrain — Race                    2026-08-14 20:11 · 20 drivers
    ▸ Bahrain — Qualifying 3            2026-08-14 19:40 · 20 drivers
    ▾ Monza — Race                      2026-08-09 21:02 · 20 drivers · reconstructed
        Session       Race  ·  Monza  ·  53 laps  ·  Clear
        Winner        Charles Leclerc / Ferrari
        Fastest lap   Lando Norris — 1:21.046
        AI difficulty 95
                                            [ Open session ]  [ Delete… ]
      ──────────────────────────────────────────────────────────────────

- Ordered by `recorded_at` desc, straight from `SessionStore.list_sessions()`.
- Collapsed by default; `_expanded: set[str]` survives a re-filter (same idiom as laps).
- `QToolButton` + arrow, `setAutoRaise(True)`, `apply_bold`, **no stylesheet** (A4b).
- Meta line uses `MUTED_TEXT_QSS`.
- The summary is a **key/value block, not a table** — this is an overview, not a detail page.
- `Winner` uses the existing `formatting.race_winner_summary` (races only, hidden otherwise).
- `Fastest lap` needs one **new Qt-free helper**, `formatting.session_fastest_lap(session)` — min
  non-zero `best_lap_time_ms` across classification entries, returning driver + time. No
  `LapStore` read, so the overview stays a single query.
- `AI difficulty` shown only when > 0 (a full-human league session has nothing meaningful);
  `—` for rows recorded before branch 0's pipeline bump.
- Signals out: `session_requested(str uid)`, `deleted_requested()`, `sessions_changed()`.

### Session detail shell — `src/ui/sessions/detail_page.py`

Deliberately thin. **The full detail layout is not yet specified — do not invent one.** Everything
below the classification table is left empty on purpose.

    [← Sessions]   Monza — Race                              2026-08-09 21:02
    Clear · 53 laps · Grand Prix · uid 1844674407370955161
    Source capture: capture_20260809_210154.f1cap.zst               [ Delete… ]

    ┌ POS │ DRIVER │ TEAM │ GRID │ STOPS │ BEST │ TIME │ PTS ┐  ← shared builder
    └ … ┘

- `build_classification_table(session, name_of, is_sprint_race=slot.is_sprint_race)` — the shared
  builder from `ui/components/classification_table.py`, `is_sprint_race` from `slot_for_session`.
  **Must not grow a duplicate table.**
- The uid is shown on purpose: it is what a bug report needs.
- "Source capture" resolves via `CaptureStore.for_session` + `resolve_capture_path`; renders
  "(archive not found)" when unresolvable.
- Signals out: `overview_requested()`, plus `sessions_changed()` after a delete.
- Explicitly **not** here: lap list, charts, tabs, comparison, assignment.

### Container — `src/ui/sessions/view.py`

`SessionsView(session_store, season_store, capture_store, lap_store)`, thin over `QStackedWidget`,
pages `overview / detail / deleted`, `_show_*` coordination, `showEvent` → `_show_overview`,
`refresh()` re-queries only the visible page. Every hop between pages goes through a signal on the
container.

**One main_window change:** it owns no `CaptureStore` on the GUI thread today (only season /
session / lap). Add `self._capture_store = CaptureStore(self._db_url)` beside the other three,
disposed on close.

### Deleted-sessions manager — `src/ui/sessions/deleted_page.py`

A plain `QTableWidget` — these are four-field stubs; cards would be overkill.

    [← Sessions]   Deleted sessions

     SESSION      TRACK    RECORDED           DELETED            CAPTURE
     Race         Monza    2026-08-09 21:02   2026-08-10 09:14   capture_20260809…zst
     Qualifying   Bahrain  2026-08-02 19:30   2026-08-03 11:02   missing
                                                    [ Restore… ]  [ Forget… ]

- Needs a new read: **`SessionStore.deleted_sessions()`** returning the descriptive tombstone rows.
  `deleted_uids()` returns bare uids and cannot feed this.
- **Honest limitation, state it in a tooltip:** the tombstone carries `session_type` but not
  `weekend_structure`, and Sprint Race and Grand Prix both report type 15 (invariant #5), so a
  deleted sprint reads as "Race". Recovering it would mean widening the tombstone — not worth it.
- Restore/Forget as row buttons *and* a context menu (matches the picker's right-click idiom, but
  discoverable).
- Empty state: muted "No deleted sessions." — the normal case.

### Restore orchestration + worker

    pipeline.restore_session(uid, session_store, capture_store, *, lap_store=None,
                             content_hash=None, captures_dir=None,
                             ingest=ingest_capture) -> RestoreOutcome

Steps: not tombstoned → early out · resolve capture (given hash, or the sole resolvable one) →
missing → refuse, tombstone untouched · `restore(uid)` · ingest · uid not in the result, or an
exception → `tombstone(uid, …)` rollback · return a frozen
`RestoreOutcome(restored, session_uid, capture_name, reason)`. `ingest` is injectable, same as
`reingest_all`, so tests drive it without a real archive.

**Worker ownership.** Ingesting a 400 MB league capture takes minutes, so this is a
`RestoreWorker(QThread)` in `ui/workers.py` shaped like `IngestWorker`: stores constructed on the
worker thread, disposed in `finally` (invariant #10), signals `done(object)` / `failed(str)`. But
**the window owns workers, not pages** — so the deleted page confirms and chooses the capture on
the GUI thread, then emits `restore_requested(uid, content_hash)`; `SessionsView` re-emits;
`main_window` runs the worker, adds it to `_busy()` **and** to `_on_failed`'s worker tuple, and
calls back to refresh.

### New/changed store API, collected

| Where | Addition | Branch |
|---|---|---|
| `SeasonStore` | `assignment_for(session_uid) -> tuple[int, int] \| None` (reverse of `assignments_for_season`) | 1 |
| `SeasonStore` | `assigned_uids() -> set[int]` across all seasons | 1 |
| `SessionStore` | `tombstone(uid, *, track_id, session_type, recorded_at)` — merge a `DeletedSessionRow` with no session row required; `delete()` refactored onto it | 3 |
| `SessionStore` | `deleted_sessions() -> list[...]` — descriptive tombstone rows | 3 |
| `pipeline` | `delete_session(...) -> DeleteOutcome` | 1 |
| `pipeline` | `restore_session(...) -> RestoreOutcome` | 3 |

---

## Tests

All `unittest`, Qt-free — nothing here needs a `QApplication`. Run from the **workspace root**:

    python3 -m unittest discover -s f1telemetry/test -t .

| File | Covers | Branch |
|---|---|---|
| `test/domain/test_domain_normalize.py` (extend) | `ai_difficulty` normalized from both formats | 0 |
| `test/storage/test_storage.py` (extend) | `SeasonStore.assignment_for` (hit / miss), `assigned_uids` | 1 |
| `test/ingest/test_session_delete.py` (new) | refuses an assigned uid and names season+round; deletes an unassigned one; removes lap rows **and** trace files; unknown uid is a clean no-op | 1 |
| `test/storage/test_storage.py` (extend) | `tombstone()` writes with no session row; `delete` → tombstone field values; `restore` clears; `deleted_sessions()` rows; `is_deleted` | 3 |
| `test/ingest/test_restore_session.py` (new) | happy path via injected `ingest`; **rollback re-tombstones** when ingest raises; rollback when the capture does not yield the uid; missing archive leaves the tombstone; no capture row at all; multi-capture selection by hash | 3 |
| `test/ui/test_formatting.py` (extend) | `session_fastest_lap` — normal, all-zero `best_lap_time_ms`, no classification, ties | 2 |
| `test/ui/test_styles.py` | no change needed — it already gates all of `src/ui`, so new modules are covered the moment they exist | — |

### Manual checks — the real app, not the suite

Called out explicitly because B2's bugs were only reachable this way.

1. Sessions replaces the placeholder in the sidebar; lands on the overview.
2. Cards collapsed by default; expand shows the summary; expansion survives typing in the filter.
3. Open session → detail → back returns to the overview with the filter intact.
4. Delete an **unassigned** session from Sessions → gone from Sessions, from the Laps overview and
   from the weekend picker; `lap_traces/<uid>/` is gone from disk.
5. Delete an **assigned** session from Sessions → refused, message names the season and round; the
   session is still there.
6. **The regression branch 1 fixes:** open round 5's weekend, tick *Show captures from all tracks*,
   right-click a session assigned to round 3 → Delete is refused. On `staging` today it deletes.
7. `Deleted sessions (N)` count matches the manager; track / type / recorded / deleted all render.
8. Restore with the archive present → session returns to Sessions, to Laps *with its traces
   rebuilt*, and to the weekend picker; the classification matches what it was.
9. **Restore with the archive missing** — rename the file in `captures/` first → honest failure,
   tombstone still listed, session still absent, no half-state. Then Help → *Find moved captures…*
   → Restore succeeds.
10. Restore when two captures hold the uid → chooser appears and names both files.
11. Forget → row disappears; then Help → *Re-read captures* **resurrects** the session, proving the
    tombstone was really cleared.
12. **A4 regression:** switch the OS light↔dark theme while on the overview, the detail page and the
    deleted page — every label recolours, nothing freezes.
13. Restore while a recording or ingest is running → blocked by `_busy()`.
14. Detail page's "Source capture" shows the file name, and "(archive not found)" after a rename.
15. **Branch 0:** AI difficulty shows `—` on pre-bump rows and a number after the guided re-ingest;
    the re-ingest prompt appears once on first launch after the bump.

---

## Docs to update as the branches land

Not yet applied — most of these describe work that does not exist yet, and writing them now would
be false.

- **`PRIORITIES.md`** — E1/E2 rows → in progress, pointing here; the cycle-framing correction
  (open decision above); new **E1b** (session-centric assignment) and **E1c** (roster names in
  Sessions detail) rows in P3; a note recording the weekend-picker delete bug and where it was fixed.
- **`ROADMAP.md` → Other surfaces** — Sessions / Deleted-sessions entries updated from "planned" to
  what shipped; the E13 boundary paragraph (`recorded_by` lives on Captures, and why).
- **`DECISIONS.md` → UI** — four decisions: delete refuses assigned sessions and is enforced at
  `pipeline.delete_session`; restore is single-capture re-ingest with tombstone rollback; Sessions
  detail uses entry names, not roster names, and why; the Sessions/Captures boundary.
- **`ARCHITECTURE.md`** — `ui/` section gains `ui/sessions/`; the pipeline section gains
  `delete_session` / `restore_session`; the threading section gains `RestoreWorker`.
- **`PACKAGING.md`** — branch 0 only: the `PIPELINE_VERSION` 3 history line.
- **`CHANGELOG.md`** — a bullet per branch under `## Unreleased`, each stating the re-ingest answer
  (**yes** for branch 0, no for 1–4).
- **`../Claude.md`** — invariant #4 gains a line naming `pipeline.delete_session` as the deletion
  guard; the "Current status" placeholder list drops Sessions.

## Workflow reminders for the implementing session

- Code changes **in chat only** — complete change blocks with surrounding context, never direct
  edits to source files. Docs may be edited directly once a plan is approved.
- Never run `git commit`; suggest the message.
- Branch off `staging`, never `main`. Feature branches PR into `staging` **unlabelled**.
- Every user-visible change adds a bullet under `## Unreleased` in `CHANGELOG.md`.
- Hand over anything that launches the app; read-only inspection is fine to run directly.
