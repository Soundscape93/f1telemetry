# f1telemetry

A personal desktop app that captures F1 25 / F1 26 UDP telemetry from a PS5, analyses the
player's own laps, and records league / multiplayer results and standings for a private racing
league.

**Used for:** (1) analysing own laps across a session by overlaying N laps on a shared distance
grid; (2) publishing practice/quali/race results and standings to the league (screenshot/file);
(3) possibly, later, packaging for colleagues to analyse their own laps. Colleagues are
near-term test users; a hosted multi-user version is possible but uncertain, and nothing in the
design depends on it.

> This file is the always-loaded context. Deeper material lives in `docs/` — see
> [Where to look](#where-to-look). Keep this file short; put detail in the `docs/` files.

## How we work

- **Design-first, reviewable changes.** The author writes/reviews the code by hand and values
  understanding over speed. Explain non-obvious decisions; keep diffs focused and layer-clean.
- **Confirm before editing code.** For implementation work, discuss the intended change first
  and do not modify files unless the author explicitly asks to apply it. Keep code out of the
  chat unless the author asks for it there.
- **Do not run git commits.** When a change is ready, suggest appropriate commit message(s) for
  the author to run; never execute `git commit`.
- **Git root is nested.** The repository root is `f1telemetry/`, not the workspace root
  (`F1-TELEMETRY/`). Run git-oriented commands from `f1telemetry/`.
- **Verify before "done".** Logic is proven in a throwaway sandbox and/or the `unittest` suite
  before it's considered finished. Tests use plain `unittest` + `subTest` (not pytest).
- **Absolute imports** everywhere under `f1telemetry.src.<layer>...`.
- **Layered separation is the rule** (see `docs/ARCHITECTURE.md`). Ingest, protocol, domain,
  storage, analysis, and UI are decoupled; everything from the normalizer up is
  format-agnostic — 2025 vs 2026 differ *only* in the wire structs and parser at the bottom.

## Tech stack

- Python 3.10+ (modern syntax: `X | None`, etc.), developed on Linux; the game runs on a PS5.
- **UI:** PySide6 (+ PyQtGraph for charts).
- **Storage:** SQLite via SQLAlchemy 2.0 (`DeclarativeBase`, `Mapped`/`mapped_column`), kept
  engine-agnostic so it *could* move to Postgres if a hosted server is ever built.
- **Wire parsing:** `ctypes.LittleEndianStructure` (`_pack_ = 1`), one struct set per format.

## Repository layout

```
F1-TELEMETRY/                   # VS Code workspace root — NOT the git repo; holds untracked
                                #   data + dev scratch that stays out of version control:
  captures/                     # capture recordings — source of truth; gzip-archived to
                                #   .f1cap.gz after ingest, never auto-deleted
  rosters/                      # canonical per-season roster JSON:
                                #   season_<id>.json; CSV is import-only (see DECISIONS)
  diagnose_participants.py      # dev tool: raw Participants per session (read-only)
  dump_classifications.py       # dev tool: assemble() + classification dump (read-only)
  session_history_scan.py       # dev tool: Session History scan (read-only)
  *_demo.py                     # dev sandboxes: decode / parser / normalizer /
                                #   assembler / storage demos
  *.f1cap, *.db                 # loose dev captures + dev databases (demo.db, f1league.db)
  Data Output from F1 25 *.pdf  # the UDP spec PDFs (2025 v3 + 2026 season pack)
  f1telemetry/                  # ← the git repository root (code + docs + tests)
    Claude.md                   # this file
    README.md
    docs/                       # ARCHITECTURE, DECISIONS, TELEMETRY_NOTES, ROADMAP
    src/
      ingest/    recording.py (.f1cap read/write), recorder.py, sources.py,
                 archive.py (gzip .f1cap.gz), inspect.py (capture-summary CLI)
      protocol/  base.py, header.py, enums.py, reference.py, registry.py, parser.py,
                 v2025/structs.py, v2026/structs.py
      domain/    models.py, normalizer.py, season.py, calendars.py, roster.py
      session/   assembler.py
      storage/   schema.py, sessions.py, seasons.py
      analysis/  standings.py
      ui/        app.py, main_window.py, season_roster.py, workers.py, formatting.py,
                 seasons/ (view.py=SeasonsView container + overview/create/detail/weekend
                   _page.py, labels.py) — pages coordinated by navigation signals
                 components/ (tables.py, classification_table.py) — shared widgets
      pipeline.py               # Qt-free ingest orchestration (ingest_capture)
    test/                       # unittest suites (test_*.py); run from the repo root:
                                #   python3 -m f1telemetry.test.<name>
```

## Core invariants (the ones that bite)

Each of these has caused or prevented a real bug — treat them as load-bearing:

1. **The roster is accumulated across all Participants frames, not taken from one packet.** A
   late (post-race/podium) Participants packet can report a smaller `num_active_cars`; trusting
   a single frame leaves high-vehicle-index cars unmatched in the classification join (blank
   name / number 0 / team −1). The assembler merges every frame by vehicle index. Details in
   `docs/TELEMETRY_NOTES.md`.
2. **Per-car arrays are indexed by vehicle index, not finishing position.** The classification
   is joined to the roster by vehicle index, then sorted by position only for display.
3. **Sessions split on `header.session_uid`;** `uid == 0` frames are init noise and ignored.
4. **`session_assignments.session_uid` is deliberately NOT a foreign key** to `sessions`, so
   re-ingesting a capture (replace-by-uid) never wipes manual round placements.
5. **Slot (Q1/Q2/Q3/Sprint/Race) is derived, never stored** — but not from `session_type`
   alone: the Sprint Race and the Grand Prix *both* report `session_type` RACE (15), so they're
   told apart by their position in the weekend. `domain/season.py:weekend_slots` resolves this
   from the game's `weekend_structure` (persisted per session), falling back to `session_link_id`
   order for legacy rows — the Grand Prix is the weekend's final race; earlier races are Sprints.
6. **Traces are indexed by lap DISTANCE, not time.** The header is 29 bytes. The recorder binds
   `0.0.0.0:20777` (set the game's UDP to broadcast).
7. **League humans often capture as name `"Player"`** (online-name sharing off), so league
   identity resolves by **race number** first; online name only when public.
8. **Format is detected per packet** from `header.packet_format` and dispatched on
   `(packet_format, packet_id)` via the registry — never a user-facing toggle.
9. **Enums are stored as raw ints** and read back via `safe_enum` (returns the member, or the
   raw int for values newer than our enum).

## Conventions

- **Module-level constants use a SINGLE leading underscore.** A double underscore triggers name
  mangling inside class bodies (`__X` → `_ClassName__X`) and has caused a `NameError`. Reserve
  `__` for class attributes you actually want mangled.
- Type hints throughout. Frozen dataclasses for domain value objects.
- Store objects are context managers (`__enter__`/`__exit__` dispose the engine); use them.

## Current status

- **Ingest / protocol / domain / storage:** complete and tested (both formats). Captures are
  gzip-archived to `.f1cap.gz` after a successful ingest; replay/ingest reads both forms.
- **Standings:** driver standings (by name or race number) and constructor standings; LEAGUE
  standings resolve drivers through the per-season roster.
- **UI:** single-window shell (sidebar + persistent record/stop header + stacked pages). The
  Seasons surface is real — overview, create, per-season detail (calendar + driver & constructor
  standings), per-season LEAGUE roster CSV import, and a weekend view with round-centric session
  assignment (its capture picker can also delete an unassigned session's stored results via
  right-click; the recording on disk is kept). LEAGUE displays prefer captured public online
  names, falling back to the first
  roster `online_names` alias when captures only say `"Player"`/blank. Reusable widgets (the
  session classification table, table primitives) live in `ui/components/`, ready for the
  upcoming surfaces. The Seasons surface is split into `ui/seasons/` — a thin `SeasonsView`
  container coordinating one widget per page via navigation signals. The custom-calendar picker
  is live: `create_page.py` embeds the reusable `ui/components/calendar_picker.py`, driven by
  `(mode, format)` rules from `domain/calendars.py` (Career/My-Team = fixed-length subset;
  Grand Prix/League = reorderable sandbox with duplicates).
  The **Laps** surface is now real: `ui/laps/` (foldable per-session lap cards + track/session
  filter → a lap detail page with tyre box, damage/setup tables and stacked telemetry graphs),
  built on `LapStore.list`/`load`, the N-series-aware `analysis/traces.py`, and reusable lap
  widgets in `ui/components/`. **Lap-view iteration 2 (same-context overlay) is done:** the detail
  page's "Compare ▾" menu overlays the weekend's fastest lap / same-session / same-weekend laps on
  the shared distance grid, each channel coloured *and* line-styled per lap with a legend, plus a
  Δ-time (racing-gap) row; candidate laps are enumerated by `ui/laps/comparison.py`, and the
  colour-blind palette covers the overlay too. Dashboard / Sessions / Analytics remain placeholders.
- **Next:** lap-view **2b** — route the **Motion** packet once to add a g-force `LapTrace` channel
  *and* a track-layout (XY-path) view. Also pending: the Analytics surface and an edit-calendar
  action. See `docs/ROADMAP.md`.

## Where to look

- **`docs/ARCHITECTURE.md`** — the layered pipeline, each layer's responsibility, threading.
- **`docs/DECISIONS.md`** — why the design is the way it is (read before changing a big call).
- **`docs/TELEMETRY_NOTES.md`** — F1-UDP spec facts and quirks, and the diagnostic tools; read
  before touching the parser, normalizer, or assembler.
- **`docs/ROADMAP.md`** — planned work and deferred ideas.
