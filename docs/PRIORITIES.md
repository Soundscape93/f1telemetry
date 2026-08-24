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
capture-as-interchange design was built for. **Two branches, not three** — see the order note.

- B4 locate a moved capture by content hash — **done 2026-08-03**
- B2 league capture import from a shared folder, carrying B3's one field — **done 2026-08-04**

**Cycle 2 is complete.** Both branches are on `staging` and share the `## Unreleased` section; the
grouped `staging` → `main` release PR (label **`minor`**) is what turns them into a version.
**Cycle 3 is next** — do not start it without re-reading the cycle plan above.

*B2 scope, confirmed 2026-08-03 and delivered:* the shared/manual capture import flow; an
**optional** "Recorded by" text field on the import prompt (blank is fine, no validation); and a
**proper user-facing import action** — the header's `Ingest .f1cap (test)` button retired and
replaced by something presented as the real way to import a capture someone sent you, not as a dev
affordance. Explicitly **not** in scope, and not built: any settings page, profile or identity
feature.

*Order note (revised 2026-08-03):* the listed order was B2 → B3 → B4; it is **reversed** for B4.
Both items need the same primitive — hash a capture on disk without parsing it — and B4 is the
small consumer that puts `archive.hash_capture` in place and proves it on real archives before the
large feature leans on it. B4 also fixes a live foot-gun rather than adding surface: a *moved*
capture was indistinguishable from a *deleted* one, and the only action offered was the one that
forgets it. ROADMAP already said B4 "slots in between `find_missing_captures` and
`prune_missing_captures`", and that split was already in the code.

**B3 is dropped as its own item — decided 2026-08-03.** The column, the domain field and the
`recorded_by` plumbing all exist; nothing sets a value and — the deciding fact — **nothing reads
one**. A settings page and an identity flow to feed a write-only column is speculative work. Its
stated justification was also overstated: only a *re-ingest* can't backfill it, while a *re-import*
sets it (replace-by-hash), so leaving it blank loses nothing irreversibly. It becomes one optional
"Recorded by" text field on B2's import dialog — cheap because that dialog is being built anyway,
and filled at the one moment the admin actually knows the answer. What it buys, precisely: the
shared drive shows who *uploaded*, but that record does not survive the copy-home step the design
mandates, so after import the app is the only place the answer could live. Embedding it in the
`.f1cap` header (format v2) was weighed and **rejected as unwarranted** by anything current: a real
on-disk format change for a field with no consumer.

**Cycle 3 — release-phase process.** Effectively the rest of the C block: Phase 4 packaging
reach, the installer, the real auto-updater, and the remaining build-robustness items. Promoted
above the big UI surfaces deliberately — testers are real, new surfaces are not yet needed.

*Order confirmed 2026-08-05, with one change from the list as first written.* The listed order put
C8 — the largest and riskiest — first. It runs **last** instead, and C6 moves ahead of C7:

- C5 `threading.excepthook` — **done 2026-08-05**
- C6 startup capability self-check — **done 2026-08-05**
- C7 pyqtgraph bloat trim — **done 2026-08-06.** Was sequenced **after C6, not before.** PACKAGING's own risk register gives the
  mitigation for "pyqtgraph/zstandard missed → the app silently ships the fallback" as "explicit
  hidden imports + a startup self-check". C7 edits the spec's `excludes` — the exact operation
  whose failure mode is that silent degrade — so C6 is the instrument that makes C7 verifiable
  rather than hopeful. Reversed, the trim is done blind.
- C4 clean-instance test (Windows Sandbox / second user account) — **done 2026-08-07** against the
  published v0.7.0 zip. Not code: a checklist the author executes, producing doc updates only.
- C8 Phase 4 — see the split below.

**Cycle 3 ships as two releases, not one — decided 2026-08-06.** The remaining items produce two
different kinds of artifact, and the seam is where that changes:

1. **Release 1 — C5 + C6 + C7 + F8 → shipped as v0.7.0 on 2026-08-07.** Then **C4 ran against that
   published build** — validation wants a real downloaded artifact, not a local `dist/` folder.
   **Both complete.**
2. **Release 2 — C8a + C8b + F9. All three done (2026-08-07, 2026-08-08, 2026-08-09) and sharing one
   `## Unreleased` section; the release is ready to cut** — the `staging` → `main` PR, labelled
   **`minor`** (C8a's new platform artifact and C8b's installer both add capability). Then a
   **second** clean-instance run, because **C8b changes what "install" means**: a clean-instance
   test against a zip proves nothing about an installer, and this time the run must confirm the new
   invariant — installed as admin, *runs* as a standard user. That run is in *Needs verification*.

This is a release split, not a cycle split — the cycle is C4/C7/C8a/C8b, plus **F8** and **F9**, added
2026-08-06 when preparing Release 1 exposed it. F8 was scheduled for Release 2 and **pulled into
Release 1 on 2026-08-07**: a GitHub Actions outage meant the release PR needed a fresh commit to
re-run its checks anyway, and F8 is precisely a fix to those checks.

**F8 — the `--check` gate can never fail.** Found while preparing the v0.7.0 release PR.
`bump_version.check` strips the instruction comment before testing whether the Unreleased section is
*empty*, but **not** before testing whether it states the re-ingest answer — and that comment
contains the literal string "Re-ingest needed: yes/no". So `_REINGEST_HINT in body.lower()` was
always true and the gate had never rejected anything since Phase 3. `release_unreleased` *does*
strip comments when it builds the release section, so a section with no re-ingest line passed the PR
gate and then failed `release_notes.py` in the release preflight — **after `tag.yml` had pushed the
tag**, which is the recovery path PACKAGING documents rather than the cheap PR-time failure it was
designed to be. The v0.7.0 Unreleased section genuinely had no re-ingest line, and `--check` passed.

**Why the suite never caught it:** `test_bump_version.py`'s fixture used a *stub* comment
(`<!-- instructions -->`) rather than the real `PLACEHOLDER`, so no test ever exercised the case the
bug lives in. The regression test uses `PLACEHOLDER` itself — **never a stub**.

**F8 is widened to close F6 as code.** The same `check()` now also requires a `**Known issues**`
list, with "None" an explicit valid answer (v0.4.0 and v0.4.1 legitimately had nothing to report, and
a gate with no escape becomes one people work around). F6 had been a P2 *process* item since the plan
was written and was missed on **v0.4.1 and v0.6.0** — a step that depends on remembering, twice not
remembered. `release_notes.py` was checked and is **not** affected: it reads a released section,
whose comments `release_unreleased` has already stripped.

**F9 — ship `NOTICE.md` as a PDF. Done 2026-08-08**, as scoped. Raised by C4: a tester without a
markdown viewer opens `NOTICE.md` in Notepad and reads `#` and `**`, and the LGPL v3 notice for the
bundled Qt is the one document that genuinely has to reach them. Built as **a second pandoc
invocation in the existing `guide-pdf` job**, not a new job — the apt list there is load-bearing
(see Phase 3) and was not touched. Full write-up in PACKAGING → *The notices PDF (F9)*; the summary
is in *Recently closed*.

**C8 is three deliverables under one ID, and only two are in this cycle — decided 2026-08-05.**
- **C8a macOS/Linux artifacts → Linux only — done 2026-08-07.** `release.yml` already runs an `ubuntu-latest` job for
  the guide PDF, so a tarball is nearly free, and the author develops on Linux, so it has a real
  consumer. **macOS is deliberately dropped from the cycle:** no known user, a runner to pay for,
  and an unsigned build walking into Gatekeeper. *"Nearly free" turned out to be optimistic* — the
  first CI run died in PyInstaller's collection stage, not the build: `collect_submodules` imports
  what it enumerates, and `pyqtgraph.examples` aborts the process on a machine with no display.
  C7's exclusion filtered the *result*, too late to prevent the import. Fixed by filtering during
  collection; full write-up in PACKAGING → Phase 4, including the rule it produced: **if you exclude
  a submodule from a `collect_*` call, filter during collection, not afterwards.**
