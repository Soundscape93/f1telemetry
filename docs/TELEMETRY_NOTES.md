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
- **Final Classification (id 8, sent repeatedly at session end)** is the source of truth for
  results and points. **Session History (id 11)** gives per-lap times and sectors — timing comes
  from here, not from live Lap Data. (Sector field name is `sector1_time_ms_part` — no "in".)
- **The game sends Final Classification several times per session, not once.** Measured
  2026-08-01 on `captures/20260729_200443.f1cap.zst` (a full league weekend, 105 min): **22 FC
  packets across 4 sessions** — Q1=6, Q2=5, Q3=6, Race=5. This corrects a long-standing note here
  and in DECISIONS that said "sent once at race end", and the correction is load-bearing: with
  5–6 copies, ordinary ~0.3 % packet loss essentially **cannot** lose the classification. Losing
  it means losing the whole results-screen window, which in practice only a multi-minute recorder
  stall does (see ROADMAP → *Windows recorder stalls*, fixed in v0.4.2). *Not yet measured:* the
  **temporal spread** of the copies — whether they arrive as a burst or spaced across the results
  screen. Only the counts were taken, so don't assert a spacing anywhere until someone measures it.
- **Missing Final Classification → reconstructed result.** A recording stopped well before the
  results screen (or a long recorder stall over it) can miss every copy, which used to leave the
  results table empty (0 drivers). This is **rarer than the old "sent once" note implied**. When
  it's absent, the assembler synthesizes a best-effort
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
- **`driver_id == 255` means a human** (no AI driver id). AI `driver_id`s map via `DRIVER_NAMES`,
  which is **complete** as of 2026-08-02 — every id from both UDP spec PDFs (F1 25 v3 and the
  2026 season pack) is in `protocol/reference.py`. An unresolved id now means a value newer than
  the specs we have, not a gap to fill; `_name()` yields a readable placeholder either way. Use
  `diagnose_participants.py` to see whether any ids still fail to resolve.
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

## A red flag skips a lap number — the gap is correct
A red-flagged race leaves a **one-lap hole in the lap numbering**, and it is not a capture bug.
Confirmed in-game (2026-08-03) and the same for every player, because it is how the game runs a
restart rather than anything about the telemetry:

1. the race is red-flagged during lap *n* — that lap ends slow, since the game takes over control;
2. the *race strategy* window appears, and the player presses restart;
3. racing resumes on lap ***n+2***.

Lap *n+1* is never driven. In real F1 that lap is the trip from the pit lane back to the starting
grid; the game skips it and restarts directly from the grid box, so no lap row is ever produced for
it. A capture of such a race therefore shows e.g. laps 1–11 then 13–20, with 12 simply absent.

**Why this is worth writing down:** that symptom looks exactly like the "missing middle laps" bug
(PRIORITIES → A3), which was real but had a completely different cause — the Windows machine
sleeping mid-session, fixed in v0.4.2. Tell them apart by the **size and shape** of the gap: a
single missing lap number bracketed by a slow lap is a red-flag restart and is expected; a run of
several consecutive laps missing, usually with the Final Classification gone too, is lost telemetry.
Only the second one is a bug.

## `tyre_age_laps` is unreliable at the lap boundary — split stints on wear

*Found 2026-08-24 while specifying the E1 tyre-life chart.*

`LapTyreContext.age_laps` comes from Car Status snapshotted as the car crosses the line, and the
snapshot straddles the game's own increment. Inside a **single** stint the stored sequence looks
like this (session `11708585…`, laps 1-9, one set of mediums):

    lap 1 age 0 | lap 2 age 2 | lap 3 age 2 | lap 4 age 4 | lap 5 age 4 | lap 6 age 5 …

Age both jumps by 2 and repeats. **Do not derive stint boundaries from it.** A rule of
"new stint when age does not increment by exactly 1" turns that 27-lap race into **fourteen**
stints.

