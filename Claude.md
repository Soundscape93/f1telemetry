# F1 Telemetry App — Project Context

Personal Python app to analyze F1 25 / F1 26 lap telemetry (speed, brake, throttle,
steer, gear, RPM, ERS traces) and store league / multiplayer race results.

**Used for:** (1) analyzing own laps across a session by overlaying N laps;
(2) publishing practice/quali/race results to a league WhatsApp channel as a
screenshot or file; (3) later, packaging for friends to analyze their own laps.

## Status
- **Ingest layer: done** (recorder, sources, capture format; verified live + round-trip,
  covered by `test/WellFormedPacketsTest.py`). The recorder consumes a `PacketSource` so the
  socket code lives only in `LiveUDPSource`, refuses to overwrite an existing capture (`xb`
  + up-front check), and the reader validates header version and record length.
- Game emits **format 2025** (confirmed from a real capture); format 2026 also decodes
  correctly off the same header offsets.
- **Next: milestone 2 (protocol layer)**, built for format 2025 first, then mirror 2026.

## Stack & key decisions
- Python 3.10+ (modern syntax: `X | None`, etc.).
- Wire parsing: `ctypes.LittleEndianStructure` with `_pack_ = 1`, mirroring the C
  structs 1:1. Chosen for native unsigned types and packed nested arrays. (Java was
  ruled out for lacking unsigned integer types.)
- Structured storage: SQLite via SQLAlchemy. Keep the schema engine-agnostic so it
  can move to Postgres only if a central, hosted league server is ever built; the
  shipped desktop app stays on SQLite.
- Dense per-lap traces: stored as Parquet/npz files referenced by the lap row, NOT as
  rows in SQLite (~5400 samples per 90 s lap at 60 Hz).
- **All telemetry traces are indexed by lap distance, not time**, so laps overlay
  corner-for-corner regardless of pace.

## Architecture — the version boundary is the core idea
Pipeline: Sources -> Parser (+ registry) -> versioned wire structs (v2025 / v2026)
-> Normalizer -> Session Assembler -> Storage + Analysis -> UI.

The 2025-vs-2026 difference lives ONLY in the parser and the wire structs. From the
Normalizer down, everything operates on version-agnostic domain models and never
branches on format. Format is detected per packet from `m_packetFormat` (header byte 0)
and dispatched on `(packet_format, packet_id)` via a registry dict — it is NOT a
user-facing toggle. Adding a future format = new struct submodule + registry entries;
nothing downstream changes.

## Package layout
Modules live under the `src/` package, so imports and `-m` runs include it — e.g.
`python -m f1telemetry.src.ingest.recorder` and
`from f1telemetry.src.ingest.sources import FileReplaySource`.
```
f1telemetry/
  src/
    ingest/        # DONE: recording.py (.f1cap format), recorder.py, sources.py, inspect.py
    protocol/      # NEXT: header.py, enums.py, v2025/, v2026/, registry.py, parser.py
    domain/        # models.py (dataclasses), normalize.py
    session/       # assembler.py (frame join + lap/session state machine)
    storage/       # db.py, repositories.py, traces.py
    analysis/      # traces.py, ers.py, delta.py
  test/
```

## Milestones
1. Ingest — capture & replay. **DONE.**
2. Protocol — header, enums, MVP structs (2025 first, then mirror 2026), registry,
   parser. Goal: replay prints decoded speed / gear / lap-distance to the console.
3. Domain — models + normalizer. Goal: replay yields completed `Lap` objects + traces.
4. Storage — SQLite schema + repositories + trace store.
5. Analysis — channel extraction, lap delta on a shared distance grid, ERS usage.
6. UI — overlay laps interactively; render a results card for WhatsApp export.

## MVP packet subset (do NOT build all 16 packets x 2 formats up front)
Build only these first: Lap Data (2), Car Telemetry (6), Session (1),
Participants (4), Car Status (7) [ERS], Final Classification (8), Session History (11),
plus Motion (0) for g-force. Defer Car Setups, Car Damage, Tyre Sets, Motion Ex,
Lobby Info, Time Trial, Lap Positions, and Event until a feature needs them.

## Key spec facts
- **The header is identical across 2025 and 2026.** Parse it generically; dispatch on
  `(packet_format, packet_id)`.
- **2025 -> 2026 differences:** car count 22 -> 24 (most per-car array sizes change);
  g-force fields `float` -> `int16` (divide by 1000.0 in 2026); several IDs
  `uint8` -> `uint16`; new Car Telemetry 2 packet (id 16) in 2026; ERS deploy-mode
  value 3 renamed overtake -> boost; engine temperature `uint16` -> `uint8`; the
  Collision event gains a severity byte.
- **Wheel array order is always RL, RR, FL, FR.**
- **Vehicle index is session-scoped only.** Own car = `header.player_car_index`. The
  league roster (alias -> person) is a stage-2 JSON file, not needed for solo analysis.
- **Restricted telemetry:** the own car is always fully public. For other cars,
  ERS / fuel / wear / damage / setups are zeroed unless they opt into "Public".
  Driving channels (speed, throttle, brake, steer, gear, rpm, drs, temps) are always
  visible for every car.
- **Authoritative sources:** Final Classification (id 8, sent once at race end) is the
  source of truth for results and points. Session History (id 11) gives per-lap times
  and sectors.
- **Frame join:** the "rate as specified in menus" packets share
  `header.frame_identifier` and ship together on the same frame; carry forward the
  slower packets (Session 2/s, Car Damage 10/s) into each sample.

## Conventions
- Module-level constants use a SINGLE leading underscore. A double underscore triggers
  name mangling inside class bodies (`__X` becomes `_ClassName__X`) and has already
  caused a `NameError` once. Reserve `__` for class attributes you actually want mangled.
- Type hints throughout.

## .f1cap capture format
Header: magic `b"F1TELCAP"` + uint16 format version. Then records of:
double `recv_time` (unix seconds), uint32 length, then `length` payload bytes.
Length-prefixed to preserve UDP datagram boundaries (the parser decodes one whole
datagram at a time); timestamped so realtime replay reproduces the original timing
and ordering.