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
capture-as-interchange design was built for.

- B2 league capture import from a shared folder
- B3 `recorded_by` wiring (ships with B2)
- B4 locate a moved capture by content hash (shares B2's hash/scan machinery)

**Cycle 3 — release-phase process.** Effectively the rest of the C block: Phase 4 packaging
reach, the installer, the real auto-updater, and the remaining build-robustness items. Promoted
above the big UI surfaces deliberately — testers are real, new surfaces are not yet needed.

- C8 Phase 4 (macOS/Linux artifacts, Inno Setup installer + firewall allow-rule, velopack)
- C5 `threading.excepthook`, C6 startup capability self-check, C7 pyqtgraph bloat trim
- C4 clean-instance test (Windows Sandbox / second user account)

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

Nothing is left in P1. See *Recently closed* for what each item settled — including the fact that
the "open the app twice" checklist item passed *before* WAL existed, so it wants a re-test that
actually exercises it.

## P2 — after P1

| ID | Item | Status | Detail in |
|---|---|---|---|
| B2 | League capture import from a shared folder | open | ROADMAP → Capture compression; DECISIONS → Storage |
| B3 | `recorded_by` is plumbed but never set | open | ROADMAP → Capture compression |
| B4 | Locate a moved capture by content hash | open | ROADMAP → Capture compression; DECISIONS → Storage |
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
| C5 | `threading.excepthook` for worker threads | PACKAGING → Phase 0 |
| C6 | Startup capability self-check (degraded pyqtgraph/zstandard) | PACKAGING → Risks |
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

---

## Needs verification

Built or believed-done, but never proven. Each names *how* it gets proven, so it can be picked
up opportunistically rather than scheduled.

- **B1 — GP-multiplayer roster grouping.** `ROSTER_SEASON_MODES` was widened to include
  `GRAND_PRIX` (the 2026 league runs in Grand Prix multiplayer), but the league's *normal* state
  — drivers captured as `"Player"` with telemetry restricted, grouped by race number via
  `roster.member_key` — has never been tested on a real capture. **Plan:** the author sets their
  own online name/ID to restricted at the **next race (~mid-August 2026)**. Deliberately *not*
  asking other members to change their settings, since they'd risk leaving them restricted
  afterwards. Season-critical if wrong (standings), so verify before trusting a full season's
  table.
- **E11 — track map rotation.** Possibly already correct; unconfirmed. **Plan:** compare the
  rendered map against the in-game track map when recording the next sessions. Note that absolute
  rotation deliberately follows the game's world frame, **not** F1.com broadcast art
  (DECISIONS → UI) — so "different from broadcast" is expected and is not the thing being checked.
- **A3 — "missing middle laps".** The aborted Windows race showing laps 1–2 then ~16–18 is almost
  certainly the same sleep root cause fixed in v0.4.2. **Plan:** spot-check on the next long
  Windows race; not worth a dedicated investigation.
- **A5 — `ES_DISPLAY_REQUIRED`.** Never isolated from `ES_SYSTEM_REQUIRED`; dropping it is a
  one-line experiment that would stop the screen staying lit. Also untested against a
  policy-managed machine, where a *lock* cannot be prevented (only sleep can).

## Recently closed

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
  **Leaves behind:** the Phase-1 "open the app twice" checklist item passed *before* WAL existed,
  so its result means "the contention never happened", not "WAL handled it". PACKAGING now asks for
  a re-test.
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
  game running — nothing wedged. See C2 above for what this does *not* prove.
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
