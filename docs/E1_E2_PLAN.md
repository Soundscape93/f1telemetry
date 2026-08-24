# E1/E2 — Sessions surface + deleted-sessions manager: agreed plan

**Status: in progress.** Branches 0 and 1 are merged; branch 2 is split into 2a/2b/2c and 2a is
built. Agreed 2026-08-20 against `staging` at `ee97af3`; **detail-view layout specified and
approved 2026-08-24** (see *Session detail view* below). This file exists so the work can be
picked up cold in a later session — it carries the decisions, the API shapes, the gotchas found
while reading the code, and the branch order. PRIORITIES stays the index; this is the detail.

### Where the work actually stands (verified 2026-08-24)

| Branch | State |
|---|---|
| 0 `feature/store-ai-difficulty` | **merged** — `bb5e518`, `PIPELINE_VERSION` 3, real values in the DB |
| 1 `fix/session-delete-guard` | **merged** — `f4cccc5` |
| 2a `feature/sessions-surface` | **built, ready to PR** — container + overview + thin detail shell |
| 2b `feature/session-detail-layout` | **specified below, not started** |
| 2c `feature/session-tyre-life` | **specified below, not started** |
| 3 `feature/restore-session` | not started |
| 4 `feature/deleted-sessions-manager` | not started |

The "One decision still open" and "Bugs found while reading the code" sections below are kept as
written for the record; bugs 1 and 2 were closed by branch 1.

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

**Out — E1d, Seasons routing into a weekend-filtered Sessions overview.** *Decided 2026-08-24,
after E1's detail view was specified.* The intended end state: double-clicking a round in a
season's calendar opens the **Sessions overview filtered to that weekend**, in weekend running
order (P1, P2, … Race), each session showing its classification and opening the Sessions detail
page. The round-centric weekend page then shrinks and is eventually retired.

Recorded here because it changes what E1's surfaces are *for*, but it is **not E1 work** — it is
blocked behind both deferrals below, in a forced order: **E1c** (or league weekends read worse
than they do today), then the filtered overview, then **E1b** (the weekend page is the only writer
of `season_assignments`), then removal. The full reasoning, and the one piece of information that
has no home yet — the weekend page's *pending* / *skipped* slot rows, which a list of stored
sessions cannot express — is in PRIORITIES → E1d.

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

**Revised 2026-08-24:** branch 2 is split into 2a/2b/2c. The detail-view layout roughly tripled
its scope, and 2a is finished and independently useful — holding it while 2b grows would mean one
large review of two unrelated concerns.

| # | Branch | Contents | Re-ingest |
|---|---|---|---|
| 0 | ~~`feature/store-ai-difficulty`~~ | **merged `bb5e518`** — `ai_difficulty` through normalizer → `SessionResult` → `SessionRow` → mapping; `PIPELINE_VERSION` 2→3 | **yes** |
| 1 | ~~`fix/session-delete-guard`~~ | **merged `f4cccc5`** — `SeasonStore.assignment_for` / `assigned_uids`; `pipeline.delete_session`; `ui/components/session_actions.py`; weekend page moved onto it; "assigned to R*n*" marker in the picker | no |
| 2a | `feature/sessions-surface` | **built — PR as-is.** `src/ui/sessions/` container + overview + detail shell; `SessionsView.sessions_changed`; main_window wiring replacing the placeholder; new Qt-free formatting helpers; the duplicate `LapsView.refresh` swept up | no |
| 2b | `feature/session-detail-layout` | style tokens promoted + blue added; the 4×2 details grid; laps box with click-through; penalties box; `LapsView.show_lap` + pending-target `showEvent`; the main_window hop | no |
| 2c | `feature/session-pace-and-tyre-life` | Qt-free stint splitting (wear-drop rule) + stint-relative remapping + **both** stacked pyqtgraph charts (tyre life and lap times) | no |
| 3 | `feature/restore-session` | `SessionStore.tombstone` + `deleted_sessions()`; `pipeline.restore_session` with rollback; `RestoreWorker` | no |
| 4 | `feature/deleted-sessions-manager` | `ui/sessions/deleted_page.py`, Restore + Forget, capture chooser, main_window worker wiring | no |

