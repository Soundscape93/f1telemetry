# Roadmap

Planned work and deferred ideas. Not a commitment — a place to park intent so a future session
(or the VS Code chat) has the context. Roughly ordered by when it's likely to matter.

> **Ordering lives in [`docs/PRIORITIES.md`](PRIORITIES.md), not here.** This file is the
> catalogue of ideas and their reasoning; PRIORITIES holds the confirmed P1/P2/P3, the cycle plan,
> what is done, and what still needs verifying. Read PRIORITIES first to decide *what to work on*;
> read this file to understand *what a thing is*. If they disagree, PRIORITIES wins on ordering.

## Released

Both features that this section used to track as "next" have shipped, in **v0.4.0** (2026-08-01):
nationality flags in the driver standings, and the missing-capture prune. The `staging` grouping
mechanics they demonstrated are documented in PACKAGING → Versioning & dev release process.

## Seasons UI — remaining
- **Done: 2b — per-season rosters + league standings.** `rosters/season_<id>.json` is the
  canonical per-season roster for LEAGUE seasons. Viewing a LEAGUE season is **read-only**: if
  no roster file exists yet, the detail page *shows* a roster seeded in memory from captured
  names/numbers (merged over the previous league season's file), but writes nothing. The file is
  created only by an explicit action — a "Create roster file" button materializes the seed so it
  can be hand-edited, or CSV import writes it. The user picks a CSV from their own storage, the
  app validates it, and writes the canonical JSON; the CSV remains outside the app and is never
  the live roster path. League standings group drivers by **tagged keys resolved a whole
  classification at a time** (`LeagueRoster.session_keys`): an online-name alias first, then race
  number *for human cars only* — race numbers are unique only among humans, so an AI sharing a
  member's number is never that member — and two cars in one session can never share a row. LEAGUE
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
  (`calendar_rules`), the widget in `ui/components/calendar_picker.py`.
  *Edit-calendar action — **DONE** 2026-08-02 (was PRIORITIES → E6).* The detail page's **Edit
  calendar** button opens `ui/seasons/edit_calendar_page.py`, a fifth page reusing the same picker
  unchanged. A round that already has an assigned session is **locked**: it keeps both its
  `round_number` and its `track_id`, checked positionally (for each locked round *(n, t)* the
  proposed calendar must still have round *n* at track *t*), which covers reorder, insert-before,
  delete-before and truncate in one rule. Enforced in `SeasonStore.set_calendar`, which raises
  `CalendarConflictError`; the page catches it and names the offending rounds. Calendar only —
  mode / number / nickname / game format are not editable, since changing the format would move
  the track pool underneath the calendar (Madrid is 2026-only).

- **DONE — nationality flags in the driver standings table.** The season detail page's driver
  standings now read like the session classification table: the Driver cell carries a flag icon,
  built with the same "make the cell, then `setIcon()` when `flag_icon()` returns one" pattern, so
  icon size and row height match between the two tables. **Scope stayed deliberately narrow — the
  driver standings table only.** Constructor standings get **no** flags: the packet's nationality
  is per *driver*, not per team, so there is nothing truthful to render there. No new assets (the
  bundled flag-icons SVGs, MIT, attributed in `src/ui/assets/flags/ATTRIBUTION.md`) and **no
  storage change / no re-ingest** — `nationality_id` was already stored on every classification
  entry. The work was aggregation plumbing: `analysis/standings.py` threads `nationality_id`
  through `_Accumulator` onto `StandingRow` with the **same last-seen-wins rule already applied to
  `name`/`number`**, so a driver whose rows merge across rounds shows their most recent round's
  flag. Nationality is display-only and never part of driver identity. Fail-soft throughout: an
  unmapped id or a missing asset yields `None` and the cell simply shows no icon. Nothing else
  about standings behaviour changed.
  **Stayed out of scope:** team logos, platform logos, and any AI/PlayStation/EA branding row
  — see DECISIONS → UI ("Bundled imagery is open-licensed only").

## Other surfaces (currently placeholders)
- **E13 — a captures / maintenance surface.** The Help page has accumulated five actions that are
  not Help content: *Import captures…*, *Re-read captures*, *Find moved captures…*, *Clean up
  missing captures* and *Back up database…*. They landed there because Help was the only real page
  that wasn't a data surface, and each was individually too small to justify a page. Together they
  are now the app's whole data-maintenance story living under a heading that promises documentation.
  They want their own sidebar section, leaving Help as version / setup / about / notices.
  *Not urgent* — everything works and is discoverable — and **deliberately after Cycle 2**. Worth
  deciding alongside **E1 (Sessions)**: both are about where non-Seasons data actions live, and a
  captures surface that lists the `captures` table (file, size, sessions, recorded by, last seen)
  would answer "which capture holds this session?" — the direction `CaptureStore.for_session` was
  built for, and the first thing that would actually *read* `recorded_by`.
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
  - *1a — persistence backbone (no UI). DONE (commit 73d2c35).* Assembler captures the player's
    setup **history** and per-lap tyre context + full car damage; `laps.py` store persists lap rows
    + Parquet trace files + setup history; `ingest_capture` writes the trace files.
  - *1b — lap view. DONE.* `analysis/traces.py` (N-series-aware trace prep); reusable lap widgets in
    `ui/components/` (tyre box, damage/setup key-value tables, `TracePlot`); the `ui/laps/` surface
    (foldable per-session cards + filter → single-lap detail page); `LapStore.list`/`load` read API;
    and the app-side ingest wiring (`IngestWorker` builds a `LapStore`). Track-country flag on cards
    deferred — no `track_id → country` map exists. Detail-view polish: the lap timing is a single
    compact row (tyre+lap · sectors · lap time · valid); trace graph zoom/pan removed (plots are
    full-height, always fit to the whole lap); throttle/brake has a colour-blind palette toggle
    (green/red ↔ Okabe-Ito blue/orange) persisted via `QSettings` (new `ui/settings.py`).
  - *2 — same-context overlay. DONE.* The lap detail page's "Compare ▾" menu overlays laps on the
    shared distance grid: scopes are the weekend's **fastest lap**, **same-session** laps, and
    **same-weekend** laps (other sessions sharing the `weekend_link_id` — same track). Every channel
    is drawn per lap with a legend (in its own row above the plots) plus a bottom **Δ-time** row (the
    racing gap vs the viewed lap, from `time_deltas`). `ui/laps/comparison.py` enumerates candidates
    (a `LapRef` per lap, labelled `Lap N - Slot`); the "Fastest" scope spans the whole weekend and is
    omitted when the viewed lap *is* the fastest. Overlaid laps differ by both **colour and line
    style** (solid/dash/dot/…) and honour the persisted colour-blind palette (Okabe-Ito). All UI
    wiring over the N-series `analysis/traces.py` — no analysis rewrite. *Next here: iteration 2b.1.*
  - *2b — g-force channel + track-layout view. DONE.* Routes the **Motion** packet (carried forward
    into each sample, like Car Status — not a hard frame-join, so a Motion-less stream still builds).
    Adds four optional `LapTrace` channels: `g_lat`/`g_long` (2026 int16 ÷ 1000; the lone
    format-divergent channel) drawn as a new `TracePlot` row, and `pos_x`/`pos_z` (world coords)
    driving a new `TrackMap` panel — an equal-aspect plotted **XY path from telemetry** (no per-track
    image assets; works for any circuit). Hover a trace → nearest sample → marker on the map (via
    `TracePlot.cursor_moved` + a pyqtgraph `SignalProxy`). `read_trace` tolerates pre-2b files, so
    old laps degrade gracefully (map/g-row omitted) without re-ingest. *Map orientation:* the
    left-handed world frame is un-mirrored by negating one axis (fixes CW/CCW); the loop is closed so
    a race lap 1 (grid past the S/F line) still draws whole. **Absolute rotation follows the game's
    world frame, not the F1.com map art** — matching broadcast orientation would need a per-track
    rotation constant, deliberately not shipped (kept asset-free); a possible later opt-in.
    *Needs verification (PRIORITIES → E11):* the rendered orientation may already match the in-game
    map; to be checked against it while recording the next sessions. "Doesn't match the F1.com
    broadcast art" is expected and is not what that check is about.
  - **2b.1 — canonical track-map refinement (DONE).** The map now draws the **same clean shape every
    time** for a track, decoupled from the driven line, hover intact. A **canonical centerline =
    distance-resampled median racing line** (`analysis/track_layout.build_layout`): resample each
    usable lap's `pos_x`/`pos_z` onto one shared distance grid (out-of-range → NaN), then per-point
    `nanmedian` (1000 points). Robust to excursions/defending/missed apexes, and self-heals the
    lap-1 S/F gap (other laps cover it). Valid because F1 track world coords are fixed geometry —
    laps aggregate in raw world space with no per-lap alignment (deliberately not `traces.align`,
    which would shrink to the overlap and re-open that gap). **No Motion Ex needed** for this
    median-line version; a *true geometric* centerline would need Motion Ex / track-edge / track-width
    data and stays deferred. **Scope is the whole race weekend** (a lone quali session rarely has ≥3
    valid timed laps): `ui/laps/track_layout.TrackLayoutProvider` gathers valid Motion laps across
    the sessions sharing a `weekend_link_id` at the same `track_id`, builds the layout, and caches it
    keyed `(weekend_link_id, track_id)`. `TrackMap.set_layout` draws it; below `_MIN_LAPS` (3) usable
    laps it falls back to `set_trace` (the driven line). **Hover unchanged:** `cursor_moved` still
    emits a distance; the marker snaps to the nearest index on the canonical layout (both
    distance-indexed, same world frame). *Sector colouring — DONE (post-2c).* The Session packet
    already carries sector-boundary **distances** (`sector_2/3_lap_distance_start`) + `track_length`,
    now persisted on the session row (`track_length_m` / `sector2_start_m` / `sector3_start_m`,
    additive migration). `TrackMap` splits its outline into three coloured arcs
    (`analysis/track_layout.sector_bounds` + `SECTOR_COLOURS`, F1-map red/cyan/yellow); the traces mark
    the boundaries with dashed vertical lines every row, and a shared vertical cursor spans all trace
    rows + the map marker (clamped to the lap's distance range so hovering past the end can't stretch
    the x-axis). Always-visible map sector *labels* were tried (opaque mask, then a cut-out gap in the
    line) and removed — poor readability on complex layouts; the map uses colour alone (labels may
    return as hover/tooltips). The per-frame `sector` channel guessed at earlier proved unnecessary.
    **Corner
    numbers — future work:** no telemetry source; the clean route is a static per-track metadata
    snapshot (corner number + distance-from-S/F) transcribed from FastF1/MultiViewer
    `get_circuit_info`, keyed by our `track_id` and scaled by `track_length_m`. **Licensing:** that
    data is community/unofficial (MultiViewer; FastF1 is non-commercial/personal-use) — fine for
    private, friends-only use, but revisit/replace before any broad public distribution.
    **Priority:** deferred behind league-readiness work (packaging, GP roster import) — a visual
    enhancement only, not needed before the next league season.
    *Automatic cache refresh — **DONE** 2026-08-02 (was PRIORITIES → A1).* The provider's in-memory
    cache was never invalidated, so a stale weekend layout survived a mid-run ingest/re-ingest
    until app restart. `TrackLayoutProvider.invalidate()` now clears it whole (an ingest can touch
    any weekend; a re-ingest touches all of them), driven unconditionally from
    `MainWindow._refresh_current_view()` via `LapsView.invalidate_caches()` — *not* through the
    visible-page refresh, which would have kept the bug alive whenever the ingest finished while
    another surface was showing. Deleting a session's stored results goes the same way, via the
    weekend page's new `sessions_changed` signal. Note the cache held `None` as a real value ("fewer than
    `_MIN_LAPS` usable laps → draw the driven line"), so a weekend that later became buildable was
    stuck on the driven line; that entry is dropped too. A persisted `track_layouts/*.parquet`
    cache stays deferred (PRIORITIES → D3).
  - *2c — car-status graphic.* A car silhouette (in-game neon style, tyres as corner gauges) with
    colour-coded tyre / engine / body-damage zones. Rendered as SVG-authored `QGraphicsScene` path
    items over a Qt-free, tested `car_status.py` model; three threshold rules (tyre + engine wear
    60/80, aero/body stricter 15/40, temperatures as compound-keyed two-sided bands — see DECISIONS).
    ~90% of the data was already stored (tyre wear/damage/blisters on `LapTyreContext`; full car
    damage on `CarDamage`). **Phase A (data backbone) — DONE:** the only new ingest, the
    temperatures, is captured — tyre surface/carcass temps on `LapTyreContext`, brake/engine temps on
    `CarDamage`, snapshotted at the lap boundary from the carried-forward Car Telemetry entry
    (`tyres_surface_temperature` / `tyres_inner_temperature` / `brakes_temperature` /
    `engine_temperature`; requires re-ingest). **Phase B (threshold model) — DONE:** Qt-free
    `car_status.py` (`damage_parts` / `tyre_corners`), unit-tested. **Phase C (widget) + visual polish
    — DONE.** `CarStatusGraphic` renders the car — Inkscape-traced body regions, chassis/nose outline,
    floor-edge wings and front suspension — coloured by the model with per-part tooltips, plus four
    procedural corners (on-car tyre + inboard brake block + dashed connector to a wear/temp corner gauge),
    wired into the detail page's left column. The `_svg_path` parser was extended to the full Inkscape
    command set (S/T smooth curves, A arcs; `test_svg_path.py`) so parts are authored visually — see the
    Inkscape workflow + `docs/car_template.svg` in DECISIONS. *The "optional later: fold
    `tyre_box._wear_color` into `car_status`" item is moot* — the post-2c polish removed `TyreBox`
    entirely, so the 60/80 rule now lives only in `car_status`.
- **Analytics** — the genuinely cross-session work: same-track-different-season lap comparison,
  lap-time trends, AI-difficulty analysis, team-performance trends, ERS-deployment views. (The
  single-lap and same-context overlay graphs moved into the Laps surface — see above.) In-memory
  `LapTrace` analytics stay desktop-bound regardless of any web future.
- **Dashboard** — recent sessions / summaries (the record header already lives above it).

## Packaging (before sharing a built app with colleagues)
**Full plan, phases, clean-machine checklist, risks, release workflow, and tester instructions
now live in [`docs/PACKAGING.md`](PACKAGING.md).** This is the priority pre-season work (≈2–3
weeks). Summary of the locked direction:
- **Tool: PyInstaller, one-folder. Windows first**; macOS/Linux best-effort later; no paid
  signing/notarization while private/free (unsigned + documented SmartScreen / Gatekeeper
  click-through). Briefcase/installer polish deferred.
- **Phase 0 (the only hard part — everything depends on it): DONE.** Dependency manifest
  (`pyproject.toml`); `src/paths.py` with `data_root()` (per-user writable dir when frozen —
  `%LOCALAPPDATA%` / `~/Library/Application Support` / `~/.local/share`; CWD-relative in dev so
  existing usage is unchanged; `F1TELEMETRY_DATA_DIR` override) **and** `resource_path()` for
  bundled assets (flag SVGs — frozen-aware `_MEIPASS`); DB + `captures/` + `lap_traces/` +
  `rosters/` routed through it via the app entry points; **file logging** (`src/logging_setup.py`) +
  **global exception hook → crash dialog** (`src/crash.py` — a windowed build has no console); a
  `__version__` (`src/version.py`, with a separate `PIPELINE_VERSION`).
- **Phase 1 — DONE (2026-07-25).** PyInstaller Windows one-folder build (`packaging/` spec + entry;
  hidden imports for **pyqtgraph** + **zstandard**; exclude QtWebEngine/Qml/etc.; bundle flag SVGs),
  verified on the Win11 clean-machine checklist. **Also pulled forward from Phase 3: a notify-only
  update check** (`src/update_check.py` + Help page). User-facing setup now lives in
  `docs/USER_GUIDE.md`; the Help page carries the same in-app.
- **Phase 2 — migration vs pipeline-version vs auto-reingest: DONE (2026-07-25, dev).** Additive
  schema stays silent via `ensure_schema`; a separate **`PIPELINE_VERSION`** in a `meta` table
  (`storage/meta.py`, engine-agnostic — not `PRAGMA user_version`) gates a **guided,
  progress-barred, non-blocking, cancellable, idempotent** re-ingest of the archived captures the
  `captures`/`capture_sessions` tables enumerate (round assignments/rosters survive — no FK, stable
  `session_uid`). `pipeline.check_pipeline_version` + `reingest_all` are the Qt-free half,
  `ReingestWorker` the thread, offered at startup and re-runnable from Help → *Re-read captures…*.
  A populated DB with no stamp counts as legacy (0) and is offered the upgrade; a fresh one is
  adopted silently. Missing archives are surfaced (*"N of M updated"*) but don't block the stamp —
  they can never be rebuilt. `recorded_by` *is* preserved (fed back from the `captures` row).
  Windows re-verification pending on the next build.
- **Phase 3 — DONE (2026-07-26; release flow moved off `main` 2026-08-01).** **Label-driven
  release:** write the entry under `## Unreleased`, label the `staging` → `main` PR
  `major`/`minor`/`patch`, merge — `bump.yml` bumps `src/version.py` + `pyproject.toml`
  + the changelog **on the PR's branch**, and once the merge lands `tag.yml` tags `main` and calls
  `release.yml` (preflight gate + test suite →
  `USER_GUIDE.pdf` on Linux via pandoc/xelatex + the PyInstaller Windows build → a **full** GitHub
  Release). CI **verifies** the version, never stamps it (`packaging/check_version.py`), so the
  artifact is exactly the tagged commit. The PDF, `roster_template.csv`, `LICENSE` and `NOTICE.md`
  ship **beside the exe**,
  reachable from the Help page's **Open user guide** and **Licences & notices** via the new
  `paths.app_dir()` (third path kind)
  with a PDF → source-`.md` → GitHub fallback chain (the notices need only two steps — `app_dir()`
  is the repo root in a source run); **Open data / captures / logs folder** actions
  landed alongside (`%LOCALAPPDATA%` is hidden by default — the app opens Explorer rather than the
  data moving). Real self-updater — velopack/Sparkle/`tufup` — still deferred. Details + rationale in
  `docs/PACKAGING.md`.
- **Phase 4 — in progress, split into C8a/C8b/C8c (PRIORITIES → Cycle 3, Release 2).**
  **C8a done 2026-08-07:** a best-effort **Linux tarball** ships with each release (`linux-build` in
  `release.yml`); **macOS is dropped** — no known user, and an unsigned build walks into Gatekeeper.
  **C8b next:** an **Inno Setup installer**, decided as an **admin install** so it can write the
  Windows Firewall allow-rule, with the standing invariant that the app needs no admin *at runtime*.
  **C8c (velopack self-updater) deferred** — notify-only stays. Detail and rationale in
  `docs/PACKAGING.md` → Phase 4.
- **First milestone:** a zipped one-folder Windows build that runs on the author's Win11 boot and
  is shared with a few trusted testers.

### RESOLVED (v0.4.2, verified 2026-08-02) — Windows recorder stalls
*Kept in full: the reasoning took several wrong turns and the evidence is worth not re-deriving.*

Found 2026-08-01, capture `20260729_182357`.
On the packaged Windows build the recorder process stops being scheduled for minutes at a time.
Windows' default 64 KB UDP receive buffer holds only ~0.3 s of telemetry at the ~0.2 MB/s stream
rate, so everything past that is kernel-dropped; resumption shows a ~64 KB drain at 20–50 MB/s
against the 0.18–0.21 MB/s normal rate. Cost in that capture: 143 s and 468 s blackouts, losing the
Final Classification for Q1#2 and Q3 plus nearly all of Q3.

**Leading cause: system idle/lock.** The two stalls were preceded by active periods of 320.8 s and
307.2 s — a ~5-minute idle timer. The setup is a **PS5 sending telemetry to a laptop that only
records**, so the laptop sees no keyboard/mouse input for the whole session; wheel and console input
cannot reset its idle timer. This affects every console-based user with the same setup.

Explicitly **not** a broadcast/firewall/bind issue: steady-state loss is only 0.25–0.41 %, the bind
stays `0.0.0.0`, and broadcast stays the documented default — no user-facing IP setup change.
Linux's larger default buffer (212992 B) does **not** explain why this is invisible there: ~1 s of
cover wouldn't survive a multi-minute stall either. The difference is process suspension.

**Done (v0.4.1).** `SO_RCVBUF` raised to 8 MB — at the ~0.2 MB/s stream rate that turns ~0.3 s of
cover into ~40 s — and a per-iteration stall warning: a loop iteration far longer than the socket
timeout means *we* weren't running, which separates a stall from the game simply not sending (the
two look identical in a capture, but only one loses packets). Verified on Linux: buffer 212992 →
8388608 B, no false positives on four game-silence gaps, and a screen lock mid-recording did **not**
stall the recorder — which is why this never showed up in dev.