- **C8b Inno Setup installer + Windows Firewall allow-rule → done 2026-08-09.** The firewall prompt
  is PACKAGING's #3 "easy to forget". **Built as an admin install that writes the rule** (option b,
  settled 2026-08-07): elevation is normal for a Windows installer, and UAC drops the privilege
  again immediately. A per-user install with an *optional* elevated task would keep both properties
  but was rejected as the most complex option, with its failure mode landing on a tester machine we
  cannot debug. **The invariant it must not break:** the app requires no admin rights *at runtime* —
  the checklist item becomes "install as admin, run as a standard user". Rationale, the consequences
  table and all six implementation decisions are in PACKAGING → *C8b scope*; the summary is in
  *Recently closed*.
- **C8c velopack auto-updater → deferred out of Cycle 3.** PACKAGING already calls full
  self-replace on a *running* one-folder Windows app "fiddly… deferred deliberately". It is a .NET
  toolchain that would replace the zip artifact verified across three builds, for a handful of
  testers whose notify-only path was confirmed working against a real Release on 2026-08-02. It
  buys the least and risks the most. **It keeps its own P3 row** — closing Cycle 3 does *not* close
  the C block, and a deferred item with no row reads as a forgotten one.

**Cycle 4 — the UI debt Cycle 3 deliberately walked past.** First item was **A4** — **done
2026-08-15**, with **A4b** closing the last controls on 2026-08-18. Both shipped as **v0.8.1**
(label `patch`, A4 + A4b alone), released on its own rather than grouped: everything behind it is
large, so grouping would have held a five-release-old known issue behind a multi-week rework.

**Cycle 4 closed with A4b — corrected 2026-08-24.** It contained A4 and A4b and nothing else,
and both shipped as v0.8.1. An earlier version of this line placed the whole E-block inside
Cycle 4; that was wrong, and the E1/E2/E3/E5 rows below no longer say it.

**The E-block is the work after it, and its order is decided — 2026-08-18: E1/E2 → E3 → E5.**
Not "in whatever order they earn", which is what that line used to say. These three are what make
this a *full app* rather than one with placeholder sidebar entries, and **E1/E2 is next** —
picked up in its own session, deliberately not the same one that closed A4.

**A6 and E7 are explicitly held until the E-block is complete — decided 2026-08-18.** Neither is
dropped and neither is forgotten, which is why this is written down: A6 reads as due (it is
"new 2026-08-08" and "pairs naturally with A5"), and E7 has a small, tempting remainder. But
recorder observability and a constant-range verification are **polish on a working app**, while
Dashboard, Sessions, Analytics and Bug report are still placeholders a user can click into. App
completeness first; instrument it afterwards.

**C8d is deliberately NOT in Cycle 4 — decided 2026-08-15.** It is the obvious-looking next step
after C8b and will keep suggesting itself, so the decision is written here as well as in its own P3
entry: while every update still requires a Windows restart, an assisted update buys one click and
carries the app's first download-and-execute path. A4 is the better use of the same cycle. See the
C8d entry in P3 for the full reasoning and for what brings it back.

- A4 Windows light/dark switch leaves text miscoloured — **moved out of Cycle 3, 2026-08-06.** Not
  for lack of importance: it has shipped as a known issue in every release since v0.3.0. It is
  cross-surface UI refactoring in 15 files, which shares no review context with build/CI plumbing —
  putting it beside an installer spec is worse for both. It is also *not* Windows-gated the way C4
  is: `colorSchemeChanged` fires on Ubuntu too, so most of it is verifiable on the dev box.
  **Its root cause was misdiagnosed in the docs until 2026-08-06** — see PACKAGING → Phase 1 known
  issues for the corrected mechanism and the measured scope.

  **Done 2026-08-15**, on `fix/theme-switch-text-colour`. Re-measuring by AST first was worth it:
  the real scope was **33 colour-freezing calls, not the recorded 27**, and the recorded figure was
  not even counting font-only calls. 32 label sites moved to `QFont` behind named helpers in
  `ui/style.py`; the fix also turned up two never-applied stylesheets (a missing `f` prefix in
  `slider_row.py` and in `car_status_graphic.py`). A guard test now fails if a font-bearing
  stylesheet without an explicit colour reappears, so this cannot silently come back the way it
  accumulated. **A4b** carried the five remaining controls and closed on 2026-08-18 — see its
  row in P2.

**Cycle 5 (likely) — localization.** The new G block, below. Deliberately after the E-block
surfaces: translating a UI that is still growing means translating it twice.

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

Nothing is left in P1. See *Recently closed* for what each item settled. The one loose thread it
left — the "open the app twice" check having passed *before* WAL existed — is now **closed**: it was
re-run under WAL on 2026-08-05 and passes.

## P2 — after P1