**2c lands after 2b** because it is the only piece carrying a novel data-derivation rule, and the
easiest to defer if the cycle runs long. It carries **both** charts: they share the stint splitting,
the stint-relative axis and the per-stint colours, so splitting them across branches would mean
building that machinery twice. **E15 (Event-packet ingest) is deliberately not in this
block** — it carries a `PIPELINE_VERSION` bump, so it belongs beside E14, sharing **one**
re-ingest rather than two.

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

### Session detail page — `src/ui/sessions/detail_page.py`

**Layout specified and approved 2026-08-24.** Branch 2a built the header + classification table
(the "thin shell"); branch 2b builds the boxes below, 2c adds the tyre-life chart.

Every field below was checked against the code **and against the real database** before it was
specified — nothing here is designed on data we do not store.

    [← Sessions]  Monza — Race                              2026-08-09 21:02
    Clear · 53 laps · uid 1844674407370955161
    Source capture: capture_20260809_210154.f1cap.zst            [ Delete… ]

    ┌─ Session details ───────────────┐ ┌─ Final classification ──────────┐
    │ P1                    │  25     │ │ POS DRIVER TEAM GRID STOPS BEST │
    │───────────────────────┼─────────│ │  1  Leclerc  FER   2    2  1:21 │
    │ 1:21.046 (blue)       │  29/29  │ │  2  Norris   MCL   1    2  1:21 │
    │───────────────────────┼─────────│ │  …            (scrolls)         │
    │ AI 95                 │  ☀      │ │                                 │
    │───────────────────────┼─────────│ │                                 │
    │ Ferrari · Driver Car. │ 2026-08…│ │                                 │
    └─────────────────────────────────┘ └─────────────────────────────────┘

    ┌─ Laps ──────────────────────────┐ ┌─ Penalties ─────────────────────┐
    │ LAP  TYRE   GAP      TIME       │ │ No penalties were recorded for  │
    │  1    [M]   +1.203   1:22.249   │ │ this session.                   │
    │  2    [M]   —        1:21.046 ◄ │ │                                 │
    │      (clickable rows)           │ │                                 │
    └─────────────────────────────────┘ └─────────────────────────────────┘

    ┌─ Tyre life ──────────────────────────────────── full width ────────┐
    │ 100% ┤━━╲___  (M)                                                   │
    │      │       ╲______   ━━╲____ (H)                                  │
    │   0% ┼────────────────────────────────────────                      │
    ├─ Lap times ── same stint-relative axis, same colours ──────────────┤
    │ 1:24 ┤  ╱‾‾  (M)          ╱‾‾ (H)                    ▲ = out-lap    │
    │ 1:21 ┤━━╱             ━━━╱                             (clipped)    │
    └──────┴─ 1   2   3   4   5   6 …  stint lap ───────────────────────┘

#### Top-left — session details (4×2 grid)

A `QTableWidget`, headers hidden, `showGrid(False)`, a thin bottom border per row and **no column
divider**. Not `build_kv_table`: that one bolds and spans on a `None` value, which is a different
contract. A small sibling helper beside it.

| Row | Left cell | Right cell |
|---|---|---|
| 1 | `P1` — `classification.player.position` | **Points** — race/sprint only, else `—` |
| 2 | **Session best lap**, blue — `formatting.session_fastest_lap` | **Laps completed** — `29 / 29` |
| 3 | **Difficulty** — `session.ai_difficulty` | **Conditions** — `components.WeatherIcon` |
| 4 | **Team · mode · type** — `team_display_name` + `game_mode_name` + `slot_label` | **Date** — `recorded_label` |

