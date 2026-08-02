# f1telemetry

A desktop app that captures **F1 25 / F1 26** UDP telemetry, analyses your laps, and tracks
league / multiplayer results and standings for a private racing league.

> An unofficial fan-made tool — not affiliated with or endorsed by Formula 1, the FIA, EA or
> Codemasters. See [`NOTICE.md`](NOTICE.md).

It records the game's telemetry stream to a portable capture file, reads sessions, laps and
results out of it, and presents them as season standings, weekend results and per-lap telemetry
analysis (traces, track map, car status). Built for a small private league; league members run
the same build so their captures can be shared back.

## For users

Download the latest Windows build from the **[Releases](../../releases)** page, unzip it, and run
`f1telemetry.exe` — no Python or other installs needed. The zip also contains `USER_GUIDE.pdf`
next to the exe.

**[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** covers installing, the one-time in-game telemetry and
firewall setup, recording, sharing captures, rostering, and where your data lives. The same notes
are in the app under **Help**.

The build is unsigned, so SmartScreen shows "Windows protected your PC" → **More info → Run
anyway**.

Results and telemetry are a best-effort reading of the game's UDP stream and can be incomplete —
they are not official results. Captures can contain other players' online names, so share them only
with people who expect it. Details in [`NOTICE.md`](NOTICE.md).

## For developers

Python 3.11+, PySide6 + PyQtGraph, SQLite via SQLAlchemy 2.0, `ctypes` wire structs.

The git repository root is this `f1telemetry/` directory, **not** the workspace directory above
it — that parent holds untracked captures, rosters and dev scratch. Imports are absolute
(`f1telemetry.src.*`), so **run everything from that parent directory**, not from here:

```bash
pip install -e "f1telemetry[package]"                 # setup
python3 -m f1telemetry.src.ui.app                     # the app
python3 -m unittest discover -s f1telemetry/test -t . # the whole suite (plain unittest, not pytest)
python3 -m f1telemetry.test.test_paths                # one suite
```

### Where to look

| File | What it holds |
|---|---|
| [`Claude.md`](Claude.md) | The short always-loaded context: how we work, the tech stack, and the **core invariants** that have each caused a real bug |
| [`docs/PRIORITIES.md`](docs/PRIORITIES.md) | **What to work on next** — confirmed P1/P2/P3, the cycle plan, what's done, what needs verifying |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | The catalogue of planned work and deferred ideas, with reasoning |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The layered pipeline and each layer's responsibility |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | *Why* the design is the way it is — read before overturning a big call |
| [`docs/TELEMETRY_NOTES.md`](docs/TELEMETRY_NOTES.md) | F1-UDP spec facts and quirks — read before touching the parser, normalizer or assembler |
| [`docs/PACKAGING.md`](docs/PACKAGING.md) | The build + release pipeline, and the Windows clean-machine checklist |

The single organising idea: the **2025-vs-2026 format difference lives only at the bottom** (wire
structs + parser, dispatched on `(packet_format, packet_id)`). Everything from the normalizer up
is version-agnostic.

### Releases

`main` is protected and takes PRs from `staging` only. Small branches merge into `staging`; one
labelled (`major`/`minor`/`patch`) `staging` → `main` PR cuts a release — labelling bumps the
version, merging tags and publishes. Every change adds a bullet under `## Unreleased` in
[`CHANGELOG.md`](CHANGELOG.md). Details in `docs/PACKAGING.md`.

## Licence

**Source-available, not open source.** The code is published to be read, studied and audited — not
reused. You may download and run the official release builds, and build from source for your own
private use; redistribution, modified builds, and reuse in other projects need permission first.
Full terms in [`LICENSE`](LICENSE); permission can be granted individually, so just ask.

Third-party components (Qt/PySide6 under **LGPL v3**, NumPy, Apache Arrow, SQLAlchemy, PyQtGraph,
zstandard, and the MIT-licensed flag icons) keep their own licences — see [`NOTICE.md`](NOTICE.md).

Not accepting unsolicited contributions — see [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md).
