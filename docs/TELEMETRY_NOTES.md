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
- **Missing Final Classification → reconstructed result.** Because id 8 is sent *once*, a recording
  stopped a beat early (or a single dropped datagram) can miss it entirely, which used to leave the
  results table empty (0 drivers). When it's absent, the assembler synthesizes a best-effort
  classification (`reconstruct_classification`) from the **last Lap Data frame** + **per-car Session
  History**: finishing order, laps, best lap and tyre stints are recovered exactly; **total race
  time** as the sum of Session History lap times (the game defines the FC total as race time
  *without penalties* — i.e. exactly that sum); **penalty time** from `LapData.penalties`. The one
  FC-only field is **championship points** (in no telemetry packet), left 0. Such results carry
  `Classification.is_reconstructed=True`; the UI badges them and shows a muted, display-only points
  *estimate*, and standings exclude them (see ARCHITECTURE → standings, DECISIONS).
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

## Lap-view data sources (iteration 1a)
The lap detail view pulls from packets the assembler historically ignored. All are parsed and
registered already; the work is routing them in `feed()` and snapshotting at the right moment.

- **Tyre compound & age come from Car Status (7):** `actual_tyre_compound` / `visual_tyre_compound`
  (see the tyre enums) and `tyres_age_laps`. These are current-state fields, so read the player's
  entry at the lap boundary.
- **Tyre wear comes from Car Damage (id not in the MVP subset — but parsed):** `tyres_wear[4]` is a
  **cumulative percentage over the stint**, not a per-lap value — so "tyre usage for this lap" is
  the wear reading *as the car crosses the line* (an end-of-lap snapshot), not a trace channel. The
  four entries are **RL, RR, FL, FR** (the universal wheel order) — keep that order through the UI's
  tyre graphic. `tyres_damage[4]` (puncture/damage %) and `tyre_blisters[4]` are separate from wear.
- **The rest of Car Damage is captured too** (iteration 1a): `brakes_damage[4]` (RL,RR,FL,FR), the
  three wings, `floor`/`diffuser`/`sidepod`, `gearbox`/`engine`, the six `engine_*_wear` fields, and
  the `drs_fault`/`ers_fault`/`engine_blown`/`engine_seized` flags — for the future car-body graphic
  and a damage table. Field names are **identical across 2025 and 2026**, so the normalizer reads
  either without branching. Split by consumer: per-wheel tyre fields → `LapTyreContext`; everything
  else → the `CarDamage` value object.
- **Temperatures come from Car Telemetry (6), snapshotted at the lap boundary (iteration 2c):**
  `tyres_surface_temperature[4]` and `tyres_inner_temperature[4]` (= carcass/core, the primary
  readout) land on `LapTyreContext`; `brakes_temperature[4]` (a `uint16`) and `engine_temperature`
  land on `CarDamage`. All °C, wheel order **RL, RR, FL, FR**. The assembler carries the latest Car
  Telemetry entry forward (like Car Status) and reads it in `normalize_tyre_context` /
  `normalize_car_damage` at the line. **Older laps need a re-ingest** to populate them (they load as
  zeros otherwise): the two new `laps` columns (`tyre_surface_temp`, `tyre_carcass_temp`) are
  additive-nullable and brake/engine temps ride inside the existing `damage` JSON blob, so pre-2c
  rows load with defaults.
- **Setup comes from Car Setups (5), and is a *history* not a snapshot.** The packet streams the
  player's setup continuously; a mid-session garage change shows up as a value diff. The assembler
  diffs it (frozen-dataclass `==`) and records a `SetupSnapshot(from_lap, setup)` on change, so the
  lap detail can resolve the setup active for a given lap (latest `from_lap <= lap_number`). Restricted
  telemetry doesn't bite here — the own car's setup is always fully public.
- **Per-lap fuel comes from Car Status (7) `fuel_in_tank`, NOT from Car Setups.**
  `CarSetupData.fuel_load` is the static **garage slider** (a race default of ~5 kg, a practice preset
  of ~20 kg, whatever quali was dialled to) — it never reflects consumption, so it must not be shown as
  live fuel. The real value is `fuel_in_tank` (kg; `float` in both formats), a **continuous per-frame**
  Car Status field already carried forward for ERS. It's captured as a per-lap scalar `Lap.fuel_in_tank`
  = the **first finite fuel reading of the lap's selected timed run**, i.e. fuel at the racing S/F line
  as the lap begins, falling lap by lap. Anchoring to the timed run (rather than a raw lap-boundary
  snapshot) reuses the run trimming that already discards the formation lap, out-laps and in-laps, so
  race **lap 1** shows post-formation start fuel and qualifying shows the flying lap's start fuel. It
  rides as a lap-start scalar on the in-memory `Sample` — **not** a trace channel, so `build_trace` /
  the Parquet format are unchanged. Stored in an additive-nullable `laps.fuel_in_tank` column; **older
  laps need a re-ingest** (they load as `None` → shown as `—`). `Setup.fuel_load` is retained on the
  model but no longer surfaced in the setup table; per-lap fuel is shown next to the Car Status /
  tyre-age header instead.
- **G-force + track position (iteration 2b, implemented)** live in Motion (0):
  `g_force_lateral/longitudinal` plus `world_position_x` / `world_position_z` (F1's ground plane is
  X/Z; Y is *up*, unused). **World position is `float` in both formats, but g-force is the one
  format-divergent motion channel** — `int16` in 2026 (÷1000.0 to get g), already `float` in 2025 —
  so `normalizer.motion_sample` branches on `packet_format` (the single place this difference
  lives). The assembler carries the player's latest Motion entry forward into each sample (like
  ERS), **not** a hard frame-join, so a stream without Motion still builds laps — its four optional
  `LapTrace` channels (`pos_x`, `pos_z`, `g_lat`, `g_long`) are simply None. `read_trace` tolerates
  pre-2b nine-column Parquet files, so old laps load (motion None) with no re-ingest. Powers the
  g-force `TracePlot` row and the `TrackMap` panel.
- **Motion world frame is left-handed** (X right, Y up, Z forward). A raw top-down `(pos_x, pos_z)`
  plot therefore comes out **mirrored** — the lap runs the wrong way round (CW vs CCW). `TrackMap`
  negates one axis (Z) to restore true handedness. Absolute rotation follows the game's world frame,
  not the F1.com broadcast art (matching that needs a per-track constant we deliberately don't ship).
  Also: a race **lap 1** starts at the grid slot (past the S/F line), so its trace misses the
  line→grid piece of the main straight; `TrackMap` closes the path loop to fill that gap generally.
- **Sector-boundary DISTANCES come from the Session packet** (not from lap timing). Session History
  stores sector *times* (`sector{1,2,3}_time_*`), but the **Session packet** carries the boundary
  *distances* directly — `sector_2_lap_distance_start` / `sector_3_lap_distance_start` (absolute
  metres) — plus `track_length`. These are now persisted on the session row (`track_length_m`,
  `sector2_start_m`, `sector3_start_m`; additive migration, `None` for pre-feature rows) and drive the
  track-map sector colouring and the traces' dashed sector-boundary markers (always-visible sector
  labels on the map were tried and removed — poor readability on complex layouts).
  Sector 1 is `0..sector2_start_m`. **No per-frame channel was needed:** Lap Data's per-frame `sector`
  field (`0/1/2`) stays parsed-but-unused — the earlier plan to capture it as a trace channel is moot.
  A re-ingest populates the values for older captures.

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