**Points are gated because the stored value is meaningless outside a race — not for tidiness.**
Verified against the database: `PRACTICE_1` player rows carry `points 25`, `QUALIFYING_1` rows
carry `25` and `8`. The game reports a carried-over championship figure on non-race sessions.
Gate on `is_race(session.session_type)`, with `slot.is_sprint_race` already available from
`_current()`. Anything else prints a number that is simply wrong.

**"Laps completed" is a stand-in for overtakes** (`len(my laps) / session.total_laps`). Overtakes
are not stored — see E15 below. It was chosen over *positions gained* because that is already
rendered as the ▲/▼ glyph in the classification table one box to the right, and because laps
completed means something in every session type. **When E15 lands, this cell becomes real
overtakes.**

The box also carries the **circuit outline** below the grid, filling the space a four-row grid
leaves beside a twenty-row classification. It is the player's fastest lap via `TrackMap.set_trace`,
**not** the canonical median line - see DECISIONS for the measurement behind that. When the session
has no Motion data a plain stretch takes the space instead, so the layout never leaves a hole where
a map should be.

#### Top-right — final classification

`build_classification_table(session, is_sprint_race=slot.is_sprint_race)`, unchanged from 2a. The
box title names the session type (`Final classification · Race`) because it is screenshotted and
shared on its own.
**Must not grow a duplicate table.**

**Equal box heights need a decision, and it is a layout risk.** The details grid is 4 rows; the
classification is up to 20. Cap the top row at a fixed height and let the table **scroll inside
its box**. *Approved as the first attempt 2026-08-24, explicitly provisional:* if it feels fiddly
in the app — the default window is only **900×600** — the fallback is to grow the details +
penalties column so neither table scrolls. Decide it against the running app, not on paper.

#### Middle-left — laps

Columns `LAP · TYRE · GAP · TIME`, from `LapStore.list(uid)` (DB rows only, no Parquet).

- **Gap is to the fastest of *my* laps**, not the session's. New Qt-free helpers in `formatting`:
  `my_fastest_lap(laps)` and `lap_gap_to(best_ms, lap_ms)`; `format_gap` already exists.
- Tyre icon reuses `components.tyres.tyre_pixmap(visual_compound)`.
- **Colouring:** my fastest lap is **blue** when it is also the session's fastest, **green** when
  it is not. Compare `my_fastest_lap` against `min` non-zero `best_lap_time_ms` across the
  classification entries.
- **Single click opens the lap** — see the navigation section below. The laps *overview* uses
  double-click because its row is also a fold target; here the row's only job is to open, so a
  double-click would be a needless second action. Recorded in DECISIONS so the difference does not
  read as a bug.

#### Middle-right — penalties

Per-penalty detail (type, lap, time) is **not stored**. What is stored is the aggregate on the
player's classification entry: `num_penalties` and `penalties_time_s` — real data, eight rows in
the current database carry `1 penalty / +3s`.

**Two states, because one would lie:**

- `num_penalties == 0 and penalties_time_s == 0` →
  `No penalties were recorded for this session.`
- otherwise → the aggregate (`⚑ 1 penalty · +3s`, via the existing
  `formatting.format_penalty_badge`), plus a muted second line:
  `Per-penalty detail (type and lap) isn't stored yet.`

Without the second state the page would print "no penalties" for a session that demonstrably had
one. `reference.PENALTY_NAMES` / `INFRINGEMENT_NAMES` already exist and are unused — the display
half of the real feature is written, only ingest is missing (E15).

#### Bottom — pace and tyre life, stacked (branch 2c)

Two full-width charts, **stacked, sharing one stint-relative x-axis**. *Decided 2026-08-24,
revising the earlier left/right split.* Side by side was rejected on a measurement: the default
window is `resize(900, 600)`, leaving ~700 px of content after the sidebar, so a half-width plot is
~320 px — about **8 px per lap** over a 38-lap race, too tight to pick out a single slow lap.
Stacked full-width gives ~18 px/lap. It also matches `trace_plot.py`'s existing house idiom
(stacked plots sharing one axis) and lets wear fall-off and pace fall-off be read on one vertical
line.