**Confirmed on Windows v0.4.1** (capture `20260801_214539`, 2026-08-01). The warning fired:
`recorder stalled 22.3s`, after 7.5 minutes of activity — squarely inside the machine's 5–10 minute
idle window. The race completed cleanly (`CHQF` → `SEND` → `RCWN`), and the Final Classification is
**still missing**, so the cost is real and repeatable.

The 8 MB buffer also **refined the diagnosis**, which is what it was for. A 22.3 s stall at
0.2 MB/s is ~4.5 MB — well inside 8 MB — so a merely *starved* process would have resumed with a
~4.5 MB drain. Only **0.3 KB** arrived: nothing was buffered, therefore nothing was received, so
the NIC was down too. **The machine sleeps (modern standby), it isn't just descheduled.** The old
64 KB buffer could never show this — it fills in 0.3 s, so awake-and-dropping looks identical to
asleep.

**Done (v0.4.2).** `src/keep_awake.py` — a `SetThreadExecutionState` context manager
(`ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED`) wrapped around the capture loop in
`RecorderWorker.run`. It lives on the worker thread because the flags are per-thread and die with
the thread that set them; it is a no-op off Windows and never fatal. `ES_DISPLAY_REQUIRED` is the
one judgement call — it keeps the screen lit, costing laptop battery — and is included because
screen-off can itself trigger standby; drop it if a Windows test shows `ES_SYSTEM_REQUIRED` alone
suffices.