| ID | Item | Status | Detail in |
|---|---|---|---|
| B2 | League capture import from a shared folder | **done 2026-08-04** | ROADMAP → Capture compression; DECISIONS → Storage |
| B3 | `recorded_by` is plumbed but never set | **done 2026-08-04** (one field on B2's import prompt) | ROADMAP → Capture compression |
| B4 | Locate a moved capture by content hash | **done 2026-08-03** | ROADMAP → Capture compression; DECISIONS → Storage |
| A4 | Windows light/dark switch leaves text miscoloured | **done 2026-08-15** — Cycle 4; 32 of 37 sites, five controls left as **A4b** | PACKAGING → Phase 1 known issues |
| A4b | The same freeze on five *controls* | **done 2026-08-18** — Cycle 4; sidebar + 3 buttons fixed, season card measured and deliberately kept | PACKAGING → Phase 1 known issues |
| C4 | Clean-instance test (Sandbox / second user account) | **done 2026-08-07** — Cycle 3, against v0.7.0 | PACKAGING → Build history, 4th build |
| E7 | Setup slider ranges | **confirmed 2026-08-02** — remainder **held until the E-block ships** | DECISIONS → UI |
| E1 | Sessions surface | **in progress** — branches 0-1 merged; **detail-view layout specified 2026-08-24**, branch 2 split into 2a (built) / 2b / 2c | **`E1_E2_PLAN.md`**; ROADMAP → Other surfaces |
| E2 | Deleted-sessions manager | open — **planned in full 2026-08-20**, inside E1 (branches 3-4, not started); store side partly built | **`E1_E2_PLAN.md`**; ROADMAP → Other surfaces |
| E3 | Analytics surface | open — **after E1/E2** | ROADMAP → Other surfaces |
| E5 | Bug report page | open — **last of the E-block** | ROADMAP → Other surfaces |
| E14 | Mixed dry/wet weather on a session | open — **decided 2026-08-24**; land it **before the v0.8.2 release** so it shares one re-ingest | the note below |
| E15 | Ingest Event packets — overtakes + penalty detail | open — **found 2026-08-24** while specifying the E1 detail view; bundle with **E14**, one re-ingest | the note below |
| E16 | Game-mode ids for the 2026 modes | open — **`78` observed 2026-08-24**; My Team '26 still unknown | the note below |
| F6 | Carry the CHANGELOG known-issues list forward every release | **closed by F8, 2026-08-07** — was process, now a gate | see the Cycle 3 plan above |
| F8 | `bump_version --check` reads the instruction comment, so its gates can never fail | **done 2026-08-07** — shipped in v0.7.0 | see the Cycle 3 plan above |
| F9 | Ship `NOTICE.md` as a PDF beside the exe, like `USER_GUIDE.pdf` | **done 2026-08-08** — Cycle 3, Release 2 | PACKAGING → The notices PDF (F9) |

**E7 is resolved as a question, not as code.** The ranges in `setup_panel._SETUP_SPEC` are
confirmed correct for **2026** packets. 2025 is expected to be fine too: the only range
difference between the 2025 and 2026 cars is **tyre pressure**. Remaining (small) work is to
verify the 2025 tyre-pressure bounds and record the source in `_SETUP_SPEC`.

**E14 — a session that ran both dry and wet.** `ui/components/weather.py` already draws the icon
(`weather.MIXED`); nothing selects it yet. `SessionResult.weather` is a single value, and the
assembler's `self._scaffold = normalize_session(packet)` is last-write-wins, so what is stored is
the condition at the *end* of the session.

**Not from `weatherForecastSamples`** — evaluated 2026-08-24 and rejected, for three reasons that
would otherwise be rediscovered. The samples are weekend-wide (each carries its own
`session_type`, and Sprint Race and Grand Prix both report 15, so a sprint weekend cannot be
filtered cleanly — invariant #5); past offsets roll off as the session runs, so the last packet's
forecast no longer covers the transition that actually happened; and they are a *forecast*, which
`forecast_accuracy` may mark Approximate.

**Do this instead:** accumulate the distinct `weather` values the Session packets actually report
across a session. Ground truth, no session-type filtering, no accuracy caveat, and it sets up a
real weather timeline later. Dry is `CLEAR` / `LIGHT_CLOUD` / `OVERCAST`, wet is `LIGHT_RAIN` /
`HEAVY_RAIN` / `STORM`; both present → mixed, otherwise keep the snapshot.

**E15 — the Event packets are already in every capture, unparsed.** Found 2026-08-24 while
checking what the E1 session detail view could actually show. `session/assembler.py` dispatches on
ten packet ids and **`PacketId.EVENT` is not one of them**, so every event the game sends is
decoded past. The recorder writes *every* datagram unfiltered, so the data is on disk already —
decoding one real capture gives:

    BUTN 8096 · OVTK 881 · SPTP 509 · PENA 79 · FTLP 17 · COLL 14 · STLG 10 · SEND/SSTA/RTMT 5 …

`OVTK` carries the overtaking and overtaken vehicle indices; `PENA` carries penalty type,
infringement, vehicle index, **lap number** and time. `reference.PENALTY_NAMES` and
`INFRINGEMENT_NAMES` already exist and are unused — the *display* half is written.

**This is recoverable retroactively**: a re-ingest of existing captures fills it in, with no
re-recording. It needs a `PIPELINE_VERSION` 3→4 bump, which is why it should **land with E14** and
share one re-ingest prompt rather than asking twice. It fills two E1 gaps: the detail view's
`Laps completed` cell becomes **real overtakes**, and the penalties box gains type + lap + time.

**Fuel-corrected lap time — an Analytics (E3) item, banked 2026-08-24.** Found while specifying
E1's stint-relative lap-time chart. That chart shows *observed* lap time by stint, which conflates
tyre degradation with fuel burn-off (~1.1-1.3 kg/lap, so later stints run lighter and look faster).
E1 states the caveat rather than correcting for it — a correction needs a track- and car-dependent
kg→seconds coefficient, and guessing one silently would replace an honest raw number with an
estimate.

**No ingest work is needed**: `fuel_in_tank` is already stored per lap, 406 of 406 populated. What
it needs is the estimation method and a way to show its uncertainty, which is Analytics' remit, not
session detail's. See DECISIONS → UI and ROADMAP → Analytics.

**E16 — game-mode ids for 2026.** `game_mode 78` is **Driver Career '26**, established from
observation 2026-08-24: every "Driver Career with the 2026 cars" recording carries it, checked in
the database against the session detail view. It is **not in the UDP specification** — EA has not
documented the '26 mode ids — so `GAME_MODE_NAMES` renders it `Unknown game mode (78)` today.
Add it, labelled as observed rather than specified.

**Still unknown: My Team '26**, because there is no My Team '26 recording yet. Add that id the
same way once one exists. For contrast, Grand Prix Multiplayer "Championship" (the league, also on
2026 cars) already reports `Online Custom` correctly — so only the *career* modes shifted.

Shaped exactly like the `ai_difficulty` branch: assembler → `SessionResult` → `SessionRow` → both
mappings → **`PIPELINE_VERSION` 3→4**. **Before the release**: `## Unreleased` already says
*Re-ingest needed: yes*, so one re-ingest covers this and `ai_difficulty` together; afterwards it
costs users a second one.

## P3 — later / opportunistic

| ID | Item | Detail in |
|---|---|---|
| A5 | Isolate `ES_DISPLAY_REQUIRED` from `ES_SYSTEM_REQUIRED`; managed-machine lock untested | ROADMAP → recorder stalls |
| A6 | Recorder observability: first-datagram source IP:port, periodic counts, total at stop | **new 2026-08-08**; PACKAGING → C8b scope |
| A7 | First-run "no telemetry arriving" hint in the UI — name the restart-after-install case | **done 2026-08-09** — folded into C8b; PACKAGING → C8b scope |
| B5 | Reconstructed-race points: accept / edit / store (Option 3) | ROADMAP → Storage & analysis |
| B6 | One roster shared across seasons (`roster_path`) | DECISIONS → Identity & rosters |
| C5 | `threading.excepthook` for worker threads | **done 2026-08-05** — Cycle 3; PACKAGING → Phase 0 |
| C6 | Startup capability self-check (degraded pyqtgraph/zstandard) | **done 2026-08-05** — Cycle 3; PACKAGING → Risks |
| C7 | pyqtgraph bloat trim (`pyqtgraph.examples`) | **done 2026-08-06** — Cycle 3; PACKAGING → Phase 1 known issues |
| C9 | Transitive dependency trim: scipy / pandas / pillow (~105 MB, 18%) | **later, not Cycle 3**; PACKAGING → Phase 1 known issues |
| C8a | Linux release artifact (macOS deliberately dropped) | **done 2026-08-07** — Cycle 3, Release 2; PACKAGING → Phase 4 |
| C8b | Inno Setup installer + Windows Firewall allow-rule | **done 2026-08-09** — Cycle 3, Release 2; PACKAGING → C8b scope |
| C8d | Assisted update: download + launch the installer from Help → Check for updates | **evaluated 2026-08-15 — deferred, deliberately NOT in Cycle 4**; design in PACKAGING → C8d |
| C8c | velopack real auto-updater | **still deferred** — and it now *conflicts with C8b*; see below |
| D2 | Alembic — adopt at the first non-additive migration (trigger-based) | DECISIONS → Migrations |
| D3 | Persisted `track_layouts/*.parquet` cache | DECISIONS → UI |
| D4 | True geometric centerline (needs Motion Ex / track width) | DECISIONS → UI |
| D5 | Re-validate the 2c colour thresholds against real telemetry | DECISIONS → UI |
| E4 | Dashboard surface | ROADMAP → Other surfaces |
| E8 | Track-country flag on lap cards (no `track_id → country` map) | ROADMAP → Laps 1b |
| E9 | Corner numbers on the track map (**licensing caveat**) | DECISIONS → UI |
| E10 | Sector labels as map hover/tooltips | DECISIONS → UI |
| E12 | Team colour swatches (only if team identity needs to be scannable) | DECISIONS → UI |
| E13 | Move the capture/database actions off Help into their own surface | ROADMAP → Other surfaces |
| G1 | i18n infrastructure + a language setting | **Cycle 5 (likely)**; DECISIONS → Localization |
| G2 | German translation of the UI strings | **Cycle 5 (likely)**; ROADMAP → Localization |
| G3 | German user guide + its PDF artifact | **after G2**; ROADMAP → Localization |

**A6, added 2026-08-08, and what earned it.** Between `listening on 0.0.0.0:20777` and a finished
capture, the recorder says **nothing** — so "it isn't recording" cannot be told apart from "nothing
is being sent" without reaching for `pktmon`, which is exactly what C8b's clean-machine run had to
do to disprove a firewall theory that was never true. Wanted: the **source IP:port of the first
datagram** (proves delivery *and* names the sending device), a **periodic count** while recording,
and a **total at stop**; optionally parse failures counted separately from receives, so "arriving
but not understood" is distinguishable from "not arriving". Deliberately **not** folded into C8b —
recorder-layer work, no shared review context with an installer. Pairs naturally with **A5**, since
both are about what the recording path does and does not report.

**C8d, added 2026-08-09 — and C8c is now harder than "deferred" implied.** With the installer
shipped, updating means *download the asset, elevate, restart Windows*. **C8d** is the small version:
`Help → Check for updates` already queries `/releases/latest` and shows a manual link, so extend it
to **download the installer and launch it**. No self-replace, so none of the one-folder file-lock
problem that deferred velopack — and Setup's Restart Manager already handles a running app (proven
in C8b). It keeps Program Files, the admin install and the firewall rule untouched.

**What C8d cannot do is avoid the restart.** Running the installer requires one, in any form
(measured 2026-08-09), and C8d *is* running the installer. It buys convenience — one click instead
of a manual download — not a shorter update. **And nothing else can avoid it either:** the restart
attaches to the installer-created rule itself, not to updating, since clean *first* installs need it
too (2026-08-15). Only *dropping* the rule could remove it — see the open question below.

**C8d is deferred out of Cycle 4 — decided 2026-08-15. The design is recorded in PACKAGING → C8d so
it does not have to be re-derived; this is why it waits.** The reboot eats most of the value: C8d
removes *browse, find, download, run* and leaves *elevate, close, reboot*, so the update stays a
sit-down operation and C8d makes only the small half smaller. It would also be **the app's first
path that downloads a binary and executes it** — a new trust boundary in an app that otherwise only
reads UDP and files, landing in the same release-phase area that just cost several days. Against
that, **A4 has shipped as a known issue in every release since v0.3.0** and fires on every theme
switch, while a handful of testers doing a manual download roughly monthly is the cheaper problem.
The notify-only path is confirmed working against a real Release (2026-08-02), and the group is
still small enough that a chat message covers version drift.

**What brings it back** — so a future session need not re-argue it: **either** the reboot
requirement goes away, **or** the tester group outgrows "tell them in chat", **or** a release ships
something urgent enough that version drift becomes a real support problem.

**No new item for app-side no-telemetry detection: A7 already is it.** `_hint_if_no_telemetry` fires
after 25s of zero datagrams and names both the restart case and the Public-network case, and its
advice is correct after an assisted update for exactly the reason it is correct after a manual one.
Gating it on "a matching firewall rule exists" was considered and **rejected** — parsing `netsh`
output or taking a COM dependency, Windows-only and fragile, to drop half of one sentence. **A6** is
the open half worth building, not a second hint.

**Worth doing without C8d, and much cheaper (~15 lines in `help_page.py`):** point the update
dialog's button at the matching setup asset's `browser_download_url` rather than the release page,
and **say in the dialog that installing an update needs administrator rights and a Windows restart**.
The second half stands on its own — the dialog currently says nothing about the reboot, which is the
most important fact about updating this app. It can ride along with any release.

**The open question C8b left: should the installer write the firewall rule at all?** Recorded
2026-08-15 because the trade-off genuinely moved — when C8b was decided the rule was free, and it now
costs a restart on every install and update. **The answer for now is keep it**, and the decisive
reason is that C8b's target model is *installed by an admin, run by a standard user*: in that model
the Windows first-run prompt **cannot** produce a rule, because it needs admin credentials the
standard user does not have (and under GPO with notifications off it never appears at all). Dropping
the rule would trade a documented, requested, one-time reboot for a **silent, irrecoverable
standard-user failure** — and silence is the one thing this whole investigation exists to eliminate.
The full comparison table, and the experiment that would decide it (which is a **reopening of C8b**,
not a small check), are in PACKAGING → *The open question C8b left*.

**C8c stays deferred, and now for a second reason: it conflicts with the C8b install model.**
Velopack's value rests on a **per-user, `%LOCALAPPDATA%`, non-elevated, self-replacing** install.
C8b deliberately chose the opposite — **per-machine, Program Files, elevated, machine-wide firewall
rule**. Adopting velopack means either dropping the firewall rule or reviving **option (c)** (per-user
install plus an elevated task), which was rejected as the most complex option with its failure mode
on an undebuggable tester machine. Velopack also uses versioned folders behind a stub, so the exe
path can move between versions — and the firewall rule names a path. **C8c is therefore not a small
next item; it is a re-opening of C8b.** Do not pick it up as one.

**A7, added and done 2026-08-09 — and folded into C8b rather than deferred.** `Recording — waiting
for telemetry …` is correct but unhelpful when it never changes: it cannot distinguish "the game
isn't sending" from "the firewall rule isn't live yet". A user who **declines the installer's
restart** lands in exactly that state. It was reversed into C8b because a restart *request* can be
declined and the resulting failure is silent — so shipping without it would leave a hole in C8b's
own justification, which is to stop the false bug report "I installed it, pressed Record, nothing
happened". `MainWindow` now replaces the label after `_NO_TELEMETRY_HINT_MS` of zero datagrams with
one line naming the restart case and the Public-network case. **No first-run detection** — the
trigger is zero packets, and the advice is right whenever it fires, which is what kept it to ~12
lines. It **narrows** the standing "setup guidance belongs in docs, not status text" preference:
justified because this cause reaches a user who is already past the docs. **A6 stays open** as the
log-side half.

**The G block, added 2026-08-06.** Localization is a new concern that fits none of the existing
blocks, hence a new letter. The app is used by a Swiss league; most members would rather read
German.

**It splits into a decision and a body of work, and only the decision is urgent.** The
infrastructure choice is cheap now and expensive to retrofit — every UI string written between now
and then is written in one style or the other — so the approach is **settled now** (DECISIONS →
Localization: Qt `tr()` + `QTranslator`, *not* a Python dict) and adopted for new UI code as it is
written. The **bulk translation waits**, because Sessions (E1), the deleted-sessions manager (E2),
Analytics (E3) and Bug report (E5) are all still placeholders: translating a UI that is still
growing means translating it twice. Rough scale of the eventual job — ~363 candidate user-facing
strings under `src/ui/`, which is also why it is not a hand-maintained dict.

**G3 is deliberately separate from G2.** The user guide is not UI text: it is `docs/USER_GUIDE.md`
converted to PDF by `release.yml` via pandoc/xelatex. A German guide means a second source document,
a second pandoc invocation and a second artifact in the release zip — a packaging change, not a
translation one.

---

## Needs verification

Built or believed-done, but never proven. Each names *how* it gets proven, so it can be picked
up opportunistically rather than scheduled.

- **Which change makes the firewall rule need a restart (C8b) — largely answered 2026-08-15, and the
  answer is "neither, as framed".** This item posed two candidate triggers, never separated because
  every test changed both at once: (a) the **exe at the rule's path being replaced**, (b) the **rule
  being deleted and re-added**. **(a) is falsified** — clean *first* installs fail, where no previous
  exe existed at that path. **(b) survives only as a possible trigger, never as a remedy** — in the
  failing window, disabling and re-enabling the app's own rule did not help, and neither did an
  unrelated policy touch. **Plan, now opportunistic rather than blocking:** one exact `delete rule`
  + the installer's own `add rule` (a new rule object, unlike disable/enable), then record without
  rebooting. Low odds given the above. **This no longer gates C8d** — C8d was deferred on other
  grounds, and (a)'s death already settles the question it was posed for: the reboot attaches to the
  installer-created rule itself, not to updating. **Do not schedule "experiment #6", a real
  v0.7.0 → v0.8.0 upgrade test: it is not runnable**, because v0.8.0 is the first release that
  shipped an installer.
- **E11 — track map rotation.** Possibly already correct; unconfirmed. **Plan:** compare the
  rendered map against the in-game track map when recording the next sessions — which is the same
  ~2026-08-12 race B1 is waiting on, so both can be settled from one capture. Note that absolute
  rotation deliberately follows the game's world frame, **not** F1.com broadcast art
  (DECISIONS → UI) — so "different from broadcast" is expected and is not the thing being checked.
- **The second clean-instance run — the C8b invariant.** Release 2 ships an installer, and a
  clean-instance test against a zip proves nothing about one. **Plan:** run the full clean-machine
  checklist in PACKAGING against the **published Release 2 installer**, on Windows Sandbox plus the
  W11 boot, confirming the item that *changed meaning* — **installed as admin, then run as a
  standard user** with no UAC prompt, nothing written beside the exe, and the data root belonging to
  that user. Also new on that list: the rule verified with `netsh … show rule`, upgrade-in-place
  leaving one rule and one uninstall entry, uninstall removing the rule while leaving captures, and
  the zip still working standalone. **Sandbox's known limit applies** — it cannot record (no route
  to the PS5), so the "record with no prompt at all" item needs the boot.