**The x-axis is stint-relative: every stint starts again at stint lap 1**, and the axis runs to the
longest stint. Degradation is a function of stint age, not race lap, so this is what makes two
compounds comparable — medium stint lap 5 sits directly under hard stint lap 5. The actual race lap
number goes in the tooltip. Both charts use the identical axis and the identical per-stint colours,
so the two rows always align.

##### Tyre life (upper)

Backed by `LapRow.tyre_wear` — per-wheel cumulative %, **406 of 406 stored laps populated**.

- **Line value: `100 - max(wear)` — the worst wheel, not the mean.** The worst corner is what
  forces the stop, so it is the strategy-relevant number; a mean smooths away exactly the signal
  being looked for. Per-wheel values go in the tooltip.
- **Split stints on wear *dropping* or the compound changing, never on `tyre_age_laps`.** See
  TELEMETRY_NOTES — age is unreliable at the lap boundary and a naive age-based split turned one
  27-lap race into fourteen stints. Wear is monotonic within a stint and resets to ~0 on a new set.
- **Minimum 2 laps per stint**, all session types. The user's preference, and it also suppresses
  the single-lap artefact stints that pit in-laps produce.
- **No synthetic 100% anchor.** Stint 1 lap 1 already reads ~4% wear; there is no stored 100%
  sample. The y-axis runs 0-100%, so a stint starting at 95.7% reads as "near 100" on its own.
- Compound colours are already correct in `components/tyres.py:_COMPOUND_STYLE` (S red, M yellow,
  H white, I green, W blue). **Reuse; do not redefine.**

##### Observed lap time by stint (lower)

Same stints, same colours, same axis. **The name matters and should be used in the UI**: this
chart shows *observed* lap time by stint, not tyre performance — see the fuel caveat below.

**The out-lap must not be allowed to set the y-scale — this is the one thing that will make or
break this chart.** Measured across every 50%-distance race in the database, the first lap of each
*post-pit* stint carries **+14 to +37 s** (the game bundles the pit loss into it):

    comp 18  laps 3-20   stintlap1 119.594s   median-rest 82.737s   delta +36.857s
    comp 18  laps 14-29  stintlap1 112.245s   median-rest 91.487s   delta +20.758s
    comp 17  laps 22-29  stintlap1 107.636s   median-rest 88.814s   delta +18.822s

On an *absolute* axis those spikes sit at different x positions and read as "that's the stop". On a
**stint-relative** axis they all stack at x = 1, so an auto-scaled y-axis would span ~37 s and
compress the real 1-3 s degradation signal into ~5% of the plot height.

**So: plot every lap, but derive the y-range from the representative laps only** — excluding each
stint's first lap when that stint follows a pit stop. Out-laps draw as a distinct clipped marker at
the top edge, with the true time in the tooltip. Measured data is never hidden, only kept from
dictating the scale.

**Stint 1 lap 1 needs no special case** — it is a race start, a much milder +2 to +3 s, and
sometimes *faster* than the stint median (low fuel, fresh tyres).

##### The fuel caveat — state it, do not silently correct for it

**A stint-relative overlay conflates tyre degradation with fuel burn-off.** The car sheds roughly
1.1-1.3 kg of fuel per lap (`fuel_in_tank` runs 38.6 → 32.6 kg over six laps in `14435457…`), so a
later stint is partly faster **because the car is lighter**, not only because of the compound or
the tyre's condition. Overlaying stint 1 (laps 1-12, heavy) on stint 2 (laps 13-27, light) on a
shared stint-relative axis puts that difference right where a reader will attribute it to the tyre.

This is a real limitation of the view, not a bug to be worked around, so:

- **Label the chart "Observed lap time by stint"**, not "tyre performance", "degradation" or
  "pace". The title carries most of the honesty burden.
- **Caption or tooltip the caveat explicitly** — later stints run lighter on fuel, so part of any
  gain between stints is fuel, not tyre.
- **Do not apply a fuel correction here.** A correction needs a kg→seconds coefficient that is
  track- and car-dependent; picking one silently would replace an honest raw number with a
  confident estimate, which is worse on a page whose job is "what actually happened".

**Future work — fuel-corrected lap time belongs on Analytics (E3), not here.** The data is already
in place: `fuel_in_tank` is stored per lap, **406 of 406 populated**, so this needs no new ingest.
But it is a *derived, corrected* metric — it needs a coefficient, an estimation method and a way to
show its uncertainty — and the session detail page's remit is raw session fact. Analytics is where
cross-session, derived work already lives. If it ever appears here it should be an explicit
**opt-in toggle** on the chart, never the default, so the raw number stays the thing you see first.

**So, settled:**

| Surface | Shows |
|---|---|
| Session detail (E1, here) | **raw observed lap times**, coloured by compound, stint-relative x-axis |
| Analytics (E3, future) | **fuel-corrected lap-time analysis** built on `fuel_in_tank` |

##### Shared

- Charting is pyqtgraph, lazily imported, exactly as `trace_plot.py` does it.
- Stint splitting and the stint-relative remapping are **Qt-free and unit-tested** — the
  highest-value tests in this batch.
- **Plot against real lap numbers mapped to stint offsets, not list index.** Lap numbers are not
  contiguous (`11708585...` is missing laps 19-20), so a gap inside a stint must stay a gap.

#### New style tokens

`classification_table.py:44` privately holds `_POS_COLORS = {"gain": "#3fb950", "loss": "#f85149"}`.
Promote to `style.py` and add the blue, so the fastest-lap highlight is one colour everywhere
(detail page, laps box, laps view, sessions overview):

    FASTEST_LAP_BLUE = "#2f81f7"   # session fastest lap
    PERSONAL_BEST    = "#3fb950"   # my fastest, when it isn't the session's

Both are colour-bearing stylesheets, which A4 explicitly permits (`test/ui/test_styles.py` gates
only font-bearing stylesheets that set no colour).

#### Navigation — a lap row opens the Laps detail page

`SessionsView` and `LapsView` are siblings in `main_window`'s stack, and pages never reference
siblings (invariant A1). The hop goes up and across:

    sessions/detail_page  → lap_requested(uid: str, lap_number: int)
    sessions/view.py      → re-emits
    main_window           → self._sidebar.setCurrentRow(_SECTIONS.index("Laps"))
                            self._laps_view.show_lap(uid, lap_number)

**The gotcha:** `LapsView.showEvent` calls `_show_overview()` unconditionally, so becoming visible
would clobber the navigation. Do **not** rely on call ordering — `show_lap` sets a pending target
that `showEvent` consumes:

    show_lap(uid, n):  self._pending = (uid, n); self._show_detail(uid, n)
    showEvent:         honour and clear self._pending if set, else _show_overview()

Reuses the existing `LapsView._show_detail(session_uid: str, lap_number: int)`. Uids travel as
`str` because they are uint64.

#### Explicitly still out of scope