**Use cumulative wear instead.** `LapRow.tyre_wear` is monotonically non-decreasing within a stint
and resets to ~0 on a new set, so a *drop* in wear (or a compound change) is the reliable boundary.
That rule gives the correct 3 stints for `14435457…` and matches the classification's own
`tyre_stints`.

Two related traps in the same data:

- **Pit laps leave single-lap artefact stints.** In `11708585…` laps 19-20 are absent and lap 21
  reports the *old* compound at 49.8% wear — a stale in-lap reading — before lap 22 starts the
  fresh set. Any stint rule will emit a 1-lap stint there. The E1 chart's "minimum 2 laps per
  stint" rule drops it without a special case.
- **Lap numbers are not contiguous.** Plot against lap number, never list index (see also the
  red-flag note above).

Coverage is good: **406 of 406** stored laps carry `tyre_wear`, `tyre_age_laps` and
`tyre_visual_compound`.

## What `driver_status` actually reports, and what it does not

*Measured 2026-08-27 across every capture in this database (33 files, 484 emitted laps) while
implementing E17. The scan replayed each capture through the assembler's own run-splitting, so what
is described here is what the assembler sees, not what the spec promises.*

**The lap counter only advances at the end of a *timed* lap.** Crossing the line on an in-lap, in
the pit lane, or on an out-lap does not increment `current_lap_num`. So in practice and qualifying a
single lap number covers the whole sequence between two timed laps:

    lap 3 | FLYING  100.2 s  -> IN_LAP   (pit entry at 5638 m, line crossed in the pit lane)
    lap 3 | IN_GARAGE 206 s  -> OUT_LAP  (garage at d=228 m, out-lap from d=267 m)
    lap 3 | FLYING   93.1 s            <- this is Session History lap 3 (93.219)

Three consequences, all load-bearing:

- **A garage visit is always *before* the timed run of the lap that follows it.** Across all 484
  emitted laps: 69 have garage frames ahead of the selected run, **none** inside it and **none**
  after it. Checked separately: no garage sits in a buffer that was never emitted while a later lap
  was — the only non-emitted garage buffers are trailing ones (the driver parked at the end).
  This is what `Lap.preceded_by_garage` reads, and it is why the flag is computed at the boundary
  rather than stored as a raw per-lap status.
- **The lap on which a driver returns to the pits is never timed in practice or qualifying**, so it
  is never stored. Every one of the 159 emitted non-race laps here reads `FLYING` end to end — no
  in-laps, no out-laps, no garage frames inside the lap. Any rule that labels a stored practice lap
  an in-lap or an out-lap is inventing it.
- **A race never reports `IN_GARAGE`.** The game says `pit_status = IN_PIT_AREA` for a pit stop and
  keeps `IN_GARAGE` for the garage proper. So the garage flag is an *additional* run boundary beside
  wear / age / compound, never a replacement for them.

**`driver_status == IN_LAP` is not "the lap you pitted on".** The game sets it when the *planned*
in-lap comes up and leaves it set while the driver stays out. Melbourne `14435457…` reads `IN_LAP`
for the whole of laps 19, 20 **and** 21, and the stop is on 21; Suzuka `267662079…` reads it for its
last six laps and never pits again. Use `pit_lane_timer_active` instead — active on the lap's last
frames means the pit lane was entered, active on its first frames means it was left.

**`pit_status == IN_PIT_AREA` marks the lap that carries the stop, and which lap that is depends on
the circuit.** Where the pit box sits before the timing line (Melbourne, Sakhir) the stationary time
lands on the **in**-lap: `14435457…` lap 3 runs 119.594 s and lap 4 runs 87.341 s. Where it sits
after (Suzuka, Shanghai) it lands on the out-lap. Both laps are excluded from a run's average pace
for that reason.