- **A5 — `ES_DISPLAY_REQUIRED`.** Never isolated from `ES_SYSTEM_REQUIRED`; dropping it is a
  one-line experiment that would stop the screen staying lit. Also untested against a
  policy-managed machine, where a *lock* cannot be prevented (only sleep can).
## Recently closed

- **A4 + A4b — the live light/dark switch, and the guard that stops it coming back.** A4 done
  2026-08-15 on `fix/theme-switch-text-colour`, A4b done 2026-08-18; **shipped together as
  v0.8.1**, the first items of Cycle 4 and the end of a known issue carried in **every release
  since v0.3.0**.
  **Re-measuring by AST before touching anything is what made it tractable**, and is the reusable
  lesson: the real scope was **33 colour-freezing calls, not the 27 the docs recorded**, and the
  recorded figure had not even been counting the same thing. 32 label sites moved to `QFont`
  behind named helpers in `ui/style.py`; A4b carried the five remaining **controls** (sidebar plus
  three buttons), and the season card was **measured and then deliberately left as it was**.
  **The root cause had been misdiagnosed in the docs until 2026-08-06** and the corrected
  mechanism is the thing worth not re-deriving: setting *any* stylesheet hands a widget to
  `QStyleSheetStyle`, which caches a palette **at apply time**, so a label styled only
  `font-size` carries the old theme's text colour despite never asking for a colour. No
  palette-derived colour exists anywhere in the codebase.
  **Two never-applied stylesheets fell out of the work** — a missing `f` prefix in
  `slider_row.py` and in `car_status_graphic.py`, so the setup panel's min/max labels had never
  been muted and the car-status background had never been set. Both were passing the *name* of a
  colour setting instead of its value, which is a bug class worth recognising on sight.
  **A guard test now fails if a font-bearing stylesheet without an explicit colour reappears**, so
  this cannot silently re-accumulate the way it did over five releases. `MUTED_TEXT_QSS` stays
  styled on purpose — its `#8b949e` is deliberately fixed and reads on both grounds.