**Ruled out: EcoQoS opt-out.** EcoQoS throttles CPU *speed* for background processes; it neither
suspends for 22 s nor takes the network stack down. The evidence points at sleep, so this would be
cargo-culting. Not implemented.

**Verified on Windows v0.4.2** (capture `20260802_101555`, 2026-08-02) — a 27-minute untouched
recording of Q1/Q2/Q3, against a stall that previously hit at 7.5 minutes:

| | v0.4.1 | v0.4.2 |
|---|---|---|
| stall warnings | `recorder stalled 22.3s` at 7.5 min | **none in 27 min** |
| buffer drains | 64 KB @ 20–50 MB/s | **none** — every gap resumes at 0.13–0.82 MB/s |
| session clocks | — | Q1 1080→0, Q2 900→0, Q3 720→0, all complete |
| Final Classification | missing | **Q1=2, Q2=2, Q3=5 (9 total)**, no reconstructed tables |

Log shows `stay-awake active for this recording` at start and `stay-awake released` on stop, so the
request doesn't outlive the recording. Residual loss 0.64–1.04 % is the accepted Wi-Fi baseline
(PS5 → laptop), not a recorder problem. `ES_DISPLAY_REQUIRED` was kept — it was never isolated
from `ES_SYSTEM_REQUIRED`, so dropping it remains an untested one-line experiment.