**A red-flag restart reads as `OUT_LAP` and is not one.** Shanghai sprint `12316788…` lap 4 and
Shanghai race `10247048…` lap 13 are 94 % and 95 % `OUT_LAP` with the pit-lane timer never active,
and the first rule written for E17 believed them — "lane timer at the lap's start **or** `OUT_LAP`
for most of the lap". That was wrong, and this document already said why two sections up (*A red
flag skips a lap number*): the game does not time the trip from the pit lane back to the grid, so
the status is left over from a lap that was never emitted, and the lap it lands on is a **standing
start from the grid box**. Confirmed in-game 2026-08-30.

The corrected rule is one signal: **out-lap is the pit-lane timer running as the lap began, and
nothing else**. Scanned over all 470 emitted laps in this database (2026-08-30), the timer flags 15
laps and every one of them also carries a pit stop; `driver_status` flags those same 15 plus exactly
the two restarts above, and flags nothing the timer misses. The restart is read instead from the lap
*before* it — `red_flagged` on the previous emitted lap — and classified as a standing start
(`ui/sessions/lap_context.py` → `_restart_laps`). Only for a session that starts on the grid: a
practice or qualifying restart really is a pit-lane exit, and the timer catches it.

**Under a red flag the game reports the tyres as good as new.** On the lap the flag falls, wear is
read while the car is being reset in the pit lane and comes back near zero — Shanghai race lap 11
reads 1.28 % after lap 10 read 54.65 %, Shanghai sprint lap 2 reads 2.32 % after lap 1 read 6.75 %.
No set was fitted: `tyre_age_laps` counts straight through both (9 → 10 and 0 → 1), the compound is
unchanged, and the wear picks up where it left off on the restart lap (5.22 % and 6.79 %). Believing
it opens a stint in the middle of a run, and the laps stranded in front of it then vanish to the
minimum-laps filter — which is exactly what the Shanghai sprint's chart did, losing lap 1 entirely
and putting every remaining lap one place early on the stint axis. So the *wear* boundary alone is
suppressed on a red-flagged lap; age and compound keep their say, and when Shanghai race really did
change mediums for hards during its stoppage that boundary still stands.

## Safety car and red flag come from the Session packet, not from Event packets

*Measured 2026-08-27, same scan.* Both are already on a packet the assembler routes, so per-lap
attribution needs no Event ingest (which is PRIORITIES → E15, and unrelated).

- **Safety car** is `PacketSessionData.safety_car_status`, per frame. Three real deployments exist in
  this database: `2114813…` (sprint) laps 19-22, `10247048…` laps 11-13, `6912670…` laps 23-26.
  Attribution is "the state seen while this lap number was current", which is exact for a race — one
  lap-distance pass per lap number.