- **Kill mid-record → recovers on next launch. Verified 2026-08-09** during the v0.8.0 clean-test
  runs, where it is a checklist item. It had been open since 2026-08-07 only because **Windows
  Sandbox cannot record** (a VM with internet but no route to the home network, so the PS5 never
  reaches it) and the W11 boot run had not covered it. Closed on the real boot, which is the only
  place the live-recording items can be checked at all.
- **B1 — GP-multiplayer roster grouping, verified 2026-08-09.** The league's *normal* state — the
  author's own online name/ID set to **private/restricted**, drivers arriving as `"Player"` and
  grouped by race number via `roster.member_key` — was tested on a real race and **the standings
  table is correct**. This was the season-critical unknown: a wrong grouping shows up as two members
  merged into one row, or one member split across two, and neither is obvious until a season's table
  is already wrong. `ROSTER_SEASON_MODES` including `GRAND_PRIX` is therefore proven against real
  data rather than assumed.
- **C8b — the admin installer, and the six decisions it needed.** Done 2026-08-08; the last item of
  Cycle 3's Release 2. `packaging/installer/f1telemetry.iss`, compiled by `windows-build` and
  published as `f1telemetry-<tag>-windows-x64-setup.exe`: Program Files, Start-menu entry,
  uninstaller, and the Windows Firewall allow-rule that is the reason it exists. **The zip keeps
  shipping** — it is the no-elevation fallback and the artifact three builds were verified against.
  **The runtime invariant was verified, not assumed:** `paths.app_dir()` is read-only at all four
  call sites and frozen `data_root()` is `%LOCALAPPDATA%\f1telemetry`, so nothing is written beside
  the exe and Program Files is safe.
  **Four answers worth not re-deriving.** *Uninstall never touches the data root, and there is no
  opt-in checkbox either* — beyond "captures are the source of truth", an admin uninstall runs under
  the **administrator's** token while `data_root()` is per-user, so on the very machine this targets
  it would resolve the wrong profile, delete nothing and report success. *`netsh`, keyed by rule name
  and deleted before added* — legible in the install log, and idempotent across reinstalls.
  *`CloseApplications=yes` plus an `[InstallDelete]` wipe of `_internal`* — Restart Manager solves
  the one-folder file locks, and the wipe solves the half that is easy to miss, since Inno replaces
  only files it installs and anything **dropped** by a later build would linger forever. *CI builds
  it* — a hand-built installer comes from an unverified working tree and breaks both "the published
  artifact is exactly the tagged commit" and "CI verifies the version, it never stamps it"; the
  no-tag `workflow_dispatch` path answers the objection that it can now fail a release.
  **Two things the written scope had not listed.** `profile=private,domain`, **not public** — a
  home-LAN listener whose parser reads untrusted datagrams, mirroring what the Windows prompt itself
  ticks. **Its failure is silent**, so it is documented in three places: a home network Windows has
  classified as *Public* receives nothing with no error. And there is **no "launch now" checkbox** —
  the installer is elevated, so a post-install launch would hand the app an admin token and create
  the data root in the wrong profile on its very first run, disproving the invariant immediately.
  **One defect the clean-machine run found, fixed here rather than documented around:** uninstalling
  with the app **open** deleted the documents beside the exe but left `f1telemetry.exe` and
  `_internal` behind — a half-removed install, because Windows will not remove a running executable
  or its loaded DLLs. `CloseApplications=yes` covers Setup but not the uninstaller, which is itself
  holding `{app}`. An `InitializeUninstall` guard now refuses with Retry/Cancel; **that hook is the
  point — returning `False` aborts before anything is removed**, so cancelling leaves the install
  exactly as it was.
  **And one that took several days and is why the installer asks for a restart:** the installed
  build received no telemetry while the **byte-identical** zip binary recorded fine on the same
  machine and network. The rule was neither missing nor malformed — `verbose` showed the right
  program, protocol and profiles. **A rule that exists and a rule that matches are different
  things**, and Windows' default inbound action is Block, so a non-matching rule needs no Block
  rule to produce silence. **A firewall-off bisection settled in one command what two days of
  reading rule output could not** (disable the Private profile → records; re-enable → silent).
  **The remedy is `AlwaysRestart=yes`:** install → Record immediately fails *while `pktmon` confirms
  packets are arriving*; restart → Record works, same game session. Not propagation latency (the
  failing window ran for minutes) and not per-process staleness (the process was launched after the
  rule existed). **The mechanism is unnamed — corrected 2026-08-15.** This entry used to say
  "probably a stale path→rule association cached after the exe at that path is replaced"; that is
  **disproven**, because clean *first* installs fail too, with no previous exe at that path. What is
  measured: the drop is in WFP (firewall off → records; on with correct allow rules → silent), and a
  reboot is the only remedy that has ever worked. `advfirewall reset` and `gpupdate` were rejected;
  **restarting `MpsSvc` is not merely inadvisable but impossible** — `sc.exe sdshow mpssvc` shows the
  `BA` ACE carrying no `WP` (stop) right, so nothing stops the service even elevated. Full falsified
  list in PACKAGING.
  **The rule shape was a wrong turn, and the confound is the point:** three shapes were measured
  (`program`+`localport` failed; either alone worked) and written up as the root cause — but *every
  success immediately followed a firewall policy change*, and a clean install carrying the port-less
  rule still failed until restart. Rule shape was never isolated. The port-less form is kept only
  because it matches what Windows itself writes.
  **Genuinely eliminated by measurement**, not argument — the firewall-off run and a run with the
  installed app and the zip **recording the same broadcast simultaneously** close: Program Files
  path, the folder-name space, Start-menu context, working directory, standard-user context,
  packaged `_internal`, any zip-vs-installed binary difference, stale rules, and duplicate
  listeners. **Do not re-test these.**
  **Four wrong turns recorded in PACKAGING:** `pktmon` **cannot fix a firewall** (an early "it
  worked when I ran pktmon" was correlation, and cost a day); `Domain,Private` is a **superset** of
  `Private`, not a mismatch; **one successful observation is not a fix** — made three times, twice
  written into these docs as settled; and **test without a control and you measure nothing** —
  run the release zip alongside, since it takes the same broadcast. It produced **A6** and **A7**.
  **Accepted 2026-08-09 on two full clean passes**, identical both times: before restarting the
  installed app received nothing *while the zip recorded as control*, closing and reopening it did
  not help, and after restarting it recorded immediately with a `.f1cap`. **A7 was pulled into this
  branch rather than deferred** — a restart request can be declined, and that failure is silent, so
  leaving it out would have shipped C8b with a hole in its own justification.
  **`test/test_installer_script.py` is the drift net an `.iss` invites**, closing the chain `.iss` ↔
  `LiveUDPSource`'s default ↔ `main_window._PORT` — the last read as *text*, because importing
  `main_window` would pull PySide6 into a deliberately Qt-free suite. A wrong port there is a rule
  that exists, looks right, and silently receives nothing.
- **F9 — the notices PDF, and the question of which file the button opens.** Done 2026-08-08; the
  second item of Cycle 3's Release 2. `NOTICE.pdf` is built by **a second pandoc invocation in the
  existing `guide-pdf` job** (not a new job — the apt list there is load-bearing and already paid
  for), ships beside the exe in both archives, is in **both** build jobs' sanity-check lists, and is
  attached to the Release on its own so the terms are reachable without a ~250 MB download.
  **The open question is answered: *Licences & notices* prefers the PDF.** `resolve_notices` grew a
  third step and is now the same shape as `resolve_guide` — **presence decides at every step, never
  `is_frozen()`**. That one rule is correct in both worlds because the dev path is preserved by a
  fact rather than a special case: `app_dir()` is the repo root in a source run, and `NOTICE.pdf` is
  a CI artifact that never lands there (`/NOTICE.pdf` joined `/USER_GUIDE.pdf` in `.gitignore`). A
  release build finds the PDF; a source run finds only the markdown; a partial extract still gets
  the GitHub URL. Shipping a PDF and then opening raw markdown anyway would have defeated the item.
  **Two things deliberately not done, so they aren't re-proposed.** **`LICENSE` stays plain text** —
  it contains no markdown syntax at all, so it never had the problem F9 exists to fix, and running
  its hanging-indented sub-clauses through pandoc *as markdown* would reflow and damage them. And
  the notices are **not folded into `USER_GUIDE.pdf`**: the Help action would have no deep-link
  target, a distinctly named standalone file is the defensible way to deliver an LGPL notice, and G3
  would otherwise give the German guide an English legal appendix.
  **One trap found in review and worth not re-learning:** the `release` job's `download-artifact`
  has no `name:`, so it lands every artifact under `artifacts/<artifact-name>/` — and both PDFs ride
  in the one `user-guide-pdf` artifact. `artifacts/notice-pdf/NOTICE.pdf` looks right and does not
  exist. That job is **skipped on a no-tag `workflow_dispatch`**, so the dispatch test run cannot
  catch it, and it would have failed *after `tag.yml` pushed the tag*.
  Covered by `test/test_user_guide.py` (`ResolveNoticesTest`, PDF-wins and markdown-fallback cases).
  The Qt wiring has no automated test — every suite here is deliberately Qt-free — so it was
  verified by hand by dropping a `NOTICE.pdf` at the repo root and opening the action.
- **C8a — the Linux release artifact.** Done 2026-08-07; the first item of Cycle 3's Release 2. A
  `linux-build` job mirroring `windows-build` on `ubuntu-latest`, publishing
  `f1telemetry-<tag>-linux-x64.tar.gz` with the same four files beside the binary and the same
  sanity-check — `LICENSE` and `NOTICE.md` are an LGPL v3 obligation for the bundled Qt, so a
  missing one fails the build rather than shipping quietly.
  **Three choices worth not re-litigating:** a **tarball, not an AppImage** (that was already the
  plan; AppImage needs `linuxdeploy` plus a Qt plugin and is its own debugging surface); **`.tar.gz`,
  not zip**, because zip does not preserve the executable bit and the binary would need a `chmod +x`
  to run at all; and **macOS still dropped** — no known user, a runner to pay for, and an unsigned
  build walking into Gatekeeper.
  **The limit is stated, not solved:** a PyInstaller bundle links against the **glibc of the machine
  that built it**, so the artifact needs a distro at least as new as the runner's Ubuntu. Building
  for older ones means an older container, which is not worth it for a best-effort artifact.
  **The lesson it produced is worth more than the job.** The first run died in PyInstaller's
  *collection* stage, before any bundling: `collect_submodules` **imports** each package to
  enumerate it, and `pyqtgraph.examples` builds Qt objects at import time — so the isolated
  subprocess reached for the `xcb` plugin, found no display, and **aborted (SIGABRT)**. C7's
  exclusion filtered the *result*, far too late, and `on_error` cannot catch a child that died
  rather than raised. Fixed with `collect_submodules(package, filter=…)`, since a package the
  filter rejects is never recursed into. **The rule: if you exclude a submodule from a `collect_*`
  call, filter during collection, not afterwards.** The build step also sets
  `QT_QPA_PLATFORM=offscreen`, as `ci.yml` does for the suite. Windows never hit any of it — its
  platform plugin initialises without a display server, which is why a Linux artifact was the first
  thing to find it.
  Also sanitises the tag into the archive filename in both build jobs: on a no-tag
  `workflow_dispatch` the tag defaults to the branch name, and a slashed branch was read as a
  directory in the output path. Latent since Phase 3, reachable only by dispatch.
- **C4 — the clean-instance test, and what Windows Sandbox can't do.** Done 2026-08-07 against the
  downloaded **v0.7.0** Release zip, on Windows Sandbox *and* the W11 boot. Closes the two things no
  build had ever covered: the clean-instance run and the SmartScreen click-through wording.
  **Sandbox is confirmed as the right tool, with one structural limit worth not rediscovering: it
  cannot record.** It is a VM with internet but no route to the home network, so the PS5 never
  reaches it. Everything downstream of recording was covered by copying capture files in and
  ingesting them — ingest, lap traces, track map, re-ingest, backup. Only the live-recording items
  need the boot.
  **Three items unticked, and they are not equivalent** — *old-DB additive columns* is **N/A** (no
  schema moved in v0.7.0, so `ensure_schema` had nothing to ALTER); *pre-Phase-2 DB* is **carried
  forward** from the 2nd build rather than re-proven, since reproducing it means manufacturing a
  legacy unstamped database; and *kill mid-record* is genuinely **open**, now in *Needs
  verification* for the next real session.
  **Two findings recorded rather than chased:** Help → Check for updates fails inside the Sandbox
  and works on the boot (network isolation, not the app), and **A4 is confirmed still present on
  v0.7.0**. It also produced **F9** — `NOTICE.md` ships as raw markdown, unreadable in Notepad.
- **C7 — pyqtgraph bloat trim, and what it found instead.** Done 2026-08-06; the third item of
  Cycle 3. `pyqtgraph.examples` — a demo app with its own `__main__` and ~40 scripts, unreachable
  from here — is filtered out of both `hiddenimports` and `collect_data_files`, with an `excludes`
  backstop. **Deliberately one subpackage:** `opengl` / `canvas` / `flowchart` / `console` /
  `multiprocess` are reachable from pyqtgraph's own `__init__` and its lazy attribute machinery, so
  trimming them ships a build that works until one specific widget is opened.
  **The honest result: 577 MB → 576 MB, 0.17 %.** It ships on hygiene, not size, and carries **no
  CHANGELOG entry** — a release note would overstate it. The finding that mattered is where the
  weight actually is: **scipy + libs 73 MB, pandas 18 MB, pillow 14 MB — ~105 MB (18 %) of
  transitive dependencies this app does not use**, now filed as **C9** and recorded with the full
  `_internal` breakdown in PACKAGING so the hunt is not re-run.
  **Two verification traps, both worth not re-learning.** Pure-Python modules live in the **PYZ**,
  not on disk, so a file search proves nothing; and `Analysis-00.toc` records the `Analysis()`
  configuration, so it *necessarily* still matches once the exclude exists — a guaranteed false
  positive that cost a round-trip here. `PYZ-00.toc` and `COLLECT-00.toc` are the lists that decide
  what ships (0 examples, 384 pyqtgraph modules intact).
  **C6 was the instrument, and was deliberately not trusted alone.** The built app logs
  `capability charts: ok`, but that probe is `find_spec`-based and cannot prove pyqtgraph *renders* —
  so a lap detail page was opened in the frozen bundle and the traces and track map confirmed. Done
  on **Linux**, not Windows, by pointing the bundle at a scratch copy of the dev data with
  `F1TELEMETRY_DATA_DIR`; the same run also gave the first confirmation that `resource_path`
  resolves through `_MEIPASS` (89 flag assets found under `_internal/`).
- **C6 — startup capability self-check.** Done 2026-08-05; the second item of Cycle 3, and the
  prerequisite for C7. `src/capabilities.py` (Qt-free) probes four things — charts (pyqtgraph),
  capture compression (zstandard), lap traces (pyarrow) and the bundled flag SVGs — and returns a
  frozen `Capability` each. `MainWindow` logs all four on every launch and dialogues only when
  something is degraded, deferred a turn like the pipeline check and ordered **before** it: a build
  that lost pyqtgraph is worth saying before offering a multi-minute re-ingest. **No Help-page
  surface, deliberately** — Help already hosts five actions that aren't Help content (E13).
  **The one decision worth not re-litigating: probe depth is per capability.** A capability is
  probed by *importing* it, because only an import catches a module that is present but won't load
  (pyarrow's Windows DLL quirk — `find_spec` says yes while the import fails). pyqtgraph is the
  exception, probed by `find_spec` alone, because importing it would undo the laziness that keeps
  start-up quick — and the regression this exists for, *a bundle that never shipped it*, needs no
  import to see. **That is precisely what C7 risks**, which is why the order was reversed.
  **Two limits, chosen not discovered:** a module present-but-broken-at-import reads OK for
  pyqtgraph (not silent — it raises into the log on the first lap opened, which is what decided the
  split); and `traces` can never actually report degraded today, because a broken pyarrow kills
  `main_window`'s import before the window exists, making it a start-up crash rather than a silent
  degrade. That probe earns its place as a log line a tester's report carries, and stops being
  vacuous if the `LapStore` import ever goes lazy.
  A probe that throws is reported as a **degraded capability**, not dropped — failing loud beats a
  self-check that quietly shortens its own report. Covered by `test/test_capabilities.py`, whose
  logging cases are real regression tests: `assertLogs` formats each record, so a reversed `%s`
  fails the suite instead of vanishing into logging's internal error handler. One did, on the way.
- **C5 — `threading.excepthook`, and the crash-dialog thread bug it uncovered.** Done 2026-08-05;
  the first item of Cycle 3. The hook itself is nearly a no-op today and that is worth knowing
  rather than rediscovering: **`threading.excepthook` never fires for a `QThread`** (the
  interpreter calls it from `Thread._bootstrap_inner`, which QThread does not go through), and
  every worker here is a QThread. It is a net for future bare-`Thread` work and for third-party
  threads.
  **The defect found while scoping it is the substance.** Every worker's `finally` sits *outside*
  its `except` — `IngestWorker`, `ReingestWorker`, `RelocateWorker` and `ImportWorker` all dispose
  stores there — so an exception from `store.close()` escapes `run()` entirely, reaches
  `sys.excepthook` via PySide6, and had `crash._show_dialog` constructing a `QMessageBox` **on the
  worker thread**. Building a QWidget off the GUI thread is undefined behaviour in Qt and can abort
  the process: the crash handler was able to convert a survivable error into a hard crash.
  **Three decisions worth not re-litigating.** `_report` checks the thread and shows the dialog
  *directly* when already on the GUI thread — a start-up crash happens before `app.exec()`, so a
  uniformly-queued call would never be delivered. Off-thread it emits through a queued-connection
  `QObject` relay, built by `install_excepthook` on the GUI thread so the object *lives* there.
  And **only strings cross the boundary**, never the exception — its traceback would pin worker
  frames alive across threads.
  Covered by `test/test_crash.py` (Qt-free): both hooks log and chain to the previous hook,
  `KeyboardInterrupt` / `SystemExit` pass through unlogged, and `_report` builds no dialog when
  there is no GUI thread. **Verified by hand through `UpdateCheckWorker`** (Help → Check for
  updates), whose `result_ready.emit` is already outside its try/except — no capture, database or
  recording needed to make an exception escape a worker thread.
- **B2 / B3 — league capture import, and the one field `recorded_by` became.** Done 2026-08-04;
  the last of Cycle 2. *Help → Import captures…* walks a chosen folder, copies anything new into
  the local captures folder and ingests it. Read and write are split like the prune, so the count
  and the total size are shown before a thread starts and the pass acts on exactly the list the
  user agreed to.
  **Four outcomes decided by content hash**, never by name: *new* → copy home + ingest; *already
  held* → skip; *known but the local archive is gone* → copy home + `relocate` (the shared folder
  as backup of last resort, deliberately **without** re-ingesting — rebuilding derived rows is
  "Re-read captures"' job); *only `recorded_by` differs* → update in place.
  **Copy-home is the point, not an optimisation:** the shared drive is transport, the local archive
  is the home, so no row is left pointing at a folder that syncs or disconnects. The source is never
  touched. A name clash is **numbered**, not overwritten — the hash already ruled, so a clash can
  only be two *different* recordings sharing a name. **A capture already inside the captures folder
  is ingested in place** — learned in testing, by importing from a home directory containing the
  data root and watching the app copy its own archives beside themselves under `-2` names. That fix
  also restores the one capability the retired test button had: point the importer at the captures
  folder to pick up a loose recording that was never ingested.
  **One inversion of `archive_and_ingest`, on purpose:** a capture that fails to ingest **keeps**
  its local copy. Nothing is at risk (the shared original is untouched), and a capture that won't
  parse is exactly the one worth having locally to look at.
  **B3 closed as one optional field**, as decided the day before. `CaptureStore.set_recorded_by` is
  the piece that makes "a re-import can correct it" true rather than aspirational — without it an
  already-held capture is simply skipped and the value could never change. Nothing reads
  `recorded_by` yet; E13 is the first thing that plausibly would.
  **Retired the `Ingest .f1cap (test)` header button**, which had been marked dev-only in code while
  `USER_GUIDE.md` §4 documented it as *the* import path — wrong in one place or the other since
  v0.3.0. The header now carries only the record control.
  Covered by `test/ingest/test_import.py` (19 cases) plus one in `test_captures.py`. Qt wiring
  verified by hand — and it earned its keep: three bugs (a `Signal` arity mismatch that silently
  stalled the progress dialog, a missing `_close_import_dialog`, and the copy-beside-itself above)
  were only reachable through the real app, because every test suite here is deliberately Qt-free.
  **Left behind:** Help now hosts five actions that aren't Help content — filed as **E13**.
- **B4 — locate a moved capture by content hash.** Done 2026-08-03; the first item of Cycle 2.
  *Help → Find moved captures…* walks a folder the user picks and re-points a `captures` row at the
  file it finds. The point is not the feature but the gap it closes: `find_missing_captures` can
  only say the bytes aren't where the app looks, so until now a *moved* capture and a *deleted* one
  were the same thing to the app and the only action offered was the one that forgets it.
  **Three decisions worth not re-litigating.** The search space is **only the known-missing rows** —
  a row that resolves is already correct, and re-pointing it at a second copy found on a memory
  stick would be a regression, not a fix. **Name and size pre-filter; the hash rules** — a candidate
  is read only when `(basename, size)` matches a missing row (a `stat`) and accepted only when the
  sha256 of its decompressed payload matches, so a folder full of strangers is cheap and one
  recording's metadata can never be filed against another's bytes. And it **re-points rather than
  copies home**: copying into the local captures folder is what B2's import is for, and doing it
  here would silently duplicate hundreds of MB behind a button that says "find".
  **Accepted limits, chosen not discovered:** a capture renamed *as well as* moved never reaches the
  hash (still a prune job), and one found on an external drive goes missing again when the drive is
  disconnected — that is what `relocate` means.
  `archive.hash_capture` is `ingest_capture`'s read pass isolated; `test_hash_is_codec_independent`
  now asserts the two agree, so the scan path and the ingest path can't drift about what a capture
  *is*. Threaded (`RelocateWorker`), unlike the prune, because confirming a match costs a
  decompression pass per candidate.
  **Two latent defects fixed on the way** — this is the first production caller of
  `CaptureStore.relocate`, which was annotated `-> None` but returns `bool`, and derived `file_name`
  with `rsplit("/")`: the *entire path* on Windows, which would have corrupted the very field
  `known_files()` and `resolve_capture_path`'s fallback key on. `MainWindow._busy()` replaced a
  guard copy-pasted at four call sites; this was the fourth worker, and a handler that forgot one
  would let two jobs write the same SQLite file from two threads.
  Covered by 12 cases in `test/ingest/test_reingest.py`. The Qt wiring has **no automated test** —
  every UI suite here is deliberately Qt-free — so it was verified by hand.
- **A3 — "missing middle laps".** Verified 2026-08-03 and closed. A full test race on Windows under
  v0.5.0 recorded every lap continuously, confirming the root cause was the machine sleeping
  mid-session (fixed in v0.4.2) and not anything in ingest. The original symptom — laps 1–2 then
  ~16–18 — was lost telemetry, never a parsing fault, so there was nothing to fix here once v0.4.2
  landed.
  **Do not reopen this on the wrong symptom.** The same race showed a single missing lap number,
  which is *correct*: a red flag makes the game skip one lap (restart is on lap *n+2*), documented
  in TELEMETRY_NOTES → "A red flag skips a lap number". One missing number after a slow lap is the
  game; several consecutive laps missing, usually with the Final Classification gone too, is lost
  telemetry.
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
  **The loose end it left is closed:** the Phase-1 "open the app twice" checklist item had passed
  *before* WAL existed, so its result meant "the contention never happened", not "WAL handled it".
  Re-run under WAL on **2026-08-05 — passes**, so the mechanism itself is now proven rather than
  merely un-triggered. PACKAGING's checklist item is ticked.
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
  game running — nothing wedged. That run predated WAL, so it proved only that the contention never
  happened; **re-run under WAL on 2026-08-05 and passes**, which does prove the mechanism. Closed.
- **A2 / F1 / F2 / F4 and the stale-doc sweep.** This commit.

## Deferred, with reasons

- **E1/E2, E3 and E5 are no longer deferred — un-deferred 2026-08-18; not Cycle 4 work
  (corrected 2026-08-24).** Their stated
  reason here was "after Cycle 3", and Cycle 3 is closed, so leaving the project's *next* item
  filed under *Deferred* was reading as forgotten. They now have P2 rows and an order. What was
  written here is still true of the work and is worth keeping: **E1/E2 is not the small view it
  looks like** — it means building the Sessions view, linking parts of it to the Laps view, and
  then *reworking the existing Seasons view*, which would inherit data from both, so it is a
  cross-surface rework rather than one page. **E2's store side is already built**
  (`deleted_uids` / `is_deleted` / `restore`), so on paper only its UI is pending and it most
  likely lives inside E1 — **verify that against the code before planning around it.** **E3** is
  large and wants a season of accumulated data behind it. **E5** is a placeholder in `_SECTIONS`
  and most of what it would do (open logs, show version) the Help page already does, which is why
  it is last rather than first.
- **B5 reconstructed-points Option 3 → P3.** Less urgent than it looked: A2 shows the Final
  Classification arrives 5–6× per session, so reconstruction is rare, and v0.4.2 removed its main
  cause. Belongs with league-management (per-league scoring tables) when that happens.
- **B1 out of Cycle 1** — not because it is unimportant (it is season-critical) but because it is
  gated on a real race, not on us. See *Needs verification*.

## Not tracked here

`checklist_2nd_build.md` and similar files at the **workspace root** are the author's scratch
copies for moving between Windows and the shared drive. They are outside the git repo, are not
project documentation, and should not be treated as an open-work source.