**Caveat for managed machines.** `SetThreadExecutionState` prevents *sleep*; it cannot override a
group-policy or password-protected **lock**. That should still be fine — a locked-but-awake machine
keeps its NIC up and keeps scheduling the recorder, and sleep was the failure mode — but it hasn't
been tested on a policy-managed device.

**The "missing middle laps" report (aborted Windows race, laps 1–2 then ~16–18) is almost certainly
the same root cause and should be considered resolved with it** — worth a spot-check on the next
long Windows race rather than a dedicated investigation.

## Storage & analysis
- **Reconstructed-race points — accept / edit / store (Option 3, deferred).** Option 2 shipped:
  a missing Final Classification packet yields a reconstructed classification
  (`Classification.is_reconstructed`), badged in the UI, with a **muted, display-only** points
  estimate and **excluded from standings** (see DECISIONS, TELEMETRY_NOTES). Option 3 adds the
  human-in-the-loop half: an **accept/edit workflow** to confirm or hand-correct the estimated race
  points (persisted, distinct from game-reported), a **manual editor** for the points cells, and
  **re-including** the confirmed values in `compute_standings` / `compute_constructor_standings`.
  Needs a points-source distinction on the entry and belongs with **league-management** (per-league
  scoring tables) — until then estimates never reach a championship.
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
- **Complete `DRIVER_NAMES`. DONE (2026-08-02).** The AI driver-id table now holds every entry
  from both UDP spec PDFs (F1 25 v3 + the 2026 season pack). An id that still fails to resolve is
  newer than the specs we have, not a gap to fill — `diagnose_participants.py` surfaces which, and
  unknown ids degrade to a readable placeholder rather than an error.