- **The `SCAR` Event packet is worse for this**, which is worth recording because it looks like the
  obvious source. 59 of them exist and most are noise: `sc_status = 0, event_type = 3` ("Resume
  Race") fired in practice and qualifying, plus a formation-lap pair at every race start. In
  `10247048…` the deploy and resume events are 4 seconds apart while the Session field correctly
  spans three laps.
- **`FORMATION_LAP` is reported on lap 1 of every race here**, so it is stored honestly and then
  ignored by the classification — it is not a safety car, and the standing-start rule already
  accounts for that lap.
- **Red flag** is a *rise* in `num_red_flag_periods`. Only a rise: the counter is not monotonic —
  the Shanghai sprint's went 0 → 1 during lap 2 and back to 0 at lap 10 — so reading the value
  itself would flag every lap of the restart and then stop. **Thin evidence, stated as such:** this
  database holds exactly two red flags (`12316788…` lap 2, `10247048…` lap 11) and both land on the
  right lap. Revisit if a third behaves differently.

Both fields are named identically in the 2025 and 2026 wire structs, as are `driver_status`,
`pit_status` and `pit_lane_timer_active`, so none of this is format-branched.

## What the `weather` field reports, and the settling window at session start

*Measured 2026-08-31 across all 33 captures — 73 sessions, 148,778 Session packets.* This is what
E14 (mixed dry/wet) is built on, and it is the Session packet's own `weather`, not
`weatherForecastSamples` (rejected — PRIORITIES → E14 gives the three reasons).

- **18 of 73 sessions report more than one condition; 6 report both a dry and a wet one.** One of
  those six is the artifact below, so **five sessions genuinely ran dry and wet**: three Melbourne
  Q2 restarts (`20260704_181644`, LIGHT_RAIN → OVERCAST), Shanghai P1 (`20260705_132157`, twenty
  minutes of rain mid-session), Suzuka P1 (`20260718_212648`, rain in the last 59 seconds).
- **No frame-to-frame flicker.** 100 contiguous runs across the 73 sessions, and the only runs of
  ≤ 2 packets are five *whole sessions* that contain just 1-2 Session packets. Every real change is
  a step that holds. `weather` does **not** behave the way `driver_status` does.
- **But the first 3-5 packets of a session are a placeholder.** 8 of 73 sessions open with a run
  that differs from everything after it and is always settled by **session_time 2.0 s**. In 3 of
  the 8 those packets carry `num_weather_forecast_samples == 0` — the weather block is not
  populated yet. It is not the previous session's condition carried over: `…629038` follows a
  session that ended LIGHT_RAIN and its placeholder reads CLEAR.
- **It costs exactly one false mixed.** Melbourne Q1 `…629038` reads CLEAR for 1.5 s and then
  LIGHT_RAIN for the remaining 1,079 s. Under "any two distinct values" that session is mixed.
- **The dwell must be measured in session-time seconds, never in packets.** The game fast-forwards
  the session clock while the player sits in the garage, so a *genuine* 38-second wet stretch
  (`…166502`) arrives as **four packets** — the same length as the placeholder run. A `≥ N packets`
  rule cannot separate them. In seconds they separate enormously: the placeholder is gone by 2.0 s,
  the shortest real stretch is 26.4 s. Hence `_WEATHER_SETTLE_S = 3.0` in `session/assembler.py`.
- **No value outside the 0-5 enum, ever** — 148,778 packets. Observed: CLEAR 91,429 · LIGHT_CLOUD
  24,229 · OVERCAST 25,874 · LIGHT_RAIN 3,289 · STORM 3,957. **HEAVY_RAIN (4) has never occurred**
  in any capture here, so nothing about it is measured — only inferred from the appendix.
- Packets arrive at **2 Hz**, and `session_time` restarts at 0 for each session. A capture that
  starts mid-session simply begins past the window and loses nothing.

Applied to this database, a re-ingest gives **12 of 56 stored sessions** a multi-condition set, of
which **3 read as mixed** (`…166502`, `…393137`, `…098367`); the other two real ones are among the
16 tombstones. A session split across two captures takes the set of whichever is ingested last —
`save()` replaces by uid, which is pre-existing for every field, and `…398583` is that case here.

## The pit out-lap carries the whole pit loss (+14 to +37 s)

*Measured 2026-08-24 across every 50%-distance race in the database.* The game does not split pit
time across the in-lap and out-lap: the **first lap of each post-pit stint** absorbs it.

    comp 18  laps 3-20   stintlap1 119.594s   median-rest 82.737s   delta +36.857s
    comp 18  laps 14-29  stintlap1 112.245s   median-rest 91.487s   delta +20.758s
    comp 17  laps 22-29  stintlap1 107.636s   median-rest 88.814s   delta +18.822s

This matters for any per-stint pace chart: the interesting degradation signal is **1-3 s**, so an
auto-scaled y-axis that includes out-laps compresses it to near-invisibility — badly so on a
stint-relative axis, where every out-lap lands on the same x position. Derive the range from the
representative laps and let out-laps clip (DECISIONS → UI).

**The race start is not the same case.** Stint 1 lap 1 runs only +2 to +3 s over its stint median,
and is sometimes *faster* (low fuel, fresh tyres, no pit loss) — so it needs no exclusion.

## Event packets — what the codes are worth, measured across all 33 captures

*Found 2026-08-24 (unparsed); measured 2026-08-31 across all 33 captures — 13,167,492 packets,
**134,208 EVENT packets**, 73 sessions with a Session packet plus 28 uid-0 pseudo-sessions.*
This is what PRIORITIES → **E15** is built on. The recorder appends *every* datagram unfiltered, so
all of this is already on disk in every capture ever made: **a re-ingest recovers it retroactively,
with no re-recording**.

For one capture (`20260705_132157.f1cap.gz`, 905 699 packets), by packet id:

    0 MOTION 102238 · 1 SESSION 10238 · 2 LAP_DATA 102266 · 3 EVENT 9629 · 4 PARTICIPANTS 1030
    5 CAR_SETUPS 10240 · 6 CAR_TELEMETRY 102251 · 7 CAR_STATUS 102233 · 8 FINAL_CLASS 22
    10 CAR_DAMAGE 51125 · 11 SESSION_HISTORY 102549 · 12 TYRE_SETS 102267 · 13 MOTION_EX 102252
    15 LAP_POSITIONS 5110 · 16 CAR_TELEMETRY_2 102249

### The event-code spread, all 33 captures

    BUTN 106126 (79.1%) · OVTK 14635 (10.9%) · SPTP 12372 (9.2%) · COLL 272 · FTLP 206
    PENA 202 · STLG 95 · SCAR 78 · SEND 64 · SSTA 62 · LGOT 29 · RTMT 29 · TMPT 16
    CHQF 12 · DRSE 4 · RCWN 3 · RDFL 2 · DRSD 1

Per session, by type — **Race** BUTN 2660 · OVTK 366 · SPTP 325 · COLL 12.5 · PENA 3.5;
**Qualifying** OVTK 125 · SPTP 56; **Practice** SPTP 209 · OVTK 161.

**Six codes are not in the `EventDataDetails` union, and none is a gap:** `SSTA SEND LGOT CHQF
RDFL DRSE` are marker codes carrying no detail payload — `event_string_code` is the whole event.

**One real format difference:** the **2025 `Collision` struct has no `severity` field**; 2026's
does. 25 of the 272 collisions lack it. Any collision model has to make that field optional.

**`FLBK` has never occurred** in any of the 33 captures — flashback is disabled on the recording
machine. Nothing about flashback behaviour is measured here, only inferred. Overtake rows carry
`frame_identifier`, and a flashback rewinds it, so a future rule has its discriminator without a
schema change.

**Free cross-check for E17:** `RDFL` fires in exactly the two sessions where `num_red_flag_periods`
rises, and nowhere else. The Session-packet red-flag rule is independently confirmed.

### `OVTK` is a position-swap feed, not a count of overtakes

Five separate measurements, and the aggregate that looked obvious is wrong by 4.5×:

- **It is field-wide, not player-centric.** 6.9% of events involve the player at all (767 passes
  made, 238 suffered); 93.1% are AI-on-AI.
- **The indices are clean** — 0 suspect rows in 14,635. Range 0-21, always `< num_active_cars`,
  never self-referential. This is the one part that needs no defending.
- **35% of events are not overtakes.** In 5,112 the *overtaken* car is in the pit lane; in 2,827
  its `driver_status` is `IN_GARAGE`. The game fires `OVTK` for driving past a parked car. Half of
  all `OVTK` are in practice/qualifying, where the concept is meaningless.
- **Pass-and-re-pass is rampant, and a track-gap guard provably cannot filter it.** After keeping
  only events where both cars are racing, 21.7% are reversed by the same pair within 5 s (12.2%
  within 2 s); one pair swapped 41 times in a single race. But the gap between the two cars at the
  event frame is **< 0.5 m in ~90% of reversed *and* non-reversed events alike** (medians 0.00 m
  and 0.10 m) — the game fires `OVTK` on the frame the two `lap_distance` values cross, so the gap
  is ~0 *by construction*. A 5 m threshold keeps 4.2% of events and discards real passes
  indiscriminately. This is E14's minimum-packet-count in a new costume.
- **Against ground truth it is 4.5× high.** `LAP_POSITIONS` (id 15, already registered) gives each
  car's position at every lap start; its lap-over-lap changes total **1,640 across 17 races**.
  Raw `OVTK` 7,310 (4.5×); both-cars-racing 4,244 (2.6×); plus a "+30 s still ahead" forward test
  2,765 (1.7×).

**And no cancel window fixes it.** Cancelling each pass the same pair reverses within *W* seconds:

| W | counted | truth | ratio | median per-race ratio |
|---|---|---|---|---|
| 0 s | 4244 | 1640 | 2.59× | 2.34 |
| 10 s | 2158 | 1640 | 1.32× | 1.28 |
| **30 s** | **1634** | **1640** | **1.00×** | 0.91 |
| 60 s | 1528 | 1640 | 0.93× | 0.84 |

W = 30 s matches *in total* — and that is two error populations averaging out, not a fit. **Per
race it ranges 0.61× to 1.91×.** No window is per-session accurate, so none is used.

**The only rule the evidence supports** is therefore the narrow one: *neither car in the pit lane
(`pit_status` or `pit_lane_timer_active`), neither in the garage (`driver_status` outside
`{FLYING_LAP, ON_TRACK}`)*. It drops 58% of raw events and every parked-car pass, needs only the
current Lap Data frame, and freezes nothing else. Everything past it stays derived.

### `PENA` measures something different from `num_penalties` — and 37% of it arrives on uid 0

**The counts do not match, and the reason is the type mix.** Of 127 live `PENA` events: **69
Warnings, 28 lap-invalidations, 19 Retirements**, and only 3 Time penalties, 7 Grid, 1 Drive-through.
The classification's `num_penalties` counts *sporting* penalties only — restricting to
`penalty_type ∈ {0,1,2,4,6}` takes the per-car match from 5 cars to 8 of 9.

- **`lap_num` is exact**: 126 of 127 equal that car's `current_lap_num` at the event frame. It lines
  up with the stored lap rows with no adjustment.
- **255 is the not-applicable sentinel** — on `time` (124/127), `places_gained` (47) and
  `other_vehicle_idx` (79).
- **`PENA` is field-wide too** — 44.9% are the player's. Joined to the classification by
  `vehicle_index`, all **129** stored rows resolve to a named driver (the 7 reconstructed
  classifications included): **54 on an AI car, 75 on a human**, 59 of those the player's. Measured
  2026-09-01 for the Race control box, which shows the field rather than the player: a non-AI filter
  is **identical to player-only in 35 of the 42 penalised sessions** — 34 have a single human in the
  field — and **empties four boxes** that hold 8, 6, 3 and 1 penalties. Box sizes are small either
  way: 11 rows at the worst, a median of 1, and 28 of 42 boxes name a single driver.
- **`other_vehicle_index` is all-or-nothing per infringement, and clean where it is set.** It
  appears on 44 of 44 Small Collisions, 1 of 1 Big Collision and 3 of 3 Blocking rows and on **none**
  of the 81 rows of any other kind; all 48 resolve to a classification entry and none names the car
  the penalty belongs to. So the Race control box names the second car straight off the field, with
  no infringement test — the 255 sentinel already decides it.
- **Grid penalties are issued one at a time, and only in qualifying here.** All 7 fall in Q1/Q2,
  none in a race, and two cars in `972807263…` each took **two** 5-place penalties for a 10-place
  drop that `num_penalties` records only as "2". Places live on the event rows and are summed for
  display; the classification's aggregate cannot reproduce them.
- **Race numbers do not identify a car, and a name need not either.** Four league sessions here run
  two cars wearing #11 (an AI Perez and a human Fabibyte), so the number cannot disambiguate; and in
  four more, every human in the lobby reads `Player` because their online names are private. `is_ai`
  is unaffected by both — it comes off the Participants packet — which is why the Race control box
  marks humans by weight rather than trusting the name.
- **`DTSV` / `SGSV` never fire** in any of the 33 captures, so there is no issued-then-served
  double count to defend against.

**The trap — core invariant #3 does not hold for Event packets.** 75 of the 202 `PENA` events
arrive with `header.session_uid == 0`, which `SessionAssembler.process` drops as init noise. They
are not init noise: **at the end of a session the game re-broadcasts the whole accumulated penalty
log with a zeroed header** — `frame_identifier == 0`, `session_time` pinned at the session end, the
preceding packet id 8 (`FINAL_CLASSIFICATION`) in 74 of 104 cases — and it repeats, one 11-row log
arriving 64 times over. So routing `EVENT` through the existing dispatch **silently loses 37% of all
penalties**, and ingesting uid 0 naively **multiplies them by up to 7×**.

Attribution is free: `prev_uid == next_uid` in 104/104, so the surrounding packets name the session.

**The merge rule that reproduces the game's own figures** — keep live rows keyed by
`frame_identifier`; from the uid-0 replay add a detail-key only where the replay's distinct count
exceeds the live count:

> **9 of 9 cars match `num_penalties` exactly, and `penalties_time_s` matches on every time
> penalty (3, 5, 3, 3 s).**

Neither half alone gets there. Live-only misses a 3 s time penalty in `20260704_214647`; a naive
detail-tuple dedupe collapses two genuinely distinct grid penalties for car 13 in
`20260812_202452` — which the game itself records as `num_penalties = 2`. Total across all 73
sessions: **129 penalty rows**.

*(The `PENA 79` in this file's earlier single-capture snapshot was 11 live events plus 68 copies
from that replay — the number was right and its meaning was not.)*

### The session-start burst

247 `OVTK` (1.7%) land before `session_time` 1.0 s, in only 3 of 73 sessions, but they arrive in
bursts — one frame carrying **70 events** at t = 0.000 (`20260729_200443`). That is the game
resolving grid order, not racing, and the racing filter above does *not* catch it (every car reads
`ON_TRACK`). `SSTA` (96.7% < 3 s), `STLG`, `LGOT` and `SCAR` legitimately live in that window —
they *are* session-start events. `PENA` is essentially unaffected: 2 events < 3 s.

### Codes deliberately not ingested

`BUTN` (79%, controller input, no conceivable consumer) · `SPTP` (9.2%, already on
`LapData.speed_trap_fastest_speed` per car) · `FTLP` (a running best-so-far feed; the answer is
already `best_lap_time_ms`) · `RTMT` (`result_reason` is already on every classification entry) ·
`COLL` (no designed consumer; the 45 that mattered are already `PENA` rows as Small/Big Collision
infringements) · the marker codes (session and race-control facts E17 already reads off the Session
packet). See DECISIONS → Storage for the reasoning.

Also unparsed and worth knowing about: **`TYRE_SETS` (id 12)**, ~102k packets per capture, which
carries per-set wear and remaining life directly. The E1 tyre-life chart does not need it (per-lap
`tyre_wear` is enough), but it is the better source if that chart ever grows.

## Track / air temperature and time of day: the opening packets are zeroed

*Measured 2026-08-31 across all 33 captures, for the two new details-grid cells (E15).*

`track_temperature`, `air_temperature` and `time_of_day` are **top-level Session fields** — live
observations, not forecast — and none of them reached the domain layer before E15.

- **All three go blank together, in exactly the same 20 packets, across the same 4 sessions.** The
  whole payload is zeroed for the first 3-4 Session packets of a session; the fields do not settle
  independently. Observed: `[0, 0, 0, 0, 24, 24]` for track temp, `[0, 0, 0, 0, 960, 960]` for
  time of day, in the same packets.
- **Unlike E14's weather this is a packet-count artifact, not a temporal one** — three of the four
  sessions clear it while `session_time` is still `0.0`. The `_WEATHER_SETTLE_S = 3.0` guard still
  works (a settled value in **73/73** sessions), so it is reused rather than a second constant
  invented for the same artifact; but the mechanism is a zeroed payload, not a value being
  corrected.
- **`0` is a legitimate `time_of_day`** (midnight) and never a legitimate track temperature. The two
  zero together, so the temperature is the honest discriminator if one is ever needed.
- **`time_of_day` is a real clock**: valid `0..1439` minutes-since-midnight in 73/73 sessions,
  advancing in 68/73, readings such as 11:00, 15:00, 20:00. **`header.session_time` is not** — it is
  elapsed session seconds, and is what the E14 settle window measures.
- **Track temp is stable within a session**: median spread 1 °C, constant in 22/73; max spread 42 °C
  (a session that opened on the zeroed placeholder).
- **11 of 73 sessions have no Session packet before `session_time` 3.0 s** — the recording joined
  mid-session. For those, "at session start" is really "the earliest reading captured". The same is
  already true of `weather_seen`.

**`rain_percentage` was weighed and rejected for the Conditions row.** It exists only inside
`weatherForecastSamples`, and availability is not the problem — only 20 of 148,778 Session packets
carry an empty array, every session has a `time_offset == 0` sample within 3 s, and it survives to
session end in 73/73. The objection is semantic: it is a **probability of rain**, and it would render
beside `Conditions`, which is an **observed condition**. `20260704_181644 QUALIFYING_1` reads 83%;
next to a heavy-rain icon that invites "83% of what?", and next to a clear icon it reads as a
contradiction. `ui/components/weather.py` already records why the observed field beats that array.

## Game mode ids: the 2026 career modes are undocumented

*Observed 2026-08-24.* `game_mode 78` is **Driver Career '26** — every "Driver Career with the 2026
cars" recording carries it, confirmed in the database against the session detail view. It is **not
in the UDP specification**; EA has not published the '26 mode ids, and `GAME_MODE_NAMES` stops at
30/75/127, so it currently renders `Unknown game mode (78)`.

- **My Team '26 is still unknown** — no My Team '26 recording exists yet. Capture one, read the
  value, add it.
- **Grand Prix Multiplayer "Championship"** (league racing, also on 2026 cars) reports
  `Online Custom` correctly, so only the *career* mode ids shifted.

Record these as **observed**, not specified — see PRIORITIES → E16.

## Track ids worth remembering
Imola is **27** (in the 2025 calendar); Madrid is **42** (new in 2026, replaces Imola in that
calendar). `official_calendar(year)` encodes the preset order for each.

## Result status / reason — and `result_reason` is meaningless for a finisher

`ResultStatus`: INVALID, INACTIVE, ACTIVE, FINISHED, DID_NOT_FINISH, DISQUALIFIED,
NOT_CLASSIFIED, RETIRED. `ResultReason` adds detail (RETIRED, TERMINAL_DAMAGE, NOT_ENOUGH_LAPS,
BLACK_FLAGGED, RED_FLAGGED, MECHANICAL_FAILURE, …). The UI collapses non-finishers to short tags
(DNF / DSQ / NC / DNS) in `ui/formatting.py`.

**`result_reason` is not usable as a display field, measured 2026-08-31 against `f1league.db`**
(56 sessions, 1,045 classification entries). The game does not clear it when a car finishes:

- The player's row reads `FINISHED` in 55 of 56 sessions, yet `result_reason` says
  **`TERMINAL_DAMAGE` on four of them** — including three qualifying sessions finished P1, P2 and
  P4 — and `INVALID` on sixteen.
- Across every car: 77 `TERMINAL_DAMAGE` against only **18 non-finishing statuses** in total.

So the field is only meaningful when `result_status != FINISHED`, and gated that way it is blank
55 times in 56. It was evaluated as the third cell of the details grid's provenance row for E15 and
**rejected on this evidence** — see DECISIONS → UI.

## Diagnostic tools (read-only, run from the repo root)
Built during the roster-blank investigation; keep them for future data-quality work.
They read through `ingest.archive.open_capture`, so a plain `.f1cap`, a `.f1cap.gz` and a
`.f1cap.zst` all work with no manual decompression. (An older note here said they used plain
`open()` and needed uncompressed input — that was fixed with the codec-dispatch work.)

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