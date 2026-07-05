# Telemetry notes

F1-UDP spec facts and the quirks that have actually caused bugs here. Read this before
touching the parser, normalizer, or assembler. The authoritative reference is the F1 25 UDP
spec PDF (`Data_Output_from_F1_25_v3.pdf`).

## Format & header
- **The header is identical across 2025 and 2026.** Parse it generically (29 bytes) and
  dispatch on `(packet_format, packet_id)`. Format is `header.packet_format` (byte 0), never a
  user toggle.
- **2025 → 2026 differences** (all confined to the wire structs):
  - car count 22 → 24 (most per-car array sizes change);
  - g-force fields `float` → `int16` (divide by 1000.0 in 2026);
  - several IDs `uint8` → `uint16`;
  - a new Car Telemetry 2 packet (id 16) in 2026;
  - ERS deploy-mode value 3 renamed *overtake* → *boost* (same value);
  - engine temperature `uint16` → `uint8`;
  - the Collision event gains a severity byte.
- **Wheel arrays are always ordered RL, RR, FL, FR.**

## MVP packet subset
Built first (don't build all 16 × 2 up front): Lap Data (2), Car Telemetry (6), Session (1),
Participants (4), Car Status (7, for ERS), Final Classification (8), Session History (11), and
Motion (0) for g-force. Deferred until a feature needs them: Car Setups, Car Damage, Tyre Sets,
Motion Ex, Lobby Info, Time Trial, Lap Positions, Event.

## Authoritative sources & joins
- **Final Classification (id 8, sent once at race end)** is the source of truth for results and
  points. **Session History (id 11)** gives per-lap times and sectors — timing comes from here,
  not from live Lap Data. (Sector field name is `sector1_time_ms_part` — no "in".)
- **Frame join:** the "rate as specified in menus" packets share `header.frame_identifier` and
  ship together; carry the slower packets (Session ~2/s, Car Status/Damage ~10/s) forward into
  each sample. The assembler joins the player's Lap Data + Car Telemetry rows by frame id.
- **Traces are indexed by lap DISTANCE, not time**, so laps overlay corner-for-corner
  regardless of pace.

## Identity fields (Participants) — the sharp edges
The normalizer reads, per car: `ai_controlled`, `driver_id`, `network_id`, `team_id`,
`race_number`, `nationality`, `name`. Watch out for:

- **`num_active_cars` can shrink within a session.** A late post-race/podium Participants
  packet may list fewer cars than actually ran. **The final classification's car count is the
  authoritative full grid.** Do NOT build the roster from a single (last) frame — merge across
  all frames (union by vehicle index). This was a real bug: high-vehicle-index cars that finished
  mid-pack came through with blank name / number 0 / team −1 because the kept roster was short.
  Fixed in the assembler via `merge_participant`.
- **Per-car arrays are indexed by vehicle index, not finishing position.** Join the
  classification to the roster by vehicle index; sort by position only for display. The own car
  is `header.player_car_index`. Vehicle index is session-scoped.
- **Humans capture as name `"Player"` when online-name sharing is off.** In this league that's
  the norm, so **resolve league identity by race number** (distinct and stable), not by name.
  Online names appear only when a driver enables public telemetry.
- **`driver_id == 255` means a human** (no AI driver id). AI `driver_id`s map via `DRIVER_NAMES`
  — but that table is currently partial (~11 entries); an unresolved AI id usually just means the
  table needs completing from the spec appendix (see ROADMAP), not that the data is bad.
- **`network_id` is per-lobby** (and 255 when not networked) — useless as a cross-lobby key.
- **`team_id == 255` (or otherwise unknown) → "Unknown team".** Note: `team_id == -1` is *our
  normalizer's placeholder* for a car that failed the roster join — historically a bug signal,
  not a game value.
- **`name` is a NUL-padded fixed-width char buffer.** Decode by splitting on a single NUL byte
  `b"\x00"`. (A past bug used `b"\0x00"` — that's the four bytes `\x00 x 0 0`, which never
  matches, leaving 26 trailing NULs on every name.)

## Restricted telemetry
The own car is always fully public. For other cars, ERS / fuel / wear / damage / setups are
zeroed unless the driver opts into "Public". Driving channels (speed, throttle, brake, steer,
gear, rpm, drs, temps) are always visible for every car.

## Session type: Sprint Race == Race (both report 15)
The game reports `session_type` **RACE (15)** for *both* the Sprint Race and the Grand Prix — a
sprint weekend therefore has two type-15 sessions and there is no flag on the session that says
which is which. What disambiguates them is the **`weekend_structure`** array on the Session packet
(`num_sessions_in_weekend` + `weekend_structure[12]`): the ordered list of session types that make
up the weekend, e.g. `[P1, SprintShootout×3, Race, Q1, Q2, Q3, Race]`. The **first** race entry is
the Sprint; the **last** is the Grand Prix. `session_link_identifier` is monotonic across a weekend
(and equals `weekend_link_identifier` for the first session, +10 per session in observed data), so
sessions sort into true running order by it — the Sprint sits *before* Qualifying, the GP *after*.

`domain/season.py:weekend_slots` persists `weekend_structure` per session and uses it to place
each captured session (and mark still-pending ones); rows saved before it was captured fall back to
`session_link_id` order (last race = GP). Note: both Sprint and GP award points, so both stay in
`RACE_SESSION_TYPES` for standings — the slot distinction is a *display/Results* concern only.

## Track ids worth remembering
Imola is **27** (in the 2025 calendar); Madrid is **42** (new in 2026, replaces Imola in that
calendar). `official_calendar(year)` encodes the preset order for each.

## Result status / reason
`ResultStatus`: INVALID, INACTIVE, ACTIVE, FINISHED, DID_NOT_FINISH, DISQUALIFIED,
NOT_CLASSIFIED, RETIRED. `ResultReason` adds detail (RETIRED, TERMINAL_DAMAGE, NOT_ENOUGH_LAPS,
BLACK_FLAGGED, RED_FLAGGED, MECHANICAL_FAILURE, …). The UI collapses non-finishers to short tags
(DNF / DSQ / NC / DNS) in `ui/formatting.py`.

## Diagnostic tools (read-only, run from the repo root)
Built during the roster-blank investigation; keep them for future data-quality work.
Note: these tools open captures with plain `open()`, so they currently read only uncompressed
`.f1cap` files — decompress a `.f1cap.gz` first (or route them through `open_capture`, see
ROADMAP).

- **`python -m f1telemetry.src.ingest.inspect <capture.f1cap>`** — per-`(format, packet id)`
  packet tally plus byte/duration totals; the quick eyeball check that a recording is
  well-formed and contains the packet types you expect.
- **`diagnose_participants.py <capture.f1cap>`** — dumps every car's raw identity fields per
  session, aggregated across all Participants frames, and flags blanks. It classifies how each
  gap could be recovered: **within-session merge** (a good value exists in other frames), **AI
  driver-id lookup** (driverId resolves), or **cross-session backfill** (the same car is complete
  in another session). Proves whether a problem is in the recording or downstream.
- **`dump_classifications.py <capture.f1cap>`** — runs the real `assemble()` and dumps each
  session's classification with an **`inRoster`** column (does this car's vehicle index exist in
  the roster?) plus roster-vs-classification counts. Pinpoints join misses. This is what
  confirmed the `num_active_cars` roster bug (short roster → orphaned high-index rows).