## Capture compression
- **Done — the hybrid landed.** Ingest is archive-first (`pipeline.archive_and_ingest`): compress
  the raw to `.f1cap.zst` first, ingest *from* the archive (checksum-verified end-to-end), delete
  the raw only on success — a failed ingest keeps both raw and archive. New archives are **zstd**
  (level 3: ~18% smaller than gzip-6 and several times faster; benchmarked); existing `.f1cap.gz`
  stay readable and are ingested in place. Capture **metadata is in the DB** (`captures` +
  `capture_sessions`, `CaptureStore`, keyed by a codec-independent content hash) so captures are
  queryable without decompressing. The diagnostic tools read through `open_capture`. See
  ARCHITECTURE → Capture compression and DECISIONS → Storage.
- **Done — league capture import** (B2 + B3, 2026-08-04). *Help → Import captures…* is the flow the
  whole capture-as-interchange design was built for. Read and write are split like the prune:
  `find_importable_captures` is a walk plus one `stat` per file and a single `known_files()` query
  — no archive opened — so the user sees the count and the total size before a thread starts, and
  `import_captures` is what acts on the list they agreed to.
  **Four outcomes, decided by content hash**, not by name: *new* → copy home + ingest; *already
  held* → skip (a re-synced folder is a no-op, which is the entire reason the table is keyed on a
  hash); *known but missing locally* → copy home + `relocate`, the one path that treats the shared
  folder as a backup of last resort, deliberately without re-ingesting (rebuilding derived rows is
  "Re-read captures"' job); *only `recorded_by` differs* → update in place.
  **Copy-home is the point, not an optimisation:** the shared drive is transport and the local
  archive is the home, so no row is ever left pointing at a folder that syncs, disconnects or gets
  tidied up by someone else. The source is never touched; copies go via `.part` + `os.replace`, the
  same guarantee `archive_capture` gives. A name clash is numbered (`monza-2.f1cap.zst`) rather than
  overwriting — it can only mean two *different* recordings sharing a name, since the hash already
  ruled. **A capture already inside the captures folder is ingested in place** (`_is_inside`): found
  the hard way, by importing from a home directory that contained the data root and watching the app
  copy its own archives beside themselves. It also makes "point it at your captures folder" the way
  to pick up a loose recording that was never ingested — the one thing the retired
  `Ingest .f1cap (test)` button did that nothing else replaced.
  A capture that fails to ingest **keeps** its local copy, unlike `archive_and_ingest`:
  nothing is at risk because the shared original is untouched, and a capture that won't parse is
  exactly the one worth having locally.
  Also **retired the `Ingest .f1cap (test)` header button** — labelled dev-only in code while the
  user guide documented it as *the* import path, wrong in one place or the other since v0.3.0.
  `docs/USER_GUIDE.md` §4 rewritten in the same branch.
  **`recorded_by` closes with it** (B3): one optional field on the import prompt, the importer's
  claim about the file. `CaptureStore.set_recorded_by` exists so "a re-import can correct it" is
  true rather than aspirational — without it an already-held capture would simply be skipped.
- **Done — pruning `captures` rows whose file is gone.** Deleting a capture file left its
  `captures` row behind, so every future re-ingest listed it under `ReingestSummary.missing` (and
  logged "no archive found") — harmless, but the noise grew with every deleted recording.
  *Help → Clean up missing captures* now clears them: `pipeline.find_missing_captures` lists what
  `resolve_capture_path` can't find, the user confirms a dialog showing every file name and
  last-known path, and `pipeline.prune_missing_captures` drops those rows (children by cascade).
  Metadata only — no file is deleted, and no session, assignment or roster can be reached.
  The design problem the deferral was about is **not** solved, it is **handed to the user**: a
  moved file and a deleted one are still indistinguishable at the row level, so the app never
  decides on its own. Manual action, explicit confirmation, a re-resolve at delete time (so a
  drive reconnected while the dialog waits keeps its capture), and a warning when *every* capture
  is missing — the signature of a moved folder. No schema change, no `PIPELINE_VERSION` bump.
  See DECISIONS → Storage.
- **Done — locating a moved capture by content hash** (B4, 2026-08-03). *Help → Find moved
  captures…* walks a folder the user picks and re-points a `captures` row at the file it finds,
  so a moved capture stops being indistinguishable from a deleted one. It slots in **between**
  `find_missing_captures` and `prune_missing_captures`, which were split for exactly this, and the
  prune dialog now sends the user here first.
  `pipeline.relocate_moved_captures` searches **only** the known-missing rows — a row that already
  resolves is correct, and re-pointing it at a second copy found on a memory stick would be a
  regression. `(file name, size)` pre-filters (a `stat`), the content hash rules:
  `archive.hash_capture` is `ingest_capture`'s read pass isolated, so the scan path and the ingest
  path can't drift about what a capture *is* (asserted in `test_hash_is_codec_independent`). The
  walk is recursive and suffix-filtered, and stops as soon as everything wanted has been found.
  Threaded (`RelocateWorker`), unlike the prune: confirming a match costs a decompression pass per
  candidate. Two deliberate limits: it **re-points, it does not copy home** (copying into the local
  captures folder is what the league import is for — conflating them would silently duplicate
  hundreds of MB behind a button that says "find"), and a capture that was renamed *as well as*
  moved never reaches the hash and stays a job for the prune. First production caller of
  `CaptureStore.relocate`, which needed two fixes on the way: it was annotated `-> None` but
  returns `bool`, and derived `file_name` with `rsplit("/")` — the *entire path* on Windows,
  breaking both `known_files()` and `resolve_capture_path`'s fallback.
- **Loose end: `recorded_by` is plumbed through `ingest_capture` / `CaptureMeta` but never set.**
  No UI wires it, and — worth being precise about — **nothing reads it either**: no view, no query,
  no standings path. The earlier claim that it is "the one capture field a re-ingest can't
  backfill" is true only of a *re-ingest*, which feeds the stored value back; a **re-import** sets
  it, because `CaptureStore.record` replaces by hash. So nothing is lost irreversibly by leaving it
  blank. **Settled 2026-08-03, shipped 2026-08-04 with B2:** not a branch of its own, but one
  **optional** "Recorded by" field on the league import prompt — filled at the moment the admin
  actually knows the answer, blank without penalty. No settings page, profile or identity feature.
  Still nothing *reads* it; if something ever does, revisit the format-v2 idea then and not before.
  See PRIORITIES → Cycle 2 and DECISIONS → Storage.

## Localization (the G block)

The app speaks English only. The league is Swiss, and most members would rather read German — so
the user-facing text should eventually be available in both, with English staying the source
language and the fallback.

- **G1 — i18n infrastructure + a language setting.** The mechanism, with one language pair wired
  end to end: `tr()` at the call sites, `QTranslator` installed at start-up, compiled `.qm` files
  shipped as bundled assets, and somewhere for the user to choose. **The approach is already
  decided** — Qt's own translation system rather than a Python dictionary of strings, for reasons
  recorded in DECISIONS → Localization.
- **G2 — German translation of the UI strings.** The bulk of the work. A **glossary comes first**:
  some vocabulary stays English on purpose (*Session*, *Season*, *Lap* are what the game and the
  league already say), and that list has to exist before translation starts rather than being
  argued out one string at a time.
- **G3 — German user guide.** Deliberately its own item: `docs/USER_GUIDE.md` is not UI text, it is
  a document converted to PDF by CI. A German edition means a second source document, a second
  pandoc invocation and a second artifact in the release zip — a packaging change more than a
  translation one.

Scheduling lives in PRIORITIES (P3, likely Cycle 5). The short version of *why not sooner*: four
UI surfaces are still placeholders, and translating a UI that is still growing means translating it
twice.

## Possible, uncertain
- **Hosted multi-user league platform** — signup / authorization, colleagues upload their own
  results. Would be additive: reuse the version-agnostic domain + storage; the schema is already
  kept engine-agnostic (SQLite → Postgres only if this happens). Nothing current depends on it.
- **Mobile / web access** for colleagues — a long-term direction, not planned.