Charts beyond tyre life, tabs, lap comparison, round assignment (E1b), roster display names (E1c).

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
| `test/ui/test_formatting.py` (extend) | `session_fastest_lap` — normal, all-zero `best_lap_time_ms`, no classification, ties | 2a |
| `test/ui/test_formatting.py` (extend) | `my_fastest_lap` / `lap_gap_to` — no timed laps, single lap, ties; `session_points_cell` — **race returns points, practice/quali return an em dash even though the stored value is non-zero** | 2b |
| `test/ui/test_tyre_stints.py` (new) | `split_tyre_stints` — the wear-drop rule against the real quirks: age jumping by 2 mid-stint, a stale in-lap reading, non-contiguous lap numbers, a stint starting on a used set, and the ≥2-lap filter dropping single-lap artefacts | 2c |
| `test/ui/test_tyre_stints.py` (new) | stint-relative remapping — every stint starts at 1; the axis runs to the longest stint; a **gap inside a stint stays a gap** (missing laps 19-20 must not shift later laps down) | 2c |
| `test/ui/test_tyre_stints.py` (new) | `pace_y_range` — the out-lap of a post-pit stint is excluded from the range while stint 1 lap 1 is not; a single-stint session with no pit stop still gets a sane range | 2c |
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

### Manual checks for the detail view (2b / 2c)

16. **Points gating:** open a Practice or Qualifying session whose stored `points` is non-zero
    (several exist) — the cell must read `—`, not `25`. A race shows the real number, a sprint
    the sprint number.
17. Session best lap renders blue; when one of my laps *is* the session's fastest, that lap row is
    blue too; when it is not, my fastest lap row is green.
18. Clicking a lap row lands on that exact lap in the Laps detail page — **and the Laps surface
    does not bounce to its overview** (the `showEvent` gotcha).
19. Coming back to Sessions and clicking a different lap navigates again (the pending target was
    consumed, not left stale).
20. A session with a penalty shows the aggregate plus the "detail isn't stored yet" line; a clean
    session shows only the empty state.
21. **Layout under stress:** at the default 900×600 window, with a 20-car classification and a
    29-lap race — do the scrolling boxes feel usable? This is the provisional call from the layout
    section; settle it here.
22. **Tyre life (2c):** a 3-stint race draws exactly 3 lines, coloured by compound, each starting
    at stint lap 1. A session with a missing lap (19–20 in `11708585…`) does not draw a straight
    line through the gap as though it were data.
22b. **Pace (2c) — the one that will fail first:** on a 2-stop race the lap-time chart must still
    show the 1–3 s degradation spread clearly. If the y-axis has stretched to ~37 s to fit the
    out-laps, the range exclusion is not working. Out-laps must still be reachable via tooltip.
22c. Both charts' x-axes line up exactly, and hovering stint lap *n* means the same lap in both.
23. **A4 regression** on the detail page specifically: switch the OS theme — the blue and green
    lap colours and the chart must both survive.

## Docs to update as the branches land

**Applied 2026-08-24** (the planning half — layout, decisions and the data findings):
`PRIORITIES.md` (E1 row, new **E15** / **E16** rows + notes), `DECISIONS.md` → UI (ten detail-view
decisions), `TELEMETRY_NOTES.md` (the `tyre_age_laps` quirk, the Event-packet census, the 2026
game-mode ids), `ARCHITECTURE.md` (`ui/sessions/`), and this file.

**Still to apply as the code lands** — these describe work that does not exist yet, so writing
them now would be false:

- **`PRIORITIES.md`** — E1/E2 rows → done as each branch merges; the cycle-framing correction
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
  (**yes** for branch 0, no for 1–4). **Nothing added for 2b/2c yet**: the CHANGELOG records
  user-visible change that shipped, and the detail view is specified but not built. Branches 0/1/2a
  are already covered by the existing Unreleased bullets.
- **`../Claude.md`** — invariant #4 gains a line naming `pipeline.delete_session` as the deletion
  guard; the "Current status" placeholder list drops Sessions.

## Workflow reminders for the implementing session

- Code changes **in chat only** — complete change blocks with surrounding context, never direct
  edits to source files. Docs may be edited directly once a plan is approved.
- Never run `git commit`; suggest the message.
- Branch off `staging`, never `main`. Feature branches PR into `staging` **unlabelled**.
- Every user-visible change adds a bullet under `## Unreleased` in `CHANGELOG.md`.
- Hand over anything that launches the app; read-only inspection is fine to run directly